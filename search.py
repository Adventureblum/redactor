import os
import json
import glob
import logging
import time
import requests
import unicodedata
import re
from datetime import datetime
from collections import defaultdict
from typing import Dict, List, Tuple, Optional

# Configuration initiale
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('processing.log')
    ]
)

# Constantes
API_KEY = os.getenv('PERPLEXITY_API_KEY')
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROCESSED_QUERIES_FILE = os.path.join(BASE_DIR, "processed_queries.json")
CONSIGNE_DIR = os.path.join(BASE_DIR, "static")

# Configuration Perplexity API
PERPLEXITY_API_URL = "https://api.perplexity.ai/chat/completions"
PERPLEXITY_MODEL = "sonar"

# Constantes pour gérer les réponses longues
REQUEST_TIMEOUT = 180.0
RETRY_DELAY = 10

# Prompt système intégré
AGENT_SYSTEM_PROMPT = """# Agent de Recherche Web Orienté Content Marketing Sophistiqué avec Sources Liens

Tu es un agent GPT spécialisé dans la recherche d'informations **STATISTIQUES et FACTUELLES** pour alimenter des articles de niveau Waalaxy/Buffer/Wirecutter.

L'utilisateur te fournira une requête spécifique à investiguer dans n'importe quelle langue.

Ta mission : **Collecter des DONNÉES CHIFFRÉES, STATISTIQUES CHOC et PREUVES CONCRÈTES** avec leurs **sources officielles** (lien direct vers l'étude, rapport ou publication originale), afin de donner une crédibilité maximale à un article sophistiqué orienté conversion.

## 🌐 Adaptation linguistique
**IMPORTANT** : Détecte automatiquement la langue de la requête utilisateur et réponds dans cette même langue.

## 🎯 Objectif principal :
Fournir des données utilisables dans un contenu marketing, **accompagnées d'URLs vérifiables**.

---

## ⚠️ Contraintes techniques strictes

1. **Chaque entrée de données doit avoir un champ `source_url` avec un lien complet vers la source originale**.
2. Priorité absolue aux sources Tier 1 → Tier 4 (gouvernements, universités, médias de référence, rapports officiels, Statista, Gartner...).
3. Bannir : blogs personnels, forums, communiqués de presse promotionnels.

---

## ✅ Format JSON enrichi avec sources

Réponds UNIQUEMENT avec un JSON valide dans ce format exact :

{
  "query": "[REQUÊTE UTILISATEUR EN TEXTE ORIGINAL]",
  "summary": "Résumé orienté content marketing avec les 2-3 statistiques les plus percutantes pour accrocher le lecteur [LANGUE DE LA REQUÊTE]",
  
  "shock_statistics": [
    {
      "statistic": "68% des entreprises échouent à...",
      "source_credibility": "Étude McKinsey 2024 sur 10,000 entreprises",
      "source_url": "https://www.mckinsey.com/lien-de-l-etude",
      "usage_potential": "Accroche d'introduction pour créer l'urgence",
      "context": "Contexte précis de la mesure"
    }
  ],
  
  "expert_insights": [
    {
      "insight": "Les experts recommandent X parce que Y",
      "authority_source": "Professeur MIT / Directeur BCG / etc.",
      "source_url": "https://www.exemple.com/etude",
      "credibility_boost": "Comment ça renforce l'autorité de l'article"
    }
  ],
  
  "benchmark_data": [
    {
      "metric": "ROI moyen de +127%",
      "sample_size": "Étude sur 5,000 utilisateurs",
      "methodology": "Mesure sur 12 mois, groupe contrôle",
      "source_url": "https://www.exemple.com/rapport",
      "article_usage": "Preuve de résultats pour section testimonials"
    }
  ],
  
  "market_trends": [
    {
      "trend": "Croissance de 340% en 2 ans",
      "supporting_data": "Données chiffrées précises",
      "source_url": "https://www.exemple.com/data",
      "future_projection": "Prévisions 2025-2026 si disponibles",
      "commercial_opportunity": "Comment ça justifie l'urgence d'agir"
    }
  ],
  
  "competitive_landscape": [
    {
      "comparison_point": "Solution A vs Solution B",
      "quantified_difference": "2.3x plus efficace selon...",
      "source_url": "https://www.exemple.com/comparatif",
      "source_reliability": "Étude indépendante, pas promotionnelle"
    }
  ],
  
  "technical_depth": "débutant/intermédiaire/expert",
  
  "credibility_boosters": [
    "Source gouvernementale française (Ministère)",
    "Étude peer-reviewed dans Nature/Science",
    "Rapport officiel Commission Européenne",
    "Meta-analyse de 47 études sur 10 ans"
  ],
  
  "content_marketing_angles": [
    "Angle 1: Problème urgent révélé par les stats",
    "Angle 2: Opportunité de marché émergente", 
    "Angle 3: Méthode prouvée par les benchmarks"
  ],
  
  "hook_potential": {
    "intro_hooks": [
      "Stat choc pour ouvrir l'article",
      "Fait surprenant contre-intuitif"
    ],
    "authority_signals": [
      "Citation d'expert pour légitimité",
      "Référence étude prestigieuse"  
    ],
    "social_proof": [
      "Nombre d'utilisateurs/clients",
      "Résultats moyens documentés"
    ]
  },
  
  "date_accessed": "YYYY-MM-DD",
  "confidence_score": 0.95,
  "commercial_readiness": "Prêt pour article sophistiqué orienté conversion"
}

---"""

