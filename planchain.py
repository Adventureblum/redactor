import os
import json
import logging
import asyncio
import aiofiles
import shutil
import threading
import glob
from typing import Dict, List, Any, Optional, Tuple
from langchain_openai import ChatOpenAI
from langchain.schema import SystemMessage, HumanMessage
from langchain.callbacks.base import BaseCallbackHandler
from concurrent.futures import ThreadPoolExecutor
from langdetect import detect

# === Configuration ===
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Clé API OpenAI
api_key = os.getenv('OPENAI_API_KEY')
if not api_key:
    raise ValueError("OPENAI_API_KEY non trouvée dans les variables d'environnement")

# Fichiers
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
MAX_WORKERS = 2  # Pour les tâches CPU

# === Détecteur de langue ===
class LanguageDetector:
    """Détecte la langue du contenu et adapte les prompts"""
    
    @staticmethod
    def detect_language(text: str) -> str:
        """Détecte la langue du texte (fr ou en)"""
        try:
            lang = detect(text)
            # On se limite à français et anglais
            if lang == 'fr':
                return 'fr'
            else:
                return 'en'  # Par défaut, anglais pour toute autre langue
        except:
            # En cas d'erreur, on détermine par des mots-clés
            french_indicators = ['comment', 'pourquoi', 'qu\'est', 'faire', 'étape', 'guide']
            text_lower = text.lower()
            french_count = sum(1 for word in french_indicators if word in text_lower)
            return 'fr' if french_count >= 2 else 'en'
    
    @staticmethod
    def get_localized_strings(lang: str) -> Dict[str, str]:
        """Retourne les chaînes localisées selon la langue"""
        strings = {
            'fr': {
                'howto_keywords': ['comment', 'étape', 'guide', 'tuto', 'faire'],
                'definitional_keywords': ['qu\'est', 'qu est', 'c\'est quoi', 'définition'],
                'comparative_keywords': ['différence', 'versus', 'vs', 'ou', 'comparaison', 'mieux'],
                'faq_keywords': ['pourquoi', 'raison', 'cause'],
                'listicle_keywords': ['liste', 'top', 'meilleur', 'classement'],
                'intro_label': 'Introduction',
                'conclusion_label': 'Conclusion',
                'prerequisites_label': 'Prérequis/Matériel nécessaire',
                'tips_label': 'Conseils et bonnes pratiques',
                'summary_label': 'Synthèse',
                'criteria_label': 'Critères de sélection',
                'recap_label': 'Récapitulatif',
                'main_sections': 'sections principales',
                'words_each': 'mots chacune',
                'absolute_constraint': 'Le plan doit contenir EXACTEMENT',
                'priority_keywords': 'MOTS-CLÉS PRIORITAIRES',
                'specific_requirements': 'EXIGENCES SPÉCIFIQUES'
            },
            'en': {
                'howto_keywords': ['how', 'step', 'guide', 'tutorial', 'make'],
                'definitional_keywords': ['what is', 'what are', 'definition', 'meaning'],
                'comparative_keywords': ['difference', 'versus', 'vs', 'or', 'comparison', 'better'],
                'faq_keywords': ['why', 'reason', 'cause'],
                'listicle_keywords': ['list', 'top', 'best', 'ranking'],
                'intro_label': 'Introduction',
                'conclusion_label': 'Conclusion',
                'prerequisites_label': 'Prerequisites/Required Materials',
                'tips_label': 'Tips and Best Practices',
                'summary_label': 'Summary',
                'criteria_label': 'Selection Criteria',
                'recap_label': 'Recap',
                'main_sections': 'main sections',
                'words_each': 'words each',
                'absolute_constraint': 'The plan must contain EXACTLY',
                'priority_keywords': 'PRIORITY KEYWORDS',
                'specific_requirements': 'SPECIFIC REQUIREMENTS'
            }
        }
        return strings.get(lang, strings['en'])

# === Callback pour logging asynchrone ===
class AsyncLoggingCallback(BaseCallbackHandler):
    def __init__(self, query_id: int):
        self.query_id = query_id
    
    def on_llm_start(self, serialized, prompts, **kwargs):
        logging.info(f"🚀 [ID {self.query_id}] Début de l'appel à GPT-4o")
    
    def on_llm_end(self, response, **kwargs):
        logging.info(f"✅ [ID {self.query_id}] Appel GPT-4o terminé avec succès")
    
    def on_llm_error(self, error, **kwargs):
        logging.error(f"❌ [ID {self.query_id}] Erreur GPT-4o: {error}")

# === Agent d'analyse d'intention et de type d'article (Multilingue) ===
class ArticleTypeAnalyzer:
    """Analyseur intelligent pour déterminer le type d'article optimal"""
    
    def __init__(self, query_id: int):
        self.query_id = query_id
        self.language_detector = LanguageDetector()
    
    def analyze_query_intent(self, query_text: str) -> str:
        """Analyse l'intention de recherche de la requête (multilingue)"""
        query_lower = query_text.lower()
        
        # Détection de la langue
        lang = self.language_detector.detect_language(query_text)
        strings = self.language_detector.get_localized_strings(lang)
        
        logging.info(f"🌐 [ID {self.query_id}] Langue détectée: {lang.upper()}")
        
        if any(word in query_lower for word in strings['howto_keywords']):
            return 'howto'
        elif any(word in query_lower for word in strings['definitional_keywords']):
            return 'definitional'
        elif any(word in query_lower for word in strings['comparative_keywords']):
            return 'comparative'
        elif any(word in query_lower for word in strings['faq_keywords']):
            return 'faq_page'
        elif any(word in query_lower for word in strings['listicle_keywords']):
            return 'listicle'
        else:
            return 'general'
    
    def get_article_type_config(self, intent: str) -> Dict:
        """Retourne la configuration spécifique au type d'article"""
        configs = {
            'howto': {
                'template': 'guide_step_by_step',
                'required_sections': ['introduction', 'prerequisites', 'steps', 'conclusion'],
                'structure_emphasis': 'sequential_steps'
            },
            'comparative': {
                'template': 'comparison_analysis',
                'required_sections': ['introduction', 'option_a', 'option_b', 'comparison', 'recommendation'],
                'structure_emphasis': 'side_by_side_analysis'
            },
            'faq_page': {
                'template': 'question_answer',
                'required_sections': ['introduction', 'main_questions', 'detailed_answers', 'conclusion'],
                'structure_emphasis': 'question_driven'
            },
            'listicle': {
                'template': 'numbered_list',
                'required_sections': ['introduction', 'items_list', 'analysis', 'conclusion'],
                'structure_emphasis': 'ranked_items'
            },
            'definitional': {
                'template': 'comprehensive_definition',
                'required_sections': ['definition', 'characteristics', 'examples', 'conclusion'],
                'structure_emphasis': 'concept_explanation'
            },
            'general': {
                'template': 'comprehensive_guide',
                'required_sections': ['introduction', 'main_content', 'analysis', 'conclusion'],
                'structure_emphasis': 'topic_coverage'
            }
        }
        
        return configs.get(intent, configs['general'])

