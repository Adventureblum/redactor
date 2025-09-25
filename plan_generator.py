#!/usr/bin/env python3
"""
Générateur de plans d'articles SEO simplifié
Version allégée focalisée sur l'essentiel
"""

import json
import os
import sys
import logging
import asyncio
import aiohttp
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor
from langchain_deepseek import ChatDeepSeek
from langchain_core.output_parsers import BaseOutputParser

# Configuration simple
class Config:
    def __init__(self):
        self.deepseek_key = os.getenv('DEEPSEEK_KEY')
        if not self.deepseek_key:
            print("❌ Variable DEEPSEEK_KEY manquante")
            sys.exit(1)
        
        self.prompts_dir = Path("prompts")
        self.static_dir = Path("static")
        self.timeout = int(os.getenv('API_TIMEOUT', '120'))

# Parser JSON simple
class JSONParser(BaseOutputParser):
    def parse(self, text: str) -> Dict:
        try:
            # Extraire JSON du texte
            start = text.find('{')
            end = text.rfind('}') + 1
            if start != -1 and end > start:
                json_text = text[start:end]
                return json.loads(json_text)
        except:
            pass
        
        # Fallback si parsing échoue
        return {
            "title": "Plan généré avec erreur",
            "structure": {
                "introduction": {"title": "Introduction", "word_count": 120},
                "conclusion": {"title": "Conclusion", "word_count": 120}
            }
        }

