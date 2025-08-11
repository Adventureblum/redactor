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
MAX_CONCURRENT_REQUESTS = 1

# Constantes pour gérer les réponses longues
REQUEST_TIMEOUT = 120.0
POLLING_INTERVAL = 2.0
MAX_POLLING_ATTEMPTS = 100

# PROMPT D'AGENT HARDCODÉ
AGENT_SYSTEM_PROMPT = """# Agent de Recherche Web Orienté Content Marketing Sophistiqué

Tu es un agent GPT spécialisé dans la recherche d'informations **STATISTIQUES et FACTUELLES** pour alimenter des articles de niveau Waalaxy/Buffer/Wirecutter.

L'utilisateur te fournira une requête spécifique à investiguer dans n'importe quelle langue.

Ta mission : **Collecter des DONNÉES CHIFFRÉES, STATISTIQUES CHOC et PREUVES CONCRÈTES** qui donneront une crédibilité maximale à un article sophistiqué orienté conversion.

## 🌐 Adaptation linguistique
**IMPORTANT** : Détecte automatiquement la langue de la requête utilisateur et réponds dans cette même langue.

## 🎯 Objectif principal WAALAXY-STYLE :
Fournir des **statistiques percutantes**, **données chiffrées surprenantes** et **preuves factuelles** qui permettront de créer :
- Des **accroches choc** ("Saviez-vous que 68% des...")
- Des **arguments d'autorité** ("Selon une étude MIT de 2024...")  
- Des **preuves sociales** ("1M+ d'utilisateurs confirment...")
- Des **benchmarks précis** ("Gain moyen mesuré : +22%...")

## 🔍 TYPES DE DONNÉES PRIORITAIRES À CHERCHER :

### 1. **STATISTIQUES CHOC** (pour accroches)
- Pourcentages surprenants ou contre-intuitifs
- Chiffres qui révèlent un problème massif
- Tendances marquantes avec évolution temporelle
- Comparaisons saisissantes (avant/après, pays, segments)

### 2. **ÉTUDES & BENCHMARKS** (pour crédibilité)
- Études universitaires récentes avec méthodologie
- Rapports d'organismes officiels (gouvernement, institutions)
- Enquêtes sectorielles avec échantillons significatifs
- Méta-analyses et revues systématiques

### 3. **DONNÉES SECTORIELLES** (pour expertise)
- Parts de marché et évolutions
- Croissance/décroissance de segments
- Innovations technologiques avec adoption
- Réglementations et normes récentes

### 4. **MÉTRIQUES DE PERFORMANCE** (pour preuves)
- ROI, taux de conversion, gains de productivité
- Temps économisé, coûts réduits
- Satisfaction client, NPS, retention
- Comparatifs de performance entre solutions

### 5. **TENDANCES COMPORTEMENTALES** (pour personas)
- Habitudes de consommation évolutives
- Préférences générationnelles chiffrées
- Usage mobile vs desktop avec stats
- Saisonnalité et pics d'activité

## ⚠️ Contraintes techniques strictes :

### Sources ULTRA-FIABLES uniquement :
- **Tier 1** : Organismes officiels (INSEE, gouvernements, UE, ONU...)
- **Tier 2** : Institutions académiques (universités, centres de recherche)
- **Tier 3** : Médias de référence avec méthodologie (McKinsey, BCG, Harvard Business Review...)
- **Tier 4** : Plateformes données sectorielles (Statista, eMarketer, Gartner...)

### BANNIR absolument :
- Forums, blogs personnels, contenus d'opinion
- Sites commerciaux sans méthodologie claire
- Communiqués de presse sans données tierces
- Contenus promotionnels ou publicitaires

## ✅ Format JSON enrichi pour content marketing :

Tu dois IMPÉRATIVEMENT répondre UNIQUEMENT avec un JSON valide dans ce format exact :

{
  "query": "[REQUÊTE UTILISATEUR EN TEXTE ORIGINAL]",
  "summary": "Résumé orienté content marketing avec les 2-3 statistiques les plus percutantes pour accrocher le lecteur [LANGUE DE LA REQUÊTE]",
  
  "shock_statistics": [
    {
      "statistic": "68% des entreprises échouent à...",
      "source_credibility": "Étude McKinsey 2024 sur 10,000 entreprises",
      "usage_potential": "Accroche d'introduction pour créer l'urgence",
      "context": "Contexte précis de la mesure"
    }
  ],
  
  "expert_insights": [
    {
      "insight": "Les experts recommandent X parce que Y",
      "authority_source": "Professeur MIT / Directeur BCG / etc.",
      "credibility_boost": "Comment ça renforce l'autorité de l'article"
    }
  ],
  
  "benchmark_data": [
    {
      "metric": "ROI moyen de +127%",
      "sample_size": "Étude sur 5,000 utilisateurs",
      "methodology": "Mesure sur 12 mois, groupe contrôle",
      "article_usage": "Preuve de résultats pour section testimonials"
    }
  ],
  
  "market_trends": [
    {
      "trend": "Croissance de 340% en 2 ans",
      "supporting_data": "Données chiffrées précises",
      "future_projection": "Prévisions 2025-2026 si disponibles",
      "commercial_opportunity": "Comment ça justifie l'urgence d'agir"
    }
  ],
  
  "competitive_landscape": [
    {
      "comparison_point": "Solution A vs Solution B",
      "quantified_difference": "2.3x plus efficace selon...",
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
  ],
  
  "date_accessed": "YYYY-MM-DD",
  "confidence_score": 0.95,
  "commercial_readiness": "Prêt pour article sophistiqué orienté conversion"
}

## 🎯 Instructions de recherche SPÉCIFIQUES :

### Pour CHAQUE recherche, cherche obligatoirement :
1. **AU MOINS 3 statistiques choc** avec source + méthodologie
2. **AU MOINS 2 benchmarks** avec ROI/performance quantifiée  
3. **AU MOINS 1 étude récente** (2023-2024) d'institution reconnue
4. **AU MOINS 1 tendance** avec projection future si possible
5. **AU MOINS 2 comparaisons** quantifiées (avant/après, solution A vs B)

### Priorité absolue aux données qui permettent de dire :
- "Selon une étude [Institution] de 2024..."
- "68% des entreprises confirment que..."
- "Les utilisateurs économisent en moyenne X heures/€..."
- "La croissance mesurée est de +127% versus..."
- "9 experts sur 10 recommandent..."

## 💡 Exemples de TRANSFORMATIONS recherche → contenu :

**Recherche trouvée** : "73% des PME échouent dans leur digitalisation"
**→ Usage article** : Accroche choc + justification urgence solution

**Recherche trouvée** : "ROI moyen de 290% sur 18 mois (étude BCG)"  
**→ Usage article** : Preuve résultats + argument commercial naturel

**Recherche trouvée** : "Professeur MIT : 'L'automatisation réduit 67% erreurs'"
**→ Usage article** : Citation d'autorité + argument technique

## 🔥 MISSION ULTIME :

Tes recherches doivent permettre à l'agent créateur d'articles de produire du contenu du niveau de Waalaxy : **crédible, documenté, percutant et naturellement orienté conversion** grâce à des **données factuelles irrésistibles** ! 

**Chaque statistique trouvée = Une arme de persuasion pour l'article final !**

RÉPONDS UNIQUEMENT AVEC LE JSON DEMANDÉ, RIEN D'AUTRE."""

