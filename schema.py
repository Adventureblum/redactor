#!/usr/bin/env python3
"""
Générateur de plans d'articles SEO avec agent spécialisé - VERSION MODULAIRE
- Exploitation optimisée des données agent_response
- Prompts externalisés dans le dossier prompts/
- Parfaite maintenabilité avec séparation des responsabilités
- Utilisation de DeepSeek API au lieu d'OpenAI
- Variables d'environnement système uniquement
"""

import json
import os
import sys
import glob
from typing import Dict, List, Any, Optional
from pathlib import Path
import requests


class DeepSeekClient:
    """Client pour l'API DeepSeek"""
    
    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("Clé API DeepSeek manquante")
        self.api_key = api_key
        self.base_url = "https://api.deepseek.com/v1"
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
    
    def chat_completions_create(self, model: str, messages: List[Dict], temperature: float = 0.7, max_tokens: int = 3000):
        """Effectue un appel à l'API chat completions de DeepSeek"""
        url = f"{self.base_url}/chat/completions"
        data = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False
        }
        
        try:
            response = requests.post(url, headers=self.headers, json=data, timeout=60)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise Exception(f"Erreur lors de l'appel à l'API DeepSeek: {e}")


# Configuration DeepSeek - Variables d'environnement système uniquement
deepseek_key = os.getenv('DEEPSEEK_KEY')
if not deepseek_key:
    print("❌ Variable d'environnement DEEPSEEK_KEY manquante.")
    print("💡 Pour définir la variable:")
    print("   Linux/Mac: export DEEPSEEK_KEY='votre_clé_ici'")
    print("   Windows:   set DEEPSEEK_KEY=votre_clé_ici")
    sys.exit(1)

print(f"🔍 Debug: DEEPSEEK_KEY configurée (longueur: {len(deepseek_key)} caractères)")
deepseek_client = DeepSeekClient(deepseek_key)


class PromptManager:
    """Gestionnaire des prompts externalisés"""
    
    def __init__(self, prompts_dir: str = "prompts"):
        self.prompts_dir = Path(prompts_dir)
        self.prompts_dir.mkdir(exist_ok=True)
        self._ensure_plan_prompt_exists()
    
    def _ensure_plan_prompt_exists(self):
        """Vérifie que le prompt de génération de plans existe"""
        # Chercher d'abord .yaml puis .txt
        plan_prompt_yaml = self.prompts_dir / "plan_generator.yaml"
        plan_prompt_txt = self.prompts_dir / "plan_generator.txt"
        
        if plan_prompt_yaml.exists():
            self.plan_prompt_file = "plan_generator.yaml"
            print(f"📝 Prompt chargé: {plan_prompt_yaml}")
        elif plan_prompt_txt.exists():
            self.plan_prompt_file = "plan_generator.txt"
            print(f"📝 Prompt chargé: {plan_prompt_txt}")
        else:
            print(f"❌ Fichier prompt manquant: {plan_prompt_yaml} ou {plan_prompt_txt}")
            print("💡 Créez le fichier prompts/plan_generator.yaml ou prompts/plan_generator.txt avec votre prompt personnalisé")
            print("📄 Exemple de structure disponible dans la documentation")
            raise FileNotFoundError(f"Prompt requis non trouvé: {plan_prompt_yaml} ou {plan_prompt_txt}")
    
    def load_prompt(self, prompt_file: str) -> str:
        """Charge un prompt depuis un fichier"""
        prompt_path = self.prompts_dir / prompt_file
        if not prompt_path.exists():
            raise FileNotFoundError(f"Fichier prompt non trouvé: {prompt_path}")
        return prompt_path.read_text(encoding='utf-8')
    
    def save_prompt(self, prompt_file: str, content: str):
        """Sauvegarde un prompt dans un fichier"""
        prompt_path = self.prompts_dir / prompt_file
        prompt_path.write_text(content, encoding='utf-8')
        print(f"💾 Prompt sauvegardé: {prompt_path}")
    
    def format_plan_prompt(self, template_vars: Dict[str, Any]) -> str:
        """Formate le prompt de plan avec les variables données"""
        template = self.load_prompt(self.plan_prompt_file)
        
        try:
            return template.format(**template_vars)
        except KeyError as e:
            missing_var = str(e).strip("'")
            print(f"⚠️  Variable manquante dans le prompt: {missing_var}")
            print(f"Variables disponibles: {list(template_vars.keys())}")
            # Retourner le template non formaté plutôt que planter
            return template