# === Agent d'optimisation des snippets (Multilingue) ===
class SnippetOptimizationAgent:
    """Agent spécialisé dans l'optimisation et le placement intelligent des snippets"""
    
    def __init__(self, query_id: int, llm: ChatOpenAI):
        self.query_id = query_id
        self.llm = llm
        self.language_detector = LanguageDetector()
    
    async def optimize_snippets(self, article_plan: Dict, query_data: Dict, 
                               article_intent: str, schema_type: str) -> Dict:
        """Optimise le placement des snippets dans le plan d'article"""
        
        try:
            # Préparer les données pour le prompt
            plan_analysis = self._analyze_plan_structure(article_plan)
            query_context = self._prepare_query_context(query_data, article_intent, schema_type)
            
            # Détection de la langue
            lang = self.language_detector.detect_language(query_data.get('text', ''))
            
            # Générer le prompt d'optimisation
            optimization_prompt = self._generate_optimization_prompt(
                article_plan, plan_analysis, query_context, lang
            )
            
            # Appel LLM pour optimisation
            optimized_plan = await self._call_llm_for_optimization(optimization_prompt, lang)
            
            # Validation et application des optimisations
            final_plan = self._apply_optimizations(article_plan, optimized_plan)
            
            logging.info(f"✅ [ID {self.query_id}] Snippets optimisés et intégrés")
            return final_plan
            
        except Exception as e:
            logging.error(f"❌ [ID {self.query_id}] Erreur optimisation snippets: {e}")
            # Fallback avec valeurs par défaut
            return self._apply_fallback_snippets(article_plan)
    
    def _analyze_plan_structure(self, article_plan: Dict) -> Dict:
        """Analyse la structure du plan pour identifier les opportunités de snippets"""
        sections = article_plan.get('sections', [])
        
        analysis = {
            'total_sections': len(sections),
            'section_types': [],
            'potential_tables': 0,
            'potential_lists': 0,
            'potential_faqs': 0
        }
        
        for i, section in enumerate(sections):
            title = section.get('section_title', '').lower()
            
            # Détection des patterns dans les titres (multilingue)
            section_info = {
                'index': i,
                'title': section.get('section_title', ''),
                'type': 'standard'
            }
            
            # Détection de patterns spécifiques FR/EN
            if any(word in title for word in ['étape', 'step', 'comment', 'how']):
                section_info['type'] = 'how_to_step'
            elif any(word in title for word in ['vs', 'versus', 'comparaison', 'différence', 'comparison', 'difference']):
                section_info['type'] = 'comparison'
                analysis['potential_tables'] += 1
            elif any(word in title for word in ['liste', 'top', 'meilleur', 'list', 'best']):
                section_info['type'] = 'list'
                analysis['potential_lists'] += 1
            elif any(word in title for word in ['faq', 'question', 'problème', 'problem']):
                section_info['type'] = 'faq'
                analysis['potential_faqs'] += 1
            elif any(word in title for word in ['conseil', 'astuce', 'bonnes pratiques', 'tips', 'best practices']):
                section_info['type'] = 'tips'
            
            analysis['section_types'].append(section_info)
        
        return analysis
    
    def _prepare_query_context(self, query_data: Dict, article_intent: str, schema_type: str) -> Dict:
        """Prépare le contexte de la requête pour l'optimisation"""
        return {
            'query_text': query_data.get('text', ''),
            'article_intent': article_intent,
            'schema_type': schema_type,
            'word_count': query_data.get('word_count', 0),
            'keywords': query_data.get('top_keywords', '').split(',')[:10]
        }
    
    def _generate_optimization_prompt(self, article_plan: Dict, plan_analysis: Dict, 
                                    query_context: Dict, lang: str) -> str:
        """Génère le prompt pour l'optimisation des snippets (multilingue)"""
        
        sections_info = "\n".join([
            f"Section {i+1}: {section['title']} (Type: {section['type']})"
            for i, section in enumerate(plan_analysis['section_types'])
        ])
        
        if lang == 'fr':
            return self._get_french_optimization_prompt(article_plan, sections_info, query_context)
        else:
            return self._get_english_optimization_prompt(article_plan, sections_info, query_context)
    
    def _get_french_optimization_prompt(self, article_plan: Dict, sections_info: str, query_context: Dict) -> str:
        """Prompt d'optimisation en français"""
        return f"""Tu es un expert en optimisation SEO spécialisé dans les rich snippets Google.

**MISSION :** Analyser ce plan d'article et recommander les meilleurs formats de contenu (snippets) pour maximiser les chances d'apparition dans les résultats enrichis de Google.

**CONTEXTE DE LA REQUÊTE :**
- Requête cible : "{query_context['query_text']}"
- Type d'article : {query_context['article_intent']}
- Schema principal : {query_context['schema_type']}
- Mots cibles : {', '.join(query_context['keywords'][:5])}

**PLAN À OPTIMISER :**
Titre SEO : {article_plan.get('SEO Title', '')}

Sections disponibles :
{sections_info}

**FORMATS DE CONTENU DISPONIBLES :**
- Table_comparative : Pour comparaisons, tableaux de données
- List_numbered : Pour listes ordonnées, classements, étapes
- FAQ_structured : Pour questions-réponses
- Definition_box : Pour définitions, concepts clés
- HowTo_steps : Pour guides étape par étape
- Featured_answer : Pour réponses directes courtes
- None : Aucun format spécial

**INSTRUCTIONS :**
1. Analyse chaque section et détermine LE format le plus adapté
2. Ne recommande QU'UN SEUL format par section (pas de cumul)
3. Place les formats aux endroits les plus stratégiques
4. Utilise la logique : début = Featured_answer, milieu = formats spécialisés, fin = FAQ
5. Pour placement, utilise : "introduction", "section_1", "section_2", "section_3", "conclusion"

**FORMAT DE RÉPONSE OBLIGATOIRE (JSON strict) :**
{{
  "optimizations": [
    {{
      "section_index": 0,
      "snippet_type": "Featured_answer",
      "placement": "introduction",
      "schema_type": "{query_context['schema_type']}",
      "rationale": "Explication courte du choix"
    }}
  ]
}}

**CONTRAINTES :**
- Maximum 3 optimisations par plan
- Privilégier la qualité à la quantité
- Choisir les sections avec le plus fort potentiel SEO
- Réponse en JSON valide uniquement, aucun texte supplémentaire"""
    
    def _get_english_optimization_prompt(self, article_plan: Dict, sections_info: str, query_context: Dict) -> str:
        """Prompt d'optimisation en anglais"""
        return f"""You are an SEO expert specialized in Google rich snippets.

**MISSION:** Analyze this article plan and recommend the best content formats (snippets) to maximize chances of appearing in Google's rich results.

**QUERY CONTEXT:**
- Target query: "{query_context['query_text']}"
- Article type: {query_context['article_intent']}
- Main schema: {query_context['schema_type']}
- Target keywords: {', '.join(query_context['keywords'][:5])}

**PLAN TO OPTIMIZE:**
SEO Title: {article_plan.get('SEO Title', '')}

Available sections:
{sections_info}

**AVAILABLE CONTENT FORMATS:**
- Table_comparative: For comparisons, data tables
- List_numbered: For ordered lists, rankings, steps
- FAQ_structured: For questions and answers
- Definition_box: For definitions, key concepts
- HowTo_steps: For step-by-step guides
- Featured_answer: For short direct answers
- None: No special format

**INSTRUCTIONS:**
1. Analyze each section and determine THE most suitable format
2. Recommend ONLY ONE format per section (no cumulation)
3. Place formats at the most strategic locations
4. Use logic: beginning = Featured_answer, middle = specialized formats, end = FAQ
5. For placement, use: "introduction", "section_1", "section_2", "section_3", "conclusion"

**MANDATORY RESPONSE FORMAT (strict JSON):**
{{
  "optimizations": [
    {{
      "section_index": 0,
      "snippet_type": "Featured_answer",
      "placement": "introduction",
      "schema_type": "{query_context['schema_type']}",
      "rationale": "Brief explanation of choice"
    }}
  ]
}}

**CONSTRAINTS:**
- Maximum 3 optimizations per plan
- Prioritize quality over quantity
- Choose sections with highest SEO potential
- Response in valid JSON only, no additional text"""

    async def _call_llm_for_optimization(self, prompt: str, lang: str) -> Dict:
        """Effectue l'appel LLM pour optimisation des snippets"""
        
        system_content = {
            'fr': "Tu es un expert en optimisation SEO spécialisé dans les rich snippets Google. Tu réponds uniquement en JSON valide.",
            'en': "You are an SEO expert specialized in Google rich snippets. You respond only in valid JSON."
        }
        
        messages = [
            SystemMessage(content=system_content.get(lang, system_content['en'])),
            HumanMessage(content=prompt)
        ]
        
        logging.info(f"🔍 [ID {self.query_id}] Analyse des snippets en cours...")
        
        # Exécution asynchrone dans un thread pool
        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor(max_workers=1) as executor:
            response = await loop.run_in_executor(executor, self.llm.invoke, messages)
        
        # Parse de la réponse JSON
        try:
            response_content = response.content.strip()
            
            # Nettoyage du contenu si nécessaire
            if response_content.startswith('```json'):
                response_content = response_content.replace('```json', '').replace('```', '').strip()
            
            optimization_data = json.loads(response_content)
            return optimization_data
            
        except json.JSONDecodeError as e:
            logging.error(f"❌ [ID {self.query_id}] Erreur JSON snippets: {e}")
            raise Exception(f"Réponse LLM non valide pour snippets: {e}")
    
    def _apply_optimizations(self, original_plan: Dict, optimizations: Dict) -> Dict:
        """Applique les optimisations de snippets au plan original"""
        
        optimized_plan = json.loads(json.dumps(original_plan))  # Deep copy
        sections = optimized_plan.get('sections', [])
        
        # Initialiser toutes les sections avec des valeurs par défaut
        for section in sections:
            section['snippet_type'] = 'None'
            section['placement'] = 'none'
            section['schema_type'] = 'none'
        
        # Appliquer les optimisations
        optimizations_list = optimizations.get('optimizations', [])
        applied_count = 0
        
        for opt in optimizations_list:
            section_index = opt.get('section_index', -1)
            
            # Vérification de l'index
            if 0 <= section_index < len(sections):
                sections[section_index]['snippet_type'] = opt.get('snippet_type', 'None')
                sections[section_index]['placement'] = opt.get('placement', 'none')
                sections[section_index]['schema_type'] = opt.get('schema_type', 'none')
                applied_count += 1
                
                logging.info(f"📌 [ID {self.query_id}] Snippet {opt.get('snippet_type')} appliqué à section {section_index + 1}")
        
        # Ajout des métadonnées d'optimisation
        optimized_plan['seo_optimization'] = {
            'total_snippets': applied_count,
            'article_structure': original_plan.get('article_config', {}).get('structure_emphasis', 'standard'),
            'target_word_count': 0,  # Sera rempli par le processor principal
            'snippet_distribution': self._analyze_applied_snippets(sections)
        }
        
        logging.info(f"✅ [ID {self.query_id}] {applied_count} snippets optimisés appliqués")
        return optimized_plan
    
    def _apply_fallback_snippets(self, original_plan: Dict) -> Dict:
        """Applique des snippets par défaut en cas d'échec de l'optimisation"""
        
        fallback_plan = json.loads(json.dumps(original_plan))  # Deep copy
        sections = fallback_plan.get('sections', [])
        
        # Valeurs par défaut pour toutes les sections
        for section in sections:
            section['snippet_type'] = 'None'
            section['placement'] = 'none' 
            section['schema_type'] = 'none'
        
        # Ajout métadonnées fallback
        fallback_plan['seo_optimization'] = {
            'total_snippets': 0,
            'article_structure': 'fallback',
            'target_word_count': 0,
            'snippet_distribution': {
                'types_used': [],
                'total_count': 0,
                'distribution': {}
            }
        }
        
        logging.warning(f"⚠️ [ID {self.query_id}] Fallback snippets appliqué")
        return fallback_plan
    
    def _analyze_applied_snippets(self, sections: List[Dict]) -> Dict:
        """Analyse la distribution des snippets appliqués"""
        snippet_types = {}
        
        for section in sections:
            snippet_type = section.get('snippet_type', 'None')
            if snippet_type != 'None':
                snippet_types[snippet_type] = snippet_types.get(snippet_type, 0) + 1
        
        return {
            'types_used': list(snippet_types.keys()),
            'total_count': sum(snippet_types.values()),
            'distribution': snippet_types
        }

