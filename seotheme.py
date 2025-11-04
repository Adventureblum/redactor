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
from datetime import datetime
from typing import List, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor

from langchain_deepseek import ChatDeepSeek
from langchain.schema import SystemMessage, HumanMessage

# Configuration
DEEPSEEK_KEY = os.getenv("DEEPSEEK_KEY")
if not DEEPSEEK_KEY:
    raise ValueError("DEEPSEEK_KEY environment variable required")


class SEOContentAnalyzer:
    """Analyseur de contenu SEO générique"""
    
    def __init__(self, language: str = None, max_concurrent: int = None):
        """
        Args:
            language: 'fr' ou 'en' (None = lecture depuis system.json)
            max_concurrent: Nombre max de requêtes simultanées (None = illimité)
        """
        # Si aucune langue n'est spécifiée, lire depuis system.json
        if language is None:
            self.language = self._load_language_from_system()
        else:
            self.language = language
        self.max_concurrent = max_concurrent
        
        self.llm = ChatDeepSeek(
            model="deepseek-chat",
            api_key=DEEPSEEK_KEY,
            max_tokens=3000,
            temperature=0.1,
            timeout=120
        )

        # Configuration pour la parallélisation
        self.max_concurrent = max_concurrent or 10
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

    def __del__(self):
        """Nettoyage de l'executor"""
        if hasattr(self, 'executor'):
            self.executor.shutdown(wait=False)
    
    def _load_prompts(self):
        """Charge les prompts depuis les fichiers texte dans les sous-dossiers de langue"""
        script_dir = os.path.dirname(os.path.abspath(__file__))

        # Nouveau chemin avec sous-dossier de langue
        language_prompts_dir = os.path.join(script_dir, "prompts", self.language)

        if self.language == "fr":
            article_file = os.path.join(language_prompts_dir, "article_analysis_fr.txt")
            synthesis_file = os.path.join(language_prompts_dir, "strategic_synthesis_fr.txt")
        elif self.language == "en":
            article_file = os.path.join(language_prompts_dir, "article_analysis_en.txt")
            synthesis_file = os.path.join(language_prompts_dir, "strategic_synthesis_en.txt")
        else:
            raise ValueError(f"Language '{self.language}' not supported. Use 'fr' or 'en'")

        print(f"🔍 Recherche des prompts dans: {language_prompts_dir}")
        print(f"📄 Fichier d'analyse: {article_file}")
        print(f"📄 Fichier de synthèse: {synthesis_file}")

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
        except FileNotFoundError as e:
            raise FileNotFoundError(f"Prompt file not found: {e}. Make sure prompts/{self.language}/ directory exists.")
    
    def load_data(self, filepath: str):
        """Charge les données depuis un fichier JSON de consignes"""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # Structure selon consignesrun/*.json:
            # data['queries'] - Liste des requêtes
            # query['text'] - Texte de la requête
            # query['serp_data']['position_data'] - Dictionnaire avec position_X
            # position_data['position_X']['url'] - URL
            # position_data['position_X']['title'] - Titre
            # position_data['position_X']['content'] - Contenu structuré (si disponible)

            queries = data.get('queries', [])
            articles_before_filtering = []
            filtered_articles = []

            for query_idx, query_data in enumerate(queries):
                query = query_data.get('text', '')
                serp_data = query_data.get('serp_data', {})
                position_data = serp_data.get('position_data', {})

                # Première passe : collecter tous les articles pour calculer les moyennes
                temp_articles = []

                for position_key, position_info in position_data.items():
                    # Extraire le numéro de position depuis "position_X"
                    if not position_key.startswith('position_'):
                        continue

                    try:
                        position = int(position_key.split('_')[1])
                    except (IndexError, ValueError):
                        continue

                    url = position_info.get('url', '')
                    title = position_info.get('title', '')

                    # Extraire words_count et authority_score depuis le JSON
                    words_count_from_json = position_info.get('words_count', 0)
                    domain_authority = position_info.get('domain_authority', {})
                    authority_score = domain_authority.get('authority_score', 0)

                    # Construire le contenu textuel depuis le dict content
                    content_dict = position_info.get('content', {})
                    content_parts = []

                    # Extraire h1 d'abord
                    if 'h1' in content_dict:
                        content_parts.append(f"# {content_dict['h1']}")

                    # Trier les clés pour avoir l'ordre logique
                    sorted_keys = sorted(content_dict.keys(),
                                       key=lambda x: (int(x.split('_')[1]) if '_' in x and x.split('_')[1].isdigit() else 9999))

                    for key in sorted_keys:
                        value = content_dict[key]
                        if not value or len(value.strip()) < 10:
                            continue

                        if key.startswith('h1'):
                            continue  # Déjà traité
                        elif key.startswith('h2'):
                            content_parts.append(f"\n## {value}")
                        elif key.startswith('h3'):
                            content_parts.append(f"\n### {value}")
                        elif key.startswith('h4'):
                            content_parts.append(f"\n#### {value}")
                        elif key.startswith('p'):
                            content_parts.append(value)

                    content = "\n\n".join(content_parts)
                    word_count = len(content.split())

                    # Grouper par query
                    analysis_group = query_idx

                    article = {
                        'id': f"query_{analysis_group}_position_{position}",
                        'position': position,
                        'url': url,
                        'title': title,
                        'content': content,
                        'word_count': word_count,
                        'analysis_group': analysis_group,
                        'query': query,
                        'words_count_json': words_count_from_json,  # Données depuis le JSON
                        'authority_score': authority_score
                    }
                    temp_articles.append(article)

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

            print(f"✅ {len(self.articles)} articles chargés")
            if filtered_articles:
                print(f"🚫 {len(filtered_articles)} articles filtrés (contenu de basse qualité)")
            groups = set(a['analysis_group'] for a in self.articles)
            print(f"📊 {len(groups)} groupes d'analyse")

        except Exception as e:
            print(f"❌ Erreur chargement: {e}")
            import traceback
            traceback.print_exc()
            raise
    
    async def analyze_article(self, article: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Analyse un article individuel avec DeepSeek"""
        try:
            print(f"\n🔍 Analyse position {article['position']}: {article['title'][:60]}...")

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

            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor,
                lambda: self.llm.invoke(full_prompt)
            )

            # Parser la réponse JSON
            response_text = response.content.strip()

            # Nettoyer la réponse si elle contient du markdown
            if response_text.startswith('```json'):
                response_text = response_text.replace('```json', '').replace('```', '').strip()
            elif response_text.startswith('```'):
                response_text = response_text.replace('```', '').strip()

            # Extraire JSON si nécessaire
            start = response_text.find('{')
            end = response_text.rfind('}') + 1
            if start != -1 and end > start:
                json_text = response_text[start:end]
                result = json.loads(json_text)
            else:
                result = json.loads(response_text)

            # Ajouter les métadonnées
            result['article_id'] = article['id']
            result['timestamp'] = datetime.now().isoformat()
            result['validation_report'] = {
                'validated': True,
                'quality_score': 1.0,
                'consistency_issues': [],
                'overlap_warnings': []
            }

            print(f"✅ Position {article['position']} analysée")
            return result

        except Exception as e:
            print(f"❌ Erreur position {article['position']}: {e}")
            return None
    
    async def generate_strategic_synthesis(self, group_id: int, group_analyses: List[Dict[str, Any]], query: str) -> Dict[str, Any]:
        """Génère la synthèse stratégique pour un groupe d'analyses avec DeepSeek"""
        try:
            print(f"\n🎯 Génération synthèse stratégique groupe {group_id}...")

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

            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                self.executor,
                lambda: self.llm.invoke(full_prompt)
            )

            # Parser la réponse JSON
            response_text = response.content.strip()

            # Nettoyer la réponse si elle contient du markdown
            if response_text.startswith('```json'):
                response_text = response_text.replace('```json', '').replace('```', '').strip()
            elif response_text.startswith('```'):
                response_text = response_text.replace('```', '').strip()

            # Extraire JSON si nécessaire
            start = response_text.find('{')
            end = response_text.rfind('}') + 1
            if start != -1 and end > start:
                json_text = response_text[start:end]
                synthesis = json.loads(json_text)
            else:
                synthesis = json.loads(response_text)

            print(f"✅ Synthèse groupe {group_id} générée")
            return synthesis

        except Exception as e:
            print(f"❌ Erreur synthèse groupe {group_id}: {e}")
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
        print(f"   Mode: Queue avec {num_workers} workers")
        print(f"   Articles totaux: {len(self.articles)}")

        all_results = []

        if use_queue:
            # Mode queue avec semaphore pour DeepSeek (similaire à plan_generator.py)
            print(f"   🔧 Mode: Queue DeepSeek avec semaphore limité à {num_workers}")

            semaphore = asyncio.Semaphore(num_workers)
            all_tasks = []

            async def limited_analyze_article(article):
                async with semaphore:
                    return await self.analyze_article(article)

            # Créer toutes les tâches avec limitation de concurrence
            for article in self.articles:
                all_tasks.append(limited_analyze_article(article))

            # Exécuter toutes les tâches en parallèle avec limitation
            results = await asyncio.gather(*all_tasks, return_exceptions=True)

            # Traiter les résultats
            for result in results:
                if isinstance(result, Exception):
                    print(f"❌ Erreur: {result}")
                elif result is not None:
                    all_results.append(result)
        else:
            # Mode asyncio.gather (tous en parallèle sans limitation)
            tasks = [self.analyze_article(article) for article in self.articles]
            results = await asyncio.gather(*tasks)
            all_results = [r for r in results if r is not None]

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

        # Construction des résultats finaux par groupe
        final_results = {}
        for group_id, group_analyses in grouped_results.items():
            query = groups_queries.get(group_id, "")
            synthesis = syntheses.get(group_id, {})

            group_result = {
                "meta": {
                    "requete_cible": query,
                    "analysis_group_id": group_id,
                    "date_analyse": start_time.isoformat(),
                    "articles_analyses": len([a for a in self.articles if a['analysis_group'] == group_id]),
                    "articles_reussis": len(group_analyses),
                    "erreurs_rencontrees": len([a for a in self.articles if a['analysis_group'] == group_id]) - len(group_analyses),
                    "agent_version": "v2.1-optimized",
                    "language": self.language
                },
                "analyses_individuelles": group_analyses,
                f"synthese_strategique_analysis_{group_id}": synthesis,
                "controle_qualite": {
                    "articles_traites": len(group_analyses),
                    "erreurs_detectees": len([a for a in self.articles if a['analysis_group'] == group_id]) - len(group_analyses),
                    "score_completude": f"{len(group_analyses)}/{len([a for a in self.articles if a['analysis_group'] == group_id])} ({round(len(group_analyses)/len([a for a in self.articles if a['analysis_group'] == group_id])*100, 1) if len([a for a in self.articles if a['analysis_group'] == group_id]) > 0 else 0}%)"
                }
            }
            final_results[group_id] = group_result

        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()

        print(f"\n⚡ OPTIMISATION TERMINÉE")
        print(f"   Durée totale: {round(duration, 2)}s")
        print(f"   Articles analysés: {len(all_results)}")
        print(f"   Synthèses générées: {len(syntheses)}")
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

        group_results = []

        if use_queue and num_workers:
            # Mode queue avec semaphore pour DeepSeek
            print(f"   🔧 Mode: Queue DeepSeek avec semaphore limité à {num_workers}")

            semaphore = asyncio.Semaphore(num_workers)
            all_tasks = []

            async def limited_analyze_article(article):
                async with semaphore:
                    return await self.analyze_article(article)

            # Créer toutes les tâches avec limitation de concurrence
            for article in group_articles:
                all_tasks.append(limited_analyze_article(article))

            # Exécuter toutes les tâches en parallèle avec limitation
            results = await asyncio.gather(*all_tasks, return_exceptions=True)

            # Traiter les résultats
            for result in results:
                if isinstance(result, Exception):
                    print(f"❌ Erreur: {result}")
                elif result is not None:
                    group_results.append(result)
        else:
            # Mode asyncio.gather (tous en parallèle sans limitation)
            tasks = [self.analyze_article(article) for article in group_articles]
            results = await asyncio.gather(*tasks)
            group_results = [r for r in results if r is not None]

        # Phase 2: Synthèse stratégique pour ce groupe
        print(f"\n📊 Phase 2: Génération de la synthèse stratégique du groupe {group_id}")

        synthesis = await self.generate_strategic_synthesis(group_id, group_results, requete_cible)

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
                "agent_version": "v2.0-generic",
                "language": self.language,
                "duration_seconds": round(duration, 2)
            },
            "analyses_individuelles": group_results,
            f"synthese_strategique_analysis_{group_id}": synthesis,
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

        if use_queue and num_workers:
            # Mode queue avec semaphore pour DeepSeek
            print(f"   🔧 Mode: Queue DeepSeek avec semaphore limité à {num_workers}")

            semaphore = asyncio.Semaphore(num_workers)
            all_tasks = []

            async def limited_analyze_article(article):
                async with semaphore:
                    return await self.analyze_article(article)

            # Créer toutes les tâches avec limitation de concurrence
            for article in self.articles:
                all_tasks.append(limited_analyze_article(article))

            # Exécuter toutes les tâches en parallèle avec limitation
            results = await asyncio.gather(*all_tasks, return_exceptions=True)

            # Traiter les résultats
            self.results = []
            for result in results:
                if isinstance(result, Exception):
                    print(f"❌ Erreur: {result}")
                elif result is not None:
                    self.results.append(result)
        else:
            # Mode asyncio.gather (tous en parallèle sans limitation)
            tasks = [self.analyze_article(article) for article in self.articles]
            results = await asyncio.gather(*tasks)
            self.results = [r for r in results if r is not None]

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
    
    def _generate_simplified_output(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """Génère une version simplifiée intégrant TOUTE la synthèse stratégique"""
        meta = results.get("meta", {})
        
        # Extraire toutes les synthèses stratégiques
        syntheses = {}
        for key, value in results.items():
            if key.startswith("synthese_strategique_"):
                group_id = key.replace("synthese_strategique_", "")
                syntheses[group_id] = value
        
        # Structure simplifiée qui PRESERVE toute l'information stratégique
        simplified = {
            "meta": {
                "requete_cible": meta.get("requete_cible", ""),
                "date_analyse": meta.get("date_analyse", ""),
                "language": meta.get("language", ""),
                "analyses_totales": len(syntheses)
            },
            "syntheses_strategiques": syntheses
        }
        
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
        # Initialisation
        analyzer = SEOContentAnalyzer(language=LANGUAGE)

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
        analyzer = SEOContentAnalyzer(language=LANGUAGE)

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