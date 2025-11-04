import os
import json
import glob
import logging
import time
import requests
import unicodedata
import re
import asyncio
import aiohttp
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
PROMPT_FILE = os.path.join(BASE_DIR, "prompts", "fr", "search.md")

# Configuration Perplexity API
PERPLEXITY_API_URL = "https://api.perplexity.ai/chat/completions"
PERPLEXITY_MODEL = "sonar"

# Constantes pour gérer les réponses longues
REQUEST_TIMEOUT = 180.0
RETRY_DELAY = 10

# Configuration parallélisation
MAX_CONCURRENT_REQUESTS = 3  # Maximum 3 requêtes simultanées

def load_system_prompt() -> str:
    """Charge le prompt système depuis le fichier prompts/search.md"""
    try:
        with open(PROMPT_FILE, 'r', encoding='utf-8') as f:
            content = f.read()
            logging.info(f"Prompt système chargé depuis {PROMPT_FILE}")
            return content
    except FileNotFoundError:
        logging.error(f"Fichier prompt non trouvé: {PROMPT_FILE}")
        # Fallback basique si le fichier n'existe pas
        return "Tu es un agent spécialisé dans la recherche d'informations factuelles et statistiques."
    except Exception as e:
        logging.error(f"Erreur lecture prompt: {str(e)}")
        return "Tu es un agent spécialisé dans la recherche d'informations factuelles et statistiques."

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
        
def _coerce_agent_response(response, query_text: str) -> dict:
    """
    Garantit que la réponse agent est un dict.
    - Si `response` est déjà un dict → on le renvoie tel quel.
    - Si c'est une str (réponse brute non JSON) → on l'emballe dans un dict standardisé.
    """
    if isinstance(response, dict):
        return response
    return {
        "query": query_text,
        "summary": "Réponse non structurée renvoyée par le modèle (fallback).",
        "raw_response": str(response)
    }


async def call_agent_perplexity_sonar_async(query_text: str) -> Optional[dict]:
    """Version asynchrone de l'appel à l'agent Perplexity Sonar"""
    try:
        logging.info(f"Début appel async Perplexity Sonar pour: {query_text[:50]}...")
        
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
                    "content": load_system_prompt()
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
        
        # Appel asynchrone de l'API
        timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(PERPLEXITY_API_URL, json=payload, headers=headers) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logging.error(f"Erreur API Perplexity {response.status}: {error_text}")
                    return None
                
                response_data = await response.json()
        
        if 'choices' not in response_data or not response_data['choices']:
            logging.error("Réponse Perplexity vide ou mal formatée")
            return None
        
        response_content = response_data['choices'][0]['message']['content']
        
        # Extraire les citations si disponibles
        citations = response_data.get('citations', [])
        if citations:
            logging.info(f"Citations trouvées: {len(citations)} sources")
        
        logging.info(f"Réponse Sonar async reçue: {len(response_content)} caractères")
        
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
            # En cas d'échec de parsing, retourner la réponse brute
            logging.error("Échec parsing JSON de la réponse Sonar - retour fallback dict")
            return {
                "query": query_text,
                "summary": "Réponse non structurée renvoyée par le modèle (fallback).",
                "raw_response": response_content
            }
    except asyncio.TimeoutError:
        logging.error(f"Timeout async atteint ({REQUEST_TIMEOUT}s)")
        return None
    except aiohttp.ClientError as e:
        logging.error(f"Erreur requête HTTP async: {str(e)}")
        return None
    except Exception as e:
        logging.error(f"Erreur API Perplexity async: {str(e)}")
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
                    "content": load_system_prompt()
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
            # En cas d'échec de parsing, retourner la réponse brute
            logging.error("Échec parsing JSON de la réponse Sonar - retour fallback dict")
            return {
                "query": query_text,
                "summary": "Réponse non structurée renvoyée par le modèle (fallback).",
                "raw_response": response_content
            }
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
    try:
        if not isinstance(response_data, dict):
            logging.warning("Réponse n'est pas un dictionnaire")
            return False

        # Si c'est un fallback brut, on ne le valide pas comme 'riche', mais on l'accepte.
        if "raw_response" in response_data and not any(
            response_data.get(k) for k in ["shock_statistics", "expert_insights", "benchmark_data", "market_trends"]
        ):
            logging.info("Réponse fallback brute détectée (raw_response) – JSON minimal accepté.")
            return True

        required_fields = ['query', 'summary']
        for field in required_fields:
            if field not in response_data or not response_data[field]:
                logging.warning(f"Champ obligatoire manquant ou vide: {field}")
                return False

        data_fields = ['shock_statistics', 'expert_insights', 'benchmark_data', 'market_trends']
        has_data = any(response_data.get(f) for f in data_fields)

        if not has_data:
            logging.warning("Aucune donnée utile trouvée dans les champs principaux")
            return False

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

            if agent_response_data:
                # Sécurise: toujours un dict stocké
                target_query['agent_response'] = _coerce_agent_response(agent_response_data, query_text)

                # 6. Sauvegarde des modifications
                if save_json_file(consigne_info['filepath'], consigne_info['data']):
                    if validate_agent_response(agent_response_data, query_text):
                        logging.info(f"✅ Succès traitement ID {query_id} avec Sonar - Données JSON: {len(json.dumps(agent_response_data))} caractères")
                    else:
                        logging.info(f"✅ Succès traitement ID {query_id} avec Sonar - Réponse brute: {len(str(agent_response_data))} caractères")
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