# === Générateurs de plans spécialisés (Multilingue) ===
class SpecializedPlanGenerator:
    """Générateur de plans spécialisés selon le type d'article (multilingue)"""
    
    def __init__(self, query_id: int, llm: ChatOpenAI):
        self.query_id = query_id
        self.llm = llm
        self.article_analyzer = ArticleTypeAnalyzer(query_id)
        self.language_detector = LanguageDetector()
    
    def get_template_prompt(self, article_type: str, query_data: Dict, selected_angle: str, highlight_url: str) -> str:
        """Génère le prompt spécialisé selon le type d'article et la langue"""
        
        # Détection de la langue
        lang = self.language_detector.detect_language(query_data.get('text', ''))
        strings = self.language_detector.get_localized_strings(lang)
        
        base_data = self._format_base_data(query_data, lang)
        
        templates = {
            'howto': self._get_howto_template(query_data, selected_angle, highlight_url, base_data, lang, strings),
            'comparative': self._get_comparative_template(query_data, selected_angle, highlight_url, base_data, lang, strings),
            'faq_page': self._get_faq_template(query_data, selected_angle, highlight_url, base_data, lang, strings),
            'listicle': self._get_listicle_template(query_data, selected_angle, highlight_url, base_data, lang, strings),
            'definitional': self._get_definitional_template(query_data, selected_angle, highlight_url, base_data, lang, strings),
            'general': self._get_general_template(query_data, selected_angle, highlight_url, base_data, lang, strings)
        }
        
        return templates.get(article_type, templates['general'])
    
    def _format_base_data(self, query_data: Dict, lang: str) -> Dict:
        """Formate les données de base pour les templates"""
        plan_info = query_data.get('plan', {})
        
        # Gestion des clés FR/EN
        if lang == 'fr':
            intro_key = 'introduction'
            dev_key = 'developpement'
            sections_key = 'nombre_sections'
            words_key = 'mots_par_section'
            conclusion_key = 'conclusion'
            length_key = 'longueur'
        else:
            intro_key = 'introduction'
            dev_key = 'development'
            sections_key = 'number_sections'
            words_key = 'words_per_section'
            conclusion_key = 'conclusion'
            length_key = 'length'
        
        intro_length = plan_info.get(intro_key, {}).get(length_key, 225)
        nb_sections = plan_info.get(dev_key, {}).get(sections_key, 2)
        mots_par_section = plan_info.get(dev_key, {}).get(words_key, 300.0)
        conclusion_length = plan_info.get(conclusion_key, {}).get(length_key, 225)
        
        logging.info(f"📊 [ID {self.query_id}] Plan détecté - Intro: {intro_length} mots, Sections: {nb_sections}, Mots/section: {mots_par_section}, Conclusion: {conclusion_length} mots")
        
        return {
            'intro_length': intro_length,
            'nb_sections': nb_sections,
            'mots_par_section': int(mots_par_section),
            'conclusion_length': conclusion_length,
            'word_count': query_data.get('word_count', 0),
            'keywords': ', '.join(query_data.get('top_keywords', '').split(',')[:20])
        }
    
    def _get_howto_template(self, query_data: Dict, selected_angle: str, highlight_url: str, base_data: Dict, lang: str, strings: Dict) -> str:
        if lang == 'fr':
            return f"""Crée un plan d'article GUIDE ÉTAPE PAR ÉTAPE optimisé SEO.

**TYPE D'ARTICLE :** Guide pratique (HowTo)
**ANGLE RETENU :** {selected_angle}

**STRUCTURE OBLIGATOIRE :**
- {strings['intro_label']} : {base_data['intro_length']} mots (intégrer naturellement : {highlight_url})
- {strings['prerequisites_label']} : 150 mots
- {base_data['nb_sections']} étapes principales : {base_data['mots_par_section']} {strings['words_each']}
- {strings['tips_label']} : 200 mots
- {strings['conclusion_label']} : {base_data['conclusion_length']} mots

**CONTRAINTE ABSOLUE :** {strings['absolute_constraint']} {base_data['nb_sections']} {strings['main_sections']} de développement.

**{strings['priority_keywords']} :** {base_data['keywords']}

**{strings['specific_requirements']} :**
1. Chaque étape doit être numérotée et actionnable
2. Intégrer des sous-étapes détaillées
3. Prévoir section FAQ pour les problèmes courants
4. Structurer en progression logique
5. Intégrer conseils pratiques entre les étapes"""
        else:
            return f"""Create an SEO-optimized STEP-BY-STEP GUIDE article plan.

**ARTICLE TYPE:** Practical Guide (HowTo)
**SELECTED ANGLE:** {selected_angle}

**MANDATORY STRUCTURE:**
- {strings['intro_label']}: {base_data['intro_length']} words (naturally integrate: {highlight_url})
- {strings['prerequisites_label']}: 150 words
- {base_data['nb_sections']} main steps: {base_data['mots_par_section']} {strings['words_each']}
- {strings['tips_label']}: 200 words
- {strings['conclusion_label']}: {base_data['conclusion_length']} words

**{strings['absolute_constraint']} {base_data['nb_sections']} {strings['main_sections']}.

**{strings['priority_keywords']}:** {base_data['keywords']}

**{strings['specific_requirements']}:**
1. Each step must be numbered and actionable
2. Include detailed sub-steps
3. Include FAQ section for common issues
4. Structure in logical progression
5. Integrate practical tips between steps"""
    
    def _get_comparative_template(self, query_data: Dict, selected_angle: str, highlight_url: str, base_data: Dict, lang: str, strings: Dict) -> str:
        if lang == 'fr':
            return f"""Crée un plan d'article COMPARATEUR optimisé SEO.

**TYPE D'ARTICLE :** Comparateur/Analyse comparative
**ANGLE RETENU :** {selected_angle}

**STRUCTURE OBLIGATOIRE :**
- {strings['intro_label']} : {base_data['intro_length']} mots (intégrer naturellement : {highlight_url})
- {base_data['nb_sections']} {strings['main_sections']} : {base_data['mots_par_section']} {strings['words_each']}
- {strings['conclusion_label']} : {base_data['conclusion_length']} mots

**{strings['absolute_constraint']} {base_data['nb_sections']} {strings['main_sections']}.

**{strings['priority_keywords']} :** {base_data['keywords']}

**{strings['specific_requirements']} :**
1. Structurer en opposition claire entre options
2. Intégrer tableau comparatif avec critères précis
3. Section dédiée aux cas d'usage
4. Recommandation basée sur profils utilisateurs"""
        else:
            return f"""Create an SEO-optimized COMPARISON article plan.

**ARTICLE TYPE:** Comparator/Comparative Analysis
**SELECTED ANGLE:** {selected_angle}

**MANDATORY STRUCTURE:**
- {strings['intro_label']}: {base_data['intro_length']} words (naturally integrate: {highlight_url})
- {base_data['nb_sections']} {strings['main_sections']}: {base_data['mots_par_section']} {strings['words_each']}
- {strings['conclusion_label']}: {base_data['conclusion_length']} words

**{strings['absolute_constraint']} {base_data['nb_sections']} {strings['main_sections']}.

**{strings['priority_keywords']}:** {base_data['keywords']}

**{strings['specific_requirements']}:**
1. Structure with clear opposition between options
2. Include comparison table with precise criteria
3. Dedicated section for use cases
4. Recommendation based on user profiles"""
    
    def _get_faq_template(self, query_data: Dict, selected_angle: str, highlight_url: str, base_data: Dict, lang: str, strings: Dict) -> str:
        if lang == 'fr':
            return f"""Crée un plan d'article FAQ PAGE optimisé SEO.

**TYPE D'ARTICLE :** Page FAQ / Questions-Réponses
**ANGLE RETENU :** {selected_angle}

**STRUCTURE OBLIGATOIRE :**
- {strings['intro_label']} : {base_data['intro_length']} mots (intégrer naturellement : {highlight_url})
- Questions principales ({base_data['nb_sections']} sections) : {base_data['mots_par_section']} {strings['words_each']}
- Questions secondaires : 400 mots
- {strings['summary_label']} : {base_data['conclusion_length']} mots

**{strings['priority_keywords']} :** {base_data['keywords']}

**{strings['specific_requirements']} :**
1. Questions formulées comme recherches Google
2. Réponses directes et concises
3. Groupement thématique des questions"""
        else:
            return f"""Create an SEO-optimized FAQ PAGE article plan.

**ARTICLE TYPE:** FAQ Page / Questions & Answers
**SELECTED ANGLE:** {selected_angle}

**MANDATORY STRUCTURE:**
- {strings['intro_label']}: {base_data['intro_length']} words (naturally integrate: {highlight_url})
- Main questions ({base_data['nb_sections']} sections): {base_data['mots_par_section']} {strings['words_each']}
- Secondary questions: 400 words
- {strings['summary_label']}: {base_data['conclusion_length']} words

**{strings['priority_keywords']}:** {base_data['keywords']}

**{strings['specific_requirements']}:**
1. Questions formulated as Google searches
2. Direct and concise answers
3. Thematic grouping of questions"""
    
    def _get_listicle_template(self, query_data: Dict, selected_angle: str, highlight_url: str, base_data: Dict, lang: str, strings: Dict) -> str:
        if lang == 'fr':
            return f"""Crée un plan d'article LISTE/CLASSEMENT optimisé SEO.

**TYPE D'ARTICLE :** Listicle/Top/Classement
**ANGLE RETENU :** {selected_angle}

**STRUCTURE OBLIGATOIRE :**
- {strings['intro_label']} : {base_data['intro_length']} mots (intégrer naturellement : {highlight_url})
- {base_data['nb_sections']} items principaux : {base_data['mots_par_section']} {strings['words_each']}
- {strings['criteria_label']} : 250 mots
- {strings['recap_label']} : {base_data['conclusion_length']} mots

**{strings['priority_keywords']} :** {base_data['keywords']}

**{strings['specific_requirements']} :**
1. Items numérotés par ordre d'importance
2. Justification pour chaque choix
3. Critères de sélection transparents"""
        else:
            return f"""Create an SEO-optimized LIST/RANKING article plan.

**ARTICLE TYPE:** Listicle/Top/Ranking
**SELECTED ANGLE:** {selected_angle}

**MANDATORY STRUCTURE:**
- {strings['intro_label']}: {base_data['intro_length']} words (naturally integrate: {highlight_url})
- {base_data['nb_sections']} main items: {base_data['mots_par_section']} {strings['words_each']}
- {strings['criteria_label']}: 250 words
- {strings['recap_label']}: {base_data['conclusion_length']} words

**{strings['priority_keywords']}:** {base_data['keywords']}

**{strings['specific_requirements']}:**
1. Items numbered by order of importance
2. Justification for each choice
3. Transparent selection criteria"""
    
    def _get_definitional_template(self, query_data: Dict, selected_angle: str, highlight_url: str, base_data: Dict, lang: str, strings: Dict) -> str:
        if lang == 'fr':
            return f"""Crée un plan d'article DÉFINITION COMPLÈTE optimisé SEO.

**TYPE D'ARTICLE :** Guide définitionnel/Explication concept
**ANGLE RETENU :** {selected_angle}

**STRUCTURE OBLIGATOIRE :**
- Introduction et définition : {base_data['intro_length']} mots (intégrer naturellement : {highlight_url})
- {base_data['nb_sections']} {strings['main_sections']} : {base_data['mots_par_section']} {strings['words_each']}
- {strings['conclusion_label']} : {base_data['conclusion_length']} mots

**{strings['priority_keywords']} :** {base_data['keywords']}

**{strings['specific_requirements']} :**
1. Définition claire et concise en introduction
2. Progression du simple au complexe
3. Exemples pratiques et concrets"""
        else:
            return f"""Create an SEO-optimized COMPLETE DEFINITION article plan.

**ARTICLE TYPE:** Definitional Guide/Concept Explanation
**SELECTED ANGLE:** {selected_angle}

**MANDATORY STRUCTURE:**
- Introduction and definition: {base_data['intro_length']} words (naturally integrate: {highlight_url})
- {base_data['nb_sections']} {strings['main_sections']}: {base_data['mots_par_section']} {strings['words_each']}
- {strings['conclusion_label']}: {base_data['conclusion_length']} words

**{strings['priority_keywords']}:** {base_data['keywords']}

**{strings['specific_requirements']}:**
1. Clear and concise definition in introduction
2. Progression from simple to complex
3. Practical and concrete examples"""
    
    def _get_general_template(self, query_data: Dict, selected_angle: str, highlight_url: str, base_data: Dict, lang: str, strings: Dict) -> str:
        if lang == 'fr':
            return f"""Crée un plan d'article GUIDE COMPLET optimisé SEO.

**TYPE D'ARTICLE :** Guide général/Article complet
**ANGLE RETENU :** {selected_angle}

**STRUCTURE STANDARD :**
- {strings['intro_label']} : {base_data['intro_length']} mots (intégrer naturellement : {highlight_url})
- {base_data['nb_sections']} {strings['main_sections']} : {base_data['mots_par_section']} {strings['words_each']}
- {strings['conclusion_label']} : {base_data['conclusion_length']} mots

**{strings['priority_keywords']} :** {base_data['keywords']}

**EXIGENCES GÉNÉRALES :**
1. Coverage complète du sujet
2. Progression logique
3. Sous-sections détaillées"""
        else:
            return f"""Create an SEO-optimized COMPLETE GUIDE article plan.

**ARTICLE TYPE:** General Guide/Complete Article
**SELECTED ANGLE:** {selected_angle}

**STANDARD STRUCTURE:**
- {strings['intro_label']}: {base_data['intro_length']} words (naturally integrate: {highlight_url})
- {base_data['nb_sections']} {strings['main_sections']}: {base_data['mots_par_section']} {strings['words_each']}
- {strings['conclusion_label']}: {base_data['conclusion_length']} words

**{strings['priority_keywords']}:** {base_data['keywords']}

**GENERAL REQUIREMENTS:**
1. Complete topic coverage
2. Logical progression
3. Detailed subsections"""

