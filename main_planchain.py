import os
import json
import logging
import asyncio
import shutil
import threading
import glob
from typing import Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor
from langdetect import detect

# Import des agents spécialisés
from angle_selector import AngleSelectorAgent
from schema_detector import SchemaDetectorAgent
from plan_generator import PlanGeneratorAgent

# === Configuration ===
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Vérification de la clé API
api_key = os.getenv('OPENAI_API_KEY')
if not api_key:
    raise ValueError("OPENAI_API_KEY non trouvée dans les variables d'environnement")

# Fichiers et chemins
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

def _find_consigne_file() -> str:
    """Trouve automatiquement le fichier de consigne dans le dossier static"""
    consigne_pattern = os.path.join(STATIC_DIR, "consigne*.json")
    consigne_files = glob.glob(consigne_pattern)
    
    if not consigne_files:
        raise FileNotFoundError(f"❌ Aucun fichier de consigne trouvé dans {STATIC_DIR}/ (pattern: consigne*.json)")
    
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

# Vérification des chemins au démarrage
if not os.path.exists(STATIC_DIR):
    os.makedirs(STATIC_DIR, exist_ok=True)
    logging.warning(f"📁 Dossier static créé: {STATIC_DIR}")

try:
    CONSIGNE_FILE = _find_consigne_file()
    logging.info(f"✅ Fichier consigne.json trouvé: {CONSIGNE_FILE}")
except FileNotFoundError as e:
    logging.error(str(e))
    logging.error(f"❌ Veuillez vérifier qu'un fichier de consigne existe dans: {STATIC_DIR}")
    CONSIGNE_FILE = None

# === Configuration parallélisation ===
MAX_CONCURRENT_LLM = 3  # Nombre d'appels LLM simultanés

# === Analyseur de type d'article ===
class ArticleTypeAnalyzer:
    """Analyseur pour déterminer le type d'article optimal"""
    
    def __init__(self, query_id: int):
        self.query_id = query_id
    
    def detect_language(self, text: str) -> str:
        """Détecte la langue du texte (fr ou en)"""
        try:
            lang = detect(text)
            return 'fr' if lang == 'fr' else 'en'
        except:
            french_indicators = ['comment', 'pourquoi', 'qu\'est', 'faire', 'étape', 'guide']
            text_lower = text.lower()
            french_count = sum(1 for word in french_indicators if word in text_lower)
            return 'fr' if french_count >= 2 else 'en'
    
    def get_localized_keywords(self, lang: str) -> Dict[str, List[str]]:
        """Retourne les mots-clés selon la langue"""
        if lang == 'fr':
            return {
                'howto_keywords': ['comment', 'étape', 'guide', 'tuto', 'faire'],
                'definitional_keywords': ['qu\'est', 'qu est', 'c\'est quoi', 'définition'],
                'comparative_keywords': ['différence', 'versus', 'vs', 'ou', 'comparaison', 'mieux']
            }
        else:
            return {
                'howto_keywords': ['how', 'step', 'guide', 'tutorial', 'make'],
                'definitional_keywords': ['what is', 'what are', 'definition', 'meaning'],
                'comparative_keywords': ['difference', 'versus', 'vs', 'or', 'comparison', 'better']
            }
    
    def analyze_query_intent(self, query_text: str) -> str:
        """Analyse l'intention de recherche de la requête"""
        query_lower = query_text.lower()
        
        # Détection de la langue
        lang = self.detect_language(query_text)
        keywords = self.get_localized_keywords(lang)
        
        logging.info(f"🌐 [ID {self.query_id}] Langue détectée: {lang.upper()}")
        
        # Classification en 3 types
        if any(word in query_lower for word in keywords['howto_keywords']):
            return 'howto'
        elif any(word in query_lower for word in keywords['definitional_keywords']):
            return 'definitional'
        elif any(word in query_lower for word in keywords['comparative_keywords']):
            return 'comparative'
        else:
            return 'definitional'  # Par défaut