# Classificateur avec détection élargie
class AdvancedClassifier:
    def __init__(self):
        self.keywords = {
            'howto': {
                'strong': [
                    # Instructions directes
                    'comment', 'how to', 'étapes', 'guide', 'tutoriel', 'procédure', 'méthode',
                    'marche à suivre', 'pas à pas', 'instruction', 'mode d\'emploi', 'recette',
                    'tuto', 'walkthrough', 'démarche', 'processus', 'technique',
                    
                    # Verbes d'action
                    'faire', 'créer', 'installer', 'configurer', 'réparer', 'construire',
                    'développer', 'mettre en place', 'réaliser', 'effectuer', 'exécuter',
                    'accomplir', 'pratiquer', 'appliquer', 'implémenter', 'débuter',
                    'commencer', 'démarrer', 'lancer', 'organiser', 'planifier',
                    'préparer', 'établir', 'monter', 'assembler', 'produire',
                    
                    # Objectifs d'apprentissage
                    'apprendre à', 'maîtriser', 'devenir', 'acquérir', 'obtenir',
                    'réussir à', 'parvenir à', 'arriver à', 'être capable de',
                    'savoir comment', 'pouvoir', 'formation', 'apprentissage'
                ],
                'medium': [
                    'solution', 'résoudre', 'problème', 'astuce', 'conseil',
                    'technique', 'stratégie', 'approche', 'façon de', 'manière de',
                    'tips', 'hack', 'trick', 'secret', 'clé pour'
                ]
            },
            
            'comparative': {
                'strong': [
                    # Comparaisons directes
                    'vs', 'versus', 'contre', 'face à', 'par rapport à', 'comparé à',
                    'en comparaison', 'comparaison', 'différence', 'distinction',
                    'contraste', 'opposition', 'confrontation',
                    
                    # Choix et sélection
                    'meilleur', 'mieux', 'supérieur', 'inférieur', 'préférable',
                    'choisir', 'sélectionner', 'opter', 'préférer', 'privilégier',
                    'alternative', 'option', 'choix', 'possibilité', 'variante',
                    'substitut', 'remplaçant', 'équivalent',
                    
                    # Classements et évaluations
                    'top', 'classement', 'ranking', 'meilleurs', 'pires',
                    'premiers', 'derniers', 'leader', 'gagnant', 'perdant',
                    'champion', 'optimal', 'idéal', 'parfait', 'ultime',
                    
                    # Questions de choix
                    'ou', 'soit', 'plutôt', 'entre', 'parmi', 'lequel',
                    'laquelle', 'lesquels', 'lesquelles', 'quel', 'quelle'
                ],
                'medium': [
                    'avantages', 'inconvénients', 'pour et contre', 'pros cons',
                    'bénéfices', 'désavantages', 'points forts', 'points faibles',
                    'qualités', 'défauts', 'atouts', 'faiblesses', 'forces',
                    'limites', 'contraintes', 'restrictions', 'concurrence',
                    'concurrent', 'rival', 'compétiteur', 'benchmark'
                ]
            },
            
            'transactional': {
                'strong': [
                    # Intentions d'achat directes
                    'acheter', 'achat', 'buy', 'purchase', 'commander', 'réserver',
                    'souscrire', 'acquérir', 'investir', 'dépenser', 'payer',
                    'financer', 'louer', 'emprunter', 'contracter',
                    
                    # Prix et coûts
                    'prix', 'coût', 'tarif', 'montant', 'budget', 'frais',
                    'charge', 'dépense', 'investissement', 'valeur', 'cost',
                    'price', 'rate', 'fee', 'économiser', 'économie',
                    'pas cher', 'bon marché', 'abordable', 'gratuit', 'free',
                    'payant', 'cher', 'coûteux', 'onéreux', 'promotion',
                    'réduction', 'remise', 'rabais', 'discount', 'solde',
                    'offre', 'deal', 'bon plan', 'opportunité',
                    
                    # Services et produits
                    'abonnement', 'subscription', 'forfait', 'pack', 'formule',
                    'plan', 'version', 'édition', 'licence', 'essai', 'trial',
                    'démo', 'démonstration', 'test gratuit', 'période d\'essai',
                    
                    # Évaluations commerciales
                    'avis', 'review', 'test', 'évaluation', 'notation', 'note',
                    'recommandation', 'conseil d\'achat', 'guide d\'achat',
                    'retour d\'expérience', 'témoignage', 'feedback',
                    'opinion', 'critique', 'jugement'
                ],
                'medium': [
                    'qualité prix', 'rapport qualité prix', 'rentable', 'rentabilité',
                    'retour sur investissement', 'roi', 'bénéfice', 'profit',
                    'gain', 'économique', 'financier', 'budgétaire',
                    'commercial', 'vente', 'acheteur', 'vendeur', 'client',
                    'consommateur', 'utilisateur payant', 'premium'
                ]
            },
            
            'informational': {
                'strong': [
                    # Questions d'information
                    'qu\'est-ce que', 'qu\'est ce que', 'what is', 'c\'est quoi',
                    'définition', 'définir', 'expliquer', 'explication',
                    'comprendre', 'understanding', 'signification', 'sens',
                    'notion', 'concept', 'principe', 'théorie', 'idée',
                    
                    # Questions causales
                    'pourquoi', 'why', 'raison', 'cause', 'origine', 'source',
                    'motif', 'justification', 'explication', 'fondement',
                    'base', 'racine', 'facteur', 'élément déclencheur',
                    
                    # Recherche de connaissances
                    'savoir', 'connaître', 'information', 'renseignement',
                    'détail', 'précision', 'éclaircissement', 'clarification',
                    'connaissance', 'science', 'étude', 'recherche',
                    'analyse', 'examen', 'investigation',
                    
                    # Questions temporelles et contextuelles
                    'quand', 'when', 'où', 'where', 'who', 'qui', 'whom',
                    'combien', 'how much', 'how many', 'quelle quantité',
                    'quel nombre', 'à quel point', 'dans quelle mesure'
                ],
                'medium': [
                    'contexte', 'background', 'historique', 'évolution',
                    'développement', 'progression', 'tendance', 'mouvement',
                    'phénomène', 'situation', 'état', 'statut', 'condition',
                    'circonstance', 'environnement', 'cadre', 'domaine',
                    'secteur', 'domaine d\'application', 'usage', 'utilisation',
                    'fonction', 'rôle', 'importance', 'impact', 'influence',
                    'effet', 'conséquence', 'résultat', 'implication'
                ]
            }
        }
        
        # Patterns regex pour détecter les structures linguistiques
        self.patterns = {
            'howto': [
                r'\b(comment|how\s+to)\s+\w+',
                r'\b(étape|step)\s*\d+',
                r'\b(guide|tutoriel|tutorial)\s+(pour|to|de)',
                r'\b(installer|configurer|réparer|créer|faire)\b',
                r'\b(apprendre\s+à|learn\s+to)\s+\w+',
                r'\b(devenir|become)\s+\w+',
                r'\b(réussir\s+à|succeed\s+in)\s+\w+'
            ],
            'comparative': [
                r'\b(\w+)\s+(vs|versus|contre)\s+(\w+)',
                r'\b(\w+)\s+ou\s+(\w+)',
                r'\b(meilleur|best)\s+(\w+\s+)?entre',
                r'\b(comparaison|comparison)\s+(de|of)',
                r'\b(top\s*\d+|classement)',
                r'\b(choisir\s+entre|choose\s+between)',
                r'\b(différence\s+entre|difference\s+between)',
                r'\b(\w+)\s+(mieux\s+que|better\s+than)\s+(\w+)'
            ],
            'transactional': [
                r'\b(prix|price|cost)\s+(de|of|pour)\s+\w+',
                r'\b(acheter|buy|purchase)\s+\w+',
                r'\b(meilleur|best)\s+\w+\s+(prix|price)',
                r'\b(avis|review|test)\s+\w+',
                r'\b(gratuit|free|payant|paid)\b',
                r'\b(abonnement|subscription)\s+\w+',
                r'\b(promotion|deal|offre)\s+\w+',
                r'\b(pas\s+cher|cheap|affordable)\b'
            ],
            'informational': [
                r'\b(qu\'est-ce\s+que|what\s+is)\s+\w+',
                r'\b(pourquoi|why)\s+\w+',
                r'\b(définition|definition)\s+(de|of)',
                r'\b(comprendre|understand)\s+\w+',
                r'\b(c\'est\s+quoi|what\s+are)\s+\w+',
                r'\b(signification|meaning)\s+(de|of)'
            ]
        }
    
    def classify(self, query: str) -> str:
        import re
        
        query_lower = query.lower().strip()
        scores = {}
        
        # Analyse par mots-clés avec pondération
        for schema_type, keyword_sets in self.keywords.items():
            score = 0
            
            # Mots-clés forts (poids 3)
            for keyword in keyword_sets['strong']:
                if keyword in query_lower:
                    score += 3
            
            # Mots-clés moyens (poids 1)
            if 'medium' in keyword_sets:
                for keyword in keyword_sets['medium']:
                    if keyword in query_lower:
                        score += 1
            
            scores[schema_type] = score
        
        # Analyse par patterns regex (poids 4)
        for schema_type, patterns in self.patterns.items():
            for pattern in patterns:
                if re.search(pattern, query_lower, re.IGNORECASE):
                    scores[schema_type] += 4
        
        # Bonus pour longueur de requête selon le type
        query_words = len(query.split())
        if query_words >= 5:  # Requêtes longues souvent howto/comparative
            if 'comment' in query_lower or 'how' in query_lower:
                scores['howto'] += 2
            elif any(word in query_lower for word in ['vs', 'versus', 'ou', 'meilleur', 'choisir']):
                scores['comparative'] += 2
        
        # Détection de questions (souvent informational)
        question_words = ['qui', 'que', 'quoi', 'où', 'quand', 'comment', 'pourquoi', 'combien']
        if query.strip().endswith('?') or any(word in query_lower for word in question_words):
            scores['informational'] += 1
        
        # Retourner le type avec le score le plus élevé
        if max(scores.values()) > 0:
            best_type = max(scores, key=scores.get)
            confidence = scores[best_type]
            print(f"🎯 Scores de classification: {scores}")
            print(f"🏆 Type détecté: {best_type} (score: {confidence})")
            return best_type
        else:
            print("⚠️  Aucun type détecté clairement, utilisation du type informational par défaut")
            return 'informational'