def get_unprocessed_queries(consigne_data: Dict) -> List[int]:
    """Retourne la liste des IDs de requêtes non traitées par l'agent de recherche"""
    unprocessed_ids = []
    for query in consigne_data.get('queries', []):
        query_id = query.get('id')
        if 'agent_response' not in query or query['agent_response'] is None:
            unprocessed_ids.append(query_id)
    return sorted(unprocessed_ids)

async def process_single_query_async(query_id: int, semaphore: asyncio.Semaphore, consigne_data: Dict) -> Tuple[int, Optional[dict]]:
    """Traite une requête en mode asynchrone avec limitation de concurrence - retourne le résultat sans sauvegarder"""
    async with semaphore:
        try:
            logging.info(f"=== Début traitement async ID {query_id} ===")

            # Trouver la query spécifique dans les données en mémoire
            target_query = None
            for query in consigne_data.get('queries', []):
                if query.get('id') == query_id:
                    target_query = query
                    break
            
            if not target_query:
                logging.error(f"Query ID {query_id} non trouvée dans la consigne")
                return query_id, None

            # Vérifier si déjà traitée
            if 'agent_response' in target_query and target_query['agent_response']:
                logging.info(f"Query ID {query_id} déjà traitée")
                return query_id, target_query['agent_response']

            # Appel asynchrone à Perplexity Sonar
            query_text = target_query['text']
            logging.info(f"Traitement async avec recherche web: {query_text[:100]}...")
            
            agent_response_data = await call_agent_perplexity_sonar_async(query_text)

            if agent_response_data:
                # Sécurise: toujours un dict stocké
                coerced_response = _coerce_agent_response(agent_response_data, query_text)
                
                if validate_agent_response(agent_response_data, query_text):
                    logging.info(f"✅ Succès traitement async ID {query_id} - Données JSON: {len(json.dumps(agent_response_data))} caractères")
                else:
                    logging.info(f"✅ Succès traitement async ID {query_id} - Réponse brute: {len(str(agent_response_data))} caractères")
                
                return query_id, coerced_response
            else:
                logging.error(f"❌ Échec traitement async ID {query_id}")
                return query_id, None

        except Exception as e:
            logging.error(f"💥 Échec traitement async ID {query_id}: {str(e)}")
            return query_id, None