# === Classe de traitement asynchrone d'une requête (Multilingue) ===
class AsyncQueryProcessor:
    def __init__(self, query_id: int):
        self.query_id = query_id
        self.llm = ChatOpenAI(
            model="gpt-4o",
            temperature=0.7,
            api_key=api_key,
            callbacks=[AsyncLoggingCallback(query_id)]
        )
        self.plan_generator = SpecializedPlanGenerator(query_id, self.llm)
        self.article_analyzer = ArticleTypeAnalyzer(query_id)
        self.snippet_optimizer = SnippetOptimizationAgent(query_id, self.llm)
        self.language_detector = LanguageDetector()
    
    async def select_best_angle(self, query_data: Dict) -> str:
        """Étape 1: Sélection du meilleur angle différenciant (multilingue)"""
        
        # Détection de la langue
        lang = self.language_detector.detect_language(query_data.get('text', ''))
        
        angles_list = "\n".join([f"{i+1}. {angle}" for i, angle in enumerate(query_data.get('differentiating_angles', []))])
        semantic_analysis = query_data.get('semantic_analysis', {})
        
        if lang == 'fr':
            prompt_selection = f"""Tu es un expert en stratégie de contenu SEO. À partir de cette analyse sémantique SERP, choisis l'angle différenciant le PLUS PERTINENT pour créer un article unique qui se démarquera de la concurrence.

**REQUÊTE CIBLE (OBLIGATOIRE) :** "{query_data.get('text', 'Sujet non défini')}"
⚠️ IMPORTANT : Tu DOIS absolument choisir l'angle qui correspond le mieux à cette requête exacte.

**ANGLES DIFFÉRENCIANTS DISPONIBLES :**
{angles_list}

**CONTEXTE CONCURRENTIEL :**
- Nombre de mots cible : {query_data.get('word_count', 0)}
- Clusters thématiques identifiés : {semantic_analysis.get('clusters_count', 0)}
- Entités identifiées : {semantic_analysis.get('entities', 0)}
- Relations trouvées : {semantic_analysis.get('relations_found', 0)}

**DEMANDE :**
Choisis UN SEUL angle qui répond DIRECTEMENT à la requête "{query_data.get('text', 'Sujet non défini')}" et justifie ton choix.
Format : "ANGLE CHOISI: [titre] - JUSTIFICATION: [explication en lien direct avec la requête cible]"
"""
            system_content = "Tu es un expert en stratégie de contenu SEO spécialisé dans la sélection d'angles différenciants."
        else:
            prompt_selection = f"""You are an SEO content strategy expert. From this SERP semantic analysis, choose the MOST RELEVANT differentiating angle to create a unique article that will stand out from the competition.

**TARGET QUERY (MANDATORY):** "{query_data.get('text', 'Undefined topic')}"
⚠️ IMPORTANT: You MUST choose the angle that best matches this exact query.

**AVAILABLE DIFFERENTIATING ANGLES:**
{angles_list}

**COMPETITIVE CONTEXT:**
- Target word count: {query_data.get('word_count', 0)}
- Identified thematic clusters: {semantic_analysis.get('clusters_count', 0)}
- Identified entities: {semantic_analysis.get('entities', 0)}
- Found relations: {semantic_analysis.get('relations_found', 0)}

**REQUEST:**
Choose ONE angle that DIRECTLY answers the query "{query_data.get('text', 'Undefined topic')}" and justify your choice.
Format: "CHOSEN ANGLE: [title] - JUSTIFICATION: [explanation directly linked to the target query]"
"""
            system_content = "You are an SEO content strategy expert specialized in selecting differentiating angles."
        
        messages = [
            SystemMessage(content=system_content),
            HumanMessage(content=prompt_selection)
        ]
        
        logging.info(f"🎯 [ID {self.query_id}] Sélection de l'angle différenciant...")
        
        # Exécution asynchrone dans un thread pool
        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor(max_workers=1) as executor:
            response = await loop.run_in_executor(executor, self.llm.invoke, messages)
        
        selected_angle = response.content.strip()
        logging.info(f"✅ [ID {self.query_id}] Angle sélectionné: {selected_angle[:100]}...")
        return selected_angle
    
    async def determine_schema_type(self, query_data: Dict, article_intent: str, selected_angle: str) -> str:
        """Étape 2: Détermination du schema principal via LLM (multilingue)"""
        
        # Détection de la langue
        lang = self.language_detector.detect_language(query_data.get('text', ''))
        
        if lang == 'fr':
            prompt_schema = f"""Tu es un expert en Schema.org et optimisation SEO. Détermine le schema principal le plus approprié pour cet article.

**REQUÊTE CIBLE :** "{query_data.get('text', 'Sujet non défini')}"
**TYPE D'ARTICLE :** {article_intent}
**ANGLE SÉLECTIONNÉ :** {selected_angle}

**SCHEMAS DISPONIBLES :**
- HowTo : Pour guides étape par étape, tutoriels
- FAQPage : Pour pages questions-réponses
- Recipe : Pour recettes, instructions de cuisine
- Product : Pour présentation de produits
- Article : Pour articles génériques, actualités
- Organization : Pour présenter entreprises, services
- Person : Pour biographies, profils
- Event : Pour événements, formations
- Course : Pour formations, cours en ligne
- VideoObject : Pour contenu vidéo principal
- ImageObject : Pour contenu principalement visuel

**INSTRUCTIONS :**
1. Analyse l'intention de la requête
2. Considère le type d'article détecté
3. Choisis LE schema le plus pertinent
4. Justifie brièvement ton choix

**FORMAT DE RÉPONSE :**
Schema recommandé: [NOM_DU_SCHEMA]
Justification: [explication courte]
"""
            system_content = "Tu es un expert en Schema.org spécialisé dans l'optimisation SEO."
        else:
            prompt_schema = f"""You are a Schema.org and SEO optimization expert. Determine the most appropriate main schema for this article.

**TARGET QUERY:** "{query_data.get('text', 'Undefined topic')}"
**ARTICLE TYPE:** {article_intent}
**SELECTED ANGLE:** {selected_angle}

**AVAILABLE SCHEMAS:**
- HowTo: For step-by-step guides, tutorials
- FAQPage: For question-answer pages
- Recipe: For recipes, cooking instructions
- Product: For product presentations
- Article: For generic articles, news
- Organization: For presenting companies, services
- Person: For biographies, profiles
- Event: For events, training
- Course: For training, online courses
- VideoObject: For main video content
- ImageObject: For mainly visual content

**INSTRUCTIONS:**
1. Analyze the query intent
2. Consider the detected article type
3. Choose THE most relevant schema
4. Briefly justify your choice

**RESPONSE FORMAT:**
Recommended schema: [SCHEMA_NAME]
Justification: [brief explanation]
"""
            system_content = "You are a Schema.org expert specialized in SEO optimization."
        
        messages = [
            SystemMessage(content=system_content),
            HumanMessage(content=prompt_schema)
        ]
        
        logging.info(f"🏷️ [ID {self.query_id}] Détermination du schema principal...")
        
        # Exécution asynchrone dans un thread pool
        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor(max_workers=1) as executor:
            response = await loop.run_in_executor(executor, self.llm.invoke, messages)
        
        # Extraction du schema depuis la réponse
        response_content = response.content.strip()
        schema_type = self._extract_schema_from_response(response_content)
        
        logging.info(f"✅ [ID {self.query_id}] Schema déterminé: {schema_type}")
        return schema_type
    
    def _extract_schema_from_response(self, response: str) -> str:
        """Extrait le nom du schema depuis la réponse du LLM"""
        # Recherche du pattern "Schema recommandé: [SCHEMA]" ou "Recommended schema: [SCHEMA]"
        import re
        
        schema_match = re.search(r'(?:Schema recommandé|Recommended schema):\s*([A-Za-z]+)', response)
        if schema_match:
            return schema_match.group(1)
        
        # Fallback: recherche de schemas connus dans le texte
        known_schemas = ['HowTo', 'FAQPage', 'Recipe', 'Product', 'Article', 'Organization', 'Person', 'Event', 'Course']
        for schema in known_schemas:
            if schema.lower() in response.lower():
                return schema
        
        # Fallback final
        return 'Article'
    
    async def generate_article_plan(self, query_data: Dict, selected_angle: str, consigne_data: Dict, schema_type: str) -> Dict:
        """Étape 3: Génération du plan d'article (multilingue)"""
        
        # 1. Analyse du type d'article optimal
        query_text = query_data.get('text', '')
        article_intent = self.article_analyzer.analyze_query_intent(query_text)
        article_config = self.article_analyzer.get_article_type_config(article_intent)
        
        # Détection de la langue
        lang = self.language_detector.detect_language(query_text)
        
        logging.info(f"🎯 [ID {self.query_id}] Type d'article détecté: {article_intent}")
        logging.info(f"📋 [ID {self.query_id}] Template: {article_config['template']}")
        logging.info(f"🌐 [ID {self.query_id}] Langue: {lang.upper()}")
        
        # 2. Récupération du highlight depuis consigne_data
        highlight_url = consigne_data.get('highlight', '')
        
        # 3. Génération du prompt spécialisé (multilingue)
        specialized_prompt = self.plan_generator.get_template_prompt(
            article_intent, query_data, selected_angle, highlight_url
        )
        
        # 4. Format de sortie selon la langue
        if lang == 'fr':
            integration_text = "Description de l'intégration naturelle du lien"
            anchor_text = "Texte d'ancrage suggéré pour le lien"
            language_instruction = "Langue de réponse: Français"
        else:
            integration_text = "Description of how to naturally integrate the link"
            anchor_text = "Suggested anchor text for the link"
            language_instruction = "Response language: English"
        
        system_message_content = f"""Your objective: Create a specialized {article_intent.upper()} article outline.

Expected output format:
{{
  "SEO Title": "",
  "article_type": "{article_intent}",
  "schema_type": "{schema_type}",
  "introduction_notes": {{
    "highlight_integration": "{integration_text}",
    "suggested_anchor_text": "{anchor_text}"
  }},
  "sections": [
    {{
      "section_title": "",
      "subsections": [
        {{ "subsection_title": "" }},
        {{ "subsection_title": "" }}
      ]
    }}
  ],
  "conclusion": "",
  "article_config": {{
    "template": "{article_config['template']}",
    "structure_emphasis": "{article_config['structure_emphasis']}"
  }}
}}

Article Type Guidelines:
- {article_intent}: {article_config['structure_emphasis']}
- Required sections: {', '.join(article_config['required_sections'])}

Restrictions:
• Propose only titles and subtitles
• No snippet-related properties
• No additional textual content
{language_instruction}"""

        messages = [
            SystemMessage(content=system_message_content),
            HumanMessage(content=specialized_prompt)
        ]
        
        logging.info(f"🏗️ [ID {self.query_id}] Génération du plan {article_intent}...")
        
        # Exécution asynchrone dans un thread pool
        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor(max_workers=1) as executor:
            response = await loop.run_in_executor(executor, self.llm.invoke, messages)
        
        try:
            # Tentative de parsing du JSON
            plan_content = response.content.strip()
            
            # Nettoyage du contenu si nécessaire
            if plan_content.startswith('```json'):
                plan_content = plan_content.replace('```json', '').replace('```', '').strip()
            
            plan_json = json.loads(plan_content)
            
            # Validation du plan
            validated_plan = self._validate_plan(plan_json, article_config, query_data, schema_type)
            
            logging.info(f"✅ [ID {self.query_id}] Plan {article_intent} généré")
            return validated_plan
            
        except json.JSONDecodeError as e:
            logging.error(f"❌ [ID {self.query_id}] Erreur de parsing JSON: {e}")
            logging.error(f"Contenu reçu: {response.content}")
            
            # Fallback: structure basique
            fallback_plan = self._create_fallback_plan(query_data, article_intent, article_config, highlight_url, schema_type)
            return fallback_plan
    
    def _validate_plan(self, plan_json: Dict, article_config: Dict, query_data: Dict, schema_type: str) -> Dict:
        """Valide le plan généré (sans snippets)"""
        validated_plan = plan_json.copy()
        
        # S'assurer que les champs obligatoires sont présents
        if 'article_type' not in validated_plan:
            validated_plan['article_type'] = article_config.get('template', 'general')
        
        if 'schema_type' not in validated_plan:
            validated_plan['schema_type'] = schema_type
        
        return validated_plan
    
    def _create_fallback_plan(self, query_data: Dict, article_intent: str, article_config: Dict, highlight_url: str, schema_type: str) -> Dict:
        """Crée un plan de fallback en cas d'erreur (multilingue)"""
        # Détection de la langue
        lang = self.language_detector.detect_language(query_data.get('text', ''))
        
        if lang == 'fr':
            return {
                "SEO Title": f"Guide {query_data.get('text', 'sujet')} - Plan généré automatiquement",
                "article_type": article_intent,
                "schema_type": schema_type,
                "introduction_notes": {
                    "highlight_integration": f"Intégrer naturellement le lien {highlight_url} dans le contexte",
                    "suggested_anchor_text": "découvrez notre guide"
                },
                "sections": [
                    {
                        "section_title": "Section principale 1",
                        "subsections": [
                            {"subsection_title": "Sous-section 1.1"},
                            {"subsection_title": "Sous-section 1.2"}
                        ]
                    },
                    {
                        "section_title": "Section principale 2",
                        "subsections": [
                            {"subsection_title": "Sous-section 2.1"}
                        ]
                    }
                ],
                "conclusion": "Conclusion optimisée SEO",
                "article_config": {
                    "template": article_config['template'],
                    "structure_emphasis": article_config['structure_emphasis']
                }
            }
        else:
            return {
                "SEO Title": f"{query_data.get('text', 'topic')} Guide - Automatically Generated Plan",
                "article_type": article_intent,
                "schema_type": schema_type,
                "introduction_notes": {
                    "highlight_integration": f"Naturally integrate the link {highlight_url} in context",
                    "suggested_anchor_text": "discover our guide"
                },
                "sections": [
                    {
                        "section_title": "Main Section 1",
                        "subsections": [
                            {"subsection_title": "Subsection 1.1"},
                            {"subsection_title": "Subsection 1.2"}
                        ]
                    },
                    {
                        "section_title": "Main Section 2",
                        "subsections": [
                            {"subsection_title": "Subsection 2.1"}
                        ]
                    }
                ],
                "conclusion": "SEO-optimized conclusion",
                "article_config": {
                    "template": article_config['template'],
                    "structure_emphasis": article_config['structure_emphasis']
                }
            }
    
    async def process_query(self, query_data: Dict, consigne_data: Dict) -> Dict:
        """Traite une requête complète avec nouveau workflow"""
        try:
            logging.info(f"🚀 [ID {self.query_id}] Début du traitement: '{query_data.get('text')}'")
            
            # Vérifier si la requête a les données nécessaires
            if not all([query_data.get('differentiating_angles'), 
                       query_data.get('semantic_analysis')]):
                logging.error(f"❌ [ID {self.query_id}] Données sémantiques incomplètes")
                return {'status': 'failed', 'error': f'Données sémantiques incomplètes pour ID {self.query_id}'}
            
            # NOUVEAU WORKFLOW:
            
            # Étape 1: Sélection d'angle
            selected_angle = await self.select_best_angle(query_data)
            
            # Étape 2: Détermination du schema principal
            query_text = query_data.get('text', '')
            article_intent = self.article_analyzer.analyze_query_intent(query_text)
            schema_type = await self.determine_schema_type(query_data, article_intent, selected_angle)
            
            # Étape 3: Génération du plan de base
            article_plan = await self.generate_article_plan(
                query_data, 
                selected_angle,
                consigne_data,
                schema_type
            )
            
            # Étape 4: Optimisation des snippets
            optimized_plan = await self.snippet_optimizer.optimize_snippets(
                article_plan,
                query_data,
                article_intent,
                schema_type
            )
            
            # Finalisation avec métadonnées
            optimized_plan['seo_optimization']['target_word_count'] = query_data.get('word_count', 0)
            
            logging.info(f"🎉 [ID {self.query_id}] Traitement terminé avec succès")
            
            return {
                'query_id': self.query_id,
                'selected_angle': selected_angle,
                'article_plan': optimized_plan,
                'status': 'success'
            }
            
        except Exception as e:
            logging.error(f"💥 [ID {self.query_id}] Erreur lors du traitement: {e}")
            return {
                'query_id': self.query_id,
                'error': str(e),
                'status': 'failed'
            }