# Vérification des prérequis
if not API_KEY:
    logging.error("La variable PERPLEXITY_API_KEY n'est pas définie")
    exit(1)

def load_json_file(filepath: str) -> dict:
    """Charge un fichier JSON"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logging.error(f"Erreur lecture {filepath}: {str(e)}")
        return None

def save_json_file(filepath: str, data: dict) -> bool:
    """Sauvegarde un fichier JSON"""
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logging.error(f"Erreur écriture {filepath}: {str(e)}")
        return False

def find_consigne_by_query_id(query_id: int) -> Optional[Dict]:
    """Trouve le fichier consigne contenant la requête spécifiée"""
    try:
        consigne_files = glob.glob(os.path.join(CONSIGNE_DIR, "consigne_*.json"))
        if not consigne_files:
            logging.error("Aucun fichier consigne trouvé")
            return None

        consigne_files.sort(key=os.path.getmtime, reverse=True)

        for filepath in consigne_files:
            data = load_json_file(filepath)
            if data and any(q.get('id') == query_id for q in data.get('queries', [])):
                logging.info(f"Consigne trouvée pour ID {query_id}: {os.path.basename(filepath)}")
                return {'filepath': filepath, 'data': data}

        logging.error(f"Aucune consigne ne contient l'ID {query_id}")
        return None

    except Exception as e:
        logging.error(f"Erreur recherche consigne: {str(e)}")
        return None

def get_query_processing_status(consigne_data: Dict) -> Dict[int, bool]:
    """Retourne le statut de traitement de chaque query dans une consigne"""
    status = {}
    for query in consigne_data.get('queries', []):
        query_id = query.get('id')
        has_response = 'agent_response' in query and query['agent_response'] is not None
        status[query_id] = has_response
    return status

def find_next_unprocessed_id(consigne_data: Dict) -> Optional[int]:
    """Trouve le prochain ID non traité en respectant l'ordre séquentiel"""
    status = get_query_processing_status(consigne_data)
    
    sorted_ids = sorted(status.keys())
    
    for query_id in sorted_ids:
        if not status[query_id]:
            all_previous_processed = all(
                status.get(prev_id, False) 
                for prev_id in sorted_ids 
                if prev_id < query_id
            )
            
            if all_previous_processed:
                return query_id
            else:
                logging.warning(f"ID {query_id} trouvé non traité, mais des IDs précédents ne sont pas traités")
                for prev_id in sorted_ids:
                    if prev_id < query_id and not status[prev_id]:
                        return prev_id
                return query_id
    
    return None