async def process_consigne_batch_parallel(consigne_filepath: str) -> Dict[str, int]:
    """Traite toutes les requêtes non traitées d'un fichier consigne en mode batch parallèle"""
    try:
        logging.info(f"🚀 Début traitement batch PARALLÈLE pour {os.path.basename(consigne_filepath)}")
        
        # Charger les données de consigne
        consigne_data = load_json_file(consigne_filepath)
        if not consigne_data:
            logging.error(f"Impossible de charger {consigne_filepath}")
            return {"total_processed": 0, "total_errors": 1}
        
        # Trouver les requêtes non traitées
        unprocessed_ids = get_unprocessed_queries(consigne_data)
        if not unprocessed_ids:
            logging.info(f"Toutes les requêtes sont déjà traitées dans {os.path.basename(consigne_filepath)}")
            return {"total_processed": 0, "total_errors": 0}
        
        logging.info(f"📊 Trouvé {len(unprocessed_ids)} requêtes à traiter en parallèle: {unprocessed_ids}")
        logging.info(f"🔧 Concurrence maximale: {MAX_CONCURRENT_REQUESTS} requêtes simultanées")
        
        # Créer un semaphore pour limiter la concurrence
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
        
        # Créer toutes les tâches parallèles
        tasks = [
            process_single_query_async(query_id, semaphore, consigne_data) 
            for query_id in unprocessed_ids
        ]
        
        # Exécuter toutes les tâches en parallèle
        logging.info(f"⚡ Lancement de {len(tasks)} tâches en parallèle...")
        results_list = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Compiler les résultats et mettre à jour les données en mémoire
        results = {
            "total_processed": 0,
            "total_errors": 0,
            "files_processed": 1,
            "total_characters": 0,
            "total_statistics": 0,
            "total_citations": 0,
            "total_tokens_used": 0,
            "average_response_length": 0,
            "web_enhanced_queries": 0,
        }
        
        processed_responses = {}  # Dictionnaire pour collecter les réponses
        
        # Analyser les résultats
        for result in results_list:
            if isinstance(result, Exception):
                logging.error(f"❌ Erreur async: {result}")
                results["total_errors"] += 1
                continue
                
            query_id, agent_response = result
            
            if agent_response is not None:
                results["total_processed"] += 1
                processed_responses[query_id] = agent_response
                logging.info(f"✅ Succès async pour requête {query_id}")
                
                # Calculer les statistiques
                if isinstance(agent_response, dict):
                    response_length = len(json.dumps(agent_response, ensure_ascii=False))
                    results["total_characters"] += response_length
                    results["total_statistics"] += len(agent_response.get('shock_statistics', []) or [])
                    results["total_citations"] += len(agent_response.get('_perplexity_citations', []) or [])
                    results["total_tokens_used"] += (agent_response.get('_perplexity_usage', {}) or {}).get('total_tokens', 0) or 0
                    if any(k in agent_response for k in ('_perplexity_citations', 'shock_statistics', 'benchmark_data')):
                        results["web_enhanced_queries"] += 1
            else:
                results["total_errors"] += 1
                logging.error(f"❌ Échec async pour requête {query_id}")
        
        # Mettre à jour les données en mémoire avec tous les résultats
        for query in consigne_data.get('queries', []):
            query_id = query.get('id')
            if query_id in processed_responses:
                query['agent_response'] = processed_responses[query_id]
                logging.info(f"📝 Résultat ajouté en mémoire pour requête ID {query_id}")
        
        # Sauvegarder TOUTES les modifications une seule fois
        if processed_responses:
            if save_json_file(consigne_filepath, consigne_data):
                logging.info(f"💾 ✅ Sauvegarde globale réussie: {len(processed_responses)} requêtes mises à jour dans {os.path.basename(consigne_filepath)}")
            else:
                logging.error(f"💾 ❌ Échec de la sauvegarde globale pour {os.path.basename(consigne_filepath)}")
                results["total_errors"] += len(processed_responses)
                results["total_processed"] = 0
        
        # Calculer la moyenne
        if results["total_processed"] > 0:
            results["average_response_length"] = results["total_characters"] // results["total_processed"]
        
        logging.info(f"🏁 Traitement parallèle terminé: {results['total_processed']}/{len(unprocessed_ids)} succès")
        return results
        
    except Exception as e:
        logging.error(f"Erreur lors du traitement batch parallèle de {consigne_filepath}: {str(e)}")
        return {"total_processed": 0, "total_errors": 1}

