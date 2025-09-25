import os
import glob
import json
import aiofiles
import logging
import re
from typing import List, Dict, Tuple, Optional
from config import BASE_DIR, RESULTS_DIR

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

def find_matching_files(consigne_data: Dict) -> List[Tuple[str, Dict]]:
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
        file_text_part = id_match.group(2)

        # Recherche de la requête correspondante - logique améliorée
        matching_query = None
        for query in queries:
            if query.get('id') == file_id:
                # Correspondance par ID suffit - pas besoin de vérifier le texte exact
                # car les noms de fichiers peuvent être tronqués
                matching_query = query
                break

        if matching_query:
            matches.append((filepath, matching_query))
            logging.info(f"✓ Correspondance trouvée: {filename} -> requête ID {file_id} (\"{matching_query.get('text', '')[:50]}...\")")
        else:
            logging.warning(f"✗ Aucune correspondance pour: {filename} (ID {file_id} non trouvé dans consigne.json)")

    return matches

async def update_processed_queries(processed_results: Dict[int, Dict], consigne_data: Dict) -> bool:
    """Met à jour le fichier processed_queries.json avec les informations sémantiques"""
    try:
        processed_file = os.path.join(BASE_DIR, "processed_queries.json")

        # Charger les données existantes
        processed_data = {}
        if os.path.exists(processed_file):
            try:
                async with aiofiles.open(processed_file, 'r', encoding='utf-8') as f:
                    content = await f.read()
                    processed_data = json.loads(content)
            except Exception as e:
                logging.warning(f"Erreur lors du chargement de {processed_file}: {e}")
                processed_data = {"processed_queries": [], "query_details": {}}
        else:
            processed_data = {"processed_queries": [], "query_details": {}}

        # Fonction pour générer le hash d'une requête
        import hashlib
        def generate_query_hash(query_text: str) -> str:
            return hashlib.md5(query_text.lower().strip().encode('utf-8')).hexdigest()

        # Mettre à jour les détails pour chaque requête traitée
        for query_id, result in processed_results.items():
            # Trouver la requête correspondante dans consigne_data
            query_info = None
            for query in consigne_data.get('queries', []):
                if query.get('id') == query_id:
                    query_info = query
                    break

            if query_info:
                query_text = query_info.get('text', '')
                query_hash = generate_query_hash(query_text)

                # Ajouter le hash à la liste des requêtes traitées s'il n'y est pas
                if query_hash not in processed_data.get("processed_queries", []):
                    processed_data.setdefault("processed_queries", []).append(query_hash)

                # Mettre à jour ou créer les détails de la requête
                if "query_details" not in processed_data:
                    processed_data["query_details"] = {}

                if query_hash not in processed_data["query_details"]:
                    processed_data["query_details"][query_hash] = {
                        'id': query_id,
                        'text': query_text,
                        'processed_at': None
                    }

                # Ajouter les informations sémantiques
                processed_data["query_details"][query_hash].update({
                    'semantic': 1,  # 1 = succès du traitement sémantique
                    'semantic_processed_at': __import__('time').strftime('%Y-%m-%d %H:%M:%S'),
                    'semantic_analysis': {
                        'clusters_count': result.get('semantic_analysis', {}).get('clusters_count', 0),
                        'relations_found': result.get('semantic_analysis', {}).get('relations_found', 0),
                        'entities_count': len(result.get('semantic_analysis', {}).get('entities', [])),
                        'angles_generated': len(result.get('differentiating_angles', [])),
                        'thematic_diversity': result.get('semantic_analysis', {}).get('thematic_diversity', 0),
                        'semantic_complexity': result.get('semantic_analysis', {}).get('semantic_complexity', 0)
                    }
                })
                logging.info(f"✓ Détails sémantiques ajoutés pour la requête ID {query_id} (hash: {query_hash[:8]})")

        # Marquer les requêtes qui ont échoué (semantic = 0)
        for query in consigne_data.get('queries', []):
            query_id = query.get('id')
            if query_id not in processed_results:
                query_text = query.get('text', '')
                query_hash = generate_query_hash(query_text)

                if query_hash in processed_data.get("query_details", {}):
                    # La requête était déjà dans processed_queries mais le traitement sémantique a échoué
                    processed_data["query_details"][query_hash]['semantic'] = 0
                    processed_data["query_details"][query_hash]['semantic_processed_at'] = __import__('time').strftime('%Y-%m-%d %H:%M:%S')
                    logging.info(f"✗ Traitement sémantique échoué pour la requête ID {query_id} (hash: {query_hash[:8]})")

        # Mettre à jour les métadonnées
        processed_data.update({
            'last_updated': __import__('time').strftime('%Y-%m-%d %H:%M:%S'),
            'total_processed': len(processed_data.get("processed_queries", [])),
            'semantic_processed': len([q for q in processed_data.get("query_details", {}).values() if q.get('semantic') == 1])
        })

        # Sauvegarder le fichier mis à jour
        async with aiofiles.open(processed_file, 'w', encoding='utf-8') as f:
            content = json.dumps(processed_data, indent=2, ensure_ascii=False)
            await f.write(content)

        semantic_count = processed_data.get('semantic_processed', 0)
        logging.info(f"✓ Fichier {os.path.basename(processed_file)} mis à jour avec {semantic_count} traitements sémantiques")
        return True

    except Exception as e:
        logging.error(f"Erreur lors de la mise à jour de processed_queries.json: {e}")
        return False