def validate_sequential_processing(consigne_data: Dict) -> Tuple[bool, List[int]]:
    """Valide que le traitement respecte l'ordre séquentiel"""
    status = get_query_processing_status(consigne_data)
    sorted_ids = sorted(status.keys())
    
    missing_ids = []
    found_gap = False
    
    for query_id in sorted_ids:
        if not status[query_id]:
            missing_ids.append(query_id)
        elif missing_ids:
            found_gap = True
    
    is_valid = not found_gap
    return is_valid, missing_ids

def _sanitize_for_json(raw: str) -> str:
    """Nettoie le texte pour une meilleure compatibilité JSON"""
    s = raw

    # 1) Normalisation unicode
    s = unicodedata.normalize("NFKC", s)

    # 2) Remplacer guillemets courbes par droits
    s = s.replace("“", '"').replace("”", '"')  # guillemets typographiques
    s = s.replace("«", '"').replace("»", '"')  # guillemets français
    s = s.replace("‟", '"').replace("‶", '"')  # autres variantes
    s = s.replace("’", "'").replace("‘", "'")  # apostrophes


    # 3) Remplacer espaces exotiques par espace simple
    s = re.sub(r'[\u00A0\u2007\u202F\u2009\u200A\u200B\u2060]', ' ', s)

    # 4) Corriger clés entourées de mauvais guillemets => "key":
    s = re.sub(r'([{\[,]\s*)"([^"]+)"\s*:(?=\s*[^"])', r'\1"\2":', s)

    # 5) Supprimer virgules traînantes avant } ou ]
    s = re.sub(r',\s*(?=[}\]])', '', s)

    # 6) Élaguer lignes 100% blanches multiples (cosmétique)
    s = re.sub(r'\n\s*\n+', '\n', s)

    s = re.sub(r'([{,]\s*)([A-Za-z0-9_\-]+)(\s*):', r'\1"\2"\3:', s)

    return s.strip()

def extract_json_from_response(response_text: str) -> Optional[dict]:
    """Extrait et parse le JSON de la réponse Perplexity"""
    try:
        cleaned_response = response_text.strip()
        json_start = cleaned_response.find('{')
        json_end = cleaned_response.rfind('}')

        if json_start == -1 or json_end == -1:
            logging.error("Aucun JSON trouvé dans la réponse")
            return None

        json_content = cleaned_response[json_start:json_end + 1]

        # Nettoyage du JSON
        json_content = _sanitize_for_json(json_content)

        # Log pour debug
        logging.debug("=== DEBUG JSON COMPLET ===")
        logging.debug(json_content[:1000] + "..." if len(json_content) > 1000 else json_content)
        logging.debug("=== FIN DEBUG JSON ===")

        # Sauvegarde pour inspection
        with open("debug_sonar_response.json", "w", encoding="utf-8") as f:
            f.write(json_content)

        # Parser le JSON
        parsed_json = json.loads(json_content)
        
        # Validation des champs obligatoires
        required_fields = ['query', 'summary']
        for field in required_fields:
            if field not in parsed_json:
                logging.warning(f"Champ obligatoire manquant: {field}")
        
        return parsed_json
        
    except json.JSONDecodeError as e:
        logging.error(f"Erreur parsing JSON: {str(e)}")
        logging.debug(f"Contenu à parser: {response_text[:500]}...")
        return None
    except Exception as e:
        logging.error(f"Erreur extraction JSON: {str(e)}")
        return None

