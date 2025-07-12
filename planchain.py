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

# === Agent d'analyse d'intention et de type d'article ===
class ArticleTypeAnalyzer:
    """Analyseur intelligent pour déterminer le type d'article optimal"""
    
    def __init__(self, query_id: int):
        self.query_id = query_id
    
    def analyze_query_intent(self, query_text: str) -> str:
        """Analyse l'intention de recherche de la requête"""
        query_lower = query_text.lower()
        
        if any(word in query_lower for word in ['comment', 'étape', 'guide', 'tuto', 'faire']):
            return 'howto'
        elif any(word in query_lower for word in ['qu\'est', 'qu est', 'c\'est quoi', 'définition']):
            return 'definitional'
        elif any(word in query_lower for word in ['différence', 'versus', 'vs', 'ou', 'comparaison', 'mieux']):
            return 'comparative'
        elif any(word in query_lower for word in ['pourquoi', 'raison', 'cause']):
            return 'faq_page'
        elif any(word in query_lower for word in ['liste', 'top', 'meilleur', 'classement']):
            return 'listicle'
        else:
            return 'general'
    
    def get_article_type_config(self, intent: str) -> Dict:
        """Retourne la configuration spécifique au type d'article"""
        configs = {
            'howto': {
                'template': 'guide_step_by_step',
                'required_sections': ['introduction', 'prerequisites', 'steps', 'conclusion'],
                'snippet_types': ['HowTo', 'FAQ'],
                'structure_emphasis': 'sequential_steps'
            },
            'comparative': {
                'template': 'comparison_analysis',
                'required_sections': ['introduction', 'option_a', 'option_b', 'comparison', 'recommendation'],
                'snippet_types': ['Table', 'Featured'],
                'structure_emphasis': 'side_by_side_analysis'
            },
            'faq_page': {
                'template': 'question_answer',
                'required_sections': ['introduction', 'main_questions', 'detailed_answers', 'conclusion'],
                'snippet_types': ['FAQ', 'Definition'],
                'structure_emphasis': 'question_driven'
            },
            'listicle': {
                'template': 'numbered_list',
                'required_sections': ['introduction', 'items_list', 'analysis', 'conclusion'],
                'snippet_types': ['List', 'Featured'],
                'structure_emphasis': 'ranked_items'
            },
            'definitional': {
                'template': 'comprehensive_definition',
                'required_sections': ['definition', 'characteristics', 'examples', 'conclusion'],
                'snippet_types': ['Definition', 'FAQ'],
                'structure_emphasis': 'concept_explanation'
            },
            'general': {
                'template': 'comprehensive_guide',
                'required_sections': ['introduction', 'main_content', 'analysis', 'conclusion'],
                'snippet_types': ['Featured', 'FAQ'],
                'structure_emphasis': 'topic_coverage'
            }
        }
        
        return configs.get(intent, configs['general'])
    