def _find_consigne_file() -> str:
    """Trouve automatiquement le fichier de consigne dans le dossier static"""
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    STATIC_DIR = os.path.join(BASE_DIR, "static")
    
    consigne_pattern = os.path.join(STATIC_DIR, "consigne*.json")
    consigne_files = glob.glob(consigne_pattern)
    
    if not consigne_files:
        raise FileNotFoundError(f"❌ Aucun fichier de consigne trouvé dans {STATIC_DIR}/ (pattern: consigne*.json)")
    
    if len(consigne_files) == 1:
        found_file = consigne_files[0]
        print(f"📁 Fichier de consigne détecté: {os.path.basename(found_file)}")
        return found_file
    
    # Si plusieurs fichiers trouvés, prendre le plus récent
    consigne_files.sort(key=os.path.getmtime, reverse=True)
    most_recent = consigne_files[0]
    print(f"📁 Plusieurs fichiers de consigne trouvés, utilisation du plus récent: {os.path.basename(most_recent)}")
    return most_recent


class DataAnalyzer:
    """Analyseur de données agent_response - Responsabilité unique"""
    
    @staticmethod
    def analyze_data_richness(agent_response: Dict) -> Dict[str, int]:
        """Analyse la richesse des données agent_response pour adapter le plan"""
        return {
            'shock_statistics': len(agent_response.get('shock_statistics', [])),
            'expert_insights': len(agent_response.get('expert_insights', [])),
            'benchmark_data': len(agent_response.get('benchmark_data', [])),
            'market_trends': len(agent_response.get('market_trends', [])),
            'competitive_landscape': len(agent_response.get('competitive_landscape', [])),
            'hook_potential': 1 if agent_response.get('hook_potential') else 0,
            'credibility_boosters': len(agent_response.get('credibility_boosters', [])),
            'content_marketing_angles': len(agent_response.get('content_marketing_angles', []))
        }


