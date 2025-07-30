import os
import json
import glob
import logging
import asyncio
import aiofiles
from openai import AsyncOpenAI
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
API_KEY = os.getenv('OPENAI_API_KEY')
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROCESSED_QUERIES_FILE = os.path.join(BASE_DIR, "processed_queries.json")
CONSIGNE_DIR = os.path.join(BASE_DIR, "static")
PROMPT_ID = "pmpt_6880b85244388194931adba72102ad0e0566462e25146fc8"
MAX_CONCURRENT_REQUESTS = 1  # Séquentiel pour garantir l'ordre

# Vérification des prérequis
if not API_KEY:
    logging.error("La variable OPENAI_API_KEY n'est pas définie")
    exit(1)

# Clients
client = AsyncOpenAI(api_key=API_KEY)

async def load_json_file(filepath: str) -> dict:
    """Charge un fichier JSON de manière asynchrone"""
    try:
        async with aiofiles.open(filepath, 'r', encoding='utf-8') as f:
            content = await f.read()
            return json.loads(content)
    except Exception as e:
        logging.error(f"Erreur lecture {filepath}: {str(e)}")
        return None

async def save_json_file(filepath: str, data: dict) -> bool:
    """Sauvegarde un fichier JSON de manière asynchrone"""
    try:
        async with aiofiles.open(filepath, 'w', encoding='utf-8') as f:
            await f.write(json.dumps(data, indent=2, ensure_ascii=False))
        return True
    except Exception as e:
        logging.error(f"Erreur écriture {filepath}: {str(e)}")
        return False

async def find_consigne_by_query_id(query_id: int) -> Optional[Dict]:
    """Trouve le fichier consigne contenant la requête spécifiée"""
    try:
        consigne_files = glob.glob(os.path.join(CONSIGNE_DIR, "consigne_*.json"))
        if not consigne_files:
            logging.error("Aucun fichier consigne trouvé")
            return None

        # Recherche par ordre chronologique inverse
        consigne_files.sort(key=os.path.getmtime, reverse=True)

        for filepath in consigne_files:
            data = await load_json_file(filepath)
            if data and any(q.get('id') == query_id for q in data.get('queries', [])):
                logging.info(f"Consigne trouvée pour ID {query_id}: {os.path.basename(filepath)}")
                return {'filepath': filepath, 'data': data}

        logging.error(f"Aucune consigne ne contient l'ID {query_id}")
        return None

    except Exception as e:
        logging.error(f"Erreur recherche consigne: {str(e)}")
        return None

async def get_query_processing_status(consigne_data: Dict) -> Dict[int, bool]:
    """Retourne le statut de traitement de chaque query dans une consigne"""
    status = {}
    for query in consigne_data.get('queries', []):
        query_id = query.get('id')
        has_response = 'agent_response' in query and query['agent_response'] is not None
        status[query_id] = has_response
    return status

async def find_next_unprocessed_id(consigne_data: Dict) -> Optional[int]:
    """Trouve le prochain ID non traité en respectant l'ordre séquentiel"""
    status = await get_query_processing_status(consigne_data)
    
    # Trier les IDs pour traitement séquentiel
    sorted_ids = sorted(status.keys())
    
    for query_id in sorted_ids:
        if not status[query_id]:
            # Vérifier que tous les IDs précédents ont été traités
            all_previous_processed = all(
                status.get(prev_id, False) 
                for prev_id in sorted_ids 
                if prev_id < query_id
            )
            
            if all_previous_processed:
                return query_id
            else:
                logging.warning(f"ID {query_id} trouvé non traité, mais des IDs précédents ne sont pas traités")
                # Retourner le premier ID non traité dans l'ordre
                for prev_id in sorted_ids:
                    if prev_id < query_id and not status[prev_id]:
                        return prev_id
                return query_id
    
    return None

async def validate_sequential_processing(consigne_data: Dict) -> Tuple[bool, List[int]]:
    """Valide que le traitement respecte l'ordre séquentiel"""
    status = await get_query_processing_status(consigne_data)
    sorted_ids = sorted(status.keys())
    
    missing_ids = []
    found_gap = False
    
    for query_id in sorted_ids:
        if not status[query_id]:
            missing_ids.append(query_id)
        elif missing_ids:  # Si on trouve un traité après des non-traités
            found_gap = True
    
    is_valid = not found_gap
    return is_valid, missing_ids

