#!/usr/bin/env python3
"""
SEO Content Analyzer - Analyse automatisée de la concurrence SERP
Version générique - Fonctionne pour tous types de sujets
"""

import json
import os
import asyncio
import re
import time
import logging
import random
import signal
import sys
from datetime import datetime
from typing import List, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

try:
    from langchain_deepseek import ChatDeepSeek
    from langchain.schema import SystemMessage, HumanMessage
except ImportError as e:
    print(f"❌ Erreur d'import des dépendances LangChain: {e}")
    print("💡 Installez les dépendances avec: pip install langchain-deepseek langchain")
    sys.exit(1)

# Configuration et validation d'environnement
def validate_environment():
    """Valide les variables d'environnement et la configuration système"""
    deepseek_key = os.getenv("DEEPSEEK_KEY")
    if not deepseek_key:
        raise ValueError("❌ DEEPSEEK_KEY environment variable required")

    if len(deepseek_key.strip()) < 10:
        raise ValueError("❌ DEEPSEEK_KEY appears to be invalid (too short)")

    # Vérifier les permissions d'écriture dans le répertoire courant
    try:
        test_file = Path("temp_write_test.tmp")
        test_file.write_text("test")
        test_file.unlink()
    except (PermissionError, OSError) as e:
        raise ValueError(f"❌ No write permission in current directory: {e}")

    return deepseek_key

# Initialisation sécurisée
try:
    DEEPSEEK_KEY = validate_environment()
except Exception as e:
    print(f"❌ Configuration error: {e}")
    sys.exit(1)

# Gestionnaire global pour les interruptions
_global_analyzer = None

def signal_handler(sig, frame):
    """Gestionnaire de signal pour fermeture propre"""
    print(f"\n🛑 Signal {sig} reçu - Arrêt en cours...")
    global _global_analyzer
    if _global_analyzer:
        try:
            print("🧹 Nettoyage des ressources...")
            _global_analyzer.close()
        except Exception as e:
            print(f"⚠️ Erreur lors du nettoyage: {e}")

    print("👋 Arrêt complet")
    sys.exit(0)

# Enregistrer les gestionnaires de signal
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


class SEOAnalysisLogger:
    """Gestionnaire de logs pour l'analyse SEO - log détaillé et minifié"""

    def __init__(self, logging_dir: str = "logging"):
        # Créer le dossier logging s'il n'existe pas avec gestion d'erreurs
        self.logging_dir = logging_dir
        try:
            os.makedirs(self.logging_dir, exist_ok=True)
        except (PermissionError, OSError) as e:
            fallback_dir = "/tmp/seotheme_logs" if os.name != 'nt' else os.path.expanduser("~/seotheme_logs")
            print(f"⚠️ Cannot create logging directory {self.logging_dir}: {e}")
            print(f"📁 Using fallback directory: {fallback_dir}")
            self.logging_dir = fallback_dir
            try:
                os.makedirs(self.logging_dir, exist_ok=True)
            except Exception as fallback_error:
                print(f"❌ Cannot create fallback logging directory: {fallback_error}")
                raise

        # Chemins des fichiers de log
        self.detailed_log_path = os.path.join(self.logging_dir, "seotheme.log")
        self.main_log_path = os.path.join(self.logging_dir, "__main__.log")

        # Configuration du logger détaillé
        self.detailed_logger = logging.getLogger("seotheme_detailed")
        self.detailed_logger.setLevel(logging.INFO)

        # Configuration du logger principal (minifié)
        self.main_logger = logging.getLogger("seotheme_main")
        self.main_logger.setLevel(logging.INFO)

        # Formatter détaillé
        detailed_formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

        # Formatter minifié
        main_formatter = logging.Formatter(
            '%(asctime)s - %(message)s',
            datefmt='%H:%M:%S'
        )

        # Handler pour le log détaillé
        detailed_handler = logging.FileHandler(self.detailed_log_path, encoding='utf-8')
        detailed_handler.setLevel(logging.INFO)
        detailed_handler.setFormatter(detailed_formatter)

        # Handler pour le log principal
        main_handler = logging.FileHandler(self.main_log_path, encoding='utf-8')
        main_handler.setLevel(logging.INFO)
        main_handler.setFormatter(main_formatter)

        # Éviter la duplication des logs
        self.detailed_logger.handlers.clear()
        self.main_logger.handlers.clear()

        self.detailed_logger.addHandler(detailed_handler)
        self.main_logger.addHandler(main_handler)

        # Éviter la propagation vers le logger root
        self.detailed_logger.propagate = False
        self.main_logger.propagate = False

    def log_agent_step(self, step_type: str, query: str, position: int = None,
                      group_id: int = None, status: str = "started",
                      details: dict = None, error: str = None):
        """Log une étape d'agent avec informations détaillées et minifiées"""
        try:
            timestamp = datetime.now()

            # Validation et nettoyage des paramètres d'entrée
            step_type = str(step_type) if step_type is not None else "UNKNOWN"
            query = str(query)[:200] if query is not None else "NO_QUERY"  # Limiter la taille
            status = str(status).lower() if status is not None else "unknown"

            # Construction du message de base
            if position is not None:
                base_info = f"Query '{query}' - Position {position}"
            else:
                base_info = f"Query '{query}'"

            if group_id is not None:
                base_info += f" (Group {group_id})"

            # Message détaillé pour seotheme.log
            if status == "started":
                detailed_msg = f"AGENT_START - {step_type} - {base_info}"
            elif status == "completed":
                detailed_msg = f"AGENT_COMPLETE - {step_type} - {base_info}"
            elif status == "error":
                error_msg = str(error)[:500] if error else "Unknown error"  # Limiter les erreurs longues
                detailed_msg = f"AGENT_ERROR - {step_type} - {base_info} - Error: {error_msg}"
            else:
                detailed_msg = f"AGENT_{status.upper()} - {step_type} - {base_info}"

            # Ajouter les détails si fournis avec gestion d'erreur JSON
            if details:
                try:
                    details_str = json.dumps(details, ensure_ascii=False, separators=(',', ':'))
                    # Limiter la taille des détails
                    if len(details_str) > 1000:
                        details_str = details_str[:997] + "..."
                    detailed_msg += f" - Details: {details_str}"
                except (TypeError, ValueError) as e:
                    detailed_msg += f" - Details: [JSON_ERROR: {str(e)}]"

            # Message minifié pour _main_.log
            if status == "started":
                main_msg = f"🚀 {step_type} - {base_info}"
            elif status == "completed":
                main_msg = f"✅ {step_type} - {base_info}"
            elif status == "error":
                error_msg = str(error)[:100] if error else "Unknown error"  # Plus court pour main log
                main_msg = f"❌ {step_type} - {base_info} - {error_msg}"
            else:
                main_msg = f"📊 {step_type} - {base_info}"

            # Écrire dans les logs avec gestion d'erreur
            try:
                self.detailed_logger.info(detailed_msg)
                self.main_logger.info(main_msg)
            except Exception as log_error:
                print(f"⚠️ Logging error: {log_error}")
                # Log de fallback vers stdout
                print(f"FALLBACK_LOG: {main_msg}")

        except Exception as e:
            # Dernière tentative de log d'erreur
            print(f"❌ Critical logging error: {e}")
            print(f"FAILED_LOG_ATTEMPT: {step_type} - {status}")
            if hasattr(self, 'detailed_logger'):
                try:
                    self.detailed_logger.error(f"LOGGING_FAILURE: {str(e)}")
                except:
                    pass

    def log_analysis_summary(self, total_articles: int, successful: int,
                           groups: int, duration: float):
        """Log un résumé d'analyse avec validation des paramètres"""
        try:
            # Validation et conversion sécurisée des paramètres
            total_articles = max(0, int(total_articles)) if total_articles is not None else 0
            successful = max(0, int(successful)) if successful is not None else 0
            groups = max(0, int(groups)) if groups is not None else 0
            duration = max(0.0, float(duration)) if duration is not None else 0.0

            success_rate = (successful / total_articles * 100) if total_articles > 0 else 0

            detailed_msg = f"ANALYSIS_SUMMARY - Total Articles: {total_articles}, Successful: {successful}, Groups: {groups}, Duration: {duration:.2f}s, Success Rate: {success_rate:.1f}%"
            main_msg = f"📊 Analysis Complete - {successful}/{total_articles} articles ({success_rate:.1f}%), {groups} groups, {duration:.2f}s"

            self.detailed_logger.info(detailed_msg)
            self.main_logger.info(main_msg)

        except Exception as e:
            print(f"⚠️ Error logging analysis summary: {e}")
            print(f"FALLBACK_SUMMARY: {successful}/{total_articles} articles in {duration}s")

    def close(self):
        """Ferme proprement les handlers de logging"""
        try:
            for handler in self.detailed_logger.handlers:
                handler.close()
            for handler in self.main_logger.handlers:
                handler.close()
        except Exception as e:
            print(f"⚠️ Error closing log handlers: {e}")