# Vérification des prérequis
if not API_KEY:
    logging.error("La variable OPENAI_API_KEY n'est pas définie")
    exit(1)

# Client OpenAI
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

async def validate_sequential_processing(consigne_data: Dict) -> Tuple[bool, List[int]]:
    """Valide que le traitement respecte l'ordre séquentiel"""
    status = await get_query_processing_status(consigne_data)
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

def extract_json_from_response(response_text: str) -> Optional[dict]:
    """Extrait et parse le JSON de la réponse de l'agent"""
    try:
        # Nettoyer la réponse
        cleaned_response = response_text.strip()
        
        # Chercher les marqueurs JSON
        json_start = cleaned_response.find('{')
        json_end = cleaned_response.rfind('}')
        
        if json_start == -1 or json_end == -1:
            logging.error("Aucun JSON trouvé dans la réponse")
            return None
        
        json_content = cleaned_response[json_start:json_end + 1]
        
        # Parser le JSON
        parsed_json = json.loads(json_content)
        
        # Validation des champs obligatoires
        required_fields = ['query', 'summary', 'shock_statistics']
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

async def call_agent_openai(query_text: str) -> Optional[dict]:
    """Appelle l'agent OpenAI avec le prompt intégré et retourne le JSON parsé"""
    try:
        logging.info(f"Début appel OpenAI pour: {query_text[:50]}...")
        
        # Construction du message avec le prompt système intégré
        messages = [
            {
                "role": "system",
                "content": AGENT_SYSTEM_PROMPT
            },
            {
                "role": "user", 
                "content": query_text
            }
        ]
        
        # Appel à l'API OpenAI standard (pas de prompt ID)
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.7,
            max_tokens=4000,
            timeout=REQUEST_TIMEOUT
        )
        
        if not response.choices or not response.choices[0].message:
            logging.error("Réponse OpenAI vide")
            return None
        
        response_content = response.choices[0].message.content
        logging.info(f"Réponse brute reçue: {len(response_content)} caractères")
        
        # Extraire et valider le JSON
        parsed_result = extract_json_from_response(response_content)
        
        if parsed_result:
            logging.info(f"JSON parsé avec succès: {len(str(parsed_result))} caractères")
            return parsed_result
        else:
            logging.error("Échec parsing JSON de la réponse")
            return None

    except asyncio.TimeoutError:
        logging.error(f"Timeout de requête atteint ({REQUEST_TIMEOUT}s)")
        return None
    except Exception as e:
        logging.error(f"Erreur API OpenAI: {str(e)}")
        return None