async def update_consigne_data(consigne_data: Dict, processed_results: Dict[int, Dict]) -> bool:
    """Met à jour consigne.json avec les résultats traités"""
    try:
        consigne_file = _find_consigne_file()

        # Mise à jour des requêtes avec les résultats
        for query in consigne_data.get('queries', []):
            query_id = query.get('id')
            if query_id in processed_results:
                result_data = processed_results[query_id]

                # Affichage des données à ajouter
                content_structure = result_data.get('content_structure', {})
                print(f"🔄 MISE À JOUR REQUÊTE ID {query_id} ('{query.get('text', 'N/A')[:50]}...')")
                print(f"   - Structure de contenu présente: {'OUI' if content_structure else 'NON'}")
                if content_structure:
                    print(f"     • Intention: {content_structure.get('search_intention', 'N/A')}")
                    print(f"     • Complexité: {content_structure.get('topic_complexity', 'N/A')}")
                    print(f"     • Sections disponibles: {len(content_structure.get('sections_config', {}).get('titulaires', []))}")

                # Écraser les données existantes avec les nouvelles
                query.update({
                    'top_keywords': result_data.get('top_keywords', ''),
                    'word_count': result_data.get('word_count', 0),
                    'plan': result_data.get('plan', {}),
                    'semantic_analysis': result_data.get('semantic_analysis', {}),
                    'differentiating_angles': result_data.get('differentiating_angles', []),
                    'content_structure': content_structure
                })
                logging.info(f"✓ Requête ID {query_id} mise à jour dans consigne.json")

        # Sauvegarde du fichier mis à jour
        async with aiofiles.open(consigne_file, 'w', encoding='utf-8') as f:
            content = json.dumps(consigne_data, indent=4, ensure_ascii=False)
            await f.write(content)

        logging.info(f"✓ Fichier consigne.json mis à jour avec {len(processed_results)} résultats")
        return True

    except Exception as e:
        logging.error(f"Erreur lors de la mise à jour de consigne.json: {e}")
        return False

async def cleanup_processed_files(successful_files: List[str]) -> None:
    """Supprime les fichiers SERP traités avec succès"""
    try:
        for filepath in successful_files:
            if os.path.exists(filepath):
                os.remove(filepath)
                logging.info(f"✓ Fichier supprimé: {os.path.basename(filepath)}")

        logging.info(f"✓ Nettoyage terminé: {len(successful_files)} fichiers supprimés")

    except Exception as e:
        logging.error(f"Erreur lors du nettoyage des fichiers: {e}")