# === Générateurs de plans spécialisés ===
class SpecializedPlanGenerator:
    """Générateur de plans spécialisés selon le type d'article"""
    
    def __init__(self, query_id: int, llm: ChatOpenAI):
        self.query_id = query_id
        self.llm = llm
        self.article_analyzer = ArticleTypeAnalyzer(query_id)
    
    def get_template_prompt(self, article_type: str, query_data: Dict, selected_angle: str, highlight_url: str) -> str:
        """Génère le prompt spécialisé selon le type d'article"""
        
        base_data = self._format_base_data(query_data)
        
        templates = {
            'howto': self._get_howto_template(query_data, selected_angle, highlight_url, base_data),
            'comparative': self._get_comparative_template(query_data, selected_angle, highlight_url, base_data),
            'faq_page': self._get_faq_template(query_data, selected_angle, highlight_url, base_data),
            'listicle': self._get_listicle_template(query_data, selected_angle, highlight_url, base_data),
            'definitional': self._get_definitional_template(query_data, selected_angle, highlight_url, base_data),
            'general': self._get_general_template(query_data, selected_angle, highlight_url, base_data)
        }
        
        return templates.get(article_type, templates['general'])
    
    def _format_base_data(self, query_data: Dict) -> Dict:
        """Formate les données de base pour les templates en utilisant les vraies valeurs du plan"""
        plan_info = query_data.get('plan', {})
        
        # Utilisation des vraies valeurs du plan, pas de valeurs par défaut
        intro_length = plan_info.get('introduction', {}).get('longueur', 225)
        nb_sections = plan_info.get('developpement', {}).get('nombre_sections', 2)
        mots_par_section = plan_info.get('developpement', {}).get('mots_par_section', 300.0)
        conclusion_length = plan_info.get('conclusion', {}).get('longueur', 225)
        
        logging.info(f"📊 Plan détecté - Intro: {intro_length} mots, Sections: {nb_sections}, Mots/section: {mots_par_section}, Conclusion: {conclusion_length} mots")
        
        return {
            'intro_length': intro_length,
            'nb_sections': nb_sections,
            'mots_par_section': int(mots_par_section),  # Conversion en entier pour l'affichage
            'conclusion_length': conclusion_length,
            'word_count': query_data.get('word_count', 0),
            'keywords': ', '.join(query_data.get('top_keywords', '').split(',')[:20])
        }
    
    def _get_howto_template(self, query_data: Dict, selected_angle: str, highlight_url: str, base_data: Dict) -> str:
        return f"""Crée un plan d'article GUIDE ÉTAPE PAR ÉTAPE optimisé SEO.

**TYPE D'ARTICLE :** Guide pratique (HowTo)
**ANGLE RETENU :** {selected_angle}

**STRUCTURE OBLIGATOIRE POUR GUIDE :**
- Introduction : {base_data['intro_length']} mots (intégrer naturellement : {highlight_url})
- Prérequis/Matériel nécessaire : 150 mots
- {base_data['nb_sections']} étapes principales : {base_data['mots_par_section']} mots chacune
- Conseils et bonnes pratiques : 200 mots
- Conclusion : {base_data['conclusion_length']} mots

**CONTRAINTE ABSOLUE :** Le plan doit contenir EXACTEMENT {base_data['nb_sections']} sections principales de développement, pas plus, pas moins.

**INTÉGRATION SNIPPETS DANS LES SECTIONS :**
Chaque section doit inclure snippet_type et placement optimal.
Pour les guides : HowTo Schema (étapes), FAQ (problèmes courants)

**MOTS-CLÉS PRIORITAIRES :** {base_data['keywords']}

**EXIGENCES SPÉCIFIQUES AU GUIDE :**
1. Chaque étape doit être numérotée et actionnable
2. Intégrer des sous-étapes détaillées
3. Prévoir section FAQ pour les problèmes courants
4. Structurer en progression logique
5. Intégrer conseils pratiques entre les étapes
6. RESPECTER IMPÉRATIVEMENT : {base_data['nb_sections']} sections de développement exactement"""
    
    def _get_comparative_template(self, query_data: Dict, selected_angle: str, highlight_url: str, base_data: Dict) -> str:
        return f"""Crée un plan d'article COMPARATEUR optimisé SEO.

**TYPE D'ARTICLE :** Comparateur/Analyse comparative
**ANGLE RETENU :** {selected_angle}

**STRUCTURE OBLIGATOIRE POUR COMPARATEUR :**
- Introduction : {base_data['intro_length']} mots (intégrer naturellement : {highlight_url})
- {base_data['nb_sections']} sections principales de développement : {base_data['mots_par_section']} mots chacune
- Conclusion : {base_data['conclusion_length']} mots

**CONTRAINTE ABSOLUE :** Le plan doit contenir EXACTEMENT {base_data['nb_sections']} sections principales de développement, pas plus, pas moins.

**STRUCTURE SUGGÉRÉE POUR LES {base_data['nb_sections']} SECTIONS PRINCIPALES :**
Pour un comparateur efficace, les {base_data['nb_sections']} sections devraient être organisées ainsi :
- Section 1 : Présentation détaillée de l'Option A
- Section 2 : Présentation détaillée de l'Option B  
- Section 3 : Tableau comparatif et analyse finale
(Si plus de 3 sections : ajouter critères spécialisés, cas d'usage, recommandations par profils)

**INTÉGRATION SNIPPETS DANS LES SECTIONS :**
Chaque section doit inclure snippet_type et placement optimal.
Pour les comparateurs : Table Schema (comparaison), Featured Snippet (recommandation)

**MOTS-CLÉS PRIORITAIRES :** {base_data['keywords']}

**EXIGENCES SPÉCIFIQUES AU COMPARATEUR :**
1. Structurer en opposition claire entre options
2. Intégrer tableau comparatif avec critères précis
3. Section dédiée aux cas d'usage selon le nombre de sections disponibles
4. Recommandation basée sur profils utilisateurs
5. FAQ sur les différences principales si espace disponible
6. RESPECTER IMPÉRATIVEMENT : {base_data['nb_sections']} sections de développement exactement"""
    
    def _get_faq_template(self, query_data: Dict, selected_angle: str, highlight_url: str, base_data: Dict) -> str:
        return f"""Crée un plan d'article FAQ PAGE optimisé SEO.

**TYPE D'ARTICLE :** Page FAQ / Questions-Réponses
**ANGLE RETENU :** {selected_angle}

**STRUCTURE OBLIGATOIRE POUR FAQ :**
- Introduction : {base_data['intro_length']} mots (intégrer naturellement : {highlight_url})
- Questions principales ({base_data['nb_sections']} sections) : {base_data['mots_par_section']} mots chacune
- Questions secondaires et détails : 400 mots
- Synthèse et points clés : {base_data['conclusion_length']} mots

**INTÉGRATION SNIPPETS DANS LES SECTIONS :**
Chaque section doit inclure snippet_type et placement optimal.
Pour les FAQ : FAQ Schema (questions principales), Definition (concepts clés)

**MOTS-CLÉS PRIORITAIRES :** {base_data['keywords']}

**EXIGENCES SPÉCIFIQUES AUX FAQ :**
1. Questions formulées comme recherches Google
2. Réponses directes et concises
3. Groupement thématique des questions
4. Progression du général au spécifique
5. Intégration de questions longue traîne
6. RESPECTER IMPÉRATIVEMENT : {base_data['nb_sections']} sections de développement exactement"""
    
    def _get_listicle_template(self, query_data: Dict, selected_angle: str, highlight_url: str, base_data: Dict) -> str:
        return f"""Crée un plan d'article LISTE/CLASSEMENT optimisé SEO.

**TYPE D'ARTICLE :** Listicle/Top/Classement
**ANGLE RETENU :** {selected_angle}

**STRUCTURE OBLIGATOIRE POUR LISTICLE :**
- Introduction : {base_data['intro_length']} mots (intégrer naturellement : {highlight_url})
- {base_data['nb_sections']} items principaux : {base_data['mots_par_section']} mots chacun
- Critères de sélection/Méthodologie : 250 mots
- Récapitulatif et recommandations : {base_data['conclusion_length']} mots

**INTÉGRATION SNIPPETS DANS LES SECTIONS :**
Chaque section doit inclure snippet_type et placement optimal.
Pour les listes : List Schema (items), Featured Snippet (top recommandation)

**MOTS-CLÉS PRIORITAIRES :** {base_data['keywords']}

**EXIGENCES SPÉCIFIQUES AU LISTICLE :**
1. Items numérotés par ordre d'importance
2. Justification pour chaque choix
3. Critères de sélection transparents
4. Points forts/faibles pour chaque item
5. Conclusion avec podium/recommandation finale
6. RESPECTER IMPÉRATIVEMENT : {base_data['nb_sections']} items principaux exactement"""
    
    def _get_definitional_template(self, query_data: Dict, selected_angle: str, highlight_url: str, base_data: Dict) -> str:
        return f"""Crée un plan d'article DÉFINITION COMPLÈTE optimisé SEO.

**TYPE D'ARTICLE :** Guide définitionnel/Explication concept
**ANGLE RETENU :** {selected_angle}

**STRUCTURE OBLIGATOIRE POUR DÉFINITION :**
- Introduction et définition : {base_data['intro_length']} mots (intégrer naturellement : {highlight_url})
- {base_data['nb_sections']} sections principales de développement : {base_data['mots_par_section']} mots chacune
- Conclusion et points clés : {base_data['conclusion_length']} mots

**CONTRAINTE ABSOLUE :** Le plan doit contenir EXACTEMENT {base_data['nb_sections']} sections principales de développement, pas plus, pas moins.

**STRUCTURE SUGGÉRÉE POUR LES {base_data['nb_sections']} SECTIONS PRINCIPALES :**
Pour un guide définitionnel efficace, les {base_data['nb_sections']} sections devraient couvrir :
- Section 1 : Caractéristiques principales et spécificités
- Section 2 : Types, variantes et classifications
- Section 3 : Exemples concrets et cas d'usage pratiques
(Si plus de 3 sections : ajouter contexte historique, comparaisons, applications avancées)

**INTÉGRATION SNIPPETS DANS LES SECTIONS :**
Chaque section doit inclure snippet_type et placement optimal.
Pour les définitions : Definition Schema (concept principal), FAQ (questions courantes)

**MOTS-CLÉS PRIORITAIRES :** {base_data['keywords']}

**EXIGENCES SPÉCIFIQUES À LA DÉFINITION :**
1. Définition claire et concise en introduction
2. Progression du simple au complexe
3. Exemples pratiques et concrets
4. Différenciation avec concepts proches
5. FAQ sur les malentendus courants si espace disponible
6. RESPECTER IMPÉRATIVEMENT : {base_data['nb_sections']} sections de développement exactement"""
    
    def _get_general_template(self, query_data: Dict, selected_angle: str, highlight_url: str, base_data: Dict) -> str:
        return f"""Crée un plan d'article GUIDE COMPLET optimisé SEO.

**TYPE D'ARTICLE :** Guide général/Article complet
**ANGLE RETENU :** {selected_angle}

**STRUCTURE STANDARD :**
- Introduction : {base_data['intro_length']} mots (intégrer naturellement : {highlight_url})
- {base_data['nb_sections']} sections principales : {base_data['mots_par_section']} mots chacune
- Conclusion : {base_data['conclusion_length']} mots

**INTÉGRATION SNIPPETS DANS LES SECTIONS :**
Chaque section doit inclure snippet_type et placement optimal.
Pour les guides généraux : Featured Snippet (réponse principale), FAQ (questions courantes)

**MOTS-CLÉS PRIORITAIRES :** {base_data['keywords']}

**EXIGENCES GÉNÉRALES :**
1. Coverage complète du sujet
2. Progression logique
3. Sous-sections détaillées
4. Intégration naturelle des mots-clés
5. Équilibre entre profondeur et accessibilité
6. RESPECTER IMPÉRATIVEMENT : {base_data['nb_sections']} sections principales exactement"""