class SectionPlanner:
    """Planificateur de sections - Responsabilité unique + Conscience de l'angle"""
    
    @staticmethod
    def suggest_optimal_sections(agent_response: Dict, base_sections: int = 3, angle_recommande: str = "") -> List[Dict]:
        """Suggère des sections optimales basées sur les données disponibles ET l'angle recommandé"""
        richness = DataAnalyzer.analyze_data_richness(agent_response)
        sections = []
        
        # 🎯 DÉTECTION AUTOMATIQUE DU TYPE D'ANGLE
        angle_type = SectionPlanner._detect_angle_type(angle_recommande)
        
        # Section 1: Toujours une section d'introduction/bases adaptée à l'angle
        sections.append({
            'type': 'éducatif',
            'focus': 'bases_concepts',
            'data_sources': ['shock_statistics', 'expert_insights'],
            'title_hint': 'Comprendre les bases/fondamentaux',
            'angle_adaptation': f"Adapter selon l'angle: {angle_recommande}",
            'angle_type': angle_type
        })
        
        # Sections adaptatives basées sur les données ET l'angle
        if richness['benchmark_data'] >= 2:
            sections.append({
                'type': 'informatif',
                'focus': 'donnees_performance',
                'data_sources': ['benchmark_data', 'shock_statistics'],
                'title_hint': 'Données de performance et statistiques clés',
                'specific_data': agent_response.get('benchmark_data', []),
                'angle_adaptation': f"Interpréter les données selon: {angle_recommande}",
                'angle_type': angle_type
            })
        
        if richness['market_trends'] >= 1:
            sections.append({
                'type': 'informatif',
                'focus': 'tendances_marche',
                'data_sources': ['market_trends', 'competitive_landscape'],
                'title_hint': 'Évolutions du marché et tendances',
                'specific_data': agent_response.get('market_trends', []),
                'angle_adaptation': f"Contextualiser selon: {angle_recommande}",
                'angle_type': angle_type
            })
        
        if richness['competitive_landscape'] >= 1:
            sections.append({
                'type': 'informatif',
                'focus': 'comparatifs',
                'data_sources': ['competitive_landscape', 'benchmark_data'],
                'title_hint': 'Comparaisons et alternatives',
                'specific_data': agent_response.get('competitive_landscape', []),
                'angle_adaptation': f"Comparer dans l'optique: {angle_recommande}",
                'angle_type': angle_type
            })
        
        if richness['expert_insights'] >= 2:
            sections.append({
                'type': 'informatif',
                'focus': 'avis_experts',
                'data_sources': ['expert_insights', 'credibility_boosters'],
                'title_hint': 'Recommandations d\'experts',
                'specific_data': agent_response.get('expert_insights', []),
                'angle_adaptation': f"Sélectionner experts pertinents pour: {angle_recommande}",
                'angle_type': angle_type
            })
        
        # Sections commerciales (toujours en fin) adaptées à l'angle
        if len(sections) < base_sections - 1:
            sections.append({
                'type': 'commercial léger',
                'focus': 'solutions_pratiques',
                'data_sources': ['content_marketing_angles', 'benchmark_data'],
                'title_hint': 'Solutions pratiques et conseils',
                'angle_adaptation': f"Proposer solutions alignées avec: {angle_recommande}",
                'angle_type': angle_type
            })
        
        sections.append({
            'type': 'commercial subtil',
            'focus': 'optimisation_resultats',
            'data_sources': ['content_marketing_angles', 'market_trends'],
            'title_hint': 'Optimiser ses résultats/choix',
            'angle_adaptation': f"Conclure en cohérence avec: {angle_recommande}",
            'angle_type': angle_type
        })
        
        return sections[:base_sections] if len(sections) > base_sections else sections
    
    @staticmethod
    def _detect_angle_type(angle_recommande: str) -> str:
        """Détecte automatiquement le type d'angle pour adapter la stratégie"""
        angle_lower = angle_recommande.lower()
        
        # Détection de mots-clés pour classifier l'angle
        if any(word in angle_lower for word in ['psycholog', 'émot', 'humain', 'stress', 'mental']):
            return 'psychologique'
        elif any(word in angle_lower for word in ['géograph', 'local', 'région', 'ville']):
            return 'géographique'
        elif any(word in angle_lower for word in ['budget', 'financ', 'économ', 'gestion']):
            return 'financier'
        elif any(word in angle_lower for word in ['technique', 'expert', 'professionnel', 'spécialisé']):
            return 'technique'
        elif any(word in angle_lower for word in ['comparai', 'versus', 'alternative', 'choix']):
            return 'comparatif'
        elif any(word in angle_lower for word in ['tendance', 'évolution', 'futur', 'innovation']):
            return 'prospectif'
        else:
            return 'généraliste'