def call_agent_perplexity_sonar(query_text: str) -> Optional[dict]:
    """Appelle l'agent Perplexity Sonar avec requests et retourne le JSON parsé"""
    try:
        logging.info(f"Début appel Perplexity Sonar pour: {query_text[:50]}...")
        
        # Headers pour l'API Perplexity
        headers = {
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json"
        }
        
        # Construction du payload pour Perplexity
        payload = {
            "model": PERPLEXITY_MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": AGENT_SYSTEM_PROMPT
                },
                {
                    "role": "user", 
                    "content": query_text
                }
            ],
            "temperature": 0.7,
            "max_tokens": 4000,
            "top_p": 0.9,
            "return_citations": True,
            "return_images": False,
            "return_related_questions": False,
            "search_recency_filter": "month",
            "top_k": 0,
            "stream": False,
            "presence_penalty": 0,
            "frequency_penalty": 1
        }
        
        # Appel de l'API avec requests
        response = requests.post(
            PERPLEXITY_API_URL, 
            json=payload, 
            headers=headers, 
            timeout=REQUEST_TIMEOUT
        )
        
        if response.status_code != 200:
            logging.error(f"Erreur API Perplexity {response.status_code}: {response.text}")
            return None
        
        response_data = response.json()
        
        if 'choices' not in response_data or not response_data['choices']:
            logging.error("Réponse Perplexity vide ou mal formatée")
            return None
        
        response_content = response_data['choices'][0]['message']['content']
        
        # Extraire les citations si disponibles
        citations = response_data.get('citations', [])
        if citations:
            logging.info(f"Citations trouvées: {len(citations)} sources")
        
        logging.info(f"Réponse Sonar reçue: {len(response_content)} caractères")
        
        # Extraire et valider le JSON
        parsed_result = extract_json_from_response(response_content)
        
        if parsed_result:
            # Ajouter les métadonnées Perplexity si disponibles
            if citations:
                parsed_result['_perplexity_citations'] = citations
            
            usage_info = response_data.get('usage', {})
            if usage_info:
                parsed_result['_perplexity_usage'] = usage_info
            
            logging.info(f"JSON parsé avec succès: {len(str(parsed_result))} caractères")
            return parsed_result
        else:
            logging.error("Échec parsing JSON de la réponse Sonar")
            return None

    except requests.exceptions.Timeout:
        logging.error(f"Timeout de requête atteint ({REQUEST_TIMEOUT}s)")
        return None
    except requests.exceptions.RequestException as e:
        logging.error(f"Erreur requête HTTP: {str(e)}")
        return None
    except Exception as e:
        logging.error(f"Erreur API Perplexity: {str(e)}")
        return None

def validate_agent_response(response_data: dict, query_text: str) -> bool:
    """Valide que la réponse de l'agent contient les données nécessaires"""
    try:
        # Vérifications de base
        if not isinstance(response_data, dict):
            logging.warning("Réponse n'est pas un dictionnaire")
            return False
        
        # Vérifier les champs obligatoires
        required_fields = ['query', 'summary']
        for field in required_fields:
            if field not in response_data or not response_data[field]:
                logging.warning(f"Champ obligatoire manquant ou vide: {field}")
                return False
        
        # Vérifier qu'il y a au moins quelques données utiles
        data_fields = ['shock_statistics', 'expert_insights', 'benchmark_data', 'market_trends']
        has_data = any(
            field in response_data and response_data[field] and len(response_data[field]) > 0 
            for field in data_fields
        )
        
        if not has_data:
            logging.warning("Aucune donnée utile trouvée dans les champs principaux")
            return False
        
        # Validation spécifique Perplexity: vérifier la présence de citations récentes
        citations = response_data.get('_perplexity_citations', [])
        if citations:
            logging.info(f"✅ Réponse enrichie avec {len(citations)} sources web récentes")
        
        return True
        
    except Exception as e:
        logging.error(f"Erreur validation réponse agent: {str(e)}")
        return False