# === Classe de traitement asynchrone d'une requête (mise à jour) ===
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
    
    def format_clusters_for_prompt(self, detailed_clusters: Dict) -> str:
        """Formate les clusters pour le prompt"""
        formatted = ""
        for i, (cluster_name, data) in enumerate(detailed_clusters.items(), 1):
            keywords = ", ".join(data.get('mots_cles', [])[:5])
            theme = data.get('theme_principal', 'Thème inconnu')
            formatted += f"**Cluster {i} ({theme}):** {keywords}\n"
        return formatted
    
    def format_relations_for_prompt(self, semantic_relations: List[Dict]) -> str:
        """Formate les relations sémantiques pour le prompt"""
        formatted = ""
        for i, rel in enumerate(semantic_relations[:5], 1):
            relation = rel.get('relation', '')
            angle = rel.get('angle_potentiel', '')
            formatted += f"{i}. {relation} → {angle}\n"
        return formatted
    
    def format_entities_for_prompt(self, strategic_entities: List[Dict]) -> str:
        """Formate les entités stratégiques pour le prompt"""
        entities_by_type = {}
        for entity in strategic_entities[:8]:
            type_key = entity.get('type', 'UNKNOWN')
            nom = entity.get('nom', '')
            if type_key not in entities_by_type:
                entities_by_type[type_key] = []
            entities_by_type[type_key].append(nom)
        
        formatted = ""
        for type_name, entities in entities_by_type.items():
            formatted += f"**{type_name}:** {', '.join(entities[:3])}\n"
        return formatted
    
    async def select_best_angle(self, query_data: Dict) -> str:
        """Étape 1: Sélection du meilleur angle différenciant (async)"""
        
        angles_list = "\n".join([f"{i+1}. {angle}" for i, angle in enumerate(query_data.get('differentiating_angles', []))])
        
        semantic_analysis = query_data.get('semantic_analysis', {})
        
        prompt_selection = f"""Tu es un expert en stratégie de contenu SEO. À partir de cette analyse sémantique SERP, choisis l'angle différenciant le PLUS PERTINENT pour créer un article unique qui se démarquera de la concurrence.

**REQUÊTE CIBLE (OBLIGATOIRE) :** "{query_data.get('text', 'Sujet non défini')}"
⚠️ IMPORTANT : Tu DOIS absolument choisir l'angle qui correspond le mieux à cette requête exacte. C'est la recherche que les utilisateurs tapent dans Google.

**ANGLES DIFFÉRENCIANTS DISPONIBLES :**
{angles_list}

**CONTEXTE CONCURRENTIEL :**
- Nombre de mots cible : {query_data.get('word_count', 0)}
- Clusters thématiques identifiés : {semantic_analysis.get('clusters_count', 0)}
- Complexité sémantique du sujet : {semantic_analysis.get('semantic_complexity', 0)}/1.0
- Diversité thématique : {semantic_analysis.get('thematic_diversity', 0)}/1.0

**CRITÈRES DE SÉLECTION (PAR ORDRE DE PRIORITÉ) :**
1. CORRESPONDANCE EXACTE avec la requête cible "{query_data.get('text', 'Sujet non défini')}"
2. Pertinence pour l'intention de recherche de cette requête spécifique
3. Potentiel de différenciation vs concurrence
4. Richesse du contenu possible
5. Capacité à couvrir plusieurs clusters thématiques

**DEMANDE :**
Choisis UN SEUL angle qui répond DIRECTEMENT à la requête "{query_data.get('text', 'Sujet non défini')}" et justifie ton choix en expliquant pourquoi cet angle est le plus adapté à cette recherche précise.
Format : "ANGLE CHOISI: [titre] - JUSTIFICATION: [explication en lien direct avec la requête cible]"
"""
        
        messages = [
            SystemMessage(content="Tu es un expert en stratégie de contenu SEO spécialisé dans la sélection d'angles différenciants."),
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
    
    async def generate_article_plan(self, query_data: Dict, selected_angle: str, consigne_data: Dict) -> Dict:
        """Étape 2: Génération du plan d'article spécialisé avec snippets intégrés"""
        
        # 1. Analyse du type d'article optimal
        query_text = query_data.get('text', '')
        article_intent = self.article_analyzer.analyze_query_intent(query_text)
        article_config = self.article_analyzer.get_article_type_config(article_intent)
        
        logging.info(f"🎯 [ID {self.query_id}] Type d'article détecté: {article_intent}")
        logging.info(f"📋 [ID {self.query_id}] Template: {article_config['template']}")
        
        # 2. Récupération du highlight depuis consigne_data
        highlight_url = consigne_data.get('highlight', '')
        
        # 3. Génération du prompt spécialisé
        specialized_prompt = self.plan_generator.get_template_prompt(
            article_intent, query_data, selected_angle, highlight_url
        )
        
        # 4. Format de sortie adapté au type d'article
        system_message_content = f"""Your objective: Create a specialized {article_intent.upper()} article outline with integrated snippets.

Expected output format:
{{
  "SEO Title": "",
  "article_type": "{article_intent}",
  "introduction_notes": {{
    "highlight_integration": "Description of how to naturally integrate the link",
    "suggested_anchor_text": "Suggested anchor text for the link"
  }},
  "sections": [
    {{
      "section_title": "",
      "snippet_type": "HowTo|FAQ|Featured|Table|List|Definition|None",
      "placement": "beginning|middle|end",
      "subsections": [
        {{ "subsection_title": "" }},
        {{ "subsection_title": "" }}
      ]
    }}
  ],
  "conclusion": "",
  "article_config": {{
    "template": "{article_config['template']}",
    "structure_emphasis": "{article_config['structure_emphasis']}",
    "recommended_snippets": {article_config['snippet_types']}
  }}
}}

IMPORTANT SNIPPET INTEGRATION:
- Each section MUST include snippet_type and placement properties
- snippet_type should be one of: {', '.join(article_config['snippet_types'])} or "None"
- placement indicates where in the section the snippet should appear
- Only assign snippets where they add real value

Article Type Guidelines:
- {article_intent}: {article_config['structure_emphasis']}
- Required sections: {', '.join(article_config['required_sections'])}
- Preferred snippets: {', '.join(article_config['snippet_types'])}

Restrictions:
 • Propose only titles and subtitles with snippet integration
 • Each section must specify snippet optimization
 • No additional textual content
Response language: Match the language of the provided data."""

        messages = [
            SystemMessage(content=system_message_content),
            HumanMessage(content=specialized_prompt)
        ]
        
        logging.info(f"🏗️ [ID {self.query_id}] Génération du plan {article_intent} avec snippets intégrés...")
        
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
            
            # Validation et enrichissement du plan
            validated_plan = self._validate_and_enrich_plan(plan_json, article_config, query_data)
            
            logging.info(f"✅ [ID {self.query_id}] Plan {article_intent} généré avec snippets intégrés")
            return validated_plan
            
        except json.JSONDecodeError as e:
            logging.error(f"❌ [ID {self.query_id}] Erreur de parsing JSON: {e}")
            logging.error(f"Contenu reçu: {response.content}")
            
            # Fallback: structure basique avec type d'article
            fallback_plan = self._create_fallback_plan(query_data, article_intent, article_config, highlight_url)
            return fallback_plan
    
    def _validate_and_enrich_plan(self, plan_json: Dict, article_config: Dict, query_data: Dict) -> Dict:
        """Valide et enrichit le plan généré"""
        validated_plan = plan_json.copy()
        
        # S'assurer que l'article_type est présent
        if 'article_type' not in validated_plan:
            validated_plan['article_type'] = article_config.get('template', 'general')
        
        # Valider que chaque section a snippet_type et placement
        for section in validated_plan.get('sections', []):
            if 'snippet_type' not in section:
                section['snippet_type'] = 'None'
            if 'placement' not in section:
                section['placement'] = 'middle'
        
        # Ajouter métadonnées sur l'optimisation
        validated_plan['seo_optimization'] = {
            'total_snippets': len([s for s in validated_plan.get('sections', []) if s.get('snippet_type') != 'None']),
            'article_structure': article_config.get('structure_emphasis', 'standard'),
            'target_word_count': query_data.get('word_count', 0),
            'snippet_distribution': self._analyze_snippet_distribution(validated_plan)
        }
        
        return validated_plan
    
    def _analyze_snippet_distribution(self, plan: Dict) -> Dict:
        """Analyse la distribution des snippets dans le plan"""
        snippet_types = {}
        for section in plan.get('sections', []):
            snippet_type = section.get('snippet_type', 'None')
            if snippet_type != 'None':
                snippet_types[snippet_type] = snippet_types.get(snippet_type, 0) + 1
        
        return {
            'types_used': list(snippet_types.keys()),
            'total_count': sum(snippet_types.values()),
            'distribution': snippet_types
        }
    
    def _create_fallback_plan(self, query_data: Dict, article_intent: str, article_config: Dict, highlight_url: str) -> Dict:
        """Crée un plan de fallback en cas d'erreur"""
        return {
            "SEO Title": f"Guide {query_data.get('text', 'sujet')} - Plan généré automatiquement",
            "article_type": article_intent,
            "introduction_notes": {
                "highlight_integration": f"Intégrer naturellement le lien {highlight_url} dans le contexte",
                "suggested_anchor_text": "découvrez notre guide"
            },
            "sections": [
                {
                    "section_title": "Section principale 1",
                    "snippet_type": article_config['snippet_types'][0] if article_config['snippet_types'] else "Featured",
                    "placement": "beginning",
                    "subsections": [
                        {"subsection_title": "Sous-section 1.1"},
                        {"subsection_title": "Sous-section 1.2"}
                    ]
                },
                {
                    "section_title": "Section principale 2",
                    "snippet_type": "FAQ",
                    "placement": "end",
                    "subsections": [
                        {"subsection_title": "Sous-section 2.1"}
                    ]
                }
            ],
            "conclusion": "Conclusion optimisée SEO",
            "article_config": {
                "template": article_config['template'],
                "structure_emphasis": article_config['structure_emphasis'],
                "recommended_snippets": article_config['snippet_types']
            },
            "seo_optimization": {
                "total_snippets": 2,
                "article_structure": "fallback",
                "target_word_count": query_data.get('word_count', 0),
                "snippet_distribution": {
                    "types_used": ["Featured", "FAQ"],
                    "total_count": 2,
                    "distribution": {"Featured": 1, "FAQ": 1}
                }
            }
        }
    
    async def process_query(self, query_data: Dict, consigne_data: Dict) -> Dict:
        """Traite une requête complète avec plan spécialisé et snippets intégrés"""
        try:
            logging.info(f"🚀 [ID {self.query_id}] Début du traitement: '{query_data.get('text')}'")
            
            # Vérifier si la requête a les données nécessaires
            if not all([query_data.get('differentiating_angles'), 
                       query_data.get('detailed_clusters'), 
                       query_data.get('semantic_analysis')]):
                logging.error(f"❌ [ID {self.query_id}] Données sémantiques incomplètes")
                return {'status': 'failed', 'error': f'Données sémantiques incomplètes pour ID {self.query_id}'}
            
            # Traitement: sélection d'angle
            selected_angle = await self.select_best_angle(query_data)
            
            # Génération du plan spécialisé avec snippets intégrés
            article_plan = await self.generate_article_plan(
                query_data, 
                selected_angle,
                consigne_data
            )
            
            logging.info(f"🎉 [ID {self.query_id}] Traitement terminé avec succès")
            
            return {
                'query_id': self.query_id,
                'selected_angle': selected_angle,
                'article_plan': article_plan,
                'status': 'success'
            }
            
        except Exception as e:
            logging.error(f"💥 [ID {self.query_id}] Erreur lors du traitement: {e}")
            return {
                'query_id': self.query_id,
                'error': str(e),
                'status': 'failed'
            }
    

# === Gestionnaire de traitement en lot parallélisé (mise à jour) ===
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
                query.get('detailed_clusters') and 
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
                                logging.info(f"✅ [ID {query_id}] Plan {plan.get('article_type', 'general')} ajouté avec snippets intégrés")
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
                    logging.info(f"📈 {updated_count} requêtes mises à jour avec plans spécialisés et snippets intégrés")
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
        """Affiche un résumé pour une requête individuelle avec plan spécialisé"""
        print(f"\n" + "="*70)
        print(f"           RÉSUMÉ REQUÊTE ID {query_id}")
        print("="*70)
        
        print(f"📌 Requête: {query_text}")
        print(f"\n🎯 ANGLE SÉLECTIONNÉ:")
        print(f"   {selected_angle[:120]}{'...' if len(selected_angle) > 120 else ''}")
        
        # Affichage du type d'article
        article_type = article_plan.get('article_type', 'general')
        print(f"\n📋 PLAN GÉNÉRÉ ({article_type.upper()}):")
        print(f"   📌 Titre SEO: {article_plan.get('SEO Title', 'Non défini')}")
        print(f"   🎯 Type d'article: {article_type}")
        
        # Affichage de l'intégration du highlight
        intro_notes = article_plan.get('introduction_notes', {})
        if intro_notes:
            print(f"\n   🔗 INTÉGRATION DU LIEN:")
            print(f"      • Stratégie: {intro_notes.get('highlight_integration', 'Non définie')[:60]}...")
            print(f"      • Ancre suggérée: {intro_notes.get('suggested_anchor_text', 'Non définie')}")
        
        # Affichage des sections avec snippets intégrés
        sections = article_plan.get('sections', [])
        print(f"\n   📊 SECTIONS AVEC SNIPPETS INTÉGRÉS: {len(sections)}")
        
        snippet_count = 0
        for i, section in enumerate(sections, 1):
            title = section.get('section_title', 'Titre non défini')
            snippet_type = section.get('snippet_type', 'None')
            placement = section.get('placement', '')
            
            if snippet_type != 'None':
                snippet_count += 1
                snippet_info = f" [📍 {snippet_type} - {placement}]"
            else:
                snippet_info = ""
            
            print(f"      {i}. {title[:45]}{'...' if len(title) > 45 else ''}{snippet_info}")
            
            if i == 3 and len(sections) > 3:
                print(f"      ... et {len(sections) - 3} autres sections")
                break
        
        # Affichage des métriques SEO
        seo_opt = article_plan.get('seo_optimization', {})
        if seo_opt:
            print(f"\n   🎯 OPTIMISATION SEO:")
            print(f"      • Total snippets intégrés: {seo_opt.get('total_snippets', 0)}")
            print(f"      • Structure: {seo_opt.get('article_structure', 'standard')}")
            print(f"      • Mots cibles: {seo_opt.get('target_word_count', 0)}")
            
            distribution = seo_opt.get('snippet_distribution', {})
            if distribution.get('types_used'):
                print(f"      • Types snippets: {', '.join(distribution['types_used'])}")
        
        print(f"\n💾 ✅ Sauvegardé dans consigne.json avec plan spécialisé")
        print("="*70 + "\n")
    
    def display_batch_summary(self, successful: List[Dict], failed: List[Dict], total: int) -> None:
        """Affiche un résumé du traitement en lot avec plans spécialisés"""
        print("\n" + "="*85)
        print("           RÉSUMÉ DU TRAITEMENT EN LOT - PLANS SPÉCIALISÉS")
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
            total_snippets = 0
            
            for result in successful:
                plan = result.get('article_plan', {})
                article_type = plan.get('article_type', 'general')
                article_types[article_type] = article_types.get(article_type, 0) + 1
                
                seo_opt = plan.get('seo_optimization', {})
                total_snippets += seo_opt.get('total_snippets', 0)
            
            print(f"\n📊 TYPES D'ARTICLES GÉNÉRÉS:")
            for article_type, count in article_types.items():
                print(f"   • {article_type}: {count} articles")
            
            print(f"\n✅ REQUÊTES TRAITÉES AVEC SUCCÈS:")
            for result in successful[:5]:
                query_id = result.get('query_id')
                plan = result.get('article_plan', {})
                plan_title = plan.get('SEO Title', 'Titre non défini')
                article_type = plan.get('article_type', 'general')
                snippet_count = plan.get('seo_optimization', {}).get('total_snippets', 0)
                print(f"   • ID {query_id}: {plan_title[:35]}... [{article_type}] ({snippet_count} snippets)")
            
            if len(successful) > 5:
                print(f"   ... et {len(successful) - 5} autres")
            
            print(f"\n🎯 MÉTRIQUES SNIPPETS:")
            print(f"   • Total snippets intégrés: {total_snippets}")
            print(f"   • Moyenne par article: {total_snippets/len(successful):.1f}")
        
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
        print(f"      - generated_article_plan (avec plans spécialisés)")
        print(f"      - article_type (howto, comparative, faq_page, etc.)")
        print(f"      - seo_optimization (métriques snippets)")
        print(f"      - plan_generation_status")
        
        print("\n✨ NOUVEAUTÉS INTÉGRÉES:")
        print(f"   • Plans spécialisés par type d'intention")
        print(f"   • Snippets intégrés directement dans les sections")
        print(f"   • Templates adaptatifs (howto, comparateur, faq, etc.)")
        print(f"   • Intégration automatique du highlight")
        print(f"   • Métriques SEO détaillées")
        
        print("\n⚡ GAIN DE TEMPS:")
        estimated_sequential_time = total * 35  # 35s par requête en séquentiel (plus complexe)
        estimated_parallel_time = max(12, total * 35 / MAX_CONCURRENT_LLM)  # En parallèle
        time_saved = estimated_sequential_time - estimated_parallel_time
        print(f"   • Temps estimé séquentiel: {estimated_sequential_time//60}min {estimated_sequential_time%60}s")
        print(f"   • Temps parallélisé: {estimated_parallel_time//60}min {estimated_parallel_time%60}s")
        print(f"   • Gain de temps: ~{time_saved//60}min {time_saved%60}s")
        
        print("\n" + "="*85)
        print("Traitement en lot avec plans spécialisés terminé !")
        print("="*85 + "\n")

# === Fonctions principales asynchrones ===
async def main_single_query_async(query_id: int):
    """Traite une seule requête par son ID (async)"""
    try:
        generator = ParallelConsignePlanGenerator()
        result = await generator.process_single_query(query_id)
        
        if result['status'] == 'success':
            article_type = result.get('article_plan', {}).get('article_type', 'general')
            print(f"🎉 Plan {article_type} avec snippets intégrés généré pour requête ID {query_id}!")
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
            print(f"🎉 Traitement parallélisé terminé! {result.get('successful', 0)} requêtes traitées avec succès.")
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
    
    print("🚀 Générateur de Plans d'Articles SEO Spécialisés")
    print("="*65)
    print(f"📁 Dossier de travail: {BASE_DIR}")
    if CONSIGNE_FILE:
        print(f"📁 Fichier consigne: {os.path.basename(CONSIGNE_FILE)}")
        print(f"📁 Fichier existe: {os.path.exists(CONSIGNE_FILE)}")
    else:
        print("📁 Fichier consigne: ❌ Non trouvé")
    print("="*65)
    print("✨ NOUVEAUTÉS MAJEURES:")
    print("   • Plans spécialisés par type d'intention")
    print("   • Templates adaptatifs (howto, comparateur, faq, listicle)")
    print("   • Snippets intégrés directement dans les sections")
    print("   • Intégration automatique du highlight")
    print("   • Métriques SEO avancées")
    print("="*65)
    
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