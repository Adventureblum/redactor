import os
import json
import re
import logging
import glob
import aiofiles
import asyncio
from datetime import datetime
from bs4 import BeautifulSoup
from urllib.parse import urlparse
from collections import Counter
from typing import List, Dict, Tuple, Optional
from config import BASE_DIR, RESULTS_DIR

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('seo_analyzer.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

STOP_WORDS_FR = {
    "le", "et", "de", "à", "dans", "un", "pour", "sur", "avec", "au", "par",
    "une", "être", "est", "il", "ou", "comme", "depuis", "que", "ce", "sont", "était", "mais"
}

def _find_consigne_file() -> str:
    """Trouve automatiquement le fichier de consigne dans le dossier static"""
    consigne_pattern = os.path.join(BASE_DIR, "static", "consigne*.json")
    consigne_files = glob.glob(consigne_pattern)

    if not consigne_files:
        raise FileNotFoundError(f"❌ Aucun fichier de consigne trouvé dans {os.path.join(BASE_DIR, 'static')}/ (pattern: consigne*.json)")

    if len(consigne_files) == 1:
        found_file = consigne_files[0]
        logging.info(f"📁 Fichier de consigne détecté: {os.path.basename(found_file)}")
        return found_file

    # Si plusieurs fichiers trouvés, prendre le plus récent
    consigne_files.sort(key=os.path.getmtime, reverse=True)
    most_recent = consigne_files[0]
    logging.info(f"📁 Plusieurs fichiers de consigne trouvés, utilisation du plus récent: {os.path.basename(most_recent)}")
    logging.info(f"   Autres fichiers ignorés: {', '.join([os.path.basename(f) for f in consigne_files[1:]])}")
    return most_recent

async def load_consigne_data() -> Optional[Dict]:
    """Charge les données de consigne.json de manière asynchrone"""
    try:
        consigne_file = _find_consigne_file()
        if not os.path.exists(consigne_file):
            logging.error(f"Le fichier {consigne_file} n'existe pas")
            return None

        async with aiofiles.open(consigne_file, 'r', encoding='utf-8') as f:
            content = await f.read()
            return json.loads(content)
    except Exception as e:
        logging.error(f"Erreur lors du chargement du fichier de consigne: {e}")
        return None

def find_matching_serp_files(consigne_data: Dict) -> List[Tuple[str, Dict]]:
    """Trouve les fichiers SERP correspondant aux requêtes de consigne.json"""
    if not os.path.exists(RESULTS_DIR):
        logging.error(f"Le dossier {RESULTS_DIR} n'existe pas")
        return []

    pattern = os.path.join(RESULTS_DIR, "serp_*.json")
    serp_files = glob.glob(pattern)
    logging.info(f"Trouvé {len(serp_files)} fichiers SERP dans {RESULTS_DIR}")

    matches = []
    queries = consigne_data.get('queries', [])

    for filepath in serp_files:
        filename = os.path.basename(filepath)

        # Extraction de l'ID depuis le nom de fichier (serp_XXX_...)
        id_match = re.match(r'serp_(\d{3})_(.+)\.json', filename)
        if not id_match:
            logging.warning(f"Format de fichier non reconnu: {filename}")
            continue

        file_id = int(id_match.group(1))

        # Recherche de la requête correspondante
        matching_query = None
        for query in queries:
            if query.get('id') == file_id:
                matching_query = query
                break

        if matching_query:
            matches.append((filepath, matching_query))
            logging.info(f"✓ Correspondance trouvée: {filename} -> requête ID {file_id}")
        else:
            logging.warning(f"✗ Aucune correspondance pour: {filename} (ID {file_id})")

    return matches

async def load_serp_file(filepath: str) -> Optional[Dict]:
    """Charge un fichier SERP de manière asynchrone"""
    try:
        async with aiofiles.open(filepath, 'r', encoding='utf-8') as f:
            content = await f.read()
            return json.loads(content)
    except Exception as e:
        logging.error(f"Erreur lors du chargement du fichier SERP {filepath}: {e}")
        return None

def analyze_structured_data(soup):
    logger.info("Analyzing structured data")
    scripts = [s.string.strip() for s in soup.find_all("script", type="application/ld+json") if s.string]
    logger.info(f"Found {len(scripts)} structured data scripts")
    return scripts

def check_mobile_optimization(soup):
    viewport = soup.find("meta", attrs={"name": "viewport"})
    return "width=device-width" in (viewport.get("content") or "").lower()

def analyze_core_web_vitals(soup):
    return {
        "lazy_loading_used": soup.find(attrs={"loading": "lazy"}) is not None,
        "uses_preconnect": soup.find("link", rel="preconnect") is not None,
        "uses_web_vitals_script": any("web-vitals" in (s.get("src") or "") for s in soup.find_all("script")),
    }

def extract_bold_keywords(soup):
    return list({tag.get_text(strip=True) for tag in soup.find_all(["b", "strong"]) if tag.get_text(strip=True)})

def extract_links(soup, domain):
    internals, externals = set(), set()
    for a in soup.find_all("a", href=True):
        netloc = urlparse(a["href"]).netloc
        (internals if not netloc or netloc == domain else externals).add(a["href"])
    return sorted(internals), sorted(externals)

def analyze_onpage_metadata(soup):
    title = soup.find("title")
    meta = soup.find("meta", attrs={"name": "description"})
    h1_tags = soup.find_all("h1")
    return {
        "title": title.get_text(strip=True) if title else None,
        "title_length": len(title.get_text(strip=True)) if title else 0,
        "meta_description": (meta.get("content") or "").strip() if meta else None,
        "meta_description_length": len((meta.get("content") or "").strip()) if meta else 0,
        "h1_count": len(h1_tags),
        "h1_content": [h.get_text(strip=True) for h in h1_tags]
    }

def analyze_images_alt(soup):
    images = soup.find_all("img")
    with_alt = [img for img in images if img.get("alt")]
    return {
        "total_images": len(images),
        "images_with_alt": len(with_alt),
        "images_missing_alt": len(images) - len(with_alt)
    }

def analyze_link_rel_attributes(soup):
    rels = {"nofollow": 0, "sponsored": 0, "ugc": 0}
    for a in soup.find_all("a", href=True):
        for rel in (a.get("rel", []) if isinstance(a.get("rel"), list) else str(a.get("rel")).split()):
            if rel in rels:
                rels[rel] += 1
    return rels

def analyze_html_size(html):
    return {"html_size_bytes": len(html)}

def analyze_word_frequency(soup):
    words = re.findall(r'\b[a-zA-Zà-ü\-]{3,}\b', soup.get_text(" ", strip=True).lower())
    freq = Counter(w for w in words if w not in STOP_WORDS_FR).most_common(10)
    return {"top_keywords": freq}

def analyze_additional_factors(soup, html):
    text = soup.get_text(" ", strip=True)
    headings = {f"h{i}": len(soup.find_all(f"h{i}")) for i in range(1, 7)}
    has_toc = any(('#' in (a.get('href') or '') or a.get("id")) for a in soup.find_all(['a', 'h2', 'h3']))
    return {
        "word_count": len(text.split()),
        "heading_tags": headings,
        "has_table_of_contents": has_toc,
        "has_video": bool(soup.find("video")),
        "has_images": bool(soup.find("img")),
        "has_breadcrumbs": any("BreadcrumbList" in (s.get("type") or "") + (s.get("itemtype") or "") for s in soup.find_all("script")),
        "has_canonical": soup.find("link", rel="canonical") is not None,
        "is_amp": "amp" in (soup.html.get("⚠️") or "").lower() if soup.html else False,
        "uses_webp_images": any(img.get("src", "").endswith(".webp") for img in soup.find_all("img")),
        "uses_lazy_images": any(img.get("loading") == "lazy" for img in soup.find_all("img")),
        "meta_social": {
            "og": len(soup.find_all("meta", property=lambda p: p and p.startswith("og:"))),
            "twitter": len(soup.find_all("meta", property=lambda p: p and p.startswith("twitter:")))
        },
        "html_language": soup.html.get("lang", "").lower() if soup.html else "",
        "meta_robots": soup.find("meta", attrs={"name": "robots"}).get("content", "") if soup.find("meta", attrs={"name": "robots"}) else None
    }

def analyze_serp_result(serp_data: Dict, result_index: int) -> Optional[Dict]:
    """Analyse un résultat SERP spécifique"""
    try:
        results = serp_data.get('results', [])
        if result_index >= len(results):
            logging.warning(f"Index {result_index} hors limites pour les résultats SERP")
            return None
            
        result = results[result_index]
        
        # Vérifier si le HTML est disponible
        html_content = result.get('html', '')
        if not html_content:
            logging.warning(f"Pas de contenu HTML pour le résultat {result_index} (success: {result.get('success', False)})")
            return None
            
        url = result.get('url', '')
        if not url:
            logging.warning(f"Pas d'URL pour le résultat {result_index}")
            return None
            
        logging.info(f"Analysing URL: {url}")
        logging.info(f"HTML content length: {len(html_content)} characters")
        
        domain = urlparse(url).netloc
        logging.info(f"Extracted domain: {domain}")
        
        # Parse HTML
        soup = BeautifulSoup(html_content, "html.parser")

        # Effectuer toutes les analyses SEO
        mobile_opt = check_mobile_optimization(soup)
        sd = analyze_structured_data(soup)
        cwv = analyze_core_web_vitals(soup)
        bold_kw = extract_bold_keywords(soup)
        il = extract_links(soup, domain)
        additional = analyze_additional_factors(soup, html_content)
        metadata = analyze_onpage_metadata(soup)
        images = analyze_images_alt(soup)
        link_rels = analyze_link_rel_attributes(soup)
        html_size = analyze_html_size(html_content)
        word_freq = analyze_word_frequency(soup)

        # Construire le rapport SEO
        seo_report = {
            "url": url,
            "position": result.get('position', result_index + 1),
            "title": result.get('title', ''),
            "success": result.get('success', False),
            "method": result.get('method', ''),
            "status": result.get('status', None),
            "error": result.get('error', None),
            "htmlLength": result.get('htmlLength', 0),
            "mobile_optimized": mobile_opt,
            "structured_data_found": bool(sd),
            "structured_data_samples": sd[:2],
            "core_web_vitals": cwv,
            "bolded_keywords": bold_kw,
            "internal_links": il[0],
            "external_links": il[1],
            "analyzed_at": datetime.now().isoformat(),
            **additional,
            **metadata,
            **images,
            **link_rels,
            **html_size,
            **word_freq
        }
        
        logging.info(f"✓ Analyse SEO terminée pour {url}")
        return seo_report
        
    except Exception as e:
        logging.error(f"Erreur lors de l'analyse du résultat SERP {result_index}: {str(e)}")
        return None

async def process_serp_file(filepath: str, query_data: Dict) -> Optional[Dict]:
    """Traite un fichier SERP et retourne les analyses SEO"""
    try:
        serp_data = await load_serp_file(filepath)
        if not serp_data:
            return None
            
        query_id = query_data.get('id')
        query_text = query_data.get('text', '')
        
        logging.info(f"🔍 Traitement SERP pour requête ID {query_id}: '{query_text}'")
        
        # Debug: afficher la structure du fichier SERP
        logging.info(f"🔍 Structure SERP pour {os.path.basename(filepath)}:")
        logging.info(f"   - Clés principales: {list(serp_data.keys())}")
        logging.info(f"   - Type de données: {type(serp_data)}")
        
        # Analyser les résultats qui ont du contenu HTML
        results = serp_data.get('organicResults', [])  # ← CORRECTION ICI
        if not results:
            # Essayer d'autres clés possibles en fallback
            for key in ['results', 'data', 'items', 'search_results']:
                if key in serp_data:
                    results = serp_data[key]
                    logging.info(f"   - Résultats trouvés sous la clé '{key}': {len(results)}")
                    break
        
        max_results = min(10, len(results))
        logging.info(f"   - Nombre de résultats à traiter: {len(results)}")
        
        seo_analyses = []
        skipped_count = 0
        
        for i in range(max_results):
            result = results[i]
            
            # Vérifier si le résultat a du contenu HTML utilisable
            if not result.get('success', False) or not result.get('html'):
                skipped_count += 1
                logging.info(f"⏭️ Résultat {i+1} ignoré - success: {result.get('success', False)}, html présent: {bool(result.get('html'))}")
                continue
                
            seo_report = analyze_serp_result(serp_data, i)
            if seo_report:
                seo_analyses.append(seo_report)
        
        # Construire le résumé pour la requête
        analysis_summary = {
            "query_id": query_id,
            "query_text": query_text,
            "total_results_found": len(results),
            "total_results_analyzed": len(seo_analyses),
            "skipped_results": skipped_count,
            "serp_analysis": seo_analyses,
            "analysis_metadata": {
                "processed_at": datetime.now().isoformat(),
                "serp_file": os.path.basename(filepath)
            }
        }
        
        logging.info(f"✓ Analyse terminée pour requête ID {query_id}: {len(seo_analyses)} résultats analysés, {skipped_count} ignorés")
        return analysis_summary
        
    except Exception as e:
        logging.error(f"Erreur lors du traitement du fichier SERP {filepath}: {str(e)}")
        return None

async def update_consigne_with_seo_data(consigne_data: Dict, processed_results: Dict[int, Dict]) -> bool:
    """Met à jour consigne.json avec les analyses SEO"""
    try:
        consigne_file = _find_consigne_file()

        # Mise à jour des requêtes avec les résultats SEO
        for query in consigne_data.get('queries', []):
            query_id = query.get('id')
            if query_id in processed_results:
                seo_data = processed_results[query_id]
                
                print(f"🔄 MISE À JOUR SEO REQUÊTE ID {query_id} ('{query.get('text', 'N/A')[:50]}...')")
                print(f"   - Résultats trouvés: {seo_data.get('total_results_found', 0)}")
                print(f"   - Résultats analysés: {seo_data.get('total_results_analyzed', 0)}")
                print(f"   - Résultats ignorés: {seo_data.get('skipped_results', 0)}")
                print(f"   - Fichier SERP: {seo_data.get('analysis_metadata', {}).get('serp_file', 'N/A')}")
                
                # Ajouter les données SEO à la requête
                query['seo_analysis'] = seo_data
                logging.info(f"✓ Requête ID {query_id} mise à jour avec les données SEO")

        # Sauvegarde du fichier mis à jour
        async with aiofiles.open(consigne_file, 'w', encoding='utf-8') as f:
            content = json.dumps(consigne_data, indent=4, ensure_ascii=False)
            await f.write(content)

        logging.info(f"✓ Fichier consigne.json mis à jour avec {len(processed_results)} analyses SEO")
        return True

    except Exception as e:
        logging.error(f"Erreur lors de la mise à jour de consigne.json: {e}")
        return False

async def cleanup_processed_serp_files(successful_files: List[str]) -> None:
    """Supprime les fichiers SERP traités avec succès"""
    try:
        for filepath in successful_files:
            if os.path.exists(filepath):
                os.remove(filepath)
                logging.info(f"✓ Fichier SERP supprimé: {os.path.basename(filepath)}")

        logging.info(f"✓ Nettoyage terminé: {len(successful_files)} fichiers SERP supprimés")

    except Exception as e:
        logging.error(f"Erreur lors du nettoyage des fichiers SERP: {e}")

async def main():
    """Fonction principale pour traiter tous les fichiers SERP"""
    logger.info("🚀 Démarrage de l'analyse SEO des fichiers SERP")
    
    try:
        # Charger les données de consigne
        logger.info("📋 Chargement des données de consigne")
        consigne_data = await load_consigne_data()
        if not consigne_data:
            logger.error("❌ Impossible de charger les données de consigne")
            return
                                            
        # Trouver les fichiers SERP correspondants
        logger.info("🔍 Recherche des fichiers SERP correspondants")
        matching_files = find_matching_serp_files(consigne_data)
        
        if not matching_files:
            logger.info("ℹ️ Aucun fichier SERP à traiter")
            return
            
        logger.info(f"📁 {len(matching_files)} fichiers SERP à traiter")

        # Traitement des fichiers SERP
        processed_results = {}
        successful_files = []
        
        for filepath, query_data in matching_files:
            logger.info(f"📄 Traitement: {os.path.basename(filepath)}")
            
            result = await process_serp_file(filepath, query_data)
            if result:
                query_id = query_data.get('id')
                processed_results[query_id] = result
                successful_files.append(filepath)
                logger.info(f"✅ Traitement réussi pour requête ID {query_id}")
            else:
                logger.error(f"❌ Échec du traitement pour {os.path.basename(filepath)}")

        # Mise à jour du fichier consigne
        if processed_results:
            logger.info("💾 Mise à jour du fichier consigne.json")
            success = await update_consigne_with_seo_data(consigne_data, processed_results)
            
            if success:
                logger.info(f"✅ {len(processed_results)} analyses SEO sauvegardées dans consigne.json")
                
                # Nettoyage des fichiers traités avec succès
                logger.info("🧹 Nettoyage des fichiers SERP traités")
                await cleanup_processed_serp_files(successful_files)
                
                print(f"\n🎉 ANALYSE SEO TERMINÉE")
                print(f"   📊 {len(processed_results)} requêtes analysées")
                print(f"   📁 {len(successful_files)} fichiers SERP traités")
                print(f"   💾 Résultats sauvegardés dans consigne.json")
            else:
                logger.error("❌ Erreur lors de la sauvegarde dans consigne.json")
        else:
            logger.warning("⚠️ Aucun résultat à sauvegarder")

    except Exception as e:
        logger.error(f"❌ Erreur critique dans l'analyse SEO: {str(e)}", exc_info=True)
        print(f"❌ Erreur: {str(e)}")

if __name__ == "__main__":
    asyncio.run(main())