async def call_agent_openai(query_text: str) -> Optional[str]:
    """Appelle l'agent OpenAI avec le bon format de requête"""
    try:
        # Création de la réponse avec le prompt pré-enregistré
        response = await client.responses.create(
            prompt={"id": PROMPT_ID, "version": "3"},
            model="gpt-4o-mini",
            input=[{
                "type": "message",
                "role": "user",
                "content": query_text
            }],
            stream=False,
            timeout=30.0
        )

        # Attendre la complétion de la réponse
        while True:
            updated = await client.responses.retrieve(response.id)
            if updated.status == "completed":
                # Extraire le contenu textuel de la réponse
                for output in updated.output:
                    if output.type == "message" and output.content:
                        return output.content[0].text
                break
            elif updated.status in ["failed", "cancelled"]:
                logging.error(f"Échec de l'exécution: {updated.status}")
                return None
            await asyncio.sleep(1)

        return None

    except Exception as e:
        logging.error(f"Erreur API OpenAI: {str(e)}")
        return None

async def process_single_query_by_id(query_id: int) -> bool:
    """Traite une requête spécifique par son ID"""
    try:
        logging.info(f"Début traitement ID {query_id}")

        # 1. Trouver la consigne correspondante
        consigne_info = await find_consigne_by_query_id(query_id)
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

        # 4. Appel à l'agent OpenAI
        query_text = target_query['text']
        logging.info(f"Traitement de: {query_text[:50]}...")
        
        agent_response = await call_agent_openai(query_text)
        if not agent_response:
            logging.error(f"Échec de l'appel OpenAI pour ID {query_id}")
            return False

        # 5. Mise à jour de la consigne
        target_query['agent_response'] = agent_response
        target_query['processed_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # 6. Sauvegarde des modifications
        if not await save_json_file(consigne_info['filepath'], consigne_info['data']):
            logging.error(f"Échec sauvegarde pour ID {query_id}")
            return False

        logging.info(f"Succès traitement ID {query_id} - Réponse: {len(agent_response)} caractères")
        return True

    except Exception as e:
        logging.error(f"Échec traitement ID {query_id}: {str(e)}")
        return False

async def process_all_consignes_sequentially() -> Dict[str, int]:
    """Traite toutes les consignes de manière séquentielle"""
    results = {"total_processed": 0, "total_errors": 0, "files_processed": 0}
    
    try:
        # Lister tous les fichiers consigne
        consigne_files = glob.glob(os.path.join(CONSIGNE_DIR, "consigne_*.json"))
        consigne_files.sort(key=os.path.getmtime)  # Ordre chronologique
        
        for filepath in consigne_files:
            logging.info(f"Traitement du fichier: {os.path.basename(filepath)}")
            
            consigne_data = await load_json_file(filepath)
            if not consigne_data:
                continue
            
            # Validation initiale
            is_valid, missing_ids = await validate_sequential_processing(consigne_data)
            if not is_valid:
                logging.warning(f"Traitement non séquentiel détecté dans {os.path.basename(filepath)}")
            
            file_processed = 0
            file_errors = 0
            
            # Traitement séquentiel des IDs manquants
            while True:
                next_id = await find_next_unprocessed_id(consigne_data)
                if next_id is None:
                    logging.info(f"Toutes les queries traitées pour {os.path.basename(filepath)}")
                    break
                
                success = await process_single_query_by_id(next_id)
                if success:
                    file_processed += 1
                    # Recharger les données pour la prochaine itération
                    consigne_data = await load_json_file(filepath)
                else:
                    file_errors += 1
                    logging.error(f"Arrêt du traitement pour {os.path.basename(filepath)} après échec ID {next_id}")
                    break
                
                # Pause entre les requêtes pour éviter la surcharge
                await asyncio.sleep(1)
            
            results["total_processed"] += file_processed
            results["total_errors"] += file_errors
            results["files_processed"] += 1
            
            logging.info(f"Fichier {os.path.basename(filepath)}: {file_processed} traités, {file_errors} erreurs")
        
        return results
        
    except Exception as e:
        logging.critical(f"Erreur globale dans process_all_consignes_sequentially: {str(e)}")
        return results

async def main():
    """Point d'entrée principal du script"""
    try:
        logging.info("Début du traitement séquentiel des consignes")
        
        results = await process_all_consignes_sequentially()
        
        logging.info(f"""
        Résumé final:
        - Fichiers traités: {results['files_processed']}
        - Queries traitées: {results['total_processed']}
        - Erreurs: {results['total_errors']}
        """)
        
        return results['total_errors'] == 0
        
    except Exception as e:
        logging.critical(f"Erreur globale: {str(e)}")
        return False

if __name__ == "__main__":
    exit_code = 0 if asyncio.run(main()) else 1
    exit(exit_code)