def process_consigne_batch(consigne_filepath: str) -> Dict[str, int]:
    """Traite toutes les requêtes non traitées d'un fichier consigne en mode batch (séquentiel par défaut)"""
    try:
        logging.info(f"Début traitement batch pour {os.path.basename(consigne_filepath)}")
        
        # Charger les données de consigne
        consigne_data = load_json_file(consigne_filepath)
        if not consigne_data:
            logging.error(f"Impossible de charger {consigne_filepath}")
            return {"total_processed": 0, "total_errors": 1}
        
        # Trouver les requêtes non traitées
        unprocessed_ids = get_unprocessed_queries(consigne_data)
        if not unprocessed_ids:
            logging.info(f"Toutes les requêtes sont déjà traitées dans {os.path.basename(consigne_filepath)}")
            return {"total_processed": 0, "total_errors": 0}
        
        logging.info(f"Trouvé {len(unprocessed_ids)} requêtes à traiter: {unprocessed_ids}")
        
        # Traiter chaque requête
        results = {
            "total_processed": 0,
            "total_errors": 0,
            "files_processed": 1,
            "total_characters": 0,
            "total_statistics": 0,
            "total_citations": 0,
            "total_tokens_used": 0,
            "average_response_length": 0,
            "web_enhanced_queries": 0,
        }
        
        for query_id in unprocessed_ids:
            success = process_single_query_by_id(query_id)
            if success:
                results["total_processed"] += 1
                
                # Recharger pour obtenir les stats de la réponse ajoutée
                updated_consigne = load_json_file(consigne_filepath)
                if updated_consigne:
                    for q in updated_consigne.get('queries', []):
                        if q.get('id') == query_id and 'agent_response' in q:
                            agent_response = q['agent_response']
                            if isinstance(agent_response, dict):
                                response_length = len(json.dumps(agent_response, ensure_ascii=False))
                                results["total_characters"] += response_length
                                results["total_statistics"] += len(agent_response.get('shock_statistics', []) or [])
                                results["total_citations"] += len(agent_response.get('_perplexity_citations', []) or [])
                                results["total_tokens_used"] += (agent_response.get('_perplexity_usage', {}) or {}).get('total_tokens', 0) or 0
                                if any(k in agent_response for k in ('_perplexity_citations', 'shock_statistics', 'benchmark_data')):
                                    results["web_enhanced_queries"] += 1
                            break
            else:
                results["total_errors"] += 1
                logging.error(f"Arrêt du batch après échec sur ID {query_id}")
                break
            
            # Pause entre requêtes pour éviter la surcharge API
            time.sleep(5)
        
        # Calculer la moyenne
        if results["total_processed"] > 0:
            results["average_response_length"] = results["total_characters"] // results["total_processed"]
        
        return results
        
    except Exception as e:
        logging.error(f"Erreur lors du traitement batch de {consigne_filepath}: {str(e)}")
        return {"total_processed": 0, "total_errors": 1}