# === Gestionnaire de traitement en lot parallélisé (Inchangé) ===
class ParallelConsignePlanGenerator:
    def __init__(self):
        self.semaphore = asyncio.Semaphore(MAX_CONCURRENT_LLM)
        self.lock = threading.Lock()
    
    def clean_semantic_data(self, query: Dict) -> Dict:
        """Supprime toutes les clés sémantiques d'une requête après génération du plan"""
        cleaned_query = query.copy()
        
        # Supprimer la clé principale semantic_analysis
        if 'semantic_analysis' in cleaned_query:
            del cleaned_query['semantic_analysis']
        
        # Supprimer detailed_clusters
        if 'detailed_clusters' in cleaned_query:
            del cleaned_query['detailed_clusters']
        
        # Supprimer semantic_relations
        if 'semantic_relations' in cleaned_query:
            del cleaned_query['semantic_relations']
        
        # Supprimer strategic_entities
        if 'strategic_entities' in cleaned_query:
            del cleaned_query['strategic_entities']
        
        # Supprimer differentiating_angles après génération du plan
        if 'differentiating_angles' in cleaned_query:
            del cleaned_query['differentiating_angles']
        
        # Supprimer seo_optimization qui est maintenant dans generated_article_plan
        if 'seo_optimization' in cleaned_query:
            del cleaned_query['seo_optimization']
        
        logging.info(f"✅ [ID {query.get('id')}] Données sémantiques et temporaires supprimées après génération du plan")
        return cleaned_query
        
    async def load_consigne_data(self) -> Dict:
        """Charge les données du fichier consigne.json de manière asynchrone"""
        try:
            # Vérification que le fichier a été trouvé au démarrage
            if CONSIGNE_FILE is None:
                raise FileNotFoundError("Aucun fichier de consigne trouvé dans le dossier static/")
            
            # Vérification du fichier avant chargement
            if not os.path.exists(CONSIGNE_FILE):
                logging.error(f"❌ Fichier non trouvé: {CONSIGNE_FILE}")
                logging.error(f"❌ Chemin absolu: {os.path.abspath(CONSIGNE_FILE)}")
                raise FileNotFoundError(f"Fichier {CONSIGNE_FILE} non trouvé")
            
            # Chargement synchrone pour plus de sûreté
            with open(CONSIGNE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            logging.info(f"✅ Données chargées depuis {os.path.basename(CONSIGNE_FILE)}")
            logging.info(f"📊 Nombre de requêtes trouvées: {len(data.get('queries', []))}")
            return data
        except FileNotFoundError:
            logging.error(f"❌ Fichier {CONSIGNE_FILE} non trouvé")
            raise
        except json.JSONDecodeError as e:
            logging.error(f"❌ Erreur de décodage JSON: {e}")
            raise
    
    def get_query_by_id(self, consigne_data: Dict, query_id: int) -> Optional[Dict]:
        """Récupère une requête spécifique par son ID"""
        queries = consigne_data.get('queries', [])
        for query in queries:
            if query.get('id') == query_id:
                return query
        return None
    
    def get_processable_queries(self, consigne_data: Dict) -> List[Dict]:
        """Retourne la liste des requêtes qui ont des données sémantiques complètes mais pas encore de plan"""
        processable = []
        for query in consigne_data.get('queries', []):
            # Vérifier si la requête a les données nécessaires pour la génération de plan
            if (query.get('differentiating_angles') and 
                query.get('semantic_analysis')):
                
                # Ignorer les requêtes qui ont déjà un plan généré
                if query.get('generated_article_plan'):
                    logging.info(f"🔄 [ID {query.get('id')}] Plan déjà généré - ignoré")
                    continue
                    
                processable.append(query)
        return processable
    
    async def save_updated_consigne(self, consigne_data: Dict, results: List[Dict]) -> None:
        """
        Sauvegarde thread-safe avec lock et shutil.move() pour éviter les conflits
        """
        def _atomic_save():
            """Fonction synchrone pour la sauvegarde atomique"""
            try:
                with self.lock:  # Utilisation du lock de l'instance
                    # Vérification que le fichier a été trouvé au démarrage
                    if CONSIGNE_FILE is None:
                        raise FileNotFoundError("Aucun fichier de consigne trouvé dans le dossier static/")
                    
                    logging.info(f"🔒 Lock acquis pour sauvegarde de {os.path.basename(CONSIGNE_FILE)}")
                    
                    # 1. Rechargement des données actuelles depuis le disque
                    logging.info(f"📥 Rechargement des données depuis {os.path.basename(CONSIGNE_FILE)}")
                    
                    if not os.path.exists(CONSIGNE_FILE):
                        raise FileNotFoundError(f"Le fichier {CONSIGNE_FILE} n'existe pas")
                    
                    with open(CONSIGNE_FILE, 'r', encoding='utf-8') as f:
                        current_data = json.load(f)
                    
                    original_size = os.path.getsize(CONSIGNE_FILE)
                    logging.info(f"📊 Fichier original - Taille: {original_size} bytes")
                    
                    # 2. Mise à jour des requêtes avec les résultats
                    results_by_id = {r['query_id']: r for r in results if r.get('status') == 'success'}
                    updated_count = 0
                    
                    for i, query in enumerate(current_data.get('queries', [])):
                        query_id = query.get('id')
                        if query_id in results_by_id:
                            result = results_by_id[query_id]
                            
                            # Mise à jour avec validation des données
                            if result.get('selected_angle') and result.get('article_plan'):
                                query['selected_differentiating_angle'] = result['selected_angle']
                                query['generated_article_plan'] = result['article_plan']
                                query['plan_generation_status'] = 'completed'
                                query['last_updated'] = result.get('timestamp', 'unknown')
                                
                                # Extraction des métriques du plan spécialisé
                                plan = result['article_plan']
                                query['article_type'] = plan.get('article_type', 'general')
                                query['seo_optimization'] = plan.get('seo_optimization', {})
                                
                                # SUPPRESSION DES DONNÉES SÉMANTIQUES APRÈS GÉNÉRATION DU PLAN
                                current_data['queries'][i] = self.clean_semantic_data(query)
                                
                                updated_count += 1
                                logging.info(f"✅ [ID {query_id}] Plan {plan.get('article_type', 'general')} ajouté avec snippets optimisés")
                            else:
                                logging.warning(f"⚠️ [ID {query_id}] Données incomplètes, ignoré")
                    
                    if updated_count == 0:
                        logging.warning("⚠️ Aucune donnée valide à sauvegarder")
                        return False
                    
                    # 3. Création du fichier temporaire avec nom unique
                    import time
                    temp_suffix = f".tmp_{int(time.time())}_{os.getpid()}"
                    temp_file = CONSIGNE_FILE + temp_suffix
                    
                    logging.info(f"📝 Écriture vers fichier temporaire: {temp_file}")
                    
                    # 4. Écriture dans le fichier temporaire
                    with open(temp_file, 'w', encoding='utf-8') as f:
                        json.dump(current_data, f, indent=4, ensure_ascii=False)
                    
                    # 5. Vérification du fichier temporaire
                    if not os.path.exists(temp_file):
                        raise Exception("Échec de création du fichier temporaire")
                    
                    temp_size = os.path.getsize(temp_file)
                    logging.info(f"✅ Fichier temporaire créé - Taille: {temp_size} bytes")
                    
                    # Vérification de cohérence (le fichier ne doit pas être vide)
                    if temp_size < 50:  # JSON minimum attendu
                        raise Exception(f"Fichier temporaire suspect (trop petit: {temp_size} bytes)")
                    
                    # 6. Sauvegarde de l'original (backup de sécurité)
                    backup_file = CONSIGNE_FILE + '.backup'
                    if os.path.exists(CONSIGNE_FILE):
                        shutil.copy2(CONSIGNE_FILE, backup_file)
                        logging.info(f"💾 Backup créé: {backup_file}")
                    
                    # 7. Remplacement atomique avec shutil.move()
                    try:
                        shutil.move(temp_file, CONSIGNE_FILE)
                        logging.info(f"🔄 Remplacement atomique réussi avec shutil.move()")
                    except Exception as move_error:
                        logging.error(f"❌ Erreur lors du move: {move_error}")
                        
                        # Fallback: copie + suppression
                        logging.info("🔄 Tentative de fallback avec copy + remove")
                        shutil.copy2(temp_file, CONSIGNE_FILE)
                        os.remove(temp_file)
                        logging.info("✅ Fallback réussi")
                    
                    # 8. Vérification finale
                    if not os.path.exists(CONSIGNE_FILE):
                        raise Exception("Le fichier final n'existe pas après sauvegarde")
                    
                    final_size = os.path.getsize(CONSIGNE_FILE)
                    logging.info(f"📊 Fichier final - Taille: {final_size} bytes")
                    
                    # 9. Validation JSON du fichier final
                    try:
                        with open(CONSIGNE_FILE, 'r', encoding='utf-8') as f:
                            json.load(f)
                        logging.info("✅ Validation JSON du fichier final réussie")
                    except json.JSONDecodeError as json_error:
                        # Restauration du backup en cas de corruption
                        if os.path.exists(backup_file):
                            shutil.copy2(backup_file, CONSIGNE_FILE)
                            logging.error(f"❌ JSON corrompu, backup restauré: {json_error}")
                            raise Exception("Fichier JSON corrompu après sauvegarde")
                        else:
                            raise Exception(f"JSON corrompu et pas de backup: {json_error}")
                    
                    # 10. Nettoyage des fichiers temporaires
                    for cleanup_file in [backup_file, temp_file]:
                        if os.path.exists(cleanup_file):
                            try:
                                os.remove(cleanup_file)
                                logging.info(f"🧹 Nettoyé: {cleanup_file}")
                            except:
                                logging.warning(f"⚠️ Impossible de nettoyer: {cleanup_file}")
                    
                    logging.info(f"✅ Sauvegarde atomique terminée avec succès")
                    logging.info(f"📈 {updated_count} requêtes mises à jour avec snippets optimisés")
                    logging.info(f"📊 Taille: {original_size} → {final_size} bytes")
                    
                    return True
                    
            except Exception as e:
                # Nettoyage d'urgence en cas d'erreur
                cleanup_files = [
                    CONSIGNE_FILE + temp_suffix if 'temp_suffix' in locals() else None,
                    CONSIGNE_FILE + '.backup'
                ]
                
                for cleanup_file in cleanup_files:
                    if cleanup_file and os.path.exists(cleanup_file):
                        try:
                            os.remove(cleanup_file)
                            logging.info(f"🧹 Nettoyage d'urgence: {cleanup_file}")
                        except:
                            pass
                
                logging.error(f"❌ Erreur dans la sauvegarde atomique: {e}")
                logging.error(f"📁 Chemin: {CONSIGNE_FILE}")
                logging.error(f"📁 Dossier parent existe: {os.path.exists(os.path.dirname(CONSIGNE_FILE))}")
                logging.error(f"📁 Fichier original existe: {os.path.exists(CONSIGNE_FILE)}")
                raise
        
        # Exécution de la sauvegarde dans un thread pour éviter de bloquer l'event loop
        try:
            loop = asyncio.get_event_loop()
            success = await loop.run_in_executor(None, _atomic_save)
            
            if success:
                logging.info("🎉 Sauvegarde thread-safe complétée avec succès")
            else:
                raise Exception("La sauvegarde a échoué")
                
        except Exception as e:
            logging.error(f"❌ Erreur lors de la sauvegarde thread-safe: {e}")
            raise
    
    async def process_query_with_semaphore(self, query_data: Dict, consigne_data: Dict) -> Dict:
        """Traite une requête avec limitation de concurrence"""
        async with self.semaphore:  # Limite la concurrence des appels LLM
            processor = AsyncQueryProcessor(query_data.get('id'))
            return await processor.process_query(query_data, consigne_data)
    
    async def process_single_query(self, query_id: int) -> Dict:
        """Traite une seule requête par son ID"""
        try:
            consigne_data = await self.load_consigne_data()
            query_data = self.get_query_by_id(consigne_data, query_id)
            
            if not query_data:
                logging.error(f"❌ Requête ID {query_id} non trouvée")
                return {'status': 'failed', 'error': f'Requête ID {query_id} non trouvée'}
            
            # Traitement de la requête avec consigne_data
            result = await self.process_query_with_semaphore(query_data, consigne_data)
            
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
                logging.warning("❌ Aucune requête avec données sémantiques complètes trouvée")
                return {'status': 'failed', 'error': 'Aucune requête processable'}
            
            logging.info(f"🚀 Traitement parallèle de {len(processable_queries)} requêtes")
            
            # Créer toutes les tâches pour traitement en parallèle
            tasks = [
                self.process_query_with_semaphore(query_data, consigne_data) 
                for query_data in processable_queries
            ]
            
            # Exécuter toutes les tâches en parallèle avec limitation de concurrence
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
            
            # Résumé global
            successful = [r for r in processed_results if r.get('status') == 'success']
            failed = [r for r in processed_results if r.get('status') == 'failed']
            
            logging.info(f"🎉 Traitement parallèle terminé - Succès: {len(successful)}, Échecs: {len(failed)}")
            
            # Affichage du résumé global
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
        """Affiche un résumé pour une requête individuelle avec snippets optimisés"""
        print(f"\n" + "="*70)
        print(f"           RÉSUMÉ REQUÊTE ID {query_id}")
        print("="*70)
        
        print(f"📌 Requête: {query_text}")
        print(f"\n🎯 ANGLE SÉLECTIONNÉ:")
        print(f"   {selected_angle[:120]}{'...' if len(selected_angle) > 120 else ''}")
        
        # Affichage du type d'article et schema
        article_type = article_plan.get('article_type', 'general')
        schema_type = article_plan.get('schema_type', 'Article')
        print(f"\n📋 PLAN GÉNÉRÉ ({article_type.upper()}):")
        print(f"   📌 Titre SEO: {article_plan.get('SEO Title', 'Non défini')}")
        print(f"   🎯 Type d'article: {article_type}")
        print(f"   🏷️ Schema principal: {schema_type}")
        
        # Affichage de l'intégration du highlight
        intro_notes = article_plan.get('introduction_notes', {})
        if intro_notes:
            print(f"\n   🔗 INTÉGRATION DU LIEN:")
            print(f"      • Stratégie: {intro_notes.get('highlight_integration', 'Non définie')[:60]}...")
            print(f"      • Ancre suggérée: {intro_notes.get('suggested_anchor_text', 'Non définie')}")
        
        # Affichage des sections avec snippets optimisés
        sections = article_plan.get('sections', [])
        print(f"\n   📊 SECTIONS AVEC SNIPPETS OPTIMISÉS: {len(sections)}")
        
        snippet_count = 0
        for i, section in enumerate(sections, 1):
            title = section.get('section_title', 'Titre non défini')
            snippet_type = section.get('snippet_type', 'None')
            placement = section.get('placement', 'none')
            schema_section = section.get('schema_type', 'none')
            
            if snippet_type != 'None':
                snippet_count += 1
                snippet_info = f" [🎯 {snippet_type}@{placement}]"
                if schema_section != 'none':
                    snippet_info += f" [📋 {schema_section}]"
            else:
                snippet_info = " [📍 Aucun snippet]"
            
            print(f"      {i}. {title[:40]}{'...' if len(title) > 40 else ''}{snippet_info}")
            
            if i == 3 and len(sections) > 3:
                print(f"      ... et {len(sections) - 3} autres sections")
                break
        
        # Affichage des métriques SEO optimisées
        seo_opt = article_plan.get('seo_optimization', {})
        if seo_opt:
            print(f"\n   🎯 OPTIMISATION SEO AVANCÉE:")
            print(f"      • Snippets optimisés: {seo_opt.get('total_snippets', 0)}")
            print(f"      • Structure: {seo_opt.get('article_structure', 'standard')}")
            print(f"      • Mots cibles: {seo_opt.get('target_word_count', 0)}")
            
            distribution = seo_opt.get('snippet_distribution', {})
            if distribution.get('types_used'):
                print(f"      • Types utilisés: {', '.join(distribution['types_used'])}")
        
        print(f"\n💾 ✅ Sauvegardé avec agent d'optimisation des snippets")
        print("="*70 + "\n")
    
    def display_batch_summary(self, successful: List[Dict], failed: List[Dict], total: int) -> None:
        """Affiche un résumé du traitement en lot avec agent d'optimisation"""
        print("\n" + "="*85)
        print("           RÉSUMÉ DU TRAITEMENT EN LOT - SNIPPETS OPTIMISÉS")
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
            total_snippets = 0
            
            for result in successful:
                plan = result.get('article_plan', {})
                article_type = plan.get('article_type', 'general')
                schema_type = plan.get('schema_type', 'Article')
                
                article_types[article_type] = article_types.get(article_type, 0) + 1
                schema_types[schema_type] = schema_types.get(schema_type, 0) + 1
                
                seo_opt = plan.get('seo_optimization', {})
                total_snippets += seo_opt.get('total_snippets', 0)
            
            print(f"\n📊 TYPES D'ARTICLES GÉNÉRÉS:")
            for article_type, count in article_types.items():
                print(f"   • {article_type}: {count} articles")
            
            print(f"\n🏷️ SCHEMAS PRINCIPAUX UTILISÉS:")
            for schema_type, count in schema_types.items():
                print(f"   • {schema_type}: {count} articles")
            
            print(f"\n✅ REQUÊTES TRAITÉES AVEC SUCCÈS:")
            for result in successful[:5]:
                query_id = result.get('query_id')
                plan = result.get('article_plan', {})
                plan_title = plan.get('SEO Title', 'Titre non défini')
                article_type = plan.get('article_type', 'general')
                schema_type = plan.get('schema_type', 'Article')
                snippet_count = plan.get('seo_optimization', {}).get('total_snippets', 0)
                print(f"   • ID {query_id}: {plan_title[:30]}... [{article_type}|{schema_type}] ({snippet_count} snippets)")
            
            if len(successful) > 5:
                print(f"   ... et {len(successful) - 5} autres")
            
            print(f"\n🎯 MÉTRIQUES SNIPPETS OPTIMISÉS:")
            print(f"   • Total snippets intégrés: {total_snippets}")
            print(f"   • Moyenne par article: {total_snippets/len(successful):.1f}")
            
            # Analyse des types de snippets utilisés
            all_snippet_types = {}
            for result in successful:
                plan = result.get('article_plan', {})
                distribution = plan.get('seo_optimization', {}).get('snippet_distribution', {})
                for snippet_type, count in distribution.get('distribution', {}).items():
                    all_snippet_types[snippet_type] = all_snippet_types.get(snippet_type, 0) + count
            
            if all_snippet_types:
                print(f"\n📈 RÉPARTITION DES FORMATS DE CONTENU:")
                for snippet_type, count in sorted(all_snippet_types.items(), key=lambda x: x[1], reverse=True):
                    print(f"   • {snippet_type}: {count} utilisations")
        
        if failed:
            print(f"\n❌ REQUÊTES EN ÉCHEC:")
            for result in failed:
                query_id = result.get('query_id', 'Unknown')
                error = result.get('error', 'Erreur inconnue')
                print(f"   • ID {query_id}: {error[:50]}{'...' if len(error) > 50 else ''}")
        
        print(f"\n💾 SAUVEGARDE:")
        print(f"   ✅ Fichier consigne.json mis à jour")
        print(f"   ✅ Nouvelles clés ajoutées pour chaque requête traitée:")
        print(f"      - selected_differentiating_angle")
        print(f"      - generated_article_plan (avec snippets optimisés)")
        print(f"      - article_type (howto, comparative, faq_page, etc.)")
        print(f"      - schema_type (HowTo, FAQPage, Article, etc.)")
        print(f"      - seo_optimization (métriques snippets avancées)")
        print(f"      - plan_generation_status")
        
        print("\n✨ NOUVELLES FONCTIONNALITÉS:")
        print(f"   • Agent SnippetOptimizationAgent dédié")
        print(f"   • Détermination automatique du schema principal")
        print(f"   • Analyse intelligente des opportunités de snippets")
        print(f"   • Placement précis des formats de contenu")
        print(f"   • Fallback robuste en cas d'échec")
        print(f"   • Métriques SEO avancées avec distribution")
        
        print("\n🔧 WORKFLOW OPTIMISÉ:")
        print(f"   1. Sélection de l'angle différenciant")
        print(f"   2. Détermination du schema principal (LLM)")
        print(f"   3. Génération du plan d'article de base")
        print(f"   4. Optimisation intelligente des snippets (LLM)")
        print(f"   5. Validation et sauvegarde")
        
        print("\n⚡ GAIN DE TEMPS:")
        estimated_sequential_time = total * 45  # 45s par requête avec optimisation
        estimated_parallel_time = max(15, total * 45 / MAX_CONCURRENT_LLM)  # En parallèle
        time_saved = estimated_sequential_time - estimated_parallel_time
        print(f"   • Temps estimé séquentiel: {estimated_sequential_time//60}min {estimated_sequential_time%60}s")
        print(f"   • Temps parallélisé: {estimated_parallel_time//60}min {estimated_parallel_time%60}s")
        print(f"   • Gain de temps: ~{time_saved//60}min {time_saved%60}s")
        
        print("\n" + "="*85)
        print("Traitement en lot avec agent d'optimisation terminé !")
        print("="*85 + "\n")

# === Fonctions principales asynchrones ===
async def main_single_query_async(query_id: int):
    """Traite une seule requête par son ID (async)"""
    try:
        generator = ParallelConsignePlanGenerator()
        result = await generator.process_single_query(query_id)
        
        if result['status'] == 'success':
            article_type = result.get('article_plan', {}).get('article_type', 'general')
            schema_type = result.get('article_plan', {}).get('schema_type', 'Article')
            print(f"🎉 Plan {article_type} avec schema {schema_type} et snippets optimisés généré pour requête ID {query_id}!")
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
    """Traite toutes les requêtes disponibles en parallèle (async)"""
    try:
        generator = ParallelConsignePlanGenerator()
        result = await generator.process_all_queries()
        
        if result['status'] == 'completed':
            print(f"🎉 Traitement parallélisé terminé! {result.get('successful', 0)} requêtes traitées avec agent d'optimisation.")
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
    """Point d'entrée principal avec choix du mode"""
    import sys
    
    print("🚀 Générateur de Plans d'Articles SEO avec Agent d'Optimisation")
    print("="*70)
    print(f"📁 Dossier de travail: {BASE_DIR}")
    if CONSIGNE_FILE:
        print(f"📁 Fichier consigne: {os.path.basename(CONSIGNE_FILE)}")
        print(f"📁 Fichier existe: {os.path.exists(CONSIGNE_FILE)}")
    else:
        print("📁 Fichier consigne: ❌ Non trouvé")
    print("="*70)
    print("✨ NOUVELLES FONCTIONNALITÉS MAJEURES:")
    print("   • Agent SnippetOptimizationAgent spécialisé")
    print("   • Détermination automatique du schema principal")
    print("   • Analyse intelligente des opportunités de snippets")
    print("   • Placement précis des formats de contenu")
    print("   • Workflow en 4 étapes optimisé")
    print("   • Gestion d'erreurs robuste avec fallbacks")
    print("="*70)
    
    if len(sys.argv) > 1:
        try:
            query_id = int(sys.argv[1])
            print(f"Mode: Traitement de la requête ID {query_id}")
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