class DataAssigner:
    """Assignateur de données aux sections - Responsabilité unique + Conscience d'angle"""
    
    @staticmethod
    def assign_specific_data_to_section(section: Dict, agent_response: Dict) -> Dict:
        """Assigne des données spécifiques à une section basée sur son focus ET son angle"""
        section_copy = section.copy()
        assigned_data = {}
        
        focus = section.get('focus', '')
        angle_type = section.get('angle_type', 'généraliste')
        angle_adaptation = section.get('angle_adaptation', '')
        
        # Assignation spécifique par focus (logique existante)
        if focus == 'bases_concepts':
            stats = agent_response.get('shock_statistics', [])
            if stats:
                assigned_data['primary_statistic'] = stats[0]
                assigned_data['supporting_insights'] = agent_response.get('expert_insights', [])[:1]
        
        elif focus == 'donnees_performance':
            assigned_data['benchmark_metrics'] = agent_response.get('benchmark_data', [])
            assigned_data['supporting_statistics'] = agent_response.get('shock_statistics', [])[1:] if len(agent_response.get('shock_statistics', [])) > 1 else []
        
        elif focus == 'tendances_marche':
            assigned_data['market_trends'] = agent_response.get('market_trends', [])
            assigned_data['competitive_data'] = agent_response.get('competitive_landscape', [])
        
        elif focus == 'comparatifs':
            assigned_data['comparisons'] = agent_response.get('competitive_landscape', [])
            assigned_data['quantified_benefits'] = [b for b in agent_response.get('benchmark_data', []) if 'économis' in b.get('metric', '').lower()]
        
        elif focus == 'avis_experts':
            assigned_data['expert_opinions'] = agent_response.get('expert_insights', [])
            assigned_data['authority_sources'] = agent_response.get('credibility_boosters', [])
        
        elif focus in ['solutions_pratiques', 'optimisation_resultats']:
            assigned_data['marketing_angles'] = agent_response.get('content_marketing_angles', [])
            assigned_data['hook_elements'] = agent_response.get('hook_potential', {})
        
        # 🎯 ENRICHISSEMENT AVEC L'ANGLE
        assigned_data['angle_context'] = {
            'angle_type': angle_type,
            'angle_instruction': angle_adaptation,
            'prioritized_approach': DataAssigner._get_approach_by_angle(angle_type)
        }
        
        section_copy['assigned_data'] = assigned_data
        return section_copy
    
    @staticmethod
    def _get_approach_by_angle(angle_type: str) -> str:
        """Retourne l'approche prioritaire selon le type d'angle détecté"""
        approaches = {
            'psychologique': 'Privilégier l\'impact émotionnel et humain des données',
            'géographique': 'Contextualiser selon les spécificités locales/régionales',
            'financier': 'Mettre l\'accent sur l\'aspect économique et budgétaire',
            'technique': 'Approfondir les aspects techniques et expertises',
            'comparatif': 'Structurer en comparaisons et alternatives',
            'prospectif': 'Orienter vers les évolutions et tendances futures',
            'généraliste': 'Équilibrer tous les aspects selon les données disponibles'
        }
        return approaches.get(angle_type, approaches['généraliste'])


class ContextBuilder:
    """Constructeur de contexte enrichi - Responsabilité unique + Contexte d'angle"""
    
    @staticmethod
    def create_enhanced_data_context(sections_with_data: List[Dict]) -> str:
        """Crée un contexte de données enrichi avec assignation par section ET directives d'angle"""
        context_parts = []
        
        for i, section in enumerate(sections_with_data, 1):
            section_context = [f"**SECTION {i} - {section.get('title_hint', 'Section')} ({section.get('type', 'informatif')})**"]
            
            assigned_data = section.get('assigned_data', {})
            
            # 🎯 AJOUT DU CONTEXTE D'ANGLE EN PREMIER
            angle_context = assigned_data.get('angle_context', {})
            if angle_context:
                section_context.append(f"🎯 ANGLE D'APPROCHE: {angle_context.get('angle_type', 'généraliste').upper()}")
                section_context.append(f"📋 INSTRUCTION: {angle_context.get('angle_instruction', 'Traitement standard')}")
                section_context.append(f"🎨 APPROCHE PRIORITAIRE: {angle_context.get('prioritized_approach', 'Équilibrer tous les aspects')}")
                section_context.append("")  # Ligne vide pour séparation
            
            # Données spécifiques assignées (logique existante)
            for data_type, data_content in assigned_data.items():
                if not data_content or data_type == 'angle_context':  # Skip angle_context déjà traité
                    continue
                    
                if data_type == 'primary_statistic' and isinstance(data_content, dict):
                    section_context.append(f"📊 STATISTIQUE PRINCIPALE: {data_content.get('statistic', 'N/A')}")
                    if 'usage_potential' in data_content:
                        section_context.append(f"   → Usage suggéré: {data_content['usage_potential']}")
                
                elif data_type == 'benchmark_metrics' and isinstance(data_content, list):
                    section_context.append(f"📈 MÉTRIQUES DE PERFORMANCE ({len(data_content)} éléments):")
                    for metric in data_content:
                        section_context.append(f"   • {metric.get('metric', 'N/A')} | {metric.get('sample_size', 'N/A')}")
                
                elif data_type == 'market_trends' and isinstance(data_content, list):
                    section_context.append(f"📈 TENDANCES MARCHÉ ({len(data_content)} éléments):")
                    for trend in data_content:
                        section_context.append(f"   • {trend.get('trend', 'N/A')}")
                        if 'commercial_opportunity' in trend:
                            section_context.append(f"     💡 Opportunité: {trend['commercial_opportunity']}")
                
                elif data_type == 'expert_opinions' and isinstance(data_content, list):
                    section_context.append(f"👨‍💼 AVIS D'EXPERTS ({len(data_content)} éléments):")
                    for insight in data_content:
                        section_context.append(f"   • {insight.get('insight', 'N/A')}")
                        if 'authority_source' in insight:
                            section_context.append(f"     🏛️ Source: {insight['authority_source']}")
                
                elif data_type == 'comparisons' and isinstance(data_content, list):
                    section_context.append(f"⚖️ ÉLÉMENTS COMPARATIFS ({len(data_content)} éléments):")
                    for comp in data_content:
                        section_context.append(f"   • {comp.get('comparison_point', 'N/A')}: {comp.get('quantified_difference', 'N/A')}")
                
                elif data_type == 'marketing_angles' and isinstance(data_content, list):
                    section_context.append(f"🎯 ANGLES MARKETING: {' | '.join(data_content)}")
                
                elif data_type == 'hook_elements' and isinstance(data_content, dict):
                    if 'intro_hooks' in data_content:
                        section_context.append(f"🪝 ÉLÉMENTS D'ACCROCHE: {' | '.join(data_content['intro_hooks'])}")
            
            if len(section_context) > 1:  # Si on a plus que juste le titre
                context_parts.append('\n'.join(section_context))
        
        return '\n\n'.join(context_parts)