def process_all_consignes_sequentially() -> Dict[str, int]:
    """Traite toutes les consignes de manière séquentielle avec gestion d'erreurs améliorée."""
    results = {
        "total_processed": 0,
        "total_errors": 0,
        "files_processed": 0,
        "total_characters": 0,
        "total_statistics": 0,
        "total_citations": 0,
        "total_tokens_used": 0,
        "average_response_length": 0,
        "web_enhanced_queries": 0,
    }

    try:
        consigne_files = glob.glob(os.path.join(CONSIGNE_DIR, "consigne_*.json"))
        consigne_files.sort(key=os.path.getmtime)

        for filepath in consigne_files:
            logging.info(f"📁 Traitement du fichier: {os.path.basename(filepath)}")

            consigne_data = load_json_file(filepath)
            if not consigne_data:
                logging.error(f"Impossible de charger {os.path.basename(filepath)} — on saute.")
                continue

            # Validation séquentielle (log-only)
            is_valid, missing_ids = validate_sequential_processing(consigne_data)
            if not is_valid:
                logging.warning(f"⚠️ Traitement non séquentiel détecté dans {os.path.basename(filepath)} — IDs manquants: {missing_ids}")

            # Compteurs par fichier
            file_processed = 0
            file_errors = 0
            file_response_length = 0
            file_stats_count = 0
            file_citations_count = 0
            file_tokens_count = 0
            file_web_enhanced_count = 0

            # Traitement séquentiel
            while True:
                next_id = find_next_unprocessed_id(consigne_data)
                if next_id is None:
                    logging.info(f"✅ Toutes les queries traitées pour {os.path.basename(filepath)}")
                    break

                success = process_single_query_by_id(next_id)
                if success:
                    file_processed += 1

                    # Recharger la consigne pour lire la réponse persistée
                    consigne_data = load_json_file(filepath)
                    if not consigne_data:
                        logging.error(f"Échec rechargement {os.path.basename(filepath)} après traitement de l'ID {next_id}")
                        file_errors += 1
                        break

                    # Récupérer la query et sa réponse
                    for q in consigne_data.get('queries', []):
                        if q.get('id') == next_id and 'agent_response' in q:
                            agent_response = q['agent_response']

                            # Longueur de réponse (str ou dict)
                            try:
                                if isinstance(agent_response, dict):
                                    file_response_length += len(json.dumps(agent_response, ensure_ascii=False))
                                else:
                                    file_response_length += len(str(agent_response))
                            except Exception as e:
                                logging.warning(f"Longueur non calculable pour ID {next_id}: {e}")

                            # Statistiques/citations/tokens + tag 'web_enhanced' (dict uniquement)
                            if isinstance(agent_response, dict):
                                file_stats_count += len(agent_response.get('shock_statistics', []) or [])
                                file_citations_count += len(agent_response.get('_perplexity_citations', []) or [])
                                file_tokens_count += (agent_response.get('_perplexity_usage', {}) or {}).get('total_tokens', 0) or 0

                                if any(k in agent_response for k in ('_perplexity_citations', 'shock_statistics', 'benchmark_data', 'market_trends')):
                                    file_web_enhanced_count += 1
                            else:
                                logging.warning(f"Réponse brute non JSON pour query {next_id} (fallback)")

                            break  # on sort du for des queries
                else:
                    file_errors += 1
                    logging.error(f"❌ Arrêt du traitement pour {os.path.basename(filepath)} après échec ID {next_id}")
                    break

                # Pause entre requêtes API
                time.sleep(5)

            # Agrégation des compteurs par fichier vers le total
            results["total_processed"] += file_processed
            results["total_errors"] += file_errors
            results["files_processed"] += 1
            results["total_characters"] += file_response_length
            results["total_statistics"] += file_stats_count
            results["total_citations"] += file_citations_count
            results["total_tokens_used"] += file_tokens_count
            results["web_enhanced_queries"] += file_web_enhanced_count

            logging.info(
                f"📊 Fichier {os.path.basename(filepath)} — "
                f"{file_processed} traités, {file_errors} erreurs, "
                f"{file_stats_count} stats, {file_citations_count} citations, "
                f"{file_tokens_count} tokens, {file_response_length} caractères."
            )

        # Moyenne des longueurs
        if results["total_processed"] > 0:
            results["average_response_length"] = results["total_characters"] // results["total_processed"]

        return results

    except Exception as e:
        logging.critical(f"💥 Erreur globale dans process_all_consignes_sequentially: {str(e)}")
        return results



async def process_latest_consigne_batch_parallel() -> bool:
    """Traite le dernier fichier consigne en mode batch parallèle asynchrone"""
    try:
        # Trouver le fichier consigne le plus récent
        consigne_files = glob.glob(os.path.join(CONSIGNE_DIR, "consigne_*.json"))
        if not consigne_files:
            logging.error("Aucun fichier consigne trouvé")
            return False
        
        consigne_files.sort(key=os.path.getmtime, reverse=True)
        latest_consigne = consigne_files[0]
        
        logging.info(f"📁 Traitement PARALLÈLE du fichier le plus récent: {os.path.basename(latest_consigne)}")
        
        start_time = datetime.now()
        results = await process_consigne_batch_parallel(latest_consigne)
        end_time = datetime.now()
        
        duration = end_time - start_time
        
        logging.info(f"""
📈 === RÉSUMÉ BATCH PARALLÈLE CONSIGNE {os.path.basename(latest_consigne)} ===
- Queries traitées: {results['total_processed']}
- Queries enrichies web: {results['web_enhanced_queries']}
- Erreurs: {results['total_errors']}
- Caractères générés: {results['total_characters']:,}
- Statistiques trouvées: {results['total_statistics']}
- Citations web: {results['total_citations']}
- Tokens utilisés: {results['total_tokens_used']:,}
- Longueur moyenne: {results['average_response_length']} caractères
- Durée totale: {duration}
- Concurrence utilisée: {MAX_CONCURRENT_REQUESTS} requêtes simultanées
- Succès: {results['total_errors'] == 0}
===============================================""")
        
        return results['total_errors'] == 0
        
    except Exception as e:
        logging.error(f"Erreur lors du traitement batch parallèle consigne: {str(e)}")
        return False