# Générateur principal
class SimplePlanGenerator:
    def __init__(self):
        self.config = Config()
        self.classifier = AdvancedClassifier()
        self.parser = JSONParser()
        
        # Modèle LangChain
        self.llm = ChatDeepSeek(
            model="deepseek-chat",
            api_key=self.config.deepseek_key,
            max_tokens=3000,
            temperature=0.7,
            timeout=self.config.timeout
        )
        
        # Charger les données
        self.consigne_path = self._find_consigne_file()
        with open(self.consigne_path, 'r', encoding='utf-8') as f:
            self.consigne_data = json.load(f)
    
    def _find_consigne_file(self) -> Path:
        consigne_files = list(self.config.static_dir.glob("consigne*.json"))
        if not consigne_files:
            raise FileNotFoundError("Fichier consigne*.json introuvable")
        return consigne_files[0]
    
    def _load_prompt(self, schema_type: str) -> str:
        """Charge le prompt selon le type de schéma"""
        prompt_files = {
            'howto': 'howto.md',
            'comparative': 'comparator.md',
            'transactional': 'transactor.md',
            'informational': 'plan_generator.md'
        }
        
        prompt_file = self.config.prompts_dir / prompt_files[schema_type]
        if not prompt_file.exists():
            raise FileNotFoundError(f"Prompt {prompt_file} introuvable")
        
        return prompt_file.read_text(encoding='utf-8')
    
    def _prepare_variables(self, query_data: Dict) -> Dict:
        """Prépare les variables pour le template"""
        return {
            'requete': query_data.get('text', ''),
            'word_count': query_data.get('word_count', 1000),
            'top_keywords': query_data.get('top_keywords', ''),
            'nb_sections': 3,
            'agent_response': json.dumps(query_data.get('agent_response', {}),
                                       ensure_ascii=False, indent=2),
            'differentiating_angles': json.dumps(query_data.get('differentiating_angles', []),
                                               ensure_ascii=False, indent=2)
        }
    
    def generate_plan(self, query_data: Dict) -> Optional[Dict]:
        """Génère un plan pour une requête"""
        try:
            # Classification automatique
            query_text = query_data.get('text', '')
            schema_type = self.classifier.classify(query_text)
            
            print(f"🎯 Schéma détecté: {schema_type}")
            
            # Charger le prompt approprié
            prompt_template = self._load_prompt(schema_type)
            
            # Préparer les variables
            variables = self._prepare_variables(query_data)
            
            # Formater le prompt (simple remplacement)
            formatted_prompt = prompt_template
            for key, value in variables.items():
                formatted_prompt = formatted_prompt.replace(f"{{{key}}}", str(value))
            
            # Appel API
            response = self.llm.invoke(formatted_prompt)
            
            # Parser la réponse
            plan = self.parser.parse(response.content)
            
            # Ajouter métadonnées
            plan['classification_metadata'] = {
                'detected_schema': schema_type,
                'prompt_used': f"{schema_type}.md"
            }
            
            return plan
            
        except Exception as e:
            print(f"❌ Erreur génération plan: {e}")
            return None
    
    def process_queries(self, query_ids: List[int]):
        """Traite une liste de requêtes"""
        for query_id in query_ids:
            # Trouver la requête
            query_data = None
            for q in self.consigne_data['queries']:
                if q['id'] == query_id:
                    query_data = q
                    break
            
            if not query_data:
                print(f"❌ Requête {query_id} introuvable")
                continue
            
            print(f"🚀 Traitement requête {query_id}...")
            
            # Générer le plan
            plan = self.generate_plan(query_data)
            
            if plan:
                # Sauvegarder dans les données
                query_data['generated_plan'] = plan
                print(f"✅ Plan généré: {plan.get('title', 'N/A')}")
            else:
                print(f"❌ Échec génération pour requête {query_id}")
        
        # Sauvegarder le fichier
        with open(self.consigne_path, 'w', encoding='utf-8') as f:
            json.dump(self.consigne_data, f, ensure_ascii=False, indent=4)
        
        print("💾 Fichier sauvegardé")
    
    def list_queries(self):
        """Liste les requêtes disponibles"""
        print("📋 Requêtes disponibles:")
        for query in self.consigne_data.get('queries', []):
            has_plan = 'generated_plan' in query
            status = "✅ Plan" if has_plan else "⏳ Pas de plan"
            print(f"ID {query['id']:2d} | {status} | {query['text']}")