class JSONBuilder:
    """Constructeur de JSON pour les sections - Responsabilité unique"""
    
    @staticmethod
    def build_sections_json(sections_with_data: List[Dict]) -> str:
        """Construit le JSON des sections pour le prompt"""
        sections_json = []
        
        for i, section in enumerate(sections_with_data, 1):
            section_template = f'''    "section_{i}": {{
      "title": "Titre optimisé pour: {section.get('title_hint', 'Section')}",
      "angle": "{section.get('type', 'informatif')}",
      "focus_theme": "{section.get('focus', 'general')}",
      "objectives": [
        "Objectif principal basé sur le focus {section.get('focus', 'general')}",
        "Objectif secondaire exploitant les données assignées"
      ],
      "key_points": [
        "Point clé exploitant les données spécifiques assignées",
        "Point clé créant de la valeur avec les insights disponibles"
      ],
      "data_to_include": [
        "Données spécifiques assignées à cette section",
        "Éléments de preuve pertinents du contexte enrichi"
      ]'''
            
            # Ajout de détails spécifiques basés sur les données assignées
            assigned_data = section.get('assigned_data', {})
            if assigned_data:
                section_template += f''',
      "specific_data_integration": {{'''
                
                for data_type, data_content in assigned_data.items():
                    if data_content:
                        section_template += f'''
        "{data_type}": "Intégrer spécifiquement ces données dans cette section"'''
                
                section_template += '''
      }'''
            
            # Ajouter CTA pour les sections commerciales
            if "commercial" in section.get('type', ''):
                section_template += f''',
      "cta_hint": "Call-to-action adapté au niveau {section.get('type', '')}"'''
            
            section_template += "    }"
            sections_json.append(section_template)
        
        return ",\n".join(sections_json)