def process_latest_consigne_batch() -> bool:
    """Traite le dernier fichier consigne en mode batch automatique"""
    try:
        # Trouver le fichier consigne le plus récent
        consigne_files = glob.glob(os.path.join(CONSIGNE_DIR, "consigne_*.json"))
        if not consigne_files:
            logging.error("Aucun fichier consigne trouvé")
            return False
        
        consigne_files.sort(key=os.path.getmtime, reverse=True)
        latest_consigne = consigne_files[0]
        
        logging.info(f"📁 Traitement du fichier le plus récent: {os.path.basename(latest_consigne)}")
        
        start_time = datetime.now()
        results = process_consigne_batch(latest_consigne)
        end_time = datetime.now()
        
        duration = end_time - start_time
        
        logging.info(f"""
📈 === RÉSUMÉ BATCH CONSIGNE {os.path.basename(latest_consigne)} ===
- Queries traitées: {results['total_processed']}
- Queries enrichies web: {results['web_enhanced_queries']}
- Erreurs: {results['total_errors']}
- Caractères générés: {results['total_characters']:,}
- Statistiques trouvées: {results['total_statistics']}
- Citations web: {results['total_citations']}
- Tokens utilisés: {results['total_tokens_used']:,}
- Longueur moyenne: {results['average_response_length']} caractères
- Durée totale: {duration}
- Succès: {results['total_errors'] == 0}
===============================================""")
        
        return results['total_errors'] == 0
        
    except Exception as e:
        logging.error(f"Erreur lors du traitement batch consigne: {str(e)}")
        return False

async def main_async():
    """Version asynchrone de main() pour supporter le traitement parallèle"""
    import sys
    
    try:
        # Vérifier les arguments de ligne de commande
        if len(sys.argv) > 1:
            arg = sys.argv[1]
            
            if arg in ["--batch", "-b"]:
                logging.info("🚀 Mode batch: traitement séquentiel du fichier consigne le plus récent")
                return process_latest_consigne_batch()
            elif arg in ["--parallel", "-p"]:
                logging.info("⚡ Mode batch parallèle: traitement asynchrone du fichier consigne le plus récent")
                return await process_latest_consigne_batch_parallel()
            elif arg in ["--help", "-h"]:
                print("""
🔍 Agent de Recherche Web avec Perplexity Sonar

UTILISATION:
  python search.py [OPTIONS]

OPTIONS:
  --batch, -b       Traite toutes les requêtes non traitées du fichier consigne le plus récent (séquentiel)
  --parallel, -p    Traite toutes les requêtes non traitées en parallèle (3 requêtes simultanées)
  --help, -h        Affiche cette aide
  
SANS OPTION:
  Traite tous les fichiers consigne séquentiellement (comportement par défaut)

EXEMPLES:
  python search.py --batch       # Traite le dernier fichier consigne (séquentiel)
  python search.py --parallel    # Traite le dernier fichier consigne (3 parallèles)
  python search.py              # Traite tous les fichiers consigne
                """)
                return True
            else:
                logging.warning(f"Argument inconnu: {arg}. Utilisez --help pour voir les options disponibles.")
                return False
        
        # Comportement par défaut: traitement séquentiel de toutes les consignes
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

def main():
    """Point d'entrée principal du script avec reporting détaillé"""
    try:
        # Exécuter la version asynchrone
        return asyncio.run(main_async())
    except Exception as e:
        logging.critical(f"💥 Erreur lors du lancement asynchrone: {str(e)}")
        return False

if __name__ == "__main__":
    exit_code = 0 if main() else 1
    exit(exit_code)