# Version optimisée avec parallélisation
class OptimizedPlanGenerator(SimplePlanGenerator):
    
    def __init__(self):
        super().__init__()
        self.max_concurrent = 5
    
    def batch_classify_all(self, query_ids: List[int]) -> List[Tuple[Dict, str]]:
        """Phase 1: Classification ultra-rapide de TOUTES les requêtes"""
        print(f"🎯 Classification de {len(query_ids)} requêtes...")
        start_time = time.time()
        
        classified_queries = []
        for query_id in query_ids:
            query_data = None
            for q in self.consigne_data['queries']:
                if q['id'] == query_id:
                    query_data = q
                    break
            
            if query_data:
                schema_type = self.classifier.classify(query_data['text'])
                classified_queries.append((query_data, schema_type))
                print(f"  ID {query_id}: {schema_type}")
        
        elapsed = time.time() - start_time
        print(f"✅ Classification terminée en {elapsed:.2f}s ({len(classified_queries)} requêtes)")
        return classified_queries
    
    def group_by_schema(self, classified_queries: List[Tuple[Dict, str]]) -> Dict[str, List[Dict]]:
        """Phase 2: Groupement par schéma pour optimiser les prompts"""
        grouped = {}
        for query_data, schema_type in classified_queries:
            if schema_type not in grouped:
                grouped[schema_type] = []
            grouped[schema_type].append(query_data)
        
        print("📊 Répartition par schéma:")
        for schema, queries in grouped.items():
            print(f"  {schema}: {len(queries)} requêtes")
        
        return grouped
    
    async def generate_plan_async(self, query_data: Dict, schema_type: str) -> Optional[Dict]:
        """Version async de generate_plan"""
        try:
            prompt_template = self._load_prompt(schema_type)
            variables = self._prepare_variables(query_data)
            
            formatted_prompt = prompt_template
            for key, value in variables.items():
                formatted_prompt = formatted_prompt.replace(f"{{{key}}}", str(value))
            
            loop = asyncio.get_event_loop()
            with ThreadPoolExecutor() as executor:
                response = await loop.run_in_executor(
                    executor, 
                    lambda: self.llm.invoke(formatted_prompt)
                )
            
            plan = self.parser.parse(response.content)
            
            plan['classification_metadata'] = {
                'detected_schema': schema_type,
                'prompt_used': f"{schema_type}.md"
            }
            
            print(f"✅ Plan généré pour: {query_data['text'][:50]}...")
            return plan
            
        except Exception as e:
            print(f"❌ Erreur pour requête {query_data.get('id', 'N/A')}: {e}")
            return None
    
    async def batch_process_parallel(self, query_ids: List[int]):
        """Processus complet optimisé avec pré-classification + parallélisation"""
        total_start = time.time()
        
        # Phase 1: Classification ultra-rapide
        classified_queries = self.batch_classify_all(query_ids)
        grouped_queries = self.group_by_schema(classified_queries)
        
        # Phase 2: Préparer TOUTES les tâches pour parallélisation complète
        print(f"🚀 Lancement de {len(query_ids)} appels API en parallèle...")
        
        semaphore = asyncio.Semaphore(self.max_concurrent)
        all_tasks = []
        
        # Créer les tâches pour TOUTES les requêtes, peu importe leur schéma
        for schema_type, queries in grouped_queries.items():
            for query_data in queries:
                async def limited_generate(q_data=query_data, s_type=schema_type):
                    async with semaphore:
                        return await self.generate_plan_async(q_data, s_type), q_data
                
                all_tasks.append(limited_generate())
        
        # Phase 3: Exécuter TOUS les appels API simultanément
        api_start = time.time()
        results = await asyncio.gather(*all_tasks, return_exceptions=True)
        api_elapsed = time.time() - api_start
        
        print(f"⚡ Tous les appels API terminés en {api_elapsed:.2f}s")
        
        # Phase 4: Traitement des résultats
        success_count = 0
        error_count = 0
        
        for result in results:
            if isinstance(result, Exception):
                print(f"❌ Erreur: {result}")
                error_count += 1
            else:
                plan, query_data = result
                if plan and not isinstance(plan, Exception):
                    query_data['generated_plan'] = plan
                    success_count += 1
                else:
                    error_count += 1
        
        # Phase 5: Sauvegarde unique du fichier après TOUS les traitements
        print("💾 Sauvegarde du fichier consigne...")
        with open(self.consigne_path, 'w', encoding='utf-8') as f:
            json.dump(self.consigne_data, f, ensure_ascii=False, indent=4)
        
        total_elapsed = time.time() - total_start
        
        # Statistiques finales
        print(f"\n📊 Résultats du traitement parallèle:")
        print(f"   ✅ Succès: {success_count}/{len(query_ids)}")
        print(f"   ❌ Échecs: {error_count}/{len(query_ids)}")
        print(f"   ⏱️  Temps total: {total_elapsed:.2f}s")
        print(f"   🚀 Temps API: {api_elapsed:.2f}s")
        print(f"   ⚡ Gain estimé: {len(query_ids) * 3 - total_elapsed:.1f}s vs séquentiel")
    
    def process_queries_optimized(self, query_ids: List[int]):
        """Point d'entrée pour le traitement optimisé"""
        try:
            asyncio.run(self.batch_process_parallel(query_ids))
        except Exception as e:
            print(f"❌ Erreur traitement optimisé: {e}")
            print("🔄 Fallback vers traitement séquentiel...")
            super().process_queries(query_ids)