class GenerateurPlanArticleModulaire:
    """Générateur principal - Orchestrateur des composants modulaires"""
    
    def __init__(self, consigne_path: str, prompts_dir: str = "prompts"):
        self.consigne_path = consigne_path
        self.consigne_data = self.load_consigne()
        self.prompt_manager = PromptManager(prompts_dir)
        
        # Composants modulaires
        self.data_analyzer = DataAnalyzer()
        self.section_planner = SectionPlanner()
        self.data_assigner = DataAssigner()
        self.context_builder = ContextBuilder()
        self.json_builder = JSONBuilder()
        
    def load_consigne(self) -> Dict:
        """Charge le fichier consigne.json"""
        try:
            with open(self.consigne_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            print(f"❌ Fichier {self.consigne_path} non trouvé.")
            sys.exit(1)
        except json.JSONDecodeError as e:
            print(f"❌ Erreur JSON dans {self.consigne_path}: {e}")
            sys.exit(1)
    
    def save_consigne(self):
        """Sauvegarde le fichier consigne.json"""
        with open(self.consigne_path, 'w', encoding='utf-8') as f:
            json.dump(self.consigne_data, f, ensure_ascii=False, indent=4)
    
    def get_query_data(self, query_id: int) -> Optional[Dict]:
        """Récupère les données d'une requête par son ID"""
        for query in self.consigne_data.get('queries', []):
            if query['id'] == query_id:
                return query
        return None
    
    def generer_plan_article_optimise(self, query_data: Dict) -> Optional[Dict]:
            """Génère un plan d'article optimisé avec exploitation complète des données agent_response"""
            
            # Récupération des paramètres
            requete = query_data.get('text', '')
            word_count = query_data.get('word_count', 1000)
            top_keywords = query_data.get('top_keywords', '')
            plan_config = query_data.get('plan', {})
            agent_response = query_data.get('agent_response', {})
            angle_recommande = query_data.get('angle_analysis', {}).get('angle_recommande', '')
            
            # Calcul du nombre de sections optimal
            dev_config = plan_config.get('developpement', {})
            base_sections = dev_config.get('nombre_sections', 3)
            
            # 🎯 PASSAGE DE L'ANGLE AU PLANIFICATEUR (MODIFICATION ICI)
            optimal_sections = self.section_planner.suggest_optimal_sections(
                agent_response, 
                base_sections, 
                angle_recommande  # ← AJOUT DU PARAMÈTRE ANGLE
            )
            sections_with_data = [self.data_assigner.assign_specific_data_to_section(section, agent_response) for section in optimal_sections]
            enhanced_context = self.context_builder.create_enhanced_data_context(sections_with_data)
            sections_json_str = self.json_builder.build_sections_json(sections_with_data)
            
            # Construction du hook basé sur les données les plus marquantes
            hook_suggestion = "Statistique générale ou fait marquant"
            if agent_response.get('shock_statistics'):
                hook_suggestion = f"ACCROCHE RECOMMANDÉE: {agent_response['shock_statistics'][0].get('statistic', 'Stat non trouvée')}"
            
            # Préparation des variables pour le prompt
            template_vars = {
                'requete': requete,
                'word_count': word_count,
                'top_keywords': top_keywords,
                'nb_sections': len(sections_with_data),
                'enhanced_context': enhanced_context,
                'hook_suggestion': hook_suggestion,
                'sections_json_str': sections_json_str,
                'angle_recommande': angle_recommande
            }
            
            # Formatage du prompt avec le gestionnaire
            formatted_prompt = self.prompt_manager.format_plan_prompt(template_vars)
            
            try:
                response = deepseek_client.chat_completions_create(
                    model="deepseek-chat",
                    messages=[{"role": "user", "content": formatted_prompt}],
                    temperature=0.7,
                    max_tokens=3000
                )
                
                plan_content = response['choices'][0]['message']['content'].strip()
                
                # Nettoyage du contenu
                if plan_content.startswith("```json"):
                    plan_content = plan_content[7:]
                if plan_content.endswith("```"):
                    plan_content = plan_content[:-3]
                
                # Parsing JSON
                try:
                    plan_json = json.loads(plan_content.strip())
                    return plan_json
                except json.JSONDecodeError as e:
                    print(f"❌ Erreur de parsing JSON: {e}")
                    print(f"Contenu reçu: {plan_content[:500]}...")
                    return None
                    
            except Exception as e:
                print(f"❌ Erreur lors de la génération du plan: {e}")
                return None
    
    def process_queries(self, query_ids: List[int]):
        """Traite une liste de requêtes avec la version modulaire"""
        print(f"\n📝 GÉNÉRATION DE PLANS MODULAIRES POUR {len(query_ids)} REQUÊTE(S)")
        
        for query_id in query_ids:
            try:
                query_data = self.get_query_data(query_id)
                if not query_data:
                    print(f"   ❌ Aucune donnée trouvée pour ID {query_id}")
                    continue
                
                # Vérification de la présence des données agent_response
                agent_response = query_data.get('agent_response', {})
                data_richness = self.data_analyzer.analyze_data_richness(agent_response)
                total_data_points = sum(data_richness.values())
                
                print(f"   🎯 ID {query_id}: '{query_data.get('text', 'N/A')}'")
                print(f"   📊 Richesse des données: {total_data_points} éléments disponibles")
                
                # Génération du plan optimisé
                plan = self.generer_plan_article_optimise(query_data)
                
                if plan:
                    # Intégration dans consigne.json
                    for query in self.consigne_data['queries']:
                        if query['id'] == query_id:
                            query['generated_plan'] = plan
                            break
                    
                    sections_count = len(plan.get('structure', {})) - 2  # -2 pour intro et conclusion
                    print(f"   ✅ Plan modulaire généré ({sections_count} sections)")
                    if 'data_exploitation_summary' in plan:
                        print(f"   📈 Exploitation: {plan['data_exploitation_summary']}")
                else:
                    print(f"   ❌ Échec génération plan pour ID {query_id}")
                    
            except Exception as e:
                print(f"   ❌ Erreur lors de la génération du plan ID {query_id}: {e}")
        
        # Sauvegarde
        try:
            self.save_consigne()
            print(f"\n💾 Fichier {self.consigne_path} mis à jour avec succès!")
        except Exception as e:
            print(f"❌ Erreur lors de la sauvegarde: {e}")


def compare_plan_approaches():
    """Compare l'approche basique vs modulaire"""
    print("\n📊 COMPARAISON DES APPROCHES:")
    print("=" * 60)
    print("🔴 APPROCHE BASIQUE:")
    print("   - Prompt hardcodé dans le script")
    print("   - Difficile à maintenir et modifier")
    print("   - Couplage fort entre logique et contenu")
    print()
    print("🟢 APPROCHE MODULAIRE:")
    print("   - Prompts externalisés dans prompts/")
    print("   - Modification facile sans toucher au code")
    print("   - Séparation claire des responsabilités")
    print("   - Classes spécialisées pour chaque tâche")
    print("   - Maintenabilité maximale")


def main():
    """Fonction principale avec version modulaire"""
    print("📝 GÉNÉRATEUR DE PLANS D'ARTICLES SEO - VERSION MODULAIRE (DeepSeek)")
    print("=" * 70)
    print("🎯 Variables d'environnement système + Architecture modulaire + DeepSeek API")
    
    compare_plan_approaches()
    
    # Auto-détection du fichier consigne
    try:
        consigne_path = _find_consigne_file()
    except FileNotFoundError as e:
        print(str(e))
        sys.exit(1)
    
    # Initialisation du générateur modulaire
    try:
        generateur = GenerateurPlanArticleModulaire(consigne_path)
    except FileNotFoundError as e:
        print(f"\n{e}")
        print("\n📋 GUIDE DE DÉMARRAGE:")
        print("1. Créez le dossier 'prompts/' dans votre projet")
        print("2. Créez le fichier 'prompts/plan_generator.txt' avec votre prompt")
        print("3. Utilisez les variables: {requete}, {word_count}, {top_keywords}, etc.")
        sys.exit(1)
    
    # Interface utilisateur simplifiée
    print(f"\n📁 Prompt utilisé: {generateur.prompt_manager.prompts_dir}/plan_generator.txt")
    print("💡 Tapez l'ID de la requête à traiter avec la version modulaire:")
    try:
        query_id = int(input("ID: "))
        generateur.process_queries([query_id])
    except (ValueError, KeyboardInterrupt):
        print("Arrêt du programme.")


if __name__ == "__main__":
    main()