# === Processeur de requête principal ===
class QueryProcessor:
    """Processeur principal qui orchestre tous les agents"""
    
    def __init__(self, query_id: int):
        self.query_id = query_id
        self.semaphore = asyncio.Semaphore(MAX_CONCURRENT_LLM)
        
        # Initialisation des agents spécialisés
        self.angle_selector = AngleSelectorAgent(query_id)
        self.schema_detector = SchemaDetectorAgent(query_id)
        self.plan_generator = PlanGeneratorAgent(query_id)
        self.article_analyzer = ArticleTypeAnalyzer(query_id)
    
    async def process_query(self, query_data: Dict, consigne_data: Dict) -> Dict:
        """Traite une requête complète avec tous les agents"""
        try:
            logging.info(f"🚀 [ID {self.query_id}] Début du traitement commercial: '{query_data.get('text')}'")
            
            # Vérifier si la requête a les données nécessaires
            if not all([query_data.get('differentiating_angles'), 
                       query_data.get('semantic_analysis')]):
                logging.error(f"❌ [ID {self.query_id}] Données sémantiques incomplètes")
                return {'status': 'failed', 'error': f'Données sémantiques incomplètes pour ID {self.query_id}'}
            
            # Récupération du highlight depuis consigne_data
            highlight_url = consigne_data.get('highlight', '')
            
            # WORKFLOW COMMERCIAL EN 3 ÉTAPES:
            
            # Étape 1: Sélection d'angle commercial
            async with self.semaphore:
                selected_angle = await self.angle_selector.select_angle(query_data)
            
            # Étape 2: Analyse du type d'article et détermination du schéma
            query_text = query_data.get('text', '')
            article_intent = self.article_analyzer.analyze_query_intent(query_text)
            
            async with self.semaphore:
                schema_type = await self.schema_detector.determine_schema(query_data, article_intent, selected_angle)
            
            # Étape 3: Génération du plan commercial
            async with self.semaphore:
                article_plan = await self.plan_generator.generate_plan(
                    query_data, 
                    selected_angle,
                    highlight_url,
                    article_intent,
                    schema_type
                )
            
            # Finalisation avec métadonnées commerciales
            article_plan['commercial_optimization'] = {
                'target_conversion_rate': article_plan.get('commercial_ratio', 0.4),
                'conversion_points': len(article_plan.get('article_config', {}).get('conversion_points', [])),
                'commercial_sections': article_plan.get('article_config', {}).get('commercial_sections', []),
                'cta_included': bool(article_plan.get('call_to_action'))
            }
            
            logging.info(f"🎉 [ID {self.query_id}] Traitement commercial terminé avec succès")
            logging.info(f"💰 [ID {self.query_id}] Ratio commercial: {article_plan.get('commercial_ratio', 0)*100:.0f}%")
            
            return {
                'query_id': self.query_id,
                'selected_angle': selected_angle,
                'article_plan': article_plan,
                'status': 'success'
            }
            
        except Exception as e:
            logging.error(f"💥 [ID {self.query_id}] Erreur lors du traitement commercial: {e}")
            return {
                'query_id': self.query_id,
                'error': str(e),
                'status': 'failed'
            }

