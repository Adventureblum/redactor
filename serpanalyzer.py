import os
import json
import re
import logging
import asyncio
import aiofiles
from datetime import datetime
from bs4 import BeautifulSoup
import glob

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('seo_dom_analyzer_simple.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Configuration
BASE_DIR = os.path.dirname(__file__)
RESULTS_DIR = os.path.join(BASE_DIR, "results")


class SerpDomProcessor:
    """Processeur simplifié pour analyser le DOM des fichiers SERP"""
    
    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.results_dir = RESULTS_DIR
    
    def find_serp_files(self):
        """Recherche tous les fichiers SERP dans le dossier results"""
        try:
            pattern = os.path.join(self.results_dir, "serp_*.json")
            files = glob.glob(pattern)
            self.logger.info(f"Fichiers SERP trouvés: {len(files)}")
            return sorted(files)
        except Exception as e:
            self.logger.error(f"Erreur recherche fichiers: {e}")
            return []
    
    async def process_serp_file(self, filepath):
        """Traite un fichier SERP"""
        try:
            filename = os.path.basename(filepath)
            self.logger.info(f"Traitement: {filename}")
            
            async with aiofiles.open(filepath, 'r', encoding='utf-8') as f:
                content = await f.read()
                data = json.loads(content)
            
            # Vérification du succès
            if not data.get('success'):
                self.logger.warning(f"Fichier SERP non réussi: {filename}")
                return None
            
            # Extraction de la requête depuis le nom de fichier
            query_match = re.match(r'serp_(\d{3})_(.+)\.json', filename)
            if query_match:
                query = query_match.group(2).replace('_', ' ')
            else:
                query = data.get('query', '')
            
            # Extraction des résultats organiques
            organic_results = data.get('organicResults', [])
            
            if not organic_results:
                self.logger.warning(f"Aucun résultat organique dans {filename}")
                return None
            
            # Analyse de chaque résultat
            analyzed_results = []
            for idx, result in enumerate(organic_results, 1):
                html_content = result.get('html', '')
                
                if not html_content:
                    self.logger.debug(f"Position {idx}: pas de HTML")
                    continue
                
                analysis = await self.analyze_result(result, idx)
                if analysis:
                    analyzed_results.append(analysis)
            
            if not analyzed_results:
                self.logger.warning(f"Aucune analyse réussie pour {filename}")
                return None
            
            # Construction de l'analyse SERP
            serp_analysis = {
                "query": query,
                "location": data.get('location', ''),
                "device": data.get('device', 'desktop'),
                "timestamp": datetime.now().isoformat(),
                "total_results_analyzed": len(analyzed_results),
                "results": analyzed_results
            }
            
            return serp_analysis
        
        except Exception as e:
            self.logger.error(f"Erreur traitement {filepath}: {e}")
            return None
    
    def count_words_in_content(self, content_dict):
        """Compte le nombre total de mots dans le dictionnaire de contenu"""
        try:
            total_words = 0
            for text in content_dict.values():
                if text and isinstance(text, str):
                    # Utiliser une expression régulière pour compter les mots
                    # On compte les séquences de caractères alphanumériques
                    words = re.findall(r'\b\w+\b', text)
                    total_words += len(words)
            return total_words
        except Exception as e:
            self.logger.error(f"Erreur comptage mots: {e}")
            return 0

    async def analyze_result(self, result, position):
        """Analyse un résultat SERP"""
        try:
            url = result.get('url', '')
            title = result.get('title', '')
            snippet = result.get('snippet', '')
            html_raw = result.get('html', '')
            
            if not html_raw:
                return None
            
            # Parse HTML
            soup = BeautifulSoup(html_raw, 'html.parser')
            
            # Extraction des balises techniques de base
            technical_tags = self.extract_technical_tags(soup)
            
            # Extraction du contenu dans l'ordre du DOM (headings + paragraphes mélangés)
            content = self.extract_content_in_dom_order(soup)

            # Comptage des mots dans le contenu
            words_count = self.count_words_in_content(content)

            # Construction de l'analyse
            analysis = {
                "position": position,
                "url": url,
                "title": title,
                "snippet": snippet,
                "technical_analysis": technical_tags,
                "content": content,
                "words_count": words_count
            }
            
            return analysis
        
        except Exception as e:
            self.logger.error(f"Erreur analyse résultat position {position}: {e}")
            return None
    
    def extract_technical_tags(self, soup):
        """Extrait les balises techniques de base du HTML"""
        try:
            # Décompte des balises Hn
            heading_counts = {
                f'h{i}_count': len(soup.find_all(f'h{i}'))
                for i in range(1, 7)
            }
            
            # Décompte des paragraphes
            p_count = len(soup.find_all('p'))
            
            technical = {
                "doctype": self.detect_doctype(soup),
                "lang": soup.html.get('lang', '') if soup.html else '',
                "charset": self.detect_charset(soup),
                "viewport": self.detect_viewport(soup),
                "title_tag": soup.title.string if soup.title else '',
                "meta_description": self.get_meta_content(soup, 'description'),
                "canonical": self.get_link_tag(soup, 'canonical'),
                
                # Décomptes
                **heading_counts,
                "p_count": p_count,
                
                # Données structurées
                "structured_data": self.extract_structured_data(soup),
                
                # Core Web Vitals & Performance
                "performance": self.analyze_performance(soup),
                
                # Navigation & Structure
                "breadcrumbs": self.detect_breadcrumbs(soup),
                "table_of_contents": self.detect_toc(soup),
                
                # Optimisation images
                "webp_analysis": self.analyze_webp(soup),
                
                # Mobile First
                "mobile_optimization": self.analyze_mobile_first(soup)
            }
            return technical
        
        except Exception as e:
            self.logger.error(f"Erreur extraction balises techniques: {e}")
            return {}
    
    def detect_doctype(self, soup):
        """Détecte le DOCTYPE"""
        for item in soup.contents:
            if hasattr(item, 'name') and item.name is None:
                doctype_text = str(item).strip().lower()
                if 'html' in doctype_text:
                    return 'HTML5' if 'html' == doctype_text.replace('<!doctype', '').strip().replace('>', '') else 'HTML4/XHTML'
        return 'unknown'
    
    def detect_charset(self, soup):
        """Détecte le charset"""
        charset_tag = soup.find('meta', charset=True)
        if charset_tag:
            return charset_tag.get('charset', '')
        
        content_type = soup.find('meta', attrs={'http-equiv': 'Content-Type'})
        if content_type:
            content = content_type.get('content', '')
            if 'charset=' in content:
                return content.split('charset=')[-1].strip()
        
        return ''
    
    def detect_viewport(self, soup):
        """Détecte la balise viewport"""
        viewport = soup.find('meta', attrs={'name': 'viewport'})
        return viewport.get('content', '') if viewport else ''
    
    def get_meta_content(self, soup, name):
        """Récupère le contenu d'une balise meta"""
        meta = soup.find('meta', attrs={'name': name})
        if not meta:
            meta = soup.find('meta', attrs={'property': f'og:{name}'})
        return meta.get('content', '') if meta else ''
    
    def get_link_tag(self, soup, rel):
        """Récupère l'URL d'une balise link"""
        link = soup.find('link', rel=rel)
        return link.get('href', '') if link else ''
    
    def extract_structured_data(self, soup):
        """Extrait et analyse les données structurées JSON-LD"""
        try:
            json_ld_scripts = soup.find_all('script', type='application/ld+json')
            
            if not json_ld_scripts:
                return {
                    "has_structured_data": False,
                    "count": 0,
                    "types": []
                }
            
            structured_data = []
            types_found = []
            
            for script in json_ld_scripts:
                try:
                    data = json.loads(script.string)
                    
                    # Gestion des @graph
                    if isinstance(data, dict) and '@graph' in data:
                        items = data['@graph']
                    elif isinstance(data, list):
                        items = data
                    else:
                        items = [data]
                    
                    for item in items:
                        if isinstance(item, dict) and '@type' in item:
                            schema_type = item['@type']
                            if isinstance(schema_type, list):
                                types_found.extend(schema_type)
                            else:
                                types_found.append(schema_type)
                            
                            structured_data.append({
                                "type": schema_type,
                                "has_name": 'name' in item,
                                "has_description": 'description' in item,
                                "has_image": 'image' in item,
                                "data": item
                            })
                
                except json.JSONDecodeError:
                    continue
            
            return {
                "has_structured_data": len(structured_data) > 0,
                "count": len(structured_data),
                "types": list(set(types_found)),
                "schemas": structured_data
            }
        
        except Exception as e:
            self.logger.error(f"Erreur extraction structured data: {e}")
            return {"has_structured_data": False, "count": 0, "types": []}
    
    def analyze_performance(self, soup):
        """Analyse les indicateurs de performance (Core Web Vitals proxy)"""
        try:
            html_str = str(soup)
            
            # Taille du HTML
            html_size = len(html_str.encode('utf-8'))
            
            # Resources
            css_links = soup.find_all('link', rel='stylesheet')
            js_scripts = soup.find_all('script', src=True)
            
            # Détection minification CSS
            css_minified = 0
            css_not_minified = 0
            for link in css_links:
                href = link.get('href', '')
                if '.min.css' in href:
                    css_minified += 1
                elif '.css' in href:
                    css_not_minified += 1
            
            # Détection minification JS
            js_minified = 0
            js_not_minified = 0
            for script in js_scripts:
                src = script.get('src', '')
                if '.min.js' in src:
                    js_minified += 1
                elif '.js' in src:
                    js_not_minified += 1
            
            # Inline CSS/JS
            inline_styles = soup.find_all('style')
            inline_scripts = soup.find_all('script', src=False)
            
            # Détection lazy loading
            lazy_images = soup.find_all('img', loading='lazy')
            
            # Détection preload/prefetch
            preload_links = soup.find_all('link', rel='preload')
            prefetch_links = soup.find_all('link', rel='prefetch')
            dns_prefetch = soup.find_all('link', rel='dns-prefetch')
            preconnect = soup.find_all('link', rel='preconnect')
            
            # Fonts optimization
            font_display_swap = len(soup.find_all('link', attrs={'rel': 'stylesheet', 'href': lambda x: x and 'fonts.googleapis.com' in x and 'display=swap' in x}))
            
            return {
                "html_size_bytes": html_size,
                "html_size_kb": round(html_size / 1024, 2),
                "external_resources": {
                    "css_count": len(css_links),
                    "css_minified": css_minified,
                    "css_not_minified": css_not_minified,
                    "js_count": len(js_scripts),
                    "js_minified": js_minified,
                    "js_not_minified": js_not_minified
                },
                "inline_resources": {
                    "inline_styles_count": len(inline_styles),
                    "inline_scripts_count": len(inline_scripts)
                },
                "optimization": {
                    "has_lazy_loading": len(lazy_images) > 0,
                    "lazy_images_count": len(lazy_images),
                    "has_preload": len(preload_links) > 0,
                    "preload_count": len(preload_links),
                    "has_prefetch": len(prefetch_links) > 0,
                    "has_dns_prefetch": len(dns_prefetch) > 0,
                    "has_preconnect": len(preconnect) > 0,
                    "font_display_swap": font_display_swap > 0
                },
                "minification_score": self.calculate_minification_score(
                    css_minified, css_not_minified, js_minified, js_not_minified
                )
            }
        
        except Exception as e:
            self.logger.error(f"Erreur analyse performance: {e}")
            return {}
    
    def calculate_minification_score(self, css_min, css_not_min, js_min, js_not_min):
        """Calcule un score de minification (0-100)"""
        total = css_min + css_not_min + js_min + js_not_min
        if total == 0:
            return 100
        minified = css_min + js_min
        return round((minified / total) * 100, 2)
    
    def detect_breadcrumbs(self, soup):
        """Détecte les fils d'Ariane (breadcrumbs)"""
        try:
            # Méthode 1: Schema.org BreadcrumbList dans JSON-LD
            json_ld_scripts = soup.find_all('script', type='application/ld+json')
            has_schema_breadcrumb = False
            
            for script in json_ld_scripts:
                try:
                    data = json.loads(script.string)
                    if isinstance(data, dict):
                        if data.get('@type') == 'BreadcrumbList':
                            has_schema_breadcrumb = True
                            break
                        if '@graph' in data:
                            for item in data['@graph']:
                                if isinstance(item, dict) and item.get('@type') == 'BreadcrumbList':
                                    has_schema_breadcrumb = True
                                    break
                except:
                    continue
            
            # Méthode 2: Balises HTML avec aria-label ou class
            breadcrumb_nav = soup.find('nav', attrs={'aria-label': lambda x: x and 'breadcrumb' in x.lower()})
            if not breadcrumb_nav:
                breadcrumb_nav = soup.find(class_=lambda x: x and 'breadcrumb' in str(x).lower())
            
            # Méthode 3: Microdata
            has_microdata = bool(soup.find(attrs={'itemtype': lambda x: x and 'BreadcrumbList' in x}))
            
            breadcrumb_items = []
            if breadcrumb_nav:
                items = breadcrumb_nav.find_all(['a', 'span', 'li'])
                breadcrumb_items = [item.get_text(strip=True) for item in items if item.get_text(strip=True)]
            
            return {
                "has_breadcrumbs": has_schema_breadcrumb or bool(breadcrumb_nav) or has_microdata,
                "has_schema_breadcrumb": has_schema_breadcrumb,
                "has_html_breadcrumb": bool(breadcrumb_nav),
                "has_microdata": has_microdata,
                "breadcrumb_items": breadcrumb_items,
                "breadcrumb_depth": len(breadcrumb_items)
            }
        
        except Exception as e:
            self.logger.error(f"Erreur détection breadcrumbs: {e}")
            return {"has_breadcrumbs": False}
    
    def detect_toc(self, soup):
        """Détecte la table des matières (Table of Contents)"""
        try:
            # Recherche par attributs ARIA
            toc = soup.find(attrs={'role': 'navigation', 'aria-label': lambda x: x and any(term in x.lower() for term in ['table', 'contents', 'matières', 'sommaire'])})
            
            # Recherche par ID
            if not toc:
                toc = soup.find(id=lambda x: x and any(term in x.lower() for term in ['toc', 'table-of-contents', 'sommaire', 'table-matiere']))
            
            # Recherche par class
            if not toc:
                toc = soup.find(class_=lambda x: x and any(term in str(x).lower() for term in ['toc', 'table-of-contents', 'sommaire', 'table-matiere']))
            
            toc_items = []
            if toc:
                links = toc.find_all('a')
                toc_items = [
                    {
                        "text": link.get_text(strip=True),
                        "href": link.get('href', '')
                    }
                    for link in links if link.get_text(strip=True)
                ]
            
            return {
                "has_toc": bool(toc),
                "toc_items_count": len(toc_items),
                "toc_items": toc_items
            }
        
        except Exception as e:
            self.logger.error(f"Erreur détection TOC: {e}")
            return {"has_toc": False}
    
    def analyze_webp(self, soup):
        """Analyse l'utilisation du format WebP"""
        try:
            all_images = soup.find_all('img')
            
            webp_count = 0
            non_webp_count = 0
            picture_elements = len(soup.find_all('picture'))
            
            for img in all_images:
                src = img.get('src', '').lower()
                srcset = img.get('srcset', '').lower()
                
                if '.webp' in src or '.webp' in srcset:
                    webp_count += 1
                elif src and not src.startswith('data:'):
                    non_webp_count += 1
            
            # Détection des sources WebP dans <picture>
            picture_webp = len(soup.find_all('source', type='image/webp'))
            
            total_images = webp_count + non_webp_count
            webp_percentage = round((webp_count / total_images * 100), 2) if total_images > 0 else 0
            
            return {
                "total_images": total_images,
                "webp_images": webp_count,
                "non_webp_images": non_webp_count,
                "webp_percentage": webp_percentage,
                "uses_picture_element": picture_elements > 0,
                "picture_elements_count": picture_elements,
                "picture_webp_sources": picture_webp,
                "has_modern_format": webp_count > 0 or picture_webp > 0
            }
        
        except Exception as e:
            self.logger.error(f"Erreur analyse WebP: {e}")
            return {}
    
    def analyze_mobile_first(self, soup):
        """Analyse l'optimisation Mobile First"""
        try:
            viewport = self.detect_viewport(soup)
            
            # Analyse du viewport
            has_viewport = bool(viewport)
            viewport_valid = 'width=device-width' in viewport if viewport else False
            initial_scale = 'initial-scale=1' in viewport if viewport else False
            
            # Media queries CSS
            inline_styles = soup.find_all('style')
            css_links = soup.find_all('link', rel='stylesheet')
            
            media_queries_inline = 0
            for style in inline_styles:
                if style.string and '@media' in style.string:
                    media_queries_inline += style.string.count('@media')
            
            # Détection de media queries dans les attributs media
            media_specific_css = len(soup.find_all('link', rel='stylesheet', media=True))
            
            # Touch icons
            apple_touch_icon = len(soup.find_all('link', rel=lambda x: x and 'apple-touch-icon' in x))
            
            # Responsive images
            srcset_images = len(soup.find_all('img', srcset=True))
            sizes_images = len(soup.find_all('img', sizes=True))
            
            # PWA indicators
            manifest = soup.find('link', rel='manifest')
            theme_color = soup.find('meta', attrs={'name': 'theme-color'})
            
            # AMP detection
            is_amp = bool(soup.find('html', attrs={'amp': True})) or bool(soup.find('html', attrs={'⚡': True}))
            
            # Calcul score Mobile First
            mobile_score = 0
            if has_viewport and viewport_valid:
                mobile_score += 30
            if initial_scale:
                mobile_score += 10
            if media_queries_inline > 0 or media_specific_css > 0:
                mobile_score += 20
            if srcset_images > 0 or sizes_images > 0:
                mobile_score += 20
            if apple_touch_icon > 0:
                mobile_score += 10
            if manifest:
                mobile_score += 10
            
            return {
                "viewport": {
                    "has_viewport": has_viewport,
                    "is_valid": viewport_valid,
                    "has_initial_scale": initial_scale,
                    "content": viewport
                },
                "responsive_design": {
                    "media_queries_inline": media_queries_inline,
                    "media_specific_css": media_specific_css,
                    "srcset_images": srcset_images,
                    "sizes_images": sizes_images
                },
                "mobile_icons": {
                    "apple_touch_icon": apple_touch_icon,
                    "has_manifest": bool(manifest),
                    "has_theme_color": bool(theme_color)
                },
                "advanced": {
                    "is_amp": is_amp
                },
                "mobile_first_score": min(mobile_score, 100)
            }
        
        except Exception as e:
            self.logger.error(f"Erreur analyse Mobile First: {e}")
            return {}
    
    def extract_content_in_dom_order(self, soup):
        """Extrait les headings et paragraphes dans l'ordre du DOM"""
        try:
            content_dict = {}
            
            # Compteurs pour chaque type
            h_counters = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0, 6: 0}
            p_counter = 0
            
            # Parcourir tous les éléments headings et paragraphes dans l'ordre du DOM
            for tag in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p']):
                text = tag.get_text(strip=True)
                
                if not text:
                    continue
                
                if tag.name.startswith('h'):
                    # C'est un heading
                    level = int(tag.name[1])
                    h_counters[level] += 1
                    
                    # Réinitialiser les compteurs des niveaux inférieurs
                    for lower_level in range(level + 1, 7):
                        h_counters[lower_level] = 0
                    
                    # Créer la clé
                    if level == 1:
                        key = "h1"
                    else:
                        key = f"h{level}_{h_counters[level]}"
                    
                    content_dict[key] = text
                
                elif tag.name == 'p':
                    # C'est un paragraphe
                    p_counter += 1
                    key = f"p_{p_counter}"
                    content_dict[key] = text
            
            return content_dict
        
        except Exception as e:
            self.logger.error(f"Erreur extraction contenu DOM: {e}")
            return {}
    
    def analyze_page_types(self, results):
        """Analyse statistique des types de page dans le SERP - DÉSACTIVÉE"""
        return {
            "analysis_disabled": True,
            "message": "Type detection feature removed"
        }