async def validate_agent_response(response_data: dict, query_text: str) -> bool:
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
        
        # Si on arrive ici, toutes les validations sont passées
        return True
        
    except Exception as e:
        logging.error(f"Erreur validation réponse agent: {str(e)}")
        return False

async def process_single_query_by_id(query_id: int) -> bool:
    """Traite une requête spécifique par son ID avec l'agent intégré"""
    try:
        logging.info(f"=== Début traitement ID {query_id} ===")

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

        # 4. Appel à l'agent OpenAI avec retry si nécessaire
        query_text = target_query['text']
        logging.info(f"Traitement de: {query_text[:100]}...")
        
        max_retries = 2
        for attempt in range(max_retries):
            logging.info(f"Tentative {attempt + 1}/{max_retries} pour ID {query_id}")
            
            agent_response_data = await call_agent_openai(query_text)
            
            if agent_response_data and await validate_agent_response(agent_response_data, query_text):
                # 5. Mise à jour de la consigne avec toutes les données structurées
                target_query['agent_response'] = agent_response_data
                target_query['processed_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                target_query['response_length'] = len(json.dumps(agent_response_data))
                target_query['processing_attempts'] = attempt + 1
                target_query['agent_version'] = "integrated_content_marketing_v1"
                
                # Ajout des métadonnées sur la réponse
                target_query['response_metadata'] = {
                    'statistics_count': len(agent_response_data.get('shock_statistics', [])),
                    'insights_count': len(agent_response_data.get('expert_insights', [])),
                    'benchmarks_count': len(agent_response_data.get('benchmark_data', [])),
                    'trends_count': len(agent_response_data.get('market_trends', [])),
                    'confidence_score': agent_response_data.get('confidence_score', 0),
                    'technical_depth': agent_response_data.get('technical_depth', 'unknown'),
                    'commercial_readiness': agent_response_data.get('commercial_readiness', 'unknown')
                }

                # 6. Sauvegarde des modifications
                if await save_json_file(consigne_info['filepath'], consigne_info['data']):
                    logging.info(f"✅ Succès traitement ID {query_id} - Données structurées: {len(json.dumps(agent_response_data))} caractères")
                    logging.info(f"   📊 Métadonnées: {target_query['response_metadata']['statistics_count']} stats, {target_query['response_metadata']['insights_count']} insights")
                    return True
                else:
                    logging.error(f"Échec sauvegarde pour ID {query_id}")
                    return False
            else:
                logging.warning(f"Tentative {attempt + 1} échouée pour ID {query_id}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(5)

        logging.error(f"❌ Échec définitif traitement ID {query_id} après {max_retries} tentatives")
        return False

    except Exception as e:
        logging.error(f"💥 Échec traitement ID {query_id}: {str(e)}")
        return False

async def process_all_consignes_sequentially() -> Dict[str, int]:
    """Traite toutes les consignes de manière séquentielle avec gestion d'erreurs améliorée"""
    results = {
        "total_processed": 0, 
        "total_errors": 0, 
        "files_processed": 0,
        "total_characters": 0,
        "total_statistics": 0,
        "average_response_length": 0
    }
    
    try:
        consigne_files = glob.glob(os.path.join(CONSIGNE_DIR, "consigne_*.json"))
        consigne_files.sort(key=os.path.getmtime)
        
        total_response_length = 0
        total_stats_count = 0
        
        for filepath in consigne_files:
            logging.info(f"📁 Traitement du fichier: {os.path.basename(filepath)}")
            
            consigne_data = await load_json_file(filepath)
            if not consigne_data:
                continue
            
            is_valid, missing_ids = await validate_sequential_processing(consigne_data)
            if not is_valid:
                logging.warning(f"⚠️ Traitement non séquentiel détecté dans {os.path.basename(filepath)}")
            
            file_processed = 0
            file_errors = 0
            
            # Traitement séquentiel des IDs manquants
            while True:
                next_id = await find_next_unprocessed_id(consigne_data)
                if next_id is None:
                    logging.info(f"✅ Toutes les queries traitées pour {os.path.basename(filepath)}")
                    break
                
                success = await process_single_query_by_id(next_id)
                if success:
                    file_processed += 1
                    # Recharger les données pour la prochaine itération
                    consigne_data = await load_json_file(filepath)
                    
                    # Calculer les statistiques détaillées
                    for query in consigne_data.get('queries', []):
                        if query.get('id') == next_id and 'response_metadata' in query:
                            metadata = query['response_metadata']
                            total_response_length += query.get('response_length', 0)
                            total_stats_count += metadata.get('statistics_count', 0)
                else:
                    file_errors += 1
                    logging.error(f"❌ Arrêt du traitement pour {os.path.basename(filepath)} après échec ID {next_id}")
                    break
                
                # Pause entre les requêtes
                await asyncio.sleep(2)
            
            results["total_processed"] += file_processed
            results["total_errors"] += file_errors
            results["files_processed"] += 1
            results["total_characters"] += total_response_length
            results["total_statistics"] += total_stats_count
            
            logging.info(f"📊 Fichier {os.path.basename(filepath)}: {file_processed} traités, {file_errors} erreurs")
        
        # Calculs des moyennes
        if results["total_processed"] > 0:
            results["average_response_length"] = results["total_characters"] // results["total_processed"]
        
        return results
        
    except Exception as e:
        logging.critical(f"💥 Erreur globale dans process_all_consignes_sequentially: {str(e)}")
        return results

async def main():
    """Point d'entrée principal du script avec reporting détaillé"""
    try:
        logging.info("🚀 Début du traitement avec agent Content Marketing intégré")
        
        start_time = datetime.now()
        results = await process_all_consignes_sequentially()
        end_time = datetime.now()
        
        duration = end_time - start_time
        
        logging.info(f"""
📈 === RÉSUMÉ FINAL DÉTAILLÉ ===
- Fichiers traités: {results['files_processed']}
- Queries traitées: {results['total_processed']}
- Erreurs: {results['total_errors']}
- Caractères générés: {results['total_characters']:,}
- Statistiques trouvées: {results['total_statistics']}
- Longueur moyenne: {results['average_response_length']} caractères
- Durée totale: {duration}
- Succès global: {results['total_errors'] == 0}
=================================""")
        
        return results['total_errors'] == 0
        
    except Exception as e:
        logging.critical(f"💥 Erreur globale: {str(e)}")
        return False

if __name__ == "__main__":
    exit_code = 0 if asyncio.run(main()) else 1
    exit(exit_code)