# === Gestionnaire principal ===
class PlanChainManager:
    """Gestionnaire principal pour le traitement en lot et individuel"""
    
    def __init__(self):
        self.lock = threading.Lock()
    
    def clean_semantic_data(self, query: Dict) -> Dict:
        """Supprime les données sémantiques après génération du plan"""
        cleaned_query = query.copy()
        
        # Supprimer les données temporaires
        keys_to_remove = ['semantic_analysis', 'detailed_clusters', 'semantic_relations', 
                         'strategic_entities', 'differentiating_angles']
        
        for key in keys_to_remove:
            if key in cleaned_query:
                del cleaned_query[key]
        
        logging.info(f"✅ [ID {query.get('id')}] Données sémantiques supprimées après génération du plan")
        return cleaned_query
    
    async def load_consigne_data(self) -> Dict:
        """Charge les données du fichier consigne.json"""
        try:
            if CONSIGNE_FILE is None:
                raise FileNotFoundError("Aucun fichier de consigne trouvé dans le dossier static/")
            
            if not os.path.exists(CONSIGNE_FILE):
                raise FileNotFoundError(f"Fichier {CONSIGNE_FILE} non trouvé")
            
            with open(CONSIGNE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            logging.info(f"✅ Données chargées depuis {os.path.basename(CONSIGNE_FILE)}")
            logging.info(f"📊 Nombre de requêtes trouvées: {len(data.get('queries', []))}")
            return data
        except Exception as e:
            logging.error(f"❌ Erreur lors du chargement: {e}")
            raise
    
    def get_query_by_id(self, consigne_data: Dict, query_id: int) -> Optional[Dict]:
        """Récupère une requête spécifique par son ID"""
        queries = consigne_data.get('queries', [])
        for query in queries:
            if query.get('id') == query_id:
                return query
        return None
    
    def get_processable_queries(self, consigne_data: Dict) -> List[Dict]:
        """Retourne les requêtes processables"""
        processable = []
        for query in consigne_data.get('queries', []):
            # Vérifier si la requête a les données nécessaires
            if (query.get('differentiating_angles') and 
                query.get('semantic_analysis')):
                
                # Ignorer les requêtes qui ont déjà un plan généré
                if query.get('generated_article_plan'):
                    logging.info(f"🔄 [ID {query.get('id')}] Plan déjà généré - ignoré")
                    continue
                    
                processable.append(query)
        return processable
    
    async def save_updated_consigne(self, consigne_data: Dict, results: List[Dict]) -> None:
        """Sauvegarde thread-safe avec mise à jour des résultats"""
        def _atomic_save():
            """Fonction synchrone pour la sauvegarde atomique"""
            try:
                with self.lock:
                    logging.info(f"🔒 Lock acquis pour sauvegarde de {os.path.basename(CONSIGNE_FILE)}")
                    
                    # Rechargement des données actuelles
                    if not os.path.exists(CONSIGNE_FILE):
                        raise FileNotFoundError(f"Le fichier {CONSIGNE_FILE} n'existe pas")
                    
                    with open(CONSIGNE_FILE, 'r', encoding='utf-8') as f:
                        current_data = json.load(f)
                    
                    # Mise à jour des requêtes avec les résultats commerciaux
                    results_by_id = {r['query_id']: r for r in results if r.get('status') == 'success'}
                    updated_count = 0
                    
                    for i, query in enumerate(current_data.get('queries', [])):
                        query_id = query.get('id')
                        if query_id in results_by_id:
                            result = results_by_id[query_id]
                            
                            if result.get('selected_angle') and result.get('article_plan'):
                                query['selected_differentiating_angle'] = result['selected_angle']
                                query['generated_article_plan'] = result['article_plan']
                                query['plan_generation_status'] = 'completed'
                                
                                # Extraction des métriques du plan commercial
                                plan = result['article_plan']
                                query['article_type'] = plan.get('article_type', 'definitional')
                                query['commercial_optimization'] = plan.get('commercial_optimization', {})
                                query['commercial_ratio'] = plan.get('commercial_ratio', 0.4)
                                
                                # Suppression des données sémantiques après génération
                                current_data['queries'][i] = self.clean_semantic_data(query)
                                
                                updated_count += 1
                                commercial_ratio = plan.get('commercial_ratio', 0) * 100
                                logging.info(f"✅ [ID {query_id}] Plan commercial {plan.get('article_type', 'definitional')} ajouté ({commercial_ratio:.0f}% commercial)")
                    
                    if updated_count == 0:
                        logging.warning("⚠️ Aucune donnée commerciale valide à sauvegarder")
                        return False
                    
                    # Création du fichier temporaire
                    import time
                    temp_suffix = f".tmp_{int(time.time())}_{os.getpid()}"
                    temp_file = CONSIGNE_FILE + temp_suffix
                    
                    # Écriture dans le fichier temporaire
                    with open(temp_file, 'w', encoding='utf-8') as f:
                        json.dump(current_data, f, indent=4, ensure_ascii=False)
                    
                    # Vérification du fichier temporaire
                    if not os.path.exists(temp_file):
                        raise Exception("Échec de création du fichier temporaire")
                    
                    temp_size = os.path.getsize(temp_file)
                    if temp_size < 50:
                        raise Exception(f"Fichier temporaire suspect (trop petit: {temp_size} bytes)")
                    
                    # Sauvegarde de l'original
                    backup_file = CONSIGNE_FILE + '.backup'
                    if os.path.exists(CONSIGNE_FILE):
                        shutil.copy2(CONSIGNE_FILE, backup_file)
                    
                    # Remplacement atomique
                    try:
                        shutil.move(temp_file, CONSIGNE_FILE)
                        logging.info(f"🔄 Remplacement atomique réussi")
                    except Exception as move_error:
                        logging.error(f"❌ Erreur lors du move: {move_error}")
                        shutil.copy2(temp_file, CONSIGNE_FILE)
                        os.remove(temp_file)
                        logging.info("✅ Fallback réussi")
                    
                    # Validation JSON finale
                    try:
                        with open(CONSIGNE_FILE, 'r', encoding='utf-8') as f:
                            json.load(f)
                        logging.info("✅ Validation JSON du fichier final réussie")
                    except json.JSONDecodeError as json_error:
                        if os.path.exists(backup_file):
                            shutil.copy2(backup_file, CONSIGNE_FILE)
                            logging.error(f"❌ JSON corrompu, backup restauré: {json_error}")
                            raise Exception("Fichier JSON corrompu après sauvegarde")
                    
                    # Nettoyage
                    for cleanup_file in [backup_file, temp_file]:
                        if os.path.exists(cleanup_file):
                            try:
                                os.remove(cleanup_file)
                            except:
                                pass
                    
                    logging.info(f"✅ Sauvegarde commerciale terminée - {updated_count} requêtes mises à jour")
                    return True
                    
            except Exception as e:
                logging.error(f"❌ Erreur dans la sauvegarde: {e}")
                raise
        
        # Exécution de la sauvegarde dans un thread
        try:
            loop = asyncio.get_event_loop()
            success = await loop.run_in_executor(None, _atomic_save)
            
            if success:
                logging.info("🎉 Sauvegarde commerciale thread-safe complétée")
            else:
                raise Exception("La sauvegarde commerciale a échoué")
                
        except Exception as e:
            logging.error(f"❌ Erreur lors de la sauvegarde thread-safe: {e}")
            raise
    
    async def process_single_query(self, query_id: int) -> Dict:
        """Traite une seule requête par son ID"""
        try:
            consigne_data = await self.load_consigne_data()
            query_data = self.get_query_by_id(consigne_data, query_id)
            
            if not query_data:
                logging.error(f"❌ Requête ID {query_id} non trouvée")
                return {'status': 'failed', 'error': f'Requête ID {query_id} non trouvée'}
            
            # Traitement de la requête
            processor = QueryProcessor(query_id)
            result = await processor.process_query(query_data, consigne_data)
            
            # Sauvegarde
            if result.get('status') == 'success':
                await self.save_updated_consigne(consigne_data, [result])
                self.display_single_query_summary(
                    query_id, 
                    query_data.get('text'), 
                    result['selected_angle'], 
                    result['article_plan']
                )
            
            return result
            
        except Exception as e:
            logging.error(f"💥 Erreur lors du traitement de la requête ID {query_id}: {e}")
            return {
                'query_id': query_id,
                'error': str(e),
                'status': 'failed'
            }
    
    async def process_all_queries(self) -> Dict:
        """Traite toutes les requêtes disponibles en parallèle"""
        try:
            consigne_data = await self.load_consigne_data()
            processable_queries = self.get_processable_queries(consigne_data)
            
            if not processable_queries:
                logging.warning("❌ Aucune requête processable trouvée")
                return {'status': 'failed', 'error': 'Aucune requête processable'}
            
            logging.info(f"🚀 Traitement parallèle commercial de {len(processable_queries)} requêtes")
            
            # Créer les processeurs et traiter en parallèle
            tasks = []
            for query_data in processable_queries:
                processor = QueryProcessor(query_data.get('id'))
                task = processor.process_query(query_data, consigne_data)
                tasks.append(task)
            
            # Exécuter toutes les tâches en parallèle
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Traitement des résultats
            processed_results = []
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    query_id = processable_queries[i].get('id', 'Unknown')
                    logging.error(f"❌ [ID {query_id}] Exception: {result}")
                    processed_results.append({
                        'query_id': query_id,
                        'error': str(result),
                        'status': 'failed'
                    })
                else:
                    processed_results.append(result)
            
            # Sauvegarde des résultats
            await self.save_updated_consigne(consigne_data, processed_results)
            
            # Résumé
            successful = [r for r in processed_results if r.get('status') == 'success']
            failed = [r for r in processed_results if r.get('status') == 'failed']
            
            logging.info(f"🎉 Traitement parallèle terminé - Succès: {len(successful)}, Échecs: {len(failed)}")
            
            self.display_batch_summary(successful, failed, len(processable_queries))
            
            return {
                'total_processed': len(processable_queries),
                'successful': len(successful),
                'failed': len(failed),
                'results': processed_results,
                'status': 'completed'
            }
            
        except Exception as e:
            logging.error(f"💥 Erreur lors du traitement en lot: {e}")
            return {
                'error': str(e),
                'status': 'failed'
            }
    
    def display_single_query_summary(self, query_id: int, query_text: str, selected_angle: str, 
                                   article_plan: Dict) -> None:
        """Affiche un résumé pour une requête individuelle"""
        print(f"\n" + "="*70)
        print(f"           RÉSUMÉ REQUÊTE COMMERCIALE ID {query_id}")
        print("="*70)
        
        print(f"📌 Requête: {query_text}")
        print(f"\n🎯 ANGLE COMMERCIAL SÉLECTIONNÉ:")
        print(f"   {selected_angle[:120]}{'...' if len(selected_angle) > 120 else ''}")
        
        # Affichage du type d'article et schema
        article_type = article_plan.get('article_type', 'definitional')
        schema_type = article_plan.get('schema_type', 'Article')
        commercial_ratio = article_plan.get('commercial_ratio', 0.4) * 100
        
        print(f"\n📋 PLAN COMMERCIAL GÉNÉRÉ ({article_type.upper()}):")
        print(f"   📌 Titre SEO: {article_plan.get('SEO Title', 'Non défini')}")
        print(f"   🎯 Type d'article: {article_type}")
        print(f"   🏷️ Schema principal: {schema_type}")
        print(f"   💰 Ratio commercial: {commercial_ratio:.0f}%")
        
        # Affichage des sections
        sections = article_plan.get('sections', [])
        print(f"\n   📊 SECTIONS: {len(sections)}")
        
        for i, section in enumerate(sections[:3], 1):  # Afficher les 3 premières
            title = section.get('section_title', 'Titre non défini')
            content_type = section.get('content_type', 'informational')
            commercial_info = f" [💰 COMMERCIAL]" if content_type == 'commercial' else f" [📖 Informatif]"
            print(f"      {i}. {title[:40]}{'...' if len(title) > 40 else ''}{commercial_info}")
        
        if len(sections) > 3:
            print(f"      ... et {len(sections) - 3} autres sections")
        
        # Affichage du CTA
        cta = article_plan.get('call_to_action', {})
        if cta:
            print(f"\n   🎯 CALL-TO-ACTION: {cta.get('cta_title', 'Non défini')}")
        
        print(f"\n💾 ✅ Sauvegardé avec optimisations commerciales")
        print("="*70 + "\n")
    
    def display_batch_summary(self, successful: List[Dict], failed: List[Dict], total: int) -> None:
        """Affiche un résumé du traitement en lot"""
        print("\n" + "="*85)
        print("           RÉSUMÉ DU TRAITEMENT EN LOT - PLANS COMMERCIAUX")
        print("="*85)
        
        print(f"🚀 PERFORMANCE:")
        print(f"   • Traitement parallèle: {MAX_CONCURRENT_LLM} appels LLM simultanés")
        print(f"   • Total traité: {total}")
        print(f"   • Succès: {len(successful)}")
        print(f"   • Échecs: {len(failed)}")
        print(f"   • Taux de réussite: {(len(successful)/total*100):.1f}%")
        
        if successful:
            # Analyse des types d'articles générés
            article_types = {}
            schema_types = {}
            total_commercial_ratio = 0
            cta_count = 0
            
            for result in successful:
                plan = result.get('article_plan', {})
                article_type = plan.get('article_type', 'definitional')
                schema_type = plan.get('schema_type', 'Article')
                
                article_types[article_type] = article_types.get(article_type, 0) + 1
                schema_types[schema_type] = schema_types.get(schema_type, 0) + 1
                
                total_commercial_ratio += plan.get('commercial_ratio', 0.4)
                if plan.get('call_to_action'):
                    cta_count += 1
            
            avg_commercial_ratio = (total_commercial_ratio / len(successful)) * 100
            
            print(f"\n📊 TYPES D'ARTICLES GÉNÉRÉS:")
            for article_type, count in article_types.items():
                print(f"   • {article_type}: {count} articles")
            
            print(f"\n🏷️ SCHEMAS UTILISÉS:")
            for schema_type, count in schema_types.items():
                print(f"   • {schema_type}: {count} articles")
            
            print(f"\n💰 MÉTRIQUES COMMERCIALES:")
            print(f"   • Ratio commercial moyen: {avg_commercial_ratio:.0f}%")
            print(f"   • Articles avec CTA: {cta_count}/{len(successful)} ({(cta_count/len(successful)*100):.0f}%)")
            
            print(f"\n✅ REQUÊTES TRAITÉES AVEC SUCCÈS:")
            for result in successful[:5]:
                query_id = result.get('query_id')
                plan = result.get('article_plan', {})
                plan_title = plan.get('SEO Title', 'Titre non défini')
                article_type = plan.get('article_type', 'definitional')
                commercial_ratio = plan.get('commercial_ratio', 0.4) * 100
                print(f"   • ID {query_id}: {plan_title[:25]}... [{article_type}] ({commercial_ratio:.0f}% commercial)")
            
            if len(successful) > 5:
                print(f"   ... et {len(successful) - 5} autres")
        
        if failed:
            print(f"\n❌ REQUÊTES EN ÉCHEC:")
            for result in failed[:3]:  # Afficher les 3 premiers échecs
                query_id = result.get('query_id', 'Unknown')
                error = result.get('error', 'Erreur inconnue')
                print(f"   • ID {query_id}: {error[:50]}{'...' if len(error) > 50 else ''}")
        
        print(f"\n💾 SAUVEGARDE:")
        print(f"   ✅ Fichier consigne.json mis à jour")
        print(f"   ✅ Nouvelles clés ajoutées:")
        print(f"      - selected_differentiating_angle")
        print(f"      - generated_article_plan")
        print(f"      - article_type")
        print(f"      - commercial_optimization")
        print(f"      - plan_generation_status")
        
        print("\n✨ WORKFLOW COMMERCIAL:")
        print(f"   1. Sélection d'angle avec AngleSelectorAgent")
        print(f"   2. Détermination de schéma avec SchemaDetectorAgent")
        print(f"   3. Génération de plan avec PlanGeneratorAgent")
        print(f"   4. Ratio 60% informatif / 40% commercial respecté")
        
        print("\n" + "="*85)
        print("Traitement en lot commercial terminé !")
        print("="*85 + "\n")

# === Fonctions principales ===
async def main_single_query_async(query_id: int):
    """Traite une seule requête par son ID"""
    try:
        manager = PlanChainManager()
        result = await manager.process_single_query(query_id)
        
        if result['status'] == 'success':
            article_type = result.get('article_plan', {}).get('article_type', 'definitional')
            commercial_ratio = result.get('article_plan', {}).get('commercial_ratio', 0.4) * 100
            print(f"🎉 Plan commercial {article_type} ({commercial_ratio:.0f}% commercial) généré pour requête ID {query_id}!")
            return True
        else:
            print(f"❌ Erreur: {result.get('error', 'Erreur inconnue')}")
            return False
            
    except KeyboardInterrupt:
        print("\n⚠️ Génération interrompue par l'utilisateur")
        return False
    except Exception as e:
        print(f"💥 Erreur critique: {e}")
        return False

async def main_all_queries_async():
    """Traite toutes les requêtes disponibles en parallèle"""
    try:
        manager = PlanChainManager()
        result = await manager.process_all_queries()
        
        if result['status'] == 'completed':
            print(f"🎉 Traitement parallélisé terminé! {result.get('successful', 0)} requêtes traitées.")
            return True
        else:
            print(f"❌ Erreur: {result.get('error', 'Erreur inconnue')}")
            return False
            
    except KeyboardInterrupt:
        print("\n⚠️ Génération interrompue par l'utilisateur")
        return False
    except Exception as e:
        print(f"💥 Erreur critique: {e}")
        return False

# === Wrappers synchrones ===
def main_single_query(query_id: int):
    """Wrapper synchrone pour le traitement d'une requête"""
    return asyncio.run(main_single_query_async(query_id))

def main_all_queries():
    """Wrapper synchrone pour le traitement de toutes les requêtes"""
    return asyncio.run(main_all_queries_async())

def main():
    """Point d'entrée principal"""
    import sys
    
    print("🚀 Générateur de Plans d'Articles SEO Commerciaux - Version Modulaire")
    print("="*85)
    print(f"📁 Dossier de travail: {BASE_DIR}")
    if CONSIGNE_FILE:
        print(f"📁 Fichier consigne: {os.path.basename(CONSIGNE_FILE)}")
        print(f"📁 Fichier existe: {os.path.exists(CONSIGNE_FILE)}")
    else:
        print("📁 Fichier consigne: ❌ Non trouvé")
    print("="*85)
    print("🤖 AGENTS SPÉCIALISÉS:")
    print("   • AngleSelectorAgent: Sélection d'angles différenciants")
    print("   • SchemaDetectorAgent: Détermination du schéma optimal")
    print("   • PlanGeneratorAgent: Génération de plans data-driven")
    print("="*85)
    print("✨ FONCTIONNALITÉS:")
    print("   • 3 types d'articles: HowTo, Comparative, Definitional")
    print("   • Ratio commercial: 60% informatif / 40% commercial")
    print("   • Support multilingue FR/EN")
    print("   • Traitement parallélisé avec limitation de concurrence")
    print("="*85)
    
    if len(sys.argv) > 1:
        try:
            query_id = int(sys.argv[1])
            print(f"Mode: Traitement commercial de la requête ID {query_id}")
            return main_single_query(query_id)
        except ValueError:
            print("❌ L'ID de requête doit être un nombre entier")
            return False
    else:
        print(f"Mode: Traitement parallélisé de toutes les requêtes ({MAX_CONCURRENT_LLM} simultanées)")
        return main_all_queries()

# === Point d'entrée ===
if __name__ == "__main__":
    # Configuration pour Windows
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    
    success = main()
    exit(0 if success else 1)