def process_single_query_by_id(query_id: int) -> bool:
    """Traite une requête spécifique par son ID avec l'agent Perplexity Sonar"""
    try:
        logging.info(f"=== Début traitement ID {query_id} avec Perplexity Sonar ===")

        # 1. Trouver la consigne correspondante
        consigne_info = find_consigne_by_query_id(query_id)
        if not consigne_info:
            return False

        # 2. Trouver la query spécifique
        target_query = None
        for query in consigne_info['data']['queries']:
            if query['id'] == query_id:
                target_query = query
                break
        
        if not target_query:
            logging.error(f"Query ID {query_id} non trouvée dans la consigne")
            return False

        # 3. Vérifier si déjà traitée
        if 'agent_response' in target_query and target_query['agent_response']:
            logging.info(f"Query ID {query_id} déjà traitée, passage au suivant")
            return True

        # 4. Appel à Perplexity Sonar avec retry si nécessaire
        query_text = target_query['text']
        logging.info(f"Traitement avec recherche web: {query_text[:100]}...")
        
        max_retries = 3
        for attempt in range(max_retries):
            logging.info(f"Tentative {attempt + 1}/{max_retries} pour ID {query_id}")
            
            agent_response_data = call_agent_perplexity_sonar(query_text)
            
            if agent_response_data and validate_agent_response(agent_response_data, query_text):
                # 5. Mise à jour de la consigne avec toutes les données structurées
                target_query['agent_response'] = agent_response_data
                target_query['processed_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                target_query['response_length'] = len(json.dumps(agent_response_data))
                target_query['processing_attempts'] = attempt + 1
                target_query['agent_version'] = "perplexity_sonar_content_marketing_v2"
                
                # Ajout des métadonnées sur la réponse avec infos Perplexity
                citations_count = len(agent_response_data.get('_perplexity_citations', []))
                usage_info = agent_response_data.get('_perplexity_usage', {})
                
                target_query['response_metadata'] = {
                    'statistics_count': len(agent_response_data.get('shock_statistics', [])),
                    'insights_count': len(agent_response_data.get('expert_insights', [])),
                    'benchmarks_count': len(agent_response_data.get('benchmark_data', [])),
                    'trends_count': len(agent_response_data.get('market_trends', [])),
                    'confidence_score': agent_response_data.get('confidence_score', 0),
                    'technical_depth': agent_response_data.get('technical_depth', 'unknown'),
                    'commercial_readiness': agent_response_data.get('commercial_readiness', 'unknown'),
                    'perplexity_citations': citations_count,
                    'perplexity_tokens_used': usage_info.get('total_tokens', 0),
                    'web_search_performed': citations_count > 0
                }

                # 6. Sauvegarde des modifications
                if save_json_file(consigne_info['filepath'], consigne_info['data']):
                    logging.info(f"✅ Succès traitement ID {query_id} avec Sonar - Données: {len(json.dumps(agent_response_data))} caractères")
                    logging.info(f"   📊 Stats: {target_query['response_metadata']['statistics_count']} stats, {citations_count} sources web")
                    return True
                else:
                    logging.error(f"Échec sauvegarde pour ID {query_id}")
                    return False
            else:
                logging.warning(f"Tentative {attempt + 1} échouée pour ID {query_id}")
                if attempt < max_retries - 1:
                    time.sleep(RETRY_DELAY)

        logging.error(f"❌ Échec définitif traitement ID {query_id} après {max_retries} tentatives")
        return False

    except Exception as e:
        logging.error(f"💥 Échec traitement ID {query_id}: {str(e)}")
        return False

def process_all_consignes_sequentially() -> Dict[str, int]:
    """Traite toutes les consignes de manière séquentielle avec gestion d'erreurs améliorée"""
    results = {
        "total_processed": 0, 
        "total_errors": 0, 
        "files_processed": 0,
        "total_characters": 0,
        "total_statistics": 0,
        "total_citations": 0,
        "total_tokens_used": 0,
        "average_response_length": 0,
        "web_enhanced_queries": 0
    }
    
    try:
        consigne_files = glob.glob(os.path.join(CONSIGNE_DIR, "consigne_*.json"))
        consigne_files.sort(key=os.path.getmtime)
        
        total_response_length = 0
        total_stats_count = 0
        total_citations_count = 0
        total_tokens_count = 0
        web_enhanced_count = 0
        
        for filepath in consigne_files:
            logging.info(f"📁 Traitement du fichier: {os.path.basename(filepath)}")
            
            consigne_data = load_json_file(filepath)
            if not consigne_data:
                continue
            
            is_valid, missing_ids = validate_sequential_processing(consigne_data)
            if not is_valid:
                logging.warning(f"⚠️ Traitement non séquentiel détecté dans {os.path.basename(filepath)}")
            
            file_processed = 0
            file_errors = 0
            
            # Traitement séquentiel des IDs manquants
            while True:
                next_id = find_next_unprocessed_id(consigne_data)
                if next_id is None:
                    logging.info(f"✅ Toutes les queries traitées pour {os.path.basename(filepath)}")
                    break
                
                success = process_single_query_by_id(next_id)
                if success:
                    file_processed += 1
                    # Recharger les données pour la prochaine itération
                    consigne_data = load_json_file(filepath)
                    
                    # Calculer les statistiques détaillées incluant Perplexity
                    for query in consigne_data.get('queries', []):
                        if query.get('id') == next_id and 'response_metadata' in query:
                            metadata = query['response_metadata']
                            total_response_length += query.get('response_length', 0)
                            total_stats_count += metadata.get('statistics_count', 0)
                            total_citations_count += metadata.get('perplexity_citations', 0)
                            total_tokens_count += metadata.get('perplexity_tokens_used', 0)
                            if metadata.get('web_search_performed', False):
                                web_enhanced_count += 1
                else:
                    file_errors += 1
                    logging.error(f"❌ Arrêt du traitement pour {os.path.basename(filepath)} après échec ID {next_id}")
                    break
                
                # Pause entre les requêtes Perplexity
                time.sleep(5)
            
            results["total_processed"] += file_processed
            results["total_errors"] += file_errors
            results["files_processed"] += 1
            results["total_characters"] += total_response_length
            results["total_statistics"] += total_stats_count
            results["total_citations"] += total_citations_count
            results["total_tokens_used"] += total_tokens_count
            results["web_enhanced_queries"] += web_enhanced_count
            
            logging.info(f"📊 Fichier {os.path.basename(filepath)}: {file_processed} traités, {file_errors} erreurs")
        
        # Calculs des moyennes
        if results["total_processed"] > 0:
            results["average_response_length"] = results["total_characters"] // results["total_processed"]
        
        return results
        
    except Exception as e:
        logging.critical(f"💥 Erreur globale dans process_all_consignes_sequentially: {str(e)}")
        return results

def main():
    """Point d'entrée principal du script avec reporting détaillé"""
    try:
        logging.info("🚀 Début du traitement avec Perplexity Sonar Content Marketing (requests)")
        
        start_time = datetime.now()
        results = process_all_consignes_sequentially()
        end_time = datetime.now()
        
        duration = end_time - start_time
        
        logging.info(f"""
📈 === RÉSUMÉ FINAL PERPLEXITY SONAR (REQUESTS) ===
- Fichiers traités: {results['files_processed']}
- Queries traitées: {results['total_processed']}
- Queries enrichies web: {results['web_enhanced_queries']}
- Erreurs: {results['total_errors']}
- Caractères générés: {results['total_characters']:,}
- Statistiques trouvées: {results['total_statistics']}
- Citations web: {results['total_citations']}
- Tokens utilisés: {results['total_tokens_used']:,}
- Longueur moyenne: {results['average_response_length']} caractères
- Durée totale: {duration}
- Succès global: {results['total_errors'] == 0}
===============================================""")
        
        return results['total_errors'] == 0
        
    except Exception as e:
        logging.critical(f"💥 Erreur globale: {str(e)}")
        return False

if __name__ == "__main__":
    exit_code = 0 if main() else 1
    exit(exit_code)