import os
import json
import glob
import logging
import asyncio
import aiofiles
from openai import AsyncOpenAI
from datetime import datetime
from collections import defaultdict

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
MAX_CONCURRENT_REQUESTS = 5  # Limite de requêtes simultanées à OpenAI

# Vérification des prérequis
if not API_KEY:
    logging.error("La variable OPENAI_API_KEY n'est pas définie")
    exit(1)

# Clients
client = AsyncOpenAI(api_key=API_KEY)
semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

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

async def find_matching_consigne(query_id: int) -> dict:
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
                logging.info(f"Consigne trouvée: {os.path.basename(filepath)}")
                return {'filepath': filepath, 'data': data}

        logging.error(f"Aucune consigne ne contient l'ID {query_id}")
        return None

    except Exception as e:
        logging.error(f"Erreur recherche consigne: {str(e)}")
        return None

async def call_agent_openai(query_text: str) -> str:
    """Appelle l'agent OpenAI avec le bon format de requête"""
    try:
        async with semaphore:
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

async def process_single_query(query_hash: str, query_details: dict, processed_data: dict) -> bool:
    """Traite une requête individuelle avec gestion complète"""
    query_id = query_details['id']
    query_text = query_details['text']

    try:
        logging.info(f"Début traitement ID {query_id}: {query_text[:50]}...")

        # 1. Trouver la consigne correspondante
        consigne_info = await find_matching_consigne(query_id)
        if not consigne_info:
            return False

        # 2. Appel à l'agent OpenAI
        agent_response = await call_agent_openai(query_text)
        if not agent_response:
            return False

        # 3. Mise à jour de la consigne
        for query in consigne_info['data']['queries']:
            if query['id'] == query_id:
                query['agent_response'] = agent_response
                break

        # 4. Sauvegarde des modifications
        if not await save_json_file(consigne_info['filepath'], consigne_info['data']):
            return False

        # 5. Mise à jour du statut
        processed_data['query_details'][query_hash].update({
            'treated': True,
            'treated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'response_length': len(agent_response)
        })

        logging.info(f"Succès traitement ID {query_id}")
        return True

    except Exception as e:
        logging.error(f"Échec traitement ID {query_id}: {str(e)}")
        return False

async def main():
    """Point d'entrée principal du script"""
    try:
        # 1. Chargement des requêtes à traiter
        processed_data = await load_json_file(PROCESSED_QUERIES_FILE)
        if not processed_data:
            raise ValueError("Impossible de charger processed_queries.json")

        # 2. Filtrage des requêtes non traitées
        untreated_queries = [
            (qh, qd) for qh in processed_data.get('processed_queries', [])
            for qd in [processed_data['query_details'].get(qh, {})]
            if not qd.get('treated', False)
        ]

        if not untreated_queries:
            logging.info("Aucune requête à traiter")
            return True

        logging.info(f"Début traitement de {len(untreated_queries)} requêtes")

        # 3. Traitement parallèle avec limitation de concurrence
        tasks = [
            process_single_query(qh, qd, processed_data)
            for qh, qd in untreated_queries
        ]
        results = await asyncio.gather(*tasks)

        # 4. Statistiques et sauvegarde finale
        success_count = sum(results)
        logging.info(f"Résumé: {success_count} succès / {len(untreated_queries)} requêtes")

        if not await save_json_file(PROCESSED_QUERIES_FILE, processed_data):
            raise RuntimeError("Échec sauvegarde finale")

        return success_count == len(untreated_queries)

    except Exception as e:
        logging.critical(f"Erreur globale: {str(e)}")
        return False

if __name__ == "__main__":
    exit_code = 0 if asyncio.run(main()) else 1
    exit(exit_code)