def main():
    print("📝 Générateur de Plans SEO - Version Parallélisée")
    print("=" * 50)
    
    try:
        if len(sys.argv) > 1:
            if sys.argv[1] in ['--list', '-l']:
                generator = SimplePlanGenerator()
                generator.list_queries()
                return
            elif sys.argv[1] in ['--parallel', '-p']:
                print("🚀 Mode parallèle activé")
                generator = OptimizedPlanGenerator()
                generator.list_queries()
                user_input = input("\n🎯 IDs des requêtes à traiter (ex: 1,2,3 ou 'q'): ").strip()
                
                if user_input.lower() == 'q':
                    return
                
                query_ids = [int(x.strip()) for x in user_input.split(',')]
                generator.process_queries_optimized(query_ids)
                return
            elif sys.argv[1] in ['--help', '-h']:
                print("\nOptions disponibles:")
                print("  --parallel, -p   : Traitement parallèle avec pré-classification")
                print("  --list, -l       : Lister les requêtes disponibles")
                print("  --help, -h       : Afficher cette aide")
                print("  (sans option)    : Mode séquentiel classique")
                return
        
        generator = SimplePlanGenerator()
        print("✅ Générateur initialisé")
        
        generator.list_queries()
        user_input = input("\n🎯 ID de la requête à traiter (ou 'q' pour quitter): ").strip()
        
        if user_input.lower() == 'q':
            return
        
        query_id = int(user_input)
        generator.process_queries([query_id])
        
    except Exception as e:
        print(f"❌ Erreur: {e}")

if __name__ == "__main__":
    main()