class SEOContentAnalyzer:
    """Analyseur de contenu SEO générique"""
    
    def __init__(self, language: str = None, max_concurrent: int = None, consignes_file: str = None):
        """
        Args:
            language: 'fr' ou 'en' (None = lecture depuis system.json)
            max_concurrent: Nombre max de requêtes simultanées (None = illimité)
            consignes_file: Chemin vers le fichier de consignes
        """
        # Si aucune langue n'est spécifiée, lire depuis system.json
        if language is None:
            self.language = self._load_language_from_system()
        else:
            self.language = language

        self.consignes_file = consignes_file
        self.max_concurrent = max_concurrent

        # Initialiser le logger
        self.logger = SEOAnalysisLogger()

        self.llm = ChatDeepSeek(
            model="deepseek-chat",
            api_key=DEEPSEEK_KEY,
            max_tokens=3000,
            temperature=0.1,
            timeout=120
        )

        # Configuration pour la parallélisation - PARALLÉLISME TOTAL
        # DeepSeek n'impose pas de limite, donc on permet un parallélisme illimité
        self.max_concurrent = max_concurrent or 100  # Large valeur pour ne pas limiter
        self.executor = ThreadPoolExecutor(max_workers=self.max_concurrent)

        # Charger les prompts selon la langue
        self._load_prompts()

        self.articles = []
        self.results = []

    def _load_language_from_system(self) -> str:
        """Charge la langue depuis system.json"""
        try:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            system_file = os.path.join(script_dir, "system.json")

            with open(system_file, 'r', encoding='utf-8') as f:
                system_config = json.load(f)

            language = system_config.get('language', 'fr')
            print(f"🌐 Langue chargée depuis system.json: {language}")
            return language

        except FileNotFoundError:
            print("⚠️ system.json non trouvé, utilisation du français par défaut")
            return "fr"
        except Exception as e:
            print(f"⚠️ Erreur lecture system.json: {e}, utilisation du français par défaut")
            return "fr"

    def close(self):
        """Fermeture propre des ressources"""
        try:
            if hasattr(self, 'executor'):
                print("🔄 Shutting down executor...")
                self.executor.shutdown(wait=True, timeout=30)
        except Exception as e:
            print(f"⚠️ Warning during executor shutdown: {e}")

        try:
            if hasattr(self, 'logger'):
                print("📝 Closing logger...")
                self.logger.close()
        except Exception as e:
            print(f"⚠️ Warning during logger shutdown: {e}")

    def __enter__(self):
        """Context manager entry"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit avec fermeture propre"""
        self.close()
        if exc_type is not None:
            print(f"⚠️ Exception during context: {exc_type.__name__}: {exc_val}")

    def __del__(self):
        """Nettoyage de l'executor en dernier recours"""
        try:
            if hasattr(self, 'executor'):
                self.executor.shutdown(wait=False)
        except Exception:
            pass  # Ignore les erreurs lors de la destruction
    
    def _load_prompts(self):
        """Charge les prompts depuis les fichiers texte dans les sous-dossiers de langue"""
        script_dir = os.path.dirname(os.path.abspath(__file__))

        # Nouveau chemin avec sous-dossier de langue
        language_prompts_dir = os.path.join(script_dir, "prompts", self.language)

        if self.language == "fr":
            article_file = os.path.join(language_prompts_dir, "article_analysis_fr.txt")
            synthesis_file = os.path.join(language_prompts_dir, "strategic_synthesis_fr.txt")
            angle_selector_file = os.path.join(language_prompts_dir, "angle_selector.txt")
            searchbase_file = os.path.join(language_prompts_dir, "searchbase_fr.txt")
        elif self.language == "en":
            article_file = os.path.join(language_prompts_dir, "article_analysis_en.txt")
            synthesis_file = os.path.join(language_prompts_dir, "strategic_synthesis_en.txt")
            angle_selector_file = os.path.join(language_prompts_dir, "angle_selector_en.txt")
            searchbase_file = os.path.join(language_prompts_dir, "searchbase_en.txt")
        else:
            raise ValueError(f"Language '{self.language}' not supported. Use 'fr' or 'en'")

        print(f"🔍 Recherche des prompts dans: {language_prompts_dir}")
        print(f"📄 Fichier d'analyse: {article_file}")
        print(f"📄 Fichier de synthèse: {synthesis_file}")
        print(f"📄 Fichier angle_selector: {angle_selector_file}")
        print(f"📄 Fichier searchbase: {searchbase_file}")

        try:
            # Charger et extraire le prompt d'analyse d'article
            with open(article_file, 'r', encoding='utf-8') as f:
                content = f.read()

                # Définir le nom de variable selon la langue
                if self.language == "fr":
                    prompt_var_name = 'ARTICLE_ANALYSIS_PROMPT_FR'
                elif self.language == "en":
                    prompt_var_name = 'ARTICLE_ANALYSIS_PROMPT_EN'
                else:
                    raise ValueError(f"Language '{self.language}' not supported")

                # Extraire le prompt entre les triple quotes
                start_marker = f'{prompt_var_name} = """'
                end_marker = '"""'

                start_idx = content.find(start_marker)
                if start_idx != -1:
                    start_idx += len(start_marker)
                    end_idx = content.find(end_marker, start_idx)
                    if end_idx != -1:
                        self.article_prompt = content[start_idx:end_idx].strip()
                    else:
                        raise ValueError(f"Could not find end marker for {prompt_var_name}")
                else:
                    raise ValueError(f"Could not find {prompt_var_name} in file")

            # Charger le prompt de synthèse
            with open(synthesis_file, 'r', encoding='utf-8') as f:
                self.synthesis_prompt = f.read()

            # Charger le prompt angle_selector
            with open(angle_selector_file, 'r', encoding='utf-8') as f:
                self.angle_selector_prompt = f.read()

            # Charger le prompt searchbase
            with open(searchbase_file, 'r', encoding='utf-8') as f:
                self.searchbase_prompt = f.read()
        except FileNotFoundError as e:
            raise FileNotFoundError(f"Prompt file not found: {e}. Make sure prompts/{self.language}/ directory exists.")
    
    def load_data(self, filepath: str):
        """Charge les données depuis un fichier JSON de consignes avec validation robuste"""
        if not filepath:
            raise ValueError("❌ Filepath cannot be empty")

        if not os.path.exists(filepath):
            raise FileNotFoundError(f"❌ File not found: {filepath}")

        if not os.path.isfile(filepath):
            raise ValueError(f"❌ Path is not a file: {filepath}")

        # Vérifier la taille du fichier pour éviter les fichiers trop volumineux
        file_size = os.path.getsize(filepath)
        if file_size > 100 * 1024 * 1024:  # 100MB limit
            raise ValueError(f"❌ File too large: {file_size / (1024*1024):.1f}MB (max 100MB)")

        if file_size == 0:
            raise ValueError(f"❌ Empty file: {filepath}")

        try:
            print(f"📁 Loading data from: {filepath} ({file_size / 1024:.1f}KB)")

            with open(filepath, 'r', encoding='utf-8') as f:
                try:
                    data = json.load(f)
                except json.JSONDecodeError as e:
                    raise ValueError(f"❌ Invalid JSON format in file {filepath}: {e}")

            # Validation de la structure de base du JSON
            if not isinstance(data, dict):
                raise ValueError(f"❌ Invalid JSON structure: root must be an object/dict")

            if 'queries' not in data:
                raise ValueError(f"❌ Missing required field 'queries' in JSON")

            if not isinstance(data['queries'], list):
                raise ValueError(f"❌ Field 'queries' must be a list")

            queries = data['queries']

            if len(queries) == 0:
                raise ValueError(f"❌ Empty queries list in JSON")

            print(f"📋 Found {len(queries)} queries to process")

            # Structure selon consignesrun/*.json:
            # data['queries'] - Liste des requêtes
            # query['text'] - Texte de la requête
            # query['serp_data']['position_data'] - Dictionnaire avec position_X
            # position_data['position_X']['url'] - URL
            # position_data['position_X']['title'] - Titre
            # position_data['position_X']['content'] - Contenu structuré (si disponible)

            articles_before_filtering = []
            filtered_articles = []
            validation_errors = []

            for query_idx, query_data in enumerate(queries):
                try:
                    # Validation de chaque query
                    if not isinstance(query_data, dict):
                        validation_errors.append(f"Query {query_idx}: must be an object")
                        continue

                    query = query_data.get('text', '').strip()
                    if not query:
                        validation_errors.append(f"Query {query_idx}: missing or empty 'text' field")
                        continue

                    serp_data = query_data.get('serp_data', {})
                    if not isinstance(serp_data, dict):
                        validation_errors.append(f"Query {query_idx}: 'serp_data' must be an object")
                        continue

                    position_data = serp_data.get('position_data', {})
                    if not isinstance(position_data, dict):
                        validation_errors.append(f"Query {query_idx}: 'position_data' must be an object")
                        continue

                    if len(position_data) == 0:
                        validation_errors.append(f"Query {query_idx}: empty 'position_data'")
                        continue

                    # Première passe : collecter tous les articles pour calculer les moyennes
                    temp_articles = []

                    for position_key, position_info in position_data.items():
                        # Extraire le numéro de position depuis "position_X"
                        if not position_key.startswith('position_'):
                            validation_errors.append(f"Query {query_idx}: invalid position key '{position_key}'")
                            continue

                        try:
                            position = int(position_key.split('_')[1])
                            if position <= 0 or position > 100:  # Validation range position
                                validation_errors.append(f"Query {query_idx}: position {position} out of valid range (1-100)")
                                continue
                        except (IndexError, ValueError):
                            validation_errors.append(f"Query {query_idx}: invalid position format in '{position_key}'")
                            continue

                        # Validation de position_info
                        if not isinstance(position_info, dict):
                            validation_errors.append(f"Query {query_idx}, Position {position}: info must be an object")
                            continue

                        url = str(position_info.get('url', '')).strip()
                        title = str(position_info.get('title', '')).strip()

                        # Validation des champs essentiels
                        if not url:
                            validation_errors.append(f"Query {query_idx}, Position {position}: missing URL")
                            continue

                        if not title:
                            validation_errors.append(f"Query {query_idx}, Position {position}: missing title")
                            continue

                        # Validation URL basique
                        if not (url.startswith('http://') or url.startswith('https://')):
                            validation_errors.append(f"Query {query_idx}, Position {position}: invalid URL format")
                            continue

                        # Extraire words_count et authority_score depuis le JSON avec validation
                        try:
                            words_count_from_json = int(position_info.get('words_count', 0))
                            if words_count_from_json < 0:
                                words_count_from_json = 0
                        except (ValueError, TypeError):
                            words_count_from_json = 0
                            validation_errors.append(f"Query {query_idx}, Position {position}: invalid words_count")

                        domain_authority = position_info.get('domain_authority', {})
                        if not isinstance(domain_authority, dict):
                            domain_authority = {}

                        try:
                            authority_score = float(domain_authority.get('authority_score', 0))
                            if authority_score < 0 or authority_score > 100:
                                authority_score = 0
                        except (ValueError, TypeError):
                            authority_score = 0

                        # Construire le contenu textuel depuis le dict content
                        content_dict = position_info.get('content', {})
                        if not isinstance(content_dict, dict):
                            content_dict = {}

                        content_parts = []

                        # Extraire h1 d'abord
                        if 'h1' in content_dict and content_dict['h1']:
                            content_parts.append(f"# {str(content_dict['h1']).strip()}")

                        # Trier les clés pour avoir l'ordre logique
                        try:
                            sorted_keys = sorted(content_dict.keys(),
                                               key=lambda x: (int(x.split('_')[1]) if '_' in x and x.split('_')[1].isdigit() else 9999))

                            for key in sorted_keys:
                                value = content_dict.get(key)
                                if not value or not str(value).strip() or len(str(value).strip()) < 10:
                                    continue

                                value_str = str(value).strip()

                                if key.startswith('h1'):
                                    continue  # Déjà traité
                                elif key.startswith('h2'):
                                    content_parts.append(f"\n## {value_str}")
                                elif key.startswith('h3'):
                                    content_parts.append(f"\n### {value_str}")
                                elif key.startswith('h4'):
                                    content_parts.append(f"\n#### {value_str}")
                                elif key.startswith('p'):
                                    content_parts.append(value_str)

                        except Exception as e:
                            validation_errors.append(f"Query {query_idx}, Position {position}: content processing error - {str(e)}")

                        content = "\n\n".join(content_parts)
                        word_count = len(content.split()) if content else 0

                        # Validation du contenu
                        if word_count < 10:
                            validation_errors.append(f"Query {query_idx}, Position {position}: content too short ({word_count} words)")

                        # Grouper par query
                        analysis_group = query_idx

                        article = {
                            'id': f"query_{analysis_group}_position_{position}",
                            'position': position,
                            'url': url,
                            'title': title[:500],  # Limiter la taille du titre
                            'content': content[:50000],  # Limiter la taille du contenu
                            'word_count': word_count,
                            'analysis_group': analysis_group,
                            'query': query[:200],  # Limiter la taille de la query
                            'words_count_json': words_count_from_json,
                            'authority_score': authority_score
                        }
                        temp_articles.append(article)

                except Exception as e:
                    validation_errors.append(f"Query {query_idx}: processing error - {str(e)}")
                    print(f"❌ Error processing query {query_idx}: {e}")
                    continue

                # Deuxième passe : appliquer le filtrage pour cette requête
                for article in temp_articles:
                    # Vérification de filtrage
                    should_filter = (
                        article['authority_score'] >= 90 and
                        article['words_count_json'] < 300 and
                        article['position'] <= 5  # Top 5
                    )

                    if should_filter:
                        # Calculer la moyenne des words_count des autres articles de cette requête
                        other_articles = [a for a in temp_articles if a['id'] != article['id']]
                        if other_articles:
                            avg_words = sum(a['words_count_json'] for a in other_articles) / len(other_articles)

                            # Condition supplémentaire : les autres doivent avoir plus de 1000 mots en moyenne
                            if avg_words > 1000:
                                filtered_articles.append(article)
                                print(f"⚠️ Article filtré - Position {article['position']}: {article['title'][:60]}... "
                                      f"(authority: {article['authority_score']}, mots: {article['words_count_json']}, "
                                      f"avg autres: {round(avg_words)} mots)")
                                continue

                    # Article non filtré, l'ajouter à la liste finale
                    self.articles.append(article)

            # Afficher les erreurs de validation si il y en a
            if validation_errors:
                print(f"⚠️ Validation warnings ({len(validation_errors)} issues):")
                for error in validation_errors[:10]:  # Afficher les 10 premières seulement
                    print(f"   - {error}")
                if len(validation_errors) > 10:
                    print(f"   ... et {len(validation_errors) - 10} autres warnings")

            # Vérification finale
            if len(self.articles) == 0:
                raise ValueError("❌ No valid articles found after processing and validation")

            print(f"✅ {len(self.articles)} articles chargés avec succès")
            if filtered_articles:
                print(f"🚫 {len(filtered_articles)} articles filtrés (contenu de basse qualité)")

            groups = set(a['analysis_group'] for a in self.articles)
            print(f"📊 {len(groups)} groupes d'analyse")

            # Statistiques de validation
            total_processed = len(self.articles) + len(filtered_articles)
            success_rate = (len(self.articles) / total_processed * 100) if total_processed > 0 else 0
            print(f"📈 Taux de succès de chargement: {success_rate:.1f}% ({len(self.articles)}/{total_processed})")

        except FileNotFoundError:
            raise
        except ValueError:
            raise
        except Exception as e:
            print(f"❌ Erreur critique lors du chargement: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            raise ValueError(f"Failed to load data from {filepath}: {e}") from e
    
    async def _invoke_with_retry(self, prompt: str, max_retries: int = 3, context: str = "") -> Optional[str]:
        """Invoke LLM avec retry automatique, backoff exponentiel et gestion d'erreurs avancée"""
        if not prompt or not prompt.strip():
            raise ValueError(f"Empty or invalid prompt provided for context: {context}")

        last_exception = None

        for attempt in range(max_retries):
            try:
                # Validation du prompt avant l'appel
                if len(prompt) > 50000:  # Limite de sécurité pour éviter les prompts trop longs
                    print(f"⚠️ Prompt truncated (was {len(prompt)} chars) for {context}")
                    prompt = prompt[:47000] + "\n\n[TRUNCATED]"

                loop = asyncio.get_event_loop()

                # Timeout par appel pour éviter les blocages
                try:
                    response = await asyncio.wait_for(
                        loop.run_in_executor(
                            self.executor,
                            lambda: self.llm.invoke(prompt)
                        ),
                        timeout=300  # 5 minutes max par appel
                    )
                except asyncio.TimeoutError:
                    raise TimeoutError(f"LLM call timed out after 5 minutes for {context}")

                if response and hasattr(response, 'content'):
                    content = response.content.strip()
                    if content:
                        return content
                    else:
                        raise ValueError("Empty response content from LLM")
                else:
                    raise ValueError("Invalid or empty response object from LLM")

            except Exception as e:
                last_exception = e
                error_type = type(e).__name__

                # Classification des erreurs pour adapter la stratégie de retry
                if any(keyword in str(e).lower() for keyword in ['rate limit', 'quota', 'too many requests']):
                    # Erreurs de rate limiting - attendre plus longtemps
                    wait_time = (3 ** attempt) + random.uniform(2, 5)
                    print(f"⏳ Rate limit detected - waiting {wait_time:.1f}s before retry {attempt + 1}/{max_retries}")
                elif any(keyword in str(e).lower() for keyword in ['network', 'connection', 'timeout']):
                    # Erreurs réseau - backoff progressif normal
                    wait_time = (2 ** attempt) + random.uniform(0.5, 2)
                    print(f"🌐 Network issue - retrying in {wait_time:.1f}s (attempt {attempt + 1}/{max_retries})")
                elif any(keyword in str(e).lower() for keyword in ['invalid', 'malformed', 'parse']):
                    # Erreurs de format - arrêter immédiatement
                    print(f"❌ Input/format error for {context}: {error_type} - {str(e)[:200]}")
                    raise e
                else:
                    # Autres erreurs - backoff standard
                    wait_time = (2 ** attempt) + random.uniform(0, 1)
                    print(f"⚠️ Attempt {attempt + 1}/{max_retries} failed for {context}: {error_type} - {str(e)[:200]}")

                if attempt < max_retries - 1:
                    print(f"⏳ Retrying in {wait_time:.1f}s...")
                    await asyncio.sleep(wait_time)
                else:
                    print(f"❌ Final failure after {max_retries} attempts for {context}")

                    # Log détaillé de l'échec final
                    if hasattr(self, 'logger'):
                        self.logger.log_agent_step(
                            step_type="LLM_RETRY_FAILURE",
                            query=context,
                            status="error",
                            error=f"{error_type}: {str(last_exception)[:300]}",
                            details={"attempts": max_retries, "final_error": str(last_exception)}
                        )

                    raise last_exception

        return None

    def _save_raw_response(self, response_text: str, agent_type: str, article_id: str = None, group_id: int = None) -> Dict[str, Any]:
        """Sauvegarde la réponse brute dans un format permissif et renvoie un wrapper structuré"""
        raw_response_data = {
            "agent_type": agent_type,
            "timestamp": datetime.now().isoformat(),
            "response_text": response_text,
            "metadata": {
                "article_id": article_id,
                "group_id": group_id,
                "response_length": len(response_text),
                "parsing_attempted": False,
                "parsing_successful": False
            }
        }

        return raw_response_data

    def _extract_structured_data(self, raw_response_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Extrait les données structurées d'une réponse brute sauvegardée"""
        try:
            response_text = raw_response_data.get("response_text", "")
            agent_type = raw_response_data.get("agent_type", "unknown")

            # Marquer que le parsing a été tenté
            raw_response_data["metadata"]["parsing_attempted"] = True

            # Utiliser la logique de parsing améliorée
            structured_data = self._robust_json_parse(response_text, f"extract_{agent_type}")

            if structured_data:
                raw_response_data["metadata"]["parsing_successful"] = True
                return structured_data
            else:
                # Si le parsing échoue, créer une structure de fallback
                raw_response_data["metadata"]["parsing_successful"] = False
                return self._create_fallback_structure(response_text, agent_type)

        except Exception as e:
            print(f"❌ Erreur extraction données structurées: {e}")
            raw_response_data["metadata"]["parsing_successful"] = False
            return self._create_fallback_structure(
                raw_response_data.get("response_text", ""),
                raw_response_data.get("agent_type", "unknown")
            )

    def _create_fallback_structure(self, response_text: str, agent_type: str) -> Dict[str, Any]:
        """Crée une structure de fallback quand le parsing JSON échoue"""
        if agent_type == "ARTICLE_ANALYSIS":
            return {
                "pertinence_requete": {"score": 0.5, "justification": "Parsing failed", "hors_sujet": False},
                "raw_response_fallback": response_text[:1000],  # Limiter pour éviter les gros objets
                "parsing_error": True
            }
        elif agent_type == "STRATEGIC_SYNTHESIS":
            return {
                "analyse_angles_concurrentiels": {"angles_dominants": [], "angles_emergents": []},
                "raw_response_fallback": response_text[:1000],
                "parsing_error": True
            }
        elif agent_type == "ANGLE_SELECTION":
            return {
                "angle_selectionne": "Parsing failed - manual review required",
                "raw_response_fallback": response_text[:1000],
                "parsing_error": True
            }
        elif agent_type == "SEARCHBASE_DATA":
            return {
                "meta": {"parsing_error": True},
                "raw_response_fallback": response_text[:1000],
                "parsing_error": True
            }
        else:
            return {
                "raw_response_fallback": response_text[:1000],
                "parsing_error": True
            }

    def _robust_json_parse(self, response_text: str, context: str = "") -> Optional[Dict[str, Any]]:
        """Parse JSON de manière robuste avec nettoyage automatique amélioré"""
        try:
            # Nettoyage initial des blocs markdown
            if response_text.startswith('```json'):
                response_text = response_text.replace('```json', '').replace('```', '').strip()
            elif response_text.startswith('```'):
                response_text = response_text.replace('```', '').strip()

            # Première tentative de parsing direct
            try:
                return json.loads(response_text)
            except json.JSONDecodeError:
                pass

            # Nettoyage avancé AVANT extraction
            cleaned = response_text.strip()

            # 1. Décoder les entités HTML communes
            html_entities = {
                '&#39;': "'", '&#xE9;': 'é', '&#xE0;': 'à', '&#xE8;': 'è', '&#xF4;': 'ô',
                '&quot;': '"', '&amp;': '&', '&lt;': '<', '&gt;': '>', '&nbsp;': ' '
            }
            for entity, char in html_entities.items():
                cleaned = cleaned.replace(entity, char)

            # 2. Supprimer les caractères de contrôle et problématiques
            cleaned = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', cleaned)
            cleaned = re.sub(r'[\u2018\u2019]', "'", cleaned)  # Smart quotes
            cleaned = re.sub(r'[\u201C\u201D]', '"', cleaned)  # Smart double quotes

            # 3. Tentative d'extraction du bloc JSON principal
            start = cleaned.find('{')
            end = cleaned.rfind('}') + 1
            if start != -1 and end > start:
                json_text = cleaned[start:end]

                # 4. Corrections de format JSON
                json_text = re.sub(r'(["\d\]}])\s*\n\s*([}\]])', r'\1,\2', json_text)
                json_text = re.sub(r',(\s*[}\]])', r'\1', json_text)
                json_text = re.sub(r',,+', ',', json_text)

                try:
                    return json.loads(json_text)
                except json.JSONDecodeError:
                    pass

            # Dernière tentative avec nettoyage complet
            try:
                return json.loads(cleaned)
            except json.JSONDecodeError as e:
                print(f"⚠️ Parsing JSON échoué {context}: {str(e)}")
                return None

        except Exception as e:
            print(f"❌ Erreur critique parsing JSON {context}: {e}")
            return None

    async def analyze_article(self, article: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Analyse un article individuel avec DeepSeek"""
        try:
            print(f"\n🔍 Analyse position {article['position']}: {article['title'][:60]}...")

            # Log de début d'analyse
            self.logger.log_agent_step(
                step_type="ARTICLE_ANALYSIS",
                query=article.get('query', 'N/A'),
                position=article['position'],
                group_id=article.get('analysis_group'),
                status="started",
                details={
                    "article_id": article.get('id'),
                    "title": article['title'][:100],
                    "word_count": article.get('word_count', 0)
                }
            )

            # Construire le prompt
            prompt = self.article_prompt.format(
                position=article['position'],
                title=article['title'],
                content=article['content'][:15000]  # Limiter pour ne pas dépasser le token limit
            )

            # Appel LLM synchrone dans ThreadPoolExecutor pour DeepSeek
            full_prompt = f"""You are an expert SEO content analyst. Always respond in valid JSON format.

{prompt}

IMPORTANT: Your response MUST be in valid JSON format only, no additional text or markdown."""

            # Utiliser l'invoke avec retry
            context = f"article position {article['position']}"
            response_text = await self._invoke_with_retry(
                full_prompt,
                context=context
            )
            if response_text is None:
                raise ValueError(f"Aucune réponse obtenue après retry pour {context}")

            # NOUVEAU SYSTÈME : Sauvegarder d'abord la réponse brute
            raw_response = self._save_raw_response(
                response_text,
                "ARTICLE_ANALYSIS",
                article_id=article.get('id'),
                group_id=article.get('analysis_group')
            )

            # Extraire les données structurées de la réponse brute
            result = self._extract_structured_data(raw_response)

            # La fonction _extract_structured_data garantit toujours un retour valide
            # grâce au système de fallback

            # Ajouter les métadonnées
            result['article_id'] = article['id']
            result['timestamp'] = datetime.now().isoformat()
            result['raw_response_metadata'] = raw_response['metadata']  # Inclure les infos de parsing
            result['validation_report'] = {
                'validated': raw_response['metadata']['parsing_successful'],
                'quality_score': 1.0 if raw_response['metadata']['parsing_successful'] else 0.5,
                'parsing_successful': raw_response['metadata']['parsing_successful'],
                'consistency_issues': [],
                'overlap_warnings': []
            }

            # Log de fin d'analyse réussie
            self.logger.log_agent_step(
                step_type="ARTICLE_ANALYSIS",
                query=article.get('query', 'N/A'),
                position=article['position'],
                group_id=article.get('analysis_group'),
                status="completed",
                details={
                    "article_id": article.get('id'),
                    "analysis_success": True,
                    "response_length": len(response_text)
                }
            )

            print(f"✅ Position {article['position']} analysée")
            return result

        except Exception as e:
            # Log de l'erreur
            self.logger.log_agent_step(
                step_type="ARTICLE_ANALYSIS",
                query=article.get('query', 'N/A'),
                position=article['position'],
                group_id=article.get('analysis_group'),
                status="error",
                error=str(e)
            )

            print(f"❌ Erreur position {article['position']}: {e}")
            return None
    
    async def generate_strategic_synthesis(self, group_id: int, group_analyses: List[Dict[str, Any]], query: str) -> Dict[str, Any]:
        """Génère la synthèse stratégique pour un groupe d'analyses avec DeepSeek"""
        try:
            print(f"\n🎯 Génération synthèse stratégique groupe {group_id}...")

            # Log de début de synthèse
            self.logger.log_agent_step(
                step_type="STRATEGIC_SYNTHESIS",
                query=query,
                group_id=group_id,
                status="started",
                details={
                    "analyses_count": len(group_analyses),
                    "group_id": group_id
                }
            )

            # Préparer les analyses pour le prompt
            analyses_text = json.dumps(group_analyses, indent=2, ensure_ascii=False)

            prompt = self.synthesis_prompt.format(
                requete=query,
                analyses=analyses_text[:20000]
            )
            

            # Appel LLM synchrone dans ThreadPoolExecutor pour DeepSeek
            full_prompt = f"""You are an expert SEO strategist. Always respond in valid JSON format.

{prompt}

IMPORTANT: Your response MUST be in valid JSON format only, no additional text or markdown."""

            # Utiliser l'invoke avec retry
            context = f"synthesis groupe {group_id}"
            response_text = await self._invoke_with_retry(
                full_prompt,
                context=context
            )
            if response_text is None:
                raise ValueError(f"Aucune réponse obtenue après retry pour {context}")

            # NOUVEAU SYSTÈME : Sauvegarder d'abord la réponse brute
            raw_response = self._save_raw_response(
                response_text,
                "STRATEGIC_SYNTHESIS",
                group_id=group_id
            )

            # Extraire les données structurées de la réponse brute
            synthesis = self._extract_structured_data(raw_response)

            # Log de fin de synthèse (réussie ou avec fallback)
            self.logger.log_agent_step(
                step_type="STRATEGIC_SYNTHESIS",
                query=query,
                group_id=group_id,
                status="completed",
                details={
                    "analyses_count": len(group_analyses),
                    "synthesis_success": raw_response['metadata']['parsing_successful'],
                    "parsing_successful": raw_response['metadata']['parsing_successful'],
                    "response_length": len(response_text)
                }
            )

            status_msg = "✅" if raw_response['metadata']['parsing_successful'] else "⚠️"
            print(f"{status_msg} Synthèse groupe {group_id} générée")
            return synthesis

        except Exception as e:
            # Log de l'erreur
            self.logger.log_agent_step(
                step_type="STRATEGIC_SYNTHESIS",
                query=query,
                group_id=group_id,
                status="error",
                error=str(e)
            )

            print(f"❌ Erreur synthèse groupe {group_id}: {e}")
            return {}

    async def generate_angle_selection(self, group_id: int, synthesis: Dict[str, Any], query: str) -> Dict[str, Any]:
        """Génère la sélection d'angle optimal après la synthèse stratégique"""
        try:
            print(f"\n🎯 Sélection d'angle optimal groupe {group_id}...")

            # Log de début de sélection d'angle
            self.logger.log_agent_step(
                step_type="ANGLE_SELECTION",
                query=query,
                group_id=group_id,
                status="started",
                details={
                    "group_id": group_id,
                    "synthesis_provided": bool(synthesis)
                }
            )

            # Extraire les données nécessaires de la synthèse
            meta = {"requete_cible": query}
            strategie_positionnement = synthesis.get('strategie_positionnement', {})
            opportunites_angles_uniques = synthesis.get('opportunites_angles_uniques', [])

            # Préparer les données formatées pour le prompt
            requete_cible = query
            angles_minimum = strategie_positionnement.get('socle_obligatoire', {}).get('angles_minimum', [])
            themes_incontournables = strategie_positionnement.get('socle_obligatoire', {}).get('themes_incontournables', [])

            # Remplacer les placeholders dans le prompt
            prompt = self.angle_selector_prompt.replace(
                "{meta['requete_cible']}", requete_cible
            ).replace(
                "{json.dumps(strategie_positionnement['socle_obligatoire']['angles_minimum'], ensure_ascii=False, indent=2)}",
                json.dumps(angles_minimum, ensure_ascii=False, indent=2)
            ).replace(
                "{json.dumps(strategie_positionnement['socle_obligatoire']['themes_incontournables'], ensure_ascii=False, indent=2)}",
                json.dumps(themes_incontournables, ensure_ascii=False, indent=2)
            ).replace(
                "{json.dumps(opportunites_angles_uniques, ensure_ascii=False, indent=2)}",
                json.dumps(opportunites_angles_uniques, ensure_ascii=False, indent=2)
            )

            # Appel LLM synchrone dans ThreadPoolExecutor pour DeepSeek
            full_prompt = f"""You are an expert SEO editorial strategist. Always respond in valid JSON format.

{prompt}

IMPORTANT: Your response MUST be in valid JSON format only, no additional text or markdown."""

            # Utiliser l'invoke avec retry
            context = f"angle selection groupe {group_id}"
            response_text = await self._invoke_with_retry(
                full_prompt,
                context=context
            )
            if response_text is None:
                raise ValueError(f"Aucune réponse obtenue après retry pour {context}")

            # NOUVEAU SYSTÈME : Sauvegarder d'abord la réponse brute
            raw_response = self._save_raw_response(
                response_text,
                "ANGLE_SELECTION",
                group_id=group_id
            )

            # Extraire les données structurées de la réponse brute
            angle_selection = self._extract_structured_data(raw_response)

            # Log de fin de sélection d'angle (réussie ou avec fallback)
            self.logger.log_agent_step(
                step_type="ANGLE_SELECTION",
                query=query,
                group_id=group_id,
                status="completed",
                details={
                    "group_id": group_id,
                    "angle_selected": angle_selection.get('angle_selectionne', 'N/A'),
                    "selection_success": raw_response['metadata']['parsing_successful'],
                    "parsing_successful": raw_response['metadata']['parsing_successful'],
                    "response_length": len(response_text)
                }
            )

            status_msg = "✅" if raw_response['metadata']['parsing_successful'] else "⚠️"
            print(f"{status_msg} Angle sélectionné groupe {group_id}: {angle_selection.get('angle_selectionne', 'N/A')}")
            return angle_selection

        except Exception as e:
            # Log de l'erreur
            self.logger.log_agent_step(
                step_type="ANGLE_SELECTION",
                query=query,
                group_id=group_id,
                status="error",
                error=str(e)
            )

            print(f"❌ Erreur sélection angle groupe {group_id}: {e}")
            return {}

    async def generate_searchbase_data(self, group_id: int, synthesis: Dict[str, Any], angle_selection: Dict[str, Any], query: str) -> Dict[str, Any]:
        """Génère le document de collecte de données après la sélection d'angle"""
        try:
            print(f"\n📋 Génération document de collecte de données groupe {group_id}...")

            # Log de début de génération searchbase
            self.logger.log_agent_step(
                step_type="SEARCHBASE_DATA",
                query=query,
                group_id=group_id,
                status="started",
                details={
                    "group_id": group_id,
                    "synthesis_provided": bool(synthesis),
                    "angle_selection_provided": bool(angle_selection)
                }
            )

            # Préparer les données pour le prompt searchbase
            # Le prompt searchbase attend :
            # - meta.requete_cible
            # - syntheses_strategiques.analysis
            # - angle_select

            input_data = {
                "meta": {
                    "requete_cible": query
                },
                "syntheses_strategiques": {
                    f"analysis_{group_id}": synthesis
                },
                "angle_select": angle_selection
            }

            # Convertir en JSON formaté pour le prompt
            input_json = json.dumps(input_data, indent=2, ensure_ascii=False)

            # Construire le prompt complet
            full_prompt = f"""You are an expert data research analyst and SEO specialist. Always respond in valid JSON format.

{self.searchbase_prompt}

INPUT DATA:
{input_json}

IMPORTANT: Your response MUST be in valid JSON format only, no additional text or markdown."""

            # Utiliser l'invoke avec retry
            context = f"searchbase groupe {group_id}"
            response_text = await self._invoke_with_retry(
                full_prompt,
                context=context
            )
            if response_text is None:
                raise ValueError(f"Aucune réponse obtenue après retry pour {context}")

            # NOUVEAU SYSTÈME : Sauvegarder d'abord la réponse brute
            raw_response = self._save_raw_response(
                response_text,
                "SEARCHBASE_DATA",
                group_id=group_id
            )

            # Extraire les données structurées de la réponse brute
            searchbase_data = self._extract_structured_data(raw_response)

            # Log de fin de génération searchbase (réussie ou avec fallback)
            self.logger.log_agent_step(
                step_type="SEARCHBASE_DATA",
                query=query,
                group_id=group_id,
                status="completed",
                details={
                    "group_id": group_id,
                    "searchbase_success": raw_response['metadata']['parsing_successful'],
                    "parsing_successful": raw_response['metadata']['parsing_successful'],
                    "response_length": len(response_text)
                }
            )

            status_msg = "✅" if raw_response['metadata']['parsing_successful'] else "⚠️"
            print(f"{status_msg} Document de collecte de données groupe {group_id} généré")
            return searchbase_data

        except Exception as e:
            # Log de l'erreur
            self.logger.log_agent_step(
                step_type="SEARCHBASE_DATA",
                query=query,
                group_id=group_id,
                status="error",
                error=str(e)
            )

            print(f"❌ Erreur génération searchbase groupe {group_id}: {e}")
            return {}
    
    async def run_analysis_optimized(self, use_queue: bool = True, num_workers: int = 10) -> Dict[str, Any]:
        """Lance l'analyse complète optimisée - tous les groupes en parallèle"""
        print(f"\n{'='*60}")
        print(f"🚀 ANALYSE SEO OPTIMISÉE - TOUS GROUPES EN PARALLÈLE")
        print(f"{'='*60}")

        start_time = datetime.now()

        # Identifier tous les groupes
        groups_queries = {}
        for article in self.articles:
            group_id = article['analysis_group']
            query = article['query']
            if group_id not in groups_queries:
                groups_queries[group_id] = query

        print(f"📋 Groupes détectés: {len(groups_queries)}")
        for group_id, query in groups_queries.items():
            print(f"  - Groupe {group_id}: {query}")

        # Phase 1: Analyse de TOUS les articles en parallèle
        print(f"\n📝 Phase 1: Analyse de tous les articles en parallèle")
        print(f"   Articles totaux: {len(self.articles)}")
        print(f"   🚀 Mode: Parallélisme total - {len(self.articles)} appels simultanés DeepSeek")

        all_results = []

        # Mode asyncio.gather - VRAI parallélisme total (pas de limitation artificielle)
        tasks = [self.analyze_article(article) for article in self.articles]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Traiter les résultats
        for result in results:
            if isinstance(result, Exception):
                print(f"❌ Erreur: {result}")
            elif result is not None:
                all_results.append(result)

        # Grouper les résultats par analysis_group
        grouped_results = {}
        for result in all_results:
            article_id = result.get('article_id', '')
            if 'query_' in article_id:
                group_id = int(article_id.split('_')[1])
                if group_id not in grouped_results:
                    grouped_results[group_id] = []
                grouped_results[group_id].append(result)

        print(f"✅ Phase 1 terminée: {len(all_results)} articles analysés")

        # Phase 2: Génération de toutes les synthèses en parallèle
        print(f"\n📊 Phase 2: Génération de toutes les synthèses en parallèle")
        print(f"   🚀 Parallélisme total - {len(grouped_results)} appels simultanés DeepSeek")

        synthesis_tasks = []
        for group_id, group_analyses in grouped_results.items():
            query = groups_queries.get(group_id, "")
            task = self.generate_strategic_synthesis(group_id, group_analyses, query)
            synthesis_tasks.append((group_id, task))

        # Exécuter toutes les synthèses en parallèle
        synthesis_results = await asyncio.gather(*[task for _, task in synthesis_tasks])

        # Associer les résultats aux group_ids
        syntheses = {}
        for i, (group_id, _) in enumerate(synthesis_tasks):
            syntheses[group_id] = synthesis_results[i]

        print(f"✅ Phase 2 terminée: {len(syntheses)} synthèses générées")

        # Phase 3: Sélection des angles en parallèle
        print(f"\n🎯 Phase 3: Sélection des angles optimaux en parallèle")

        # Filtrer les synthèses valides pour éviter de propager les erreurs
        valid_syntheses = {}
        skipped_groups = []

        for group_id, synthesis in syntheses.items():
            # Vérifier si la synthèse a échoué (structure de fallback)
            has_parsing_error = synthesis.get("parsing_error", False)
            has_empty_data = (
                not synthesis.get("opportunites_angles_uniques", []) and
                not synthesis.get("strategie_positionnement", {}).get("socle_obligatoire", {}).get("angles_minimum", [])
            )

            if has_parsing_error or has_empty_data:
                print(f"⚠️ Groupe {group_id} ignoré - synthèse stratégique invalide ou incomplète")
                skipped_groups.append(group_id)
            else:
                valid_syntheses[group_id] = synthesis

        if valid_syntheses:
            print(f"   🚀 Parallélisme total - {len(valid_syntheses)} appels simultanés DeepSeek")

            angle_selection_tasks = []
            for group_id, synthesis in valid_syntheses.items():
                query = groups_queries.get(group_id, "")
                task = self.generate_angle_selection(group_id, synthesis, query)
                angle_selection_tasks.append((group_id, task))

            # Exécuter toutes les sélections d'angles en parallèle
            angle_selection_results = await asyncio.gather(*[task for _, task in angle_selection_tasks])

            # Associer les résultats aux group_ids
            angle_selections = {}
            for i, (group_id, _) in enumerate(angle_selection_tasks):
                angle_selections[group_id] = angle_selection_results[i]

            # Ajouter les groupes ignorés avec une structure de fallback d'angle
            for group_id in skipped_groups:
                angle_selections[group_id] = {
                    "angle_selectionne": "Analyse impossible - données préliminaires insuffisantes",
                    "score_total": "0/12",
                    "justification_selection": "Impossible de sélectionner un angle optimal car la synthèse stratégique a échoué",
                    "parsing_error": True,
                    "dependency_failed": True
                }
        else:
            print(f"   ⚠️ Aucune synthèse valide - phase d'angle selection ignorée")
            angle_selections = {}
            for group_id in syntheses.keys():
                angle_selections[group_id] = {
                    "angle_selectionne": "Analyse impossible - données préliminaires insuffisantes",
                    "score_total": "0/12",
                    "justification_selection": "Impossible de sélectionner un angle optimal car la synthèse stratégique a échoué",
                    "parsing_error": True,
                    "dependency_failed": True
                }

        print(f"✅ Phase 3 terminée: {len(angle_selections)} angles sélectionnés")

        # Phase 4: Génération des documents de collecte de données en parallèle
        print(f"\n📋 Phase 4: Génération des documents de collecte de données en parallèle")

        # Filtrer les groupes avec synthèse et angle valides
        valid_groups_for_searchbase = {}
        skipped_searchbase_groups = []

        for group_id in syntheses.keys():
            synthesis = syntheses[group_id]
            angle_selection = angle_selections.get(group_id, {})

            # Vérifier les prérequis pour searchbase
            synthesis_failed = synthesis.get("parsing_error", False)
            angle_failed = angle_selection.get("dependency_failed", False) or angle_selection.get("parsing_error", False)

            if synthesis_failed or angle_failed:
                print(f"⚠️ Groupe {group_id} ignoré - prérequis invalides (synthèse: {'✗' if synthesis_failed else '✓'}, angle: {'✗' if angle_failed else '✓'})")
                skipped_searchbase_groups.append(group_id)
            else:
                valid_groups_for_searchbase[group_id] = (synthesis, angle_selection)

        if valid_groups_for_searchbase:
            print(f"   🚀 Parallélisme total - {len(valid_groups_for_searchbase)} appels simultanés DeepSeek")

            searchbase_tasks = []
            for group_id, (synthesis, angle_selection) in valid_groups_for_searchbase.items():
                query = groups_queries.get(group_id, "")
                task = self.generate_searchbase_data(group_id, synthesis, angle_selection, query)
                searchbase_tasks.append((group_id, task))

            # Exécuter toutes les générations searchbase en parallèle
            searchbase_results = await asyncio.gather(*[task for _, task in searchbase_tasks])

            # Associer les résultats aux group_ids
            searchbase_data = {}
            for i, (group_id, _) in enumerate(searchbase_tasks):
                searchbase_data[group_id] = searchbase_results[i]

            # Ajouter les groupes ignorés avec une structure de fallback searchbase
            for group_id in skipped_searchbase_groups:
                searchbase_data[group_id] = {
                    "meta": {
                        "parsing_error": True,
                        "dependency_failed": True,
                        "error_message": "Impossible de générer les données de collecte - prérequis invalides"
                    },
                    "parsing_error": True,
                    "dependency_failed": True
                }
        else:
            print(f"   ⚠️ Aucun groupe valide - phase searchbase ignorée")
            searchbase_data = {}
            for group_id in syntheses.keys():
                searchbase_data[group_id] = {
                    "meta": {
                        "parsing_error": True,
                        "dependency_failed": True,
                        "error_message": "Impossible de générer les données de collecte - prérequis invalides"
                    },
                    "parsing_error": True,
                    "dependency_failed": True
                }

        print(f"✅ Phase 4 terminée: {len(searchbase_data)} documents de collecte générés")

        # Sauvegarder immédiatement chaque fichier searchbase séparément
        print(f"\n💾 SAUVEGARDE DES DONNÉES SEARCHBASE")
        print(f"{'='*60}")

        main_query = self.extract_main_query_from_consignes_filename(self.consignes_file) if self.consignes_file else "default"
        for group_id, searchbase_result in searchbase_data.items():
            if searchbase_result:  # Seulement si les données existent et ne sont pas vides
                query = groups_queries.get(group_id, f"group_{group_id}")
                searchbase_path = self.save_searchbase_data(
                    searchbase_result,
                    query,
                    main_query,
                    group_id
                )
                if searchbase_path:
                    print(f"✅ Groupe {group_id}: {os.path.basename(searchbase_path)}")
                else:
                    print(f"❌ Groupe {group_id}: Échec sauvegarde")
            else:
                print(f"⚠️ Groupe {group_id}: Données searchbase vides, pas de sauvegarde")

        # Construction des résultats finaux par groupe
        final_results = {}
        for group_id, group_analyses in grouped_results.items():
            query = groups_queries.get(group_id, "")
            synthesis = syntheses.get(group_id, {})
            angle_selection = angle_selections.get(group_id, {})
            searchbase = searchbase_data.get(group_id, {})

            group_result = {
                "meta": {
                    "requete_cible": query,
                    "analysis_group_id": group_id,
                    "date_analyse": start_time.isoformat(),
                    "articles_analyses": len([a for a in self.articles if a['analysis_group'] == group_id]),
                    "articles_reussis": len(group_analyses),
                    "erreurs_rencontrees": len([a for a in self.articles if a['analysis_group'] == group_id]) - len(group_analyses),
                    "agent_version": "v2.2-optimized-with-angle-selector",
                    "language": self.language
                },
                "analyses_individuelles": group_analyses,
                f"synthese_strategique_analysis_{group_id}": synthesis,
                "angle_select": angle_selection,
                "searchbase_data": searchbase,
                "controle_qualite": {
                    "articles_traites": len(group_analyses),
                    "erreurs_detectees": len([a for a in self.articles if a['analysis_group'] == group_id]) - len(group_analyses),
                    "score_completude": f"{len(group_analyses)}/{len([a for a in self.articles if a['analysis_group'] == group_id])} ({round(len(group_analyses)/len([a for a in self.articles if a['analysis_group'] == group_id])*100, 1) if len([a for a in self.articles if a['analysis_group'] == group_id]) > 0 else 0}%)"
                }
            }
            final_results[group_id] = group_result

        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()

        # Log du résumé d'analyse globale
        total_articles_analyzed = sum(len(group_analyses) for group_analyses in grouped_results.values())
        self.logger.log_analysis_summary(
            total_articles=len(self.articles),
            successful=total_articles_analyzed,
            groups=len(final_results),
            duration=duration
        )

        print(f"\n⚡ OPTIMISATION TERMINÉE")
        print(f"   Durée totale: {round(duration, 2)}s")
        print(f"   Articles analysés: {len(all_results)}")
        print(f"   Synthèses générées: {len(syntheses)}")
        print(f"   Angles sélectionnés: {len(angle_selections)}")
        print(f"   Documents de collecte: {len(searchbase_data)}")
        print(f"   Groupes traités: {len(final_results)}")

        return final_results, groups_queries

    async def run_analysis_for_group(self, group_id: int, requete_cible: str, use_queue: bool = False, num_workers: int = None) -> Dict[str, Any]:
        """Lance l'analyse complète pour un groupe spécifique"""
        print(f"\n{'='*60}")
        print(f"🚀 ANALYSE SEO GROUPE {group_id} - {requete_cible}")
        print(f"{'='*60}")

        start_time = datetime.now()

        # Filtrer les articles pour ce groupe seulement
        group_articles = [article for article in self.articles if article['analysis_group'] == group_id]

        print(f"📋 Articles à analyser pour ce groupe: {len(group_articles)}")

        # Phase 1: Analyse des articles du groupe
        print(f"\n📝 Phase 1: Analyse individuelle des articles du groupe {group_id}")
        print(f"   🚀 Parallélisme total - {len(group_articles)} appels simultanés DeepSeek")

        group_results = []

        # Mode asyncio.gather - VRAI parallélisme total
        tasks = [self.analyze_article(article) for article in group_articles]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Traiter les résultats
        for result in results:
            if isinstance(result, Exception):
                print(f"❌ Erreur: {result}")
            elif result is not None:
                group_results.append(result)

        # Phase 2: Synthèse stratégique pour ce groupe
        print(f"\n📊 Phase 2: Génération de la synthèse stratégique du groupe {group_id}")

        synthesis = await self.generate_strategic_synthesis(group_id, group_results, requete_cible)

        # Phase 3: Sélection de l'angle optimal pour ce groupe
        print(f"\n🎯 Phase 3: Sélection de l'angle optimal du groupe {group_id}")

        angle_selection = await self.generate_angle_selection(group_id, synthesis, requete_cible)

        # Phase 4: Génération du document de collecte de données pour ce groupe
        print(f"\n📋 Phase 4: Génération du document de collecte de données du groupe {group_id}")

        searchbase_data = await self.generate_searchbase_data(group_id, synthesis, angle_selection, requete_cible)

        # Construction du résultat final pour ce groupe
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()

        final_result = {
            "meta": {
                "requete_cible": requete_cible,
                "analysis_group_id": group_id,
                "date_analyse": start_time.isoformat(),
                "articles_analyses": len(group_articles),
                "articles_reussis": len(group_results),
                "erreurs_rencontrees": len(group_articles) - len(group_results),
                "agent_version": "v2.2-with-angle-selector",
                "language": self.language,
                "duration_seconds": round(duration, 2)
            },
            "analyses_individuelles": group_results,
            f"synthese_strategique_analysis_{group_id}": synthesis,
            "angle_select": angle_selection,
            "searchbase_data": searchbase_data,
            "controle_qualite": {
                "articles_traites": len(group_results),
                "erreurs_detectees": len(group_articles) - len(group_results),
                "score_completude": f"{len(group_results)}/{len(group_articles)} ({round(len(group_results)/len(group_articles)*100, 1) if len(group_articles) > 0 else 0}%)"
            }
        }

        return final_result

    async def run_analysis(self, requete_cible: str, use_queue: bool = False, num_workers: int = None) -> Dict[str, Any]:
        """Lance l'analyse complète (méthode legacy - pour compatibilité)"""
        print(f"\n⚠️  Utilisation de la méthode legacy run_analysis")
        print(f"Recommandation: Utiliser run_analysis_for_group pour traiter chaque query séparément")

        start_time = datetime.now()

        # Phase 1: Analyse des articles
        print(f"\n📝 Phase 1: Analyse individuelle des articles")
        print(f"   🚀 Parallélisme total - {len(self.articles)} appels simultanés DeepSeek")

        # Mode asyncio.gather - VRAI parallélisme total
        tasks = [self.analyze_article(article) for article in self.articles]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Traiter les résultats
        self.results = []
        for result in results:
            if isinstance(result, Exception):
                print(f"❌ Erreur: {result}")
            elif result is not None:
                self.results.append(result)

        # Phase 2: Synthèses stratégiques par groupe
        print(f"\n📊 Phase 2: Génération des synthèses stratégiques")

        # Grouper les résultats par analysis_group
        groups = {}
        for result in self.results:
            # Extraire le group_id depuis l'article_id
            article_id = result.get('article_id', '')
            if 'analysis_' in article_id:
                group_id = int(article_id.split('_')[1])
                if group_id not in groups:
                    groups[group_id] = []
                groups[group_id].append(result)

        # Générer les synthèses
        syntheses = {}
        for group_id, group_analyses in groups.items():
            # Récupérer la requête depuis les articles du groupe
            group_query = requete_cible  # Fallback
            if group_analyses and len(group_analyses) > 0:
                # Trouver l'article correspondant pour récupérer sa requête
                for article in self.articles:
                    if article['analysis_group'] == group_id:
                        group_query = article.get('query', requete_cible)
                        break

            synthesis = await self.generate_strategic_synthesis(group_id, group_analyses, group_query)
            syntheses[f"synthese_strategique_analysis_{group_id}"] = synthesis

        # Construction du résultat final
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()

        final_result = {
            "meta": {
                "requete_cible": requete_cible,
                "date_analyse": start_time.isoformat(),
                "articles_analyses": len(self.articles),
                "articles_reussis": len(self.results),
                "erreurs_rencontrees": len(self.articles) - len(self.results),
                "agent_version": "v2.0-generic",
                "language": self.language,
                "duration_seconds": round(duration, 2)
            },
            "analyses_individuelles": self.results,
            **syntheses,
            "controle_qualite": {
                "articles_traites": len(self.results),
                "erreurs_detectees": len(self.articles) - len(self.results),
                "score_completude": f"{len(self.results)}/{len(self.articles)} ({round(len(self.results)/len(self.articles)*100, 1)}%)"
            }
        }

        return final_result
    
    def save_results(self, results: Dict[str, Any], output_path: str = "seo_analysis_results.json"):
        """Sauvegarde les résultats avec organisation par dossier de requête"""
        try:
            # Créer le dossier si nécessaire
            os.makedirs(os.path.dirname(output_path), exist_ok=True)

            # Sauvegarde complète
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
            print(f"\n💾 Résultats sauvegardés: {output_path}")

            # Génération version simplifiée
            simplified = self._generate_simplified_output(results)
            simplified_path = output_path.replace('.json', '_simplified.json')
            with open(simplified_path, 'w', encoding='utf-8') as f:
                json.dump(simplified, f, ensure_ascii=False, indent=2)
            print(f"💾 Version simplifiée: {simplified_path}")

        except Exception as e:
            print(f"❌ Erreur sauvegarde: {e}")

    def save_searchbase_data(self, searchbase_data: Dict[str, Any], query: str, main_query: str, group_id: int):
        """Sauvegarde les données searchbase dans un fichier séparé"""
        try:
            # Utiliser la même logique de nommage que les autres fichiers
            sanitized_individual_query = self.sanitize_query_for_filename(query)
            sanitized_main_query = self.sanitize_query_for_filename(main_query)

            # Créer la structure de dossiers identique
            main_folder = f"requetes/{sanitized_main_query}"
            individual_query_folder = f"{main_folder}/{sanitized_individual_query}"

            # Créer le chemin pour le fichier searchbase
            searchbase_filename = f"{sanitized_individual_query}_searchbase.json"
            output_path = f"{individual_query_folder}/{searchbase_filename}"

            # Créer le dossier si nécessaire
            os.makedirs(individual_query_folder, exist_ok=True)

            # Structure des données searchbase avec métadonnées
            searchbase_output = {
                "meta": {
                    "requete_cible": query,
                    "requete_principale": main_query,
                    "group_id": group_id,
                    "date_generation": datetime.now().isoformat(),
                    "agent_version": "searchbase-v2.2",
                    "type": "document_collecte_donnees"
                },
                "collecte_donnees": searchbase_data
            }

            # Sauvegarder le fichier
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(searchbase_output, f, ensure_ascii=False, indent=2)

            print(f"💾 Données searchbase sauvegardées: {output_path}")
            return output_path

        except Exception as e:
            print(f"❌ Erreur sauvegarde searchbase groupe {group_id}: {e}")
            return None

    def _generate_simplified_output(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """Génère une version simplifiée contenant UNIQUEMENT la synthèse stratégique et l'angle sélectionné"""
        meta = results.get("meta", {})

        # Extraire toutes les synthèses stratégiques
        syntheses = {}
        for key, value in results.items():
            if key.startswith("synthese_strategique_"):
                group_id = key.replace("synthese_strategique_", "")
                syntheses[group_id] = value

        # Extraire l'angle sélectionné s'il existe
        angle_select = results.get("angle_select", {})

        # Structure simplifiée qui PRESERVE toute l'information stratégique
        # NOTE: searchbase_data est explicitement EXCLU du fichier simplified
        simplified = {
            "meta": {
                "requete_cible": meta.get("requete_cible", ""),
                "date_analyse": meta.get("date_analyse", ""),
                "language": meta.get("language", ""),
                "analyses_totales": len(syntheses)
            },
            "syntheses_strategiques": syntheses
        }

        # Ajouter angle_select s'il existe et n'est pas vide
        if angle_select and len(angle_select) > 0:
            simplified["angle_select"] = angle_select

        return simplified

    @staticmethod
    def sanitize_query_for_filename(query: str) -> str:
        """Nettoie une requête pour l'utiliser comme nom de fichier/dossier"""
        # Remplacer les espaces par des underscores
        sanitized = query.lower().replace(' ', '_')

        # Supprimer ou remplacer les caractères spéciaux
        sanitized = re.sub(r'[^\w\-_]', '', sanitized)

        # Supprimer les underscores multiples
        sanitized = re.sub(r'_+', '_', sanitized)

        # Supprimer les underscores en début et fin
        sanitized = sanitized.strip('_')

        return sanitized

    @staticmethod
    def extract_main_query_from_consignes_filename(consignes_filepath: str) -> str:
        """Extrait la requête principale du nom du fichier consignes_XXX.json"""
        # Extraire le nom du fichier sans le chemin
        filename = os.path.basename(consignes_filepath)

        # Vérifier le format consignes_XXX.json
        if not filename.startswith('consignes_') or not filename.endswith('.json'):
            raise ValueError(f"Le fichier doit suivre le format 'consignes_XXX.json', reçu: {filename}")

        # Extraire la partie entre 'consignes_' et '.json'
        main_query = filename[10:-5]  # Enlever 'consignes_' (10 chars) et '.json' (5 chars)

        return main_query


def auto_detect_consignes_file() -> str:
    """Détecte automatiquement un fichier de consignes disponible"""
    consignes_dir = "static/consignesrun"

    if not os.path.exists(consignes_dir):
        raise FileNotFoundError(f"Dossier consignes non trouvé: {consignes_dir}")

    # Lister tous les fichiers consignes_*.json
    consignes_files = []
    for filename in os.listdir(consignes_dir):
        if filename.startswith('consignes_') and filename.endswith('.json'):
            consignes_files.append(os.path.join(consignes_dir, filename))

    if not consignes_files:
        raise FileNotFoundError(f"Aucun fichier consignes_*.json trouvé dans {consignes_dir}")

    # Prendre le plus récent ou le premier alphabétiquement
    selected_file = sorted(consignes_files)[0]

    print(f"🔍 Auto-détection: {len(consignes_files)} fichier(s) trouvé(s)")
    print(f"📄 Fichier sélectionné: {selected_file}")

    return selected_file


def parse_command_line_args():
    """Parse les arguments de ligne de commande pour le fichier de consignes"""
    import sys

    consignes_file = None
    mode = "optimized"

    i = 1
    while i < len(sys.argv):
        arg = sys.argv[i]

        if arg == "--help":
            print("🔧 SEO Content Analyzer - Version Générique")
            print("\nUtilisation:")
            print("  python seotheme.py [OPTIONS] [FICHIER_CONSIGNES]")
            print("\nOptions:")
            print("  --optimized          Mode optimisé (défaut)")
            print("  --legacy            Mode legacy (séquentiel par groupe)")
            print("  --file FICHIER      Spécifier un fichier de consignes")
            print("  --query REQUETE     Spécifier une requête (cherche consignes_REQUETE.json)")
            print("  --help              Afficher cette aide")
            print("\nExemples:")
            print("  python seotheme.py                                    → Auto-détection")
            print("  python seotheme.py --query production_video          → consignes_production_video.json")
            print("  python seotheme.py --file static/consignesrun/consignes_production_video.json")
            print("\n🚀 Mode optimisé recommandé pour de meilleures performances!")
            exit(0)
        elif arg == "--legacy":
            mode = "legacy"
        elif arg == "--optimized":
            mode = "optimized"
        elif arg == "--file" and i + 1 < len(sys.argv):
            consignes_file = sys.argv[i + 1]
            i += 1
        elif arg == "--query" and i + 1 < len(sys.argv):
            query = sys.argv[i + 1]
            consignes_file = f"static/consignesrun/consignes_{query}.json"
            i += 1
        elif not arg.startswith('--'):
            # Fichier spécifié directement
            consignes_file = arg

        i += 1

    return mode, consignes_file


async def main(consignes_file: str = None):
    """Point d'entrée principal - Traitement optimisé en parallèle"""
    global _global_analyzer

    # CONFIGURATION DYNAMIQUE
    if consignes_file is None:
        # Si aucun fichier spécifié, chercher automatiquement
        consignes_file = auto_detect_consignes_file()

    CONSIGNES_FILE = consignes_file
    OUTPUT_BASE = "seo_analysis_results"  # Base pour les noms de fichiers
    LANGUAGE = None  # None = lecture automatique depuis system.json

    # Paramètres d'exécution OPTIMISÉS
    USE_QUEUE = True  # True = mode queue/workers optimisé
    NUM_WORKERS = 10  # Nombre de workers pour traitement en parallèle

    try:
        # Initialisation avec context manager
        with SEOContentAnalyzer(language=LANGUAGE, consignes_file=CONSIGNES_FILE) as analyzer:
            # Enregistrer pour le signal handler
            _global_analyzer = analyzer

            # Extraire la requête principale du nom du fichier consignes
            main_query = analyzer.extract_main_query_from_consignes_filename(CONSIGNES_FILE)
            print(f"🎯 Requête principale extraite du fichier: '{main_query}'")

            # Chargement des données
            analyzer.load_data(CONSIGNES_FILE)

            # TRAITEMENT OPTIMISÉ - Tous les groupes en parallèle
            print(f"\n🔧 Mode optimisé: Queue globale avec {NUM_WORKERS} workers")
            print(f"⚡ Traitement de tous les groupes et synthèses en parallèle")

            # Lancer l'analyse optimisée
            all_results, groups_queries = await analyzer.run_analysis_optimized(
                use_queue=USE_QUEUE,
                num_workers=NUM_WORKERS
            )

            # Nettoyer le nom de la requête principale pour les dossiers
            sanitized_main_query = analyzer.sanitize_query_for_filename(main_query)

            # Sauvegarder les résultats pour chaque groupe
            print(f"\n💾 SAUVEGARDE DES RÉSULTATS")
            print(f"{'='*60}")

            for group_id, group_results in all_results.items():
                query = groups_queries.get(group_id, "unknown")

                # Créer le nom de fichier basé sur la requête individuelle
                sanitized_individual_query = analyzer.sanitize_query_for_filename(query)

                # Créer la structure de dossiers à 3 niveaux:
                # requetes/{requete_principale}/{requete_individuelle}/
                main_folder = f"requetes/{sanitized_main_query}"
                individual_query_folder = f"{main_folder}/{sanitized_individual_query}"

                # Créer le chemin complet pour le fichier
                output_file = f"{individual_query_folder}/{sanitized_individual_query}.json"

                # Sauvegarder les résultats pour ce groupe
                analyzer.save_results(group_results, output_file)

                print(f"✅ Groupe {group_id} sauvegardé: {output_file}")
                print(f"   📁 Fichiers: {sanitized_individual_query}.json + _simplified.json")

            # Résumé global
            print(f"\n{'='*60}")
            print(f"📊 RÉSUMÉ GLOBAL OPTIMISÉ")
            print(f"{'='*60}")
            print(f"Nombre de groupes traités: {len(groups_queries)}")

            total_articles_analyses = 0
            total_articles_reussis = 0

            for group_id, results in all_results.items():
                meta = results.get('meta', {})
                requete = meta.get('requete_cible', 'N/A')
                articles_analyses = meta.get('articles_analyses', 0)
                articles_reussis = meta.get('articles_reussis', 0)

                print(f"  - Groupe {group_id}: {requete}")
                print(f"    Articles analysés: {articles_analyses}, Réussis: {articles_reussis}")

                total_articles_analyses += articles_analyses
                total_articles_reussis += articles_reussis

            print(f"\nTOTAL OPTIMISÉ:")
            print(f"  Articles analysés: {total_articles_analyses}")
            print(f"  Articles réussis: {total_articles_reussis}")
            print(f"  Langue: {LANGUAGE}")
            print(f"  Mode: Traitement parallèle optimisé")
            print(f"\n⚡ Toutes les analyses terminées avec succès en mode optimisé!")

            # Nettoyer la référence globale
            _global_analyzer = None
            return all_results

    except Exception as e:
        print(f"\n💥 Erreur fatale: {e}")
        import traceback
        traceback.print_exc()
        return None


async def main_legacy(consignes_file: str = None):
    """Point d'entrée legacy - Traite chaque query séparément (ancienne méthode)"""

    # CONFIGURATION DYNAMIQUE
    if consignes_file is None:
        # Si aucun fichier spécifié, chercher automatiquement
        consignes_file = auto_detect_consignes_file()

    CONSIGNES_FILE = consignes_file
    OUTPUT_BASE = "seo_analysis_results"  # Base pour les noms de fichiers
    LANGUAGE = None  # None = lecture automatique depuis system.json

    # Paramètres d'exécution
    USE_QUEUE = False  # True = mode queue/workers, False = asyncio.gather
    NUM_WORKERS = None  # Nombre de workers si USE_QUEUE=True

    try:
        # Initialisation
        analyzer = SEOContentAnalyzer(language=LANGUAGE, consignes_file=CONSIGNES_FILE)

        # Extraire la requête principale du nom du fichier consignes
        main_query = analyzer.extract_main_query_from_consignes_filename(CONSIGNES_FILE)
        print(f"🎯 Requête principale extraite du fichier: '{main_query}'")

        # Chargement des données
        analyzer.load_data(CONSIGNES_FILE)

        # Identifier tous les groupes de requêtes et leurs textes
        groups_queries = {}
        for article in analyzer.articles:
            group_id = article['analysis_group']
            query = article['query']
            if group_id not in groups_queries:
                groups_queries[group_id] = query

        print(f"\n{'='*60}")
        print(f"🔍 DÉTECTION DES REQUÊTES")
        print(f"{'='*60}")
        print(f"Nombre de groupes de requêtes détectés: {len(groups_queries)}")
        for group_id, query in groups_queries.items():
            print(f"📋 Groupe {group_id}: {query}")

        # Analyse de chaque groupe séparément
        if USE_QUEUE:
            print(f"\n🔧 Mode: Queue avec {NUM_WORKERS or 'auto'} workers")
        else:
            print(f"\n🔧 Mode: Parallélisme total (asyncio.gather)")

        all_results = {}

        for group_id, query in groups_queries.items():
            print(f"\n{'='*80}")
            print(f"🚀 TRAITEMENT DU GROUPE {group_id}")
            print(f"{'='*80}")

            # Analyser ce groupe spécifique
            group_results = await analyzer.run_analysis_for_group(
                group_id=group_id,
                requete_cible=query,
                use_queue=USE_QUEUE,
                num_workers=NUM_WORKERS
            )

            # Créer le nom de fichier basé sur la requête individuelle
            sanitized_individual_query = analyzer.sanitize_query_for_filename(query)

            # Nettoyer le nom de la requête principale
            sanitized_main_query = analyzer.sanitize_query_for_filename(main_query)

            # Créer la structure de dossiers à 3 niveaux:
            # requetes/{requete_principale}/{requete_individuelle}/
            main_folder = f"requetes/{sanitized_main_query}"
            individual_query_folder = f"{main_folder}/{sanitized_individual_query}"

            # Créer le chemin complet pour le fichier
            output_file = f"{individual_query_folder}/{sanitized_individual_query}.json"

            # Sauvegarder les résultats pour ce groupe
            analyzer.save_results(group_results, output_file)

            # Stocker dans les résultats globaux
            all_results[f"group_{group_id}"] = group_results

            print(f"✅ Groupe {group_id} terminé et sauvegardé dans {output_file}")
            print(f"   📁 Fichiers créés: {sanitized_individual_query}.json et {sanitized_individual_query}_simplified.json")
            print(f"   📂 Dossier principal: {main_folder}/")
            print(f"   📂 Dossier requête: {individual_query_folder}/")

        # Résumé global
        print(f"\n{'='*60}")
        print(f"📊 RÉSUMÉ GLOBAL")
        print(f"{'='*60}")
        print(f"Nombre de groupes traités: {len(groups_queries)}")

        total_articles_analyses = 0
        total_articles_reussis = 0
        total_duration = 0

        for group_id, results in all_results.items():
            meta = results.get('meta', {})
            requete = meta.get('requete_cible', 'N/A')
            articles_analyses = meta.get('articles_analyses', 0)
            articles_reussis = meta.get('articles_reussis', 0)
            duration = meta.get('duration_seconds', 0)

            print(f"  - {group_id}: {requete}")
            print(f"    Articles analysés: {articles_analyses}, Réussis: {articles_reussis}, Durée: {duration}s")

            total_articles_analyses += articles_analyses
            total_articles_reussis += articles_reussis
            total_duration += duration

        print(f"\nTOTAL:")
        print(f"  Articles analysés: {total_articles_analyses}")
        print(f"  Articles réussis: {total_articles_reussis}")
        print(f"  Durée totale: {round(total_duration, 2)}s")
        print(f"  Langue: {LANGUAGE}")
        print(f"\n✅ Toutes les analyses terminées avec succès!")

        return all_results

    except Exception as e:
        print(f"\n💥 Erreur fatale: {e}")
        import traceback
        traceback.print_exc()
        return None


if __name__ == "__main__":
    # Vérification prérequis
    if not DEEPSEEK_KEY:
        print("❌ DEEPSEEK_KEY manquante")
        exit(1)

    # Parser les arguments de ligne de commande
    mode, consignes_file = parse_command_line_args()

    # Exécution selon le mode
    if mode == "optimized":
        print("🔧 SEO Content Analyzer - Version Optimisée")
        print("⚡ Mode: Traitement parallèle de tous les groupes et synthèses")
        results = asyncio.run(main(consignes_file))
    else:
        print("🔧 SEO Content Analyzer - Version Legacy")
        print("🐌 Mode: Traitement séquentiel par groupe")
        results = asyncio.run(main_legacy(consignes_file))

    if results:
        print(f"\n🎉 Terminé en mode {mode}!")
    else:
        print(f"\n💥 Échec en mode {mode}")
        exit(1)