class ConsigneManager:
    """Gestionnaire pour intégrer les analyses dans le fichier consigne existant"""

    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.consignes_dir = os.path.join(BASE_DIR, "static", "consignesrun")
        self.consigne_file = None
    
    def find_consigne_file(self):
        """Trouve le fichier consigne dans le dossier consignesrun"""
        try:
            if not os.path.exists(self.consignes_dir):
                self.logger.error(f"Dossier consignesrun introuvable: {self.consignes_dir}")
                return None

            consigne_files = glob.glob(os.path.join(self.consignes_dir, "*.json"))
            if not consigne_files:
                self.logger.error("Aucun fichier consigne trouvé")
                return None

            # Prendre le fichier le plus récent s'il y en a plusieurs
            self.consigne_file = max(consigne_files, key=os.path.getmtime)
            self.logger.info(f"Fichier consigne trouvé: {os.path.basename(self.consigne_file)}")
            return self.consigne_file
        except Exception as e:
            self.logger.error(f"Erreur recherche fichier consigne: {e}")
            return None

    async def load_consigne_data(self):
        """Charge les données du fichier consigne"""
        try:
            if not self.consigne_file:
                self.consigne_file = self.find_consigne_file()

            if not self.consigne_file:
                return None

            async with aiofiles.open(self.consigne_file, 'r', encoding='utf-8') as f:
                content = await f.read()
                data = json.loads(content)
                self.logger.info(f"Fichier consigne chargé: {len(data.get('queries', []))} queries")
                return data
        except Exception as e:
            self.logger.error(f"Erreur chargement consigne: {e}")
            return None
    
    async def integrate_serp_analyses(self, serp_analyses):
        """Intègre les analyses SERP dans le fichier consigne en enrichissant les queries"""
        try:
            consigne_data = await self.load_consigne_data()
            if consigne_data is None:
                return False

            # Ajouter les métadonnées d'analyse SERP
            consigne_data["serp_analysis"] = {
                "last_updated": datetime.now().isoformat(),
                "total_serp_analyzed": len(serp_analyses),
                "analysis_timestamp": datetime.now().isoformat()
            }

            # Pour chaque query de la consigne, essayer de trouver l'analyse SERP correspondante
            queries = consigne_data.get("queries", [])

            for query_info in queries:
                query_id = query_info.get("id")
                query_text = query_info.get("text", "").strip().lower()

                # Chercher l'analyse SERP correspondante (par similarité de texte)
                matching_analysis = None
                for serp_analysis in serp_analyses:
                    serp_query = serp_analysis.get("query", "").strip().lower()

                    # Correspondance exacte ou par mots-clés
                    if (query_text == serp_query or
                        all(word in serp_query for word in query_text.split()) or
                        all(word in query_text for word in serp_query.split())):
                        matching_analysis = serp_analysis
                        break

                # Si on trouve une correspondance, enrichir la query
                if matching_analysis:
                    query_info["serp_data"] = {
                        "serp_query": matching_analysis["query"],
                        "location": matching_analysis.get("location", ""),
                        "device": matching_analysis.get("device", "desktop"),
                        "timestamp": matching_analysis.get("timestamp"),
                        "total_results_analyzed": matching_analysis.get("total_results_analyzed", 0),
                        "position_data": {}
                    }

                    # Organiser les résultats par position (1, 2, 3, 4...)
                    for result in matching_analysis.get("results", []):
                        position = result.get("position")
                        if position and position <= 10:  # Limiter aux 10 premiers résultats
                            query_info["serp_data"]["position_data"][f"position_{position}"] = {
                                "url": result.get("url", ""),
                                "title": result.get("title", ""),
                                "snippet": result.get("snippet", ""),
                                "technical_analysis": result.get("technical_analysis", {}),
                                "content": result.get("content", {}),
                                "words_count": result.get("words_count", 0)
                            }

                    self.logger.info(f"✓ Query {query_id} enrichie avec {len(query_info['serp_data']['position_data'])} positions")
                else:
                    self.logger.warning(f"Aucune correspondance SERP trouvée pour query {query_id}: '{query_text}'")

            # Sauvegarder le fichier consigne enrichi
            content = json.dumps(consigne_data, indent=2, ensure_ascii=False)

            async with aiofiles.open(self.consigne_file, 'w', encoding='utf-8') as f:
                await f.write(content)

            self.logger.info(f"✓ Fichier consigne enrichi avec données SERP")
            self.logger.info(f"✓ Fichier: {os.path.basename(self.consigne_file)}")
            return True

        except Exception as e:
            self.logger.error(f"Erreur intégration SERP: {e}")
            return False


async def main():
    """Fonction principale"""
    try:
        logger.info("=== DÉMARRAGE ANALYSEUR DOM SEO SIMPLIFIÉ ===")
        
        processor = SerpDomProcessor()
        consigne_manager = ConsigneManager()
        
        serp_files = processor.find_serp_files()
        if not serp_files:
            logger.warning("Aucun fichier SERP trouvé")
            return False
        
        logger.info(f"Traitement de {len(serp_files)} fichiers SERP")
        
        successful_analyses = []
        failed_count = 0
        
        start_time = datetime.now()
        
        for idx, filepath in enumerate(serp_files, 1):
            logger.info(f"[{idx}/{len(serp_files)}] {os.path.basename(filepath)}")
            
            result = await processor.process_serp_file(filepath)
            if result:
                successful_analyses.append(result)
                logger.info(f"  ✓ {result['total_results_analyzed']} résultats analysés")
            else:
                failed_count += 1
                logger.warning(f"  ✗ Échec")
        
        if not successful_analyses:
            logger.warning("Aucune analyse réussie")
            return False
        
        elapsed = (datetime.now() - start_time).total_seconds()
        logger.info(f"Traitement terminé en {elapsed:.1f}s: {len(successful_analyses)} succès, {failed_count} échecs")
        
        # Intégration dans le fichier consigne
        logger.info("Intégration des analyses SERP dans le fichier consigne...")
        save_success = await consigne_manager.integrate_serp_analyses(successful_analyses)
        
        if save_success:
            logger.info("=== ANALYSE COMPLÈTE TERMINÉE AVEC SUCCÈS ===")
            
            # Statistiques finales
            total_results = sum(a['total_results_analyzed'] for a in successful_analyses)
            
            # Comptage du contenu (headings + paragraphes mélangés)
            total_content_items = sum(
                len(r['content']) for a in successful_analyses for r in a['results']
            )
            
            # Comptage séparé pour stats
            total_headings = sum(
                sum(1 for k in r['content'].keys() if k.startswith('h'))
                for a in successful_analyses for r in a['results']
            )
            total_paragraphs = sum(
                sum(1 for k in r['content'].keys() if k.startswith('p'))
                for a in successful_analyses for r in a['results']
            )
            
            # Nouvelles statistiques techniques
            structured_data_count = sum(
                1 for a in successful_analyses 
                for r in a['results'] 
                if r['technical_analysis'].get('structured_data', {}).get('has_structured_data', False)
            )
            
            breadcrumbs_count = sum(
                1 for a in successful_analyses 
                for r in a['results'] 
                if r['technical_analysis'].get('breadcrumbs', {}).get('has_breadcrumbs', False)
            )
            
            toc_count = sum(
                1 for a in successful_analyses 
                for r in a['results'] 
                if r['technical_analysis'].get('table_of_contents', {}).get('has_toc', False)
            )
            
            webp_usage = sum(
                r['technical_analysis'].get('webp_analysis', {}).get('webp_percentage', 0)
                for a in successful_analyses 
                for r in a['results']
            ) / total_results if total_results > 0 else 0
            
            avg_mobile_score = sum(
                r['technical_analysis'].get('mobile_optimization', {}).get('mobile_first_score', 0)
                for a in successful_analyses 
                for r in a['results']
            ) / total_results if total_results > 0 else 0
            
            print(f"\n📊 STATISTIQUES FINALES:")
            print(f"   • Requêtes analysées: {len(successful_analyses)}")
            print(f"   • Résultats SERP analysés: {total_results}")
            print(f"   • Éléments de contenu extraits: {total_content_items}")
            print(f"     - Balises Hn: {total_headings}")
            print(f"     - Paragraphes: {total_paragraphs}")
            print(f"   • Pages avec données structurées: {structured_data_count}")
            print(f"   • Pages avec breadcrumbs: {breadcrumbs_count}")
            print(f"   • Pages avec table des matières: {toc_count}")
            print(f"   • Utilisation moyenne WebP: {webp_usage:.1f}%")
            print(f"   • Score Mobile First moyen: {avg_mobile_score:.1f}/100")
            print(f"   • Temps d'exécution: {elapsed:.1f}s")
            print(f"   • Vitesse: {total_results/elapsed:.1f} pages/sec")
            print(f"   • Fichier enrichi: {os.path.basename(consigne_manager.consigne_file) if consigne_manager.consigne_file else 'consigne.json'}")
            print(f"\n🎯 ANALYSES INCLUSES:")
            print(f"   ✅ Balises techniques (doctype, charset, viewport, meta)")
            print(f"   ✅ Décompte Hn (H1-H6) et paragraphes")
            print(f"   ✅ Contenu dans l'ordre du DOM (h1, h2_1, p_1, h3_1, p_2...)")
            print(f"   ✅ Données structurées JSON-LD")
            print(f"   ✅ Core Web Vitals & Performance")
            print(f"   ✅ Breadcrumbs (Schema + HTML)")
            print(f"   ✅ Table of Contents")
            print(f"   ✅ Analyse WebP et images modernes")
            print(f"   ✅ Mobile First (viewport, responsive, PWA)")
            
            return True
        else:
            logger.error("Échec de la sauvegarde")
            return False
    
    except KeyboardInterrupt:
        logger.info("Interruption utilisateur")
        return False
    except Exception as e:
        logger.error(f"Erreur critique: {e}", exc_info=True)
        return False


if __name__ == "__main__":
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    
    success = asyncio.run(main())
    exit(0 if success else 1)