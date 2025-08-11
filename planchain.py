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
                'intro_label': 'Introduction',
                'conclusion_label': 'Conclusion',
                'cta_label': 'Call-to-Action',
                'main_sections': 'sections principales',
                'words_each': 'mots chacune',
                'absolute_constraint': 'Le plan doit contenir EXACTEMENT',
                'priority_keywords': 'MOTS-CLÉS PRIORITAIRES',
                'specific_requirements': 'EXIGENCES SPÉCIFIQUES',
                'commercial_ratio': 'RATIO COMMERCIAL (40%)',
                'informational_ratio': 'RATIO INFORMATIF (60%)'
            },
            'en': {
                'howto_keywords': ['how', 'step', 'guide', 'tutorial', 'make'],
                'definitional_keywords': ['what is', 'what are', 'definition', 'meaning'],
                'comparative_keywords': ['difference', 'versus', 'vs', 'or', 'comparison', 'better'],
                'intro_label': 'Introduction',
                'conclusion_label': 'Conclusion',
                'cta_label': 'Call-to-Action',
                'main_sections': 'main sections',
                'words_each': 'words each',
                'absolute_constraint': 'The plan must contain EXACTLY',
                'priority_keywords': 'PRIORITY KEYWORDS',
                'specific_requirements': 'SPECIFIC REQUIREMENTS',
                'commercial_ratio': 'COMMERCIAL RATIO (40%)',
                'informational_ratio': 'INFORMATIONAL RATIO (60%)'
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

# === Agent d'analyse d'intention et de type d'article (Simplifié) ===
class ArticleTypeAnalyzer:
    """Analyseur intelligent pour déterminer le type d'article optimal - 3 types seulement"""
    
    def __init__(self, query_id: int):
        self.query_id = query_id
        self.language_detector = LanguageDetector()
    
    def analyze_query_intent(self, query_text: str) -> str:
        """Analyse l'intention de recherche de la requête (multilingue) - 3 types seulement"""
        query_lower = query_text.lower()
        
        # Détection de la langue
        lang = self.language_detector.detect_language(query_text)
        strings = self.language_detector.get_localized_strings(lang)
        
        logging.info(f"🌐 [ID {self.query_id}] Langue détectée: {lang.upper()}")
        
        # Classification en 3 types seulement
        if any(word in query_lower for word in strings['howto_keywords']):
            return 'howto'
        elif any(word in query_lower for word in strings['definitional_keywords']):
            return 'definitional'
        elif any(word in query_lower for word in strings['comparative_keywords']):
            return 'comparative'
        else:
            # Par défaut : definitional (le plus polyvalent)
            return 'definitional'
    
    def get_article_type_config(self, intent: str) -> Dict:
        """Retourne la configuration spécifique au type d'article - 3 types seulement"""
        configs = {
            'howto': {
                'template': 'guide_step_by_step',
                'required_sections': ['introduction', 'prerequisites', 'steps', 'commercial_integration', 'conclusion', 'cta'],
                'structure_emphasis': 'sequential_steps_with_conversion',
                'commercial_ratio': 0.4,
                'informational_ratio': 0.6
            },
            'comparative': {
                'template': 'comparison_analysis',
                'required_sections': ['introduction', 'comparison_criteria', 'detailed_comparison', 'recommendation', 'conclusion', 'cta'],
                'structure_emphasis': 'side_by_side_analysis_with_conversion',
                'commercial_ratio': 0.4,
                'informational_ratio': 0.6
            },
            'definitional': {
                'template': 'comprehensive_definition',
                'required_sections': ['introduction', 'definition', 'characteristics', 'practical_applications', 'conclusion', 'cta'],
                'structure_emphasis': 'concept_explanation_with_conversion',
                'commercial_ratio': 0.4,
                'informational_ratio': 0.6
            }
        }
        
        return configs.get(intent, configs['definitional'])

# === Générateurs de plans spécialisés (Simplifié avec Focus Commercial) ===
class SpecializedPlanGenerator:
    """Générateur de plans spécialisés avec ratio 60% informatif / 40% commercial"""
    
    def __init__(self, query_id: int, llm: ChatOpenAI):
        self.query_id = query_id
        self.llm = llm
        self.article_analyzer = ArticleTypeAnalyzer(query_id)
        self.language_detector = LanguageDetector()
    
    def get_template_prompt(self, article_type: str, query_data: Dict, selected_angle: str, highlight_url: str) -> str:
        """Génère le prompt data-driven pour tous les types d'articles"""
        
        # Détection de la langue
        lang = self.language_detector.detect_language(query_data.get('text', ''))
        strings = self.language_detector.get_localized_strings(lang)
        
        base_data = self._format_base_data(query_data, lang)
        
        # Utilisation du nouveau template data-driven unifié
        return self._get_data_driven_template(query_data, selected_angle, highlight_url, base_data, lang, strings)
    
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
        nb_sections = plan_info.get(dev_key, {}).get(sections_key, 3)  # Minimum 3 sections pour le ratio
        mots_par_section = plan_info.get(dev_key, {}).get(words_key, 300.0)
        conclusion_length = plan_info.get(conclusion_key, {}).get(length_key, 225)
        
        logging.info(f"📊 [ID {self.query_id}] Plan détecté - Intro: {intro_length} mots, Sections: {nb_sections}, Mots/section: {mots_par_section}, Conclusion: {conclusion_length} mots")
        
        return {
            'intro_length': intro_length,
            'nb_sections': max(3, nb_sections),  # Minimum 3 sections
            'mots_par_section': int(mots_par_section),
            'conclusion_length': conclusion_length,
            'word_count': query_data.get('word_count', 0),
            'keywords': ', '.join(query_data.get('top_keywords', '').split(',')[:20])
        }
    
    def _get_data_driven_template(self, query_data: Dict, selected_angle: str, highlight_url: str, base_data: Dict, lang: str, strings: Dict) -> str:
        """Nouveau template data-driven basé sur les données exclusives"""
        
        # Extraction des données depuis query_data
        agent_response = query_data.get('agent_response', {})
        shock_stats = agent_response.get('shock_stats', [])
        expert_insights = agent_response.get('expert_insights', [])
        benchmark_data = agent_response.get('benchmark_data', [])
        market_trends = agent_response.get('market_trends', [])
        competitive_landscape = agent_response.get('competitive_landscape', [])
        sources = agent_response.get('sources', [])
        credibility_boosters = agent_response.get('credibility_boosters', [])
        content_angles = agent_response.get('content_angles', [])
        hook_potential = agent_response.get('hook_potential', {})
        
        return f"""Tu es un expert en content marketing qui crée des guides HowTo ultra-performants basés sur des DONNÉES FACTUELLES et STATISTIQUES EXCLUSIVES.

**MISSION :** Créer un plan de guide HowTo qui VEND SANS AVOIR L'AIR DE VENDRE en s'appuyant massivement sur les données statistiques et insights fournis.

**REQUÊTE :** {query_data.get('text', 'sujet')}
**ANGLE CHOISI :** {selected_angle}
**LIEN À INTÉGRER :** {highlight_url}

**LANGUE :** Adapte automatiquement ta réponse à la langue de la requête (français ou anglais).

**📊 DONNÉES EXCLUSIVES À EXPLOITER PRIORITAIREMENT :**

**STATISTIQUES CHOC disponibles :**
{chr(10).join([f"• {stat.get('statistic', 'N/A')} - Source: {stat.get('source_credibility', 'N/A')}" for stat in shock_stats[:5]])}

**INSIGHTS D'EXPERTS disponibles :**
{chr(10).join([f"• {insight.get('insight', 'N/A')} - {insight.get('authority_source', 'N/A')}" for insight in expert_insights[:3]])}

**BENCHMARKS DE PERFORMANCE disponibles :**
{chr(10).join([f"• {bench.get('metric', 'N/A')} - Échantillon: {bench.get('sample_size', 'N/A')}" for bench in benchmark_data[:3]])}

**TENDANCES MARCHÉ disponibles :**
{chr(10).join([f"• {trend.get('trend', 'N/A')} - Projection: {trend.get('future_projection', 'N/A')}" for trend in market_trends[:3]])}

**COMPARATIFS CONCURRENCE disponibles :**
{chr(10).join([f"• {comp.get('comparison_point', 'N/A')} - Différence: {comp.get('quantified_difference', 'N/A')}" for comp in competitive_landscape[:3]])}

**SOURCES CRÉDIBLES à citer :**
{chr(10).join([f"• {source.get('title', 'N/A')} ({source.get('source_type', 'N/A')}) - {source.get('publication_date', 'N/A')}" for source in sources[:5]])}

**PHILOSOPHIE COMMERCIALE "DATA-DRIVEN WAALAXY-STYLE" :**
- Tu es d'abord un CONSULTANT EXPERT qui s'appuie sur des DONNÉES EXCLUSIVES
- Chaque section COMMENCE par une statistique ou un benchmark
- Les mentions commerciales sont justifiées par les PERFORMANCES mesurées
- Tu vends une SOLUTION PROUVÉE par les données, pas une opinion

**STRUCTURE SOPHISTIQUÉE BASÉE SUR LES DONNÉES :**

1️⃣ **Introduction Statistique Choc** ({base_data['intro_length']} mots)
   - OUVRIR avec la statistique la plus surprenante des données disponibles
   - Contextualiser le problème avec les benchmarks de performance
   - Citer une source crédible pour l'autorité immédiate
   - Intégration NATURELLE du lien : "{highlight_url}" comme "étude complète"
   - **OBLIGATOIRE : Utiliser AU MOINS 2 statistiques des données fournies**

2️⃣ **Section "Pourquoi 80% échouent (données à l'appui)"** (350 mots)
   - Utiliser les benchmarks négatifs ou échecs mesurés des données
   - Citer les comparatifs concurrence pour montrer les écarts
   - Intégrer un insight d'expert pour expliquer les causes
   - → Mini-CTA contextuel : "Évitez ces erreurs mesurées chez 80% des utilisateurs"
   - **OBLIGATOIRE : Minimum 1 benchmark + 1 insight expert**

3️⃣ **Méthode prouvée en {base_data['nb_sections']} étapes DATA-DRIVEN** ({base_data['mots_par_section']} mots chacune)
   - Chaque étape COMMENCE par un résultat chiffré des données
   - Intégrer les tendances marché pour justifier chaque approche
   - Utiliser les comparatifs pour recommander les meilleures pratiques
   - Templates/outils basés sur les méthodes qui ont les meilleurs benchmarks
   - Micro-CTA par étape basé sur les résultats : "Obtenez les mêmes +45% de performance"
   - **OBLIGATOIRE : 1 statistique de performance par étape majeure**

4️⃣ **Section "Erreurs coûteuses + Preuves chiffrées"** (450 mots)
   - Utiliser les données de benchmarks pour quantifier les erreurs
   - Intégrer les insights d'experts pour expliquer les impacts
   - Cas réels avec les ROI mesurés des données disponibles
   - Comparatifs avant/après basés sur les benchmarks fournis
   - → CTA contextuel : "Économisez les X€ perdus par 67% des entreprises"
   - **OBLIGATOIRE : Quantifier chaque erreur avec les données disponibles**

5️⃣ **Section "Techniques avancées (résultats exclusifs)"** (350 mots) 
   - Exploiter les tendances futures des données pour les techniques avancées
   - Utiliser les meilleurs benchmarks pour recommander les outils premium
   - Citer les sources les plus prestigieuses pour crédibiliser
   - Stack d'outils justifié par les performances mesurées
   - → CTA soft basé sur les résultats : "Rejoignez les 15% qui obtiennent +200% de ROI"
   - **OBLIGATOIRE : Minimum 2 tendances marché + 1 benchmark top performance**

6️⃣ **FAQ Commercialement Intelligente (basée sur les données)** (250 mots)
   - Questions qui traitent les OBJECTIONS avec des preuves chiffrées
   - "Ça marche vraiment ?" → Citer les benchmarks de performance
   - "Combien ça coûte VS ROI ?" → Utiliser les données de rentabilité
   - "C'est compliqué ?" → Citer les insights d'experts sur la simplicité
   - → CTA final basé sur les résultats : "Démarrez avec +92% de chances de succès"
   - **OBLIGATOIRE : Répondre avec des données chiffrées exclusives**

**RÈGLES D'OR DATA-DRIVEN WAALAXY-STYLE :**
✅ CHAQUE section majeure COMMENCE par une donnée exclusive
✅ Citations d'experts intégrées naturellement pour l'autorité
✅ Benchmarks utilisés pour justifier CHAQUE recommandation
✅ Sources crédibles citées pour renforcer la légitimité
✅ CTA basés sur les RÉSULTATS mesurés, pas sur des promesses vagues
✅ Comparatifs concurrence pour positionner les solutions
✅ Tendances futures pour créer l'urgence d'agir

**INTÉGRATIONS COMMERCIALES BASÉES SUR LES PERFORMANCES :**
- "L'outil qui génère +{base_data.get('benchmark_ROI', 'X')}% selon notre étude exclusive..."
- "Mes clients qui utilisent X obtiennent {base_data.get('résultat_chiffré', 'Y')} en moyenne..."
- "La méthode qui surperforme de {base_data.get('comparatif_concurrence', 'Z')}% vs la concurrence..."
- "Le framework testé sur {base_data.get('échantillon', 'N')} utilisateurs avec {base_data.get('taux_succès', 'T')}% de réussite..."

**MOTS-CLÉS PRIORITAIRES :** {base_data['keywords']}

**CONTRAINTE DATA-DRIVEN :** Chaque affirmation commerciale DOIT être supportée par une donnée des agent_response.

**EXPLOITATION PRIORITAIRE DES CRÉDIBILITÉ BOOSTERS :**
{chr(10).join([f"• {booster}" for booster in credibility_boosters[:5]])}

**ANGLES CONTENT MARKETING SUGGÉRÉS DANS LES DONNÉES :**
{chr(10).join([f"• {angle}" for angle in content_angles[:3]])}

**HOOKS POTENTIELS IDENTIFIÉS :**
• Intro hooks: {', '.join(hook_potential.get('intro_hooks', [])[:2])}
• Authority signals: {', '.join(hook_potential.get('authority_signals', [])[:2])}
• Social proof: {', '.join(hook_potential.get('social_proof', [])[:2])}

**FORMAT DE SORTIE JSON OBLIGATOIRE :**
{{
  "SEO_Title": "Titre consultant expert avec statistique choc",
  "article_type": "howto_data_driven",
  "commercial_philosophy": "consultant_with_exclusive_data",
  "tone": "expert_advisor_with_proof",
  "data_integration_score": "9/10",
  "statistics_used": [
    "Liste des statistiques des agent_response intégrées dans le plan"
  ],
  "expert_citations": [
    "Liste des insights d'experts utilisés"
  ],
  "benchmark_integrations": [
    "Liste des benchmarks exploités pour justifier les recommandations"
  ],
  "sections": [
    {{
      "section_title": "Titre avec donnée chiffrée exclusive",
      "opening_statistic": "Statistique d'ouverture tirée des agent_response",
      "data_sources_used": ["Source 1", "Source 2"],
      "content_approach": "data_first_then_value",
      "commercial_integration": "performance_justified|benchmark_supported|expert_recommended|trend_based",
      "micro_cta": "CTA basé sur résultats mesurés (3-5 mots)",
      "credibility_boosters_integrated": ["Booster 1", "Booster 2"],
      "reader_takeaway": "Apprentissage concret + preuve chiffrée de fonctionnement",
      "subsections": [
        {{
          "subsection_title": "Sous-section avec métrique de performance",
          "supporting_data": "Donnée agent_response qui supporte cette section",
          "content_focus": "informational_with_proof|commercial_with_benchmark"
        }}
      ]
    }}
  ],
  "cta_strategy": "performance_based_micro_ctas",
  "value_promise": "Méthode prouvée par X études + Y résultats mesurés",
  "commercial_mentions": [
    "Mentions justifiées par les performances et benchmarks exclusifs"
  ],
  "expertise_signals": [
    "Sources crédibles + Insights experts + Benchmarks exclusifs cités"
  ],
  "unique_selling_propositions": [
    "Points de différenciation basés sur les données exclusives"
  ],
  "conversion_optimization": {{
    "urgency_creators": ["Tendances futures qui créent l'urgence"],
    "social_proof_elements": ["Éléments de preuve sociale chiffrée"],
    "authority_elements": ["Sources et experts qui renforcent l'autorité"],
    "risk_mitigation": ["Éléments qui réduisent le risque perçu"]
  }}
}}

**IMPORTANT :** Réponds UNIQUEMENT en JSON valide. EXPLOIT AU MAXIMUM les données exclusives fournies dans agent_response."""

# === Classe de traitement asynchrone d'une requête (Simplifié) ===
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
        self.language_detector = LanguageDetector()
    
    async def select_best_angle(self, query_data: Dict) -> str:
        """Étape 1: Sélection du meilleur angle différenciant (multilingue)"""
        
        # Détection de la langue
        lang = self.language_detector.detect_language(query_data.get('text', ''))
        
        angles_list = "\n".join([f"{i+1}. {angle}" for i, angle in enumerate(query_data.get('differentiating_angles', []))])
        semantic_analysis = query_data.get('semantic_analysis', {})
        
        if lang == 'fr':
            prompt_selection = f"""Tu es un expert en stratégie de contenu SEO commercial. À partir de cette analyse sémantique SERP, choisis l'angle différenciant le PLUS PERTINENT pour créer un article unique qui se démarquera de la concurrence TOUT EN FAVORISANT LA CONVERSION COMMERCIALE.

**REQUÊTE CIBLE (OBLIGATOIRE) :** "{query_data.get('text', 'Sujet non défini')}"
⚠️ IMPORTANT : Tu DOIS absolument choisir l'angle qui correspond le mieux à cette requête exacte ET qui permet une intégration commerciale naturelle.

**ANGLES DIFFÉRENCIANTS DISPONIBLES :**
{angles_list}

**CONTEXTE CONCURRENTIEL :**
- Nombre de mots cible : {query_data.get('word_count', 0)}
- Clusters thématiques identifiés : {semantic_analysis.get('clusters_count', 0)}
- Entités identifiées : {semantic_analysis.get('entities', 0)}
- Relations trouvées : {semantic_analysis.get('relations_found', 0)}

**OBJECTIF COMMERCIAL :**
L'article doit avoir un ratio 60% informatif / 40% commercial avec des opportunités de conversion naturelles.

**DEMANDE :**
Choisis UN SEUL angle qui répond DIRECTEMENT à la requête "{query_data.get('text', 'Sujet non défini')}" ET qui permet une intégration commerciale fluide.
Format : "ANGLE CHOISI: [titre] - JUSTIFICATION: [explication en lien direct avec la requête cible] - POTENTIEL COMMERCIAL: [opportunités de conversion identifiées]"
"""
            system_content = "Tu es un expert en stratégie de contenu SEO commercial spécialisé dans la sélection d'angles différenciants orientés conversion."
        else:
            prompt_selection = f"""You are a commercial SEO content strategy expert. From this SERP semantic analysis, choose the MOST RELEVANT differentiating angle to create a unique article that will stand out from the competition WHILE FAVORING COMMERCIAL CONVERSION.

**TARGET QUERY (MANDATORY):** "{query_data.get('text', 'Undefined topic')}"
⚠️ IMPORTANT: You MUST choose the angle that best matches this exact query AND allows natural commercial integration.

**AVAILABLE DIFFERENTIATING ANGLES:**
{angles_list}

**COMPETITIVE CONTEXT:**
- Target word count: {query_data.get('word_count', 0)}
- Identified thematic clusters: {semantic_analysis.get('clusters_count', 0)}
- Identified entities: {semantic_analysis.get('entities', 0)}
- Found relations: {semantic_analysis.get('relations_found', 0)}

**COMMERCIAL OBJECTIVE:**
The article must have a 60% informational / 40% commercial ratio with natural conversion opportunities.

**REQUEST:**
Choose ONE angle that DIRECTLY answers the query "{query_data.get('text', 'Undefined topic')}" AND allows smooth commercial integration.
Format: "CHOSEN ANGLE: [title] - JUSTIFICATION: [explanation directly linked to target query] - COMMERCIAL POTENTIAL: [identified conversion opportunities]"
"""
            system_content = "You are a commercial SEO content strategy expert specialized in selecting conversion-oriented differentiating angles."
        
        messages = [
            SystemMessage(content=system_content),
            HumanMessage(content=prompt_selection)
        ]
        
        logging.info(f"🎯 [ID {self.query_id}] Sélection de l'angle différenciant commercial...")
        
        # Exécution asynchrone dans un thread pool
        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor(max_workers=1) as executor:
            response = await loop.run_in_executor(executor, self.llm.invoke, messages)
        
        selected_angle = response.content.strip()
        logging.info(f"✅ [ID {self.query_id}] Angle commercial sélectionné: {selected_angle[:100]}...")
        return selected_angle
    
    async def determine_schema_type(self, query_data: Dict, article_intent: str, selected_angle: str) -> str:
        """Étape 2: Détermination du schema principal via LLM (multilingue)"""
        
        # Détection de la langue
        lang = self.language_detector.detect_language(query_data.get('text', ''))
        
        if lang == 'fr':
            prompt_schema = f"""Tu es un expert en Schema.org et optimisation SEO commercial. Détermine le schema principal le plus approprié pour cet article à visée commerciale.

**REQUÊTE CIBLE :** "{query_data.get('text', 'Sujet non défini')}"
**TYPE D'ARTICLE :** {article_intent}
**ANGLE SÉLECTIONNÉ :** {selected_angle}

**SCHEMAS DISPONIBLES (Focus Commercial) :**
- HowTo : Pour guides étape par étape, tutoriels (idéal pour conversion)
- FAQPage : Pour pages questions-réponses
- Article : Pour articles génériques, actualités
- Product : Pour présentation de produits/services
- Organization : Pour présenter entreprises, services
- Course : Pour formations, cours en ligne

**INSTRUCTIONS :**
1. Analyse l'intention de la requête
2. Considère le type d'article détecté
3. Privilégie les schemas favorisant la conversion
4. Choisis LE schema le plus pertinent pour un article commercial
5. Justifie brièvement ton choix

**FORMAT DE RÉPONSE :**
Schema recommandé: [NOM_DU_SCHEMA]
Justification: [explication courte orientée conversion]
"""
            system_content = "Tu es un expert en Schema.org spécialisé dans l'optimisation SEO commerciale."
        else:
            prompt_schema = f"""You are a Schema.org and commercial SEO optimization expert. Determine the most appropriate main schema for this commercial-focused article.

**TARGET QUERY:** "{query_data.get('text', 'Undefined topic')}"
**ARTICLE TYPE:** {article_intent}
**SELECTED ANGLE:** {selected_angle}

**AVAILABLE SCHEMAS (Commercial Focus):**
- HowTo: For step-by-step guides, tutorials (ideal for conversion)
- FAQPage: For question-answer pages
- Article: For generic articles, news
- Product: For product/service presentations
- Organization: For presenting companies, services
- Course: For training, online courses

**INSTRUCTIONS:**
1. Analyze the query intent
2. Consider the detected article type
3. Prioritize schemas that favor conversion
4. Choose THE most relevant schema for a commercial article
5. Briefly justify your choice

**RESPONSE FORMAT:**
Recommended schema: [SCHEMA_NAME]
Justification: [brief conversion-oriented explanation]
"""
            system_content = "You are a Schema.org expert specialized in commercial SEO optimization."
        
        messages = [
            SystemMessage(content=system_content),
            HumanMessage(content=prompt_schema)
        ]
        
        logging.info(f"🏷️ [ID {self.query_id}] Détermination du schema principal commercial...")
        
        # Exécution asynchrone dans un thread pool
        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor(max_workers=1) as executor:
            response = await loop.run_in_executor(executor, self.llm.invoke, messages)
        
        # Extraction du schema depuis la réponse
        response_content = response.content.strip()
        schema_type = self._extract_schema_from_response(response_content)
        
        logging.info(f"✅ [ID {self.query_id}] Schema commercial déterminé: {schema_type}")
        return schema_type
    
    def _extract_schema_from_response(self, response: str) -> str:
        """Extrait le nom du schema depuis la réponse du LLM"""
        # Recherche du pattern "Schema recommandé: [SCHEMA]" ou "Recommended schema: [SCHEMA]"
        import re
        
        schema_match = re.search(r'(?:Schema recommandé|Recommended schema):\s*([A-Za-z]+)', response)
        if schema_match:
            return schema_match.group(1)
        
        # Fallback: recherche de schemas connus dans le texte
        known_schemas = ['HowTo', 'FAQPage', 'Product', 'Article', 'Organization', 'Course']
        for schema in known_schemas:
            if schema.lower() in response.lower():
                return schema
        
        # Fallback final
        return 'Article'
    
    async def generate_article_plan(self, query_data: Dict, selected_angle: str, consigne_data: Dict, schema_type: str) -> Dict:
        """Étape 3: Génération du plan d'article commercial (multilingue)"""
        
        # 1. Analyse du type d'article optimal
        query_text = query_data.get('text', '')
        article_intent = self.article_analyzer.analyze_query_intent(query_text)
        article_config = self.article_analyzer.get_article_type_config(article_intent)
        
        # Détection de la langue
        lang = self.language_detector.detect_language(query_text)
        
        logging.info(f"🎯 [ID {self.query_id}] Type d'article détecté: {article_intent}")
        logging.info(f"📋 [ID {self.query_id}] Template: {article_config['template']}")
        logging.info(f"🌐 [ID {self.query_id}] Langue: {lang.upper()}")
        logging.info(f"💰 [ID {self.query_id}] Ratio commercial: {article_config['commercial_ratio']*100}%")
        
        # 2. Récupération du highlight depuis consigne_data
        highlight_url = consigne_data.get('highlight', '')
        
        # 3. Génération du prompt spécialisé commercial (multilingue)
        specialized_prompt = self.plan_generator.get_template_prompt(
            article_intent, query_data, selected_angle, highlight_url
        )
        
        # 4. Format de sortie selon la langue
        if lang == 'fr':
            integration_text = "Description de l'intégration naturelle du lien"
            anchor_text = "Texte d'ancrage suggéré pour le lien"
            language_instruction = "Langue de réponse: Français"
            commercial_note = "Note commerciale: Intégrer naturellement des opportunités de conversion"
        else:
            integration_text = "Description of how to naturally integrate the link"
            anchor_text = "Suggested anchor text for the link"
            language_instruction = "Response language: English"
            commercial_note = "Commercial note: Naturally integrate conversion opportunities"
        
        system_message_content = f"""Your objective: Create a specialized {article_intent.upper()} article outline with commercial focus (60% informational / 40% commercial).

Expected output format:
{{
  "SEO Title": "",
  "article_type": "{article_intent}",
  "schema_type": "{schema_type}",
  "commercial_ratio": {article_config['commercial_ratio']},
  "informational_ratio": {article_config['informational_ratio']},
  "introduction_notes": {{
    "highlight_integration": "{integration_text}",
    "suggested_anchor_text": "{anchor_text}",
    "commercial_hook": "Description of commercial integration in intro"
  }},
  "sections": [
    {{
      "section_title": "",
      "content_type": "informational|commercial",
      "commercial_integration": "none|subtle|direct",
      "subsections": [
        {{ 
          "subsection_title": "",
          "content_focus": "informational|commercial"
        }}
      ]
    }}
  ],
  "conclusion": "",
  "call_to_action": {{
    "cta_title": "Titre du CTA",
    "cta_description": "Description persuasive du CTA",
    "conversion_goal": "Objectif de conversion"
  }},
  "article_config": {{
    "template": "{article_config['template']}",
    "structure_emphasis": "{article_config['structure_emphasis']}",
    "commercial_sections": ["liste des sections commerciales"],
    "conversion_points": ["points de conversion identifiés"]
  }}
}}

Article Type Guidelines:
- {article_intent}: {article_config['structure_emphasis']}
- Required sections: {', '.join(article_config['required_sections'])}
- Commercial ratio: {article_config['commercial_ratio']*100}%
- Organization: General to Specific with commercial integration

Restrictions:
• Propose only titles and subtitles
• Clearly mark commercial vs informational sections
• Include natural conversion opportunities
• No additional textual content
{language_instruction}
{commercial_note}"""

        messages = [
            SystemMessage(content=system_message_content),
            HumanMessage(content=specialized_prompt)
        ]
        
        logging.info(f"🏗️ [ID {self.query_id}] Génération du plan commercial {article_intent}...")
        
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
            
            # Validation du plan commercial
            validated_plan = self._validate_commercial_plan(plan_json, article_config, query_data, schema_type)
            
            logging.info(f"✅ [ID {self.query_id}] Plan commercial {article_intent} généré")
            return validated_plan
            
        except json.JSONDecodeError as e:
            logging.error(f"❌ [ID {self.query_id}] Erreur de parsing JSON: {e}")
            logging.error(f"Contenu reçu: {response.content}")
            
            # Fallback: structure basique commerciale
            fallback_plan = self._create_commercial_fallback_plan(query_data, article_intent, article_config, highlight_url, schema_type)
            return fallback_plan
    
    def _validate_commercial_plan(self, plan_json: Dict, article_config: Dict, query_data: Dict, schema_type: str) -> Dict:
        """Valide le plan généré avec focus commercial"""
        validated_plan = plan_json.copy()
        
        # S'assurer que les champs obligatoires sont présents
        if 'article_type' not in validated_plan:
            validated_plan['article_type'] = article_config.get('template', 'definitional')
        
        if 'schema_type' not in validated_plan:
            validated_plan['schema_type'] = schema_type
        
        # Ajouter les ratios commerciaux
        if 'commercial_ratio' not in validated_plan:
            validated_plan['commercial_ratio'] = article_config['commercial_ratio']
        
        if 'informational_ratio' not in validated_plan:
            validated_plan['informational_ratio'] = article_config['informational_ratio']
        
        # Valider les sections commerciales
        sections = validated_plan.get('sections', [])
        commercial_count = sum(1 for section in sections if section.get('content_type') == 'commercial')
        total_sections = len(sections)
        
        if total_sections > 0:
            actual_commercial_ratio = commercial_count / total_sections
            validated_plan['calculated_commercial_ratio'] = actual_commercial_ratio
            
            # Avertissement si le ratio n'est pas respecté
            if abs(actual_commercial_ratio - article_config['commercial_ratio']) > 0.1:
                logging.warning(f"⚠️ [ID {self.query_id}] Ratio commercial calculé ({actual_commercial_ratio:.1%}) diffère du cible ({article_config['commercial_ratio']:.1%})")
        
        return validated_plan
    
    def _create_commercial_fallback_plan(self, query_data: Dict, article_intent: str, article_config: Dict, highlight_url: str, schema_type: str) -> Dict:
        """Crée un plan de fallback commercial en cas d'erreur (multilingue)"""
        # Détection de la langue
        lang = self.language_detector.detect_language(query_data.get('text', ''))
        
        if lang == 'fr':
            return {
                "SEO Title": f"Guide {query_data.get('text', 'sujet')} - Plan commercial généré automatiquement",
                "article_type": article_intent,
                "schema_type": schema_type,
                "commercial_ratio": article_config['commercial_ratio'],
                "informational_ratio": article_config['informational_ratio'],
                "introduction_notes": {
                    "highlight_integration": f"Intégrer naturellement le lien {highlight_url} dans le contexte",
                    "suggested_anchor_text": "découvrez notre solution",
                    "commercial_hook": "Accroche commerciale subtile en introduction"
                },
                "sections": [
                    {
                        "section_title": "Vue d'ensemble (Général)",
                        "content_type": "informational",
                        "commercial_integration": "none",
                        "subsections": [
                            {"subsection_title": "Contexte et enjeux", "content_focus": "informational"},
                            {"subsection_title": "Importance du sujet", "content_focus": "informational"}
                        ]
                    },
                    {
                        "section_title": "Analyse détaillée (Spécifique)",
                        "content_type": "informational",
                        "commercial_integration": "subtle",
                        "subsections": [
                            {"subsection_title": "Aspects techniques", "content_focus": "informational"},
                            {"subsection_title": "Bonnes pratiques", "content_focus": "informational"}
                        ]
                    },
                    {
                        "section_title": "Solutions et recommandations",
                        "content_type": "commercial",
                        "commercial_integration": "direct",
                        "subsections": [
                            {"subsection_title": "Outils recommandés", "content_focus": "commercial"},
                            {"subsection_title": "Services professionnels", "content_focus": "commercial"}
                        ]
                    }
                ],
                "conclusion": "Récapitulatif et transition vers l'action",
                "call_to_action": {
                    "cta_title": "Passez à l'action dès maintenant",
                    "cta_description": "Découvrez comment notre solution peut vous aider",
                    "conversion_goal": "Génération de leads"
                },
                "article_config": {
                    "template": article_config['template'],
                    "structure_emphasis": article_config['structure_emphasis'],
                    "commercial_sections": ["Solutions et recommandations"],
                    "conversion_points": ["CTA final", "Recommandations outils"]
                }
            }
        else:
            return {
                "SEO Title": f"{query_data.get('text', 'topic')} Guide - Automatically Generated Commercial Plan",
                "article_type": article_intent,
                "schema_type": schema_type,
                "commercial_ratio": article_config['commercial_ratio'],
                "informational_ratio": article_config['informational_ratio'],
                "introduction_notes": {
                    "highlight_integration": f"Naturally integrate the link {highlight_url} in context",
                    "suggested_anchor_text": "discover our solution",
                    "commercial_hook": "Subtle commercial hook in introduction"
                },
                "sections": [
                    {
                        "section_title": "Overview (General)",
                        "content_type": "informational",
                        "commercial_integration": "none",
                        "subsections": [
                            {"subsection_title": "Context and challenges", "content_focus": "informational"},
                            {"subsection_title": "Topic importance", "content_focus": "informational"}
                        ]
                    },
                    {
                        "section_title": "Detailed Analysis (Specific)",
                        "content_type": "informational",
                        "commercial_integration": "subtle",
                        "subsections": [
                            {"subsection_title": "Technical aspects", "content_focus": "informational"},
                            {"subsection_title": "Best practices", "content_focus": "informational"}
                        ]
                    },
                    {
                        "section_title": "Solutions and Recommendations",
                        "content_type": "commercial",
                        "commercial_integration": "direct",
                        "subsections": [
                            {"subsection_title": "Recommended tools", "content_focus": "commercial"},
                            {"subsection_title": "Professional services", "content_focus": "commercial"}
                        ]
                    }
                ],
                "conclusion": "Summary and transition to action",
                "call_to_action": {
                    "cta_title": "Take Action Now",
                    "cta_description": "Discover how our solution can help you",
                    "conversion_goal": "Lead generation"
                },
                "article_config": {
                    "template": article_config['template'],
                    "structure_emphasis": article_config['structure_emphasis'],
                    "commercial_sections": ["Solutions and Recommendations"],
                    "conversion_points": ["Final CTA", "Tool recommendations"]
                }
            }
    
    async def process_query(self, query_data: Dict, consigne_data: Dict) -> Dict:
        """Traite une requête complète avec workflow commercial simplifié"""
        try:
            logging.info(f"🚀 [ID {self.query_id}] Début du traitement commercial: '{query_data.get('text')}'")
            
            # Vérifier si la requête a les données nécessaires
            if not all([query_data.get('differentiating_angles'), 
                       query_data.get('semantic_analysis')]):
                logging.error(f"❌ [ID {self.query_id}] Données sémantiques incomplètes")
                return {'status': 'failed', 'error': f'Données sémantiques incomplètes pour ID {self.query_id}'}
            
            # WORKFLOW COMMERCIAL SIMPLIFIÉ:
            
            # Étape 1: Sélection d'angle commercial
            selected_angle = await self.select_best_angle(query_data)
            
            # Étape 2: Détermination du schema principal commercial
            query_text = query_data.get('text', '')
            article_intent = self.article_analyzer.analyze_query_intent(query_text)
            schema_type = await self.determine_schema_type(query_data, article_intent, selected_angle)
            
            # Étape 3: Génération du plan commercial
            article_plan = await self.generate_article_plan(
                query_data, 
                selected_angle,
                consigne_data,
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

# === Gestionnaire de traitement en lot parallélisé (Adapté Commercial) ===
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
        
        logging.info(f"✅ [ID {query.get('id')}] Données sémantiques et temporaires supprimées après génération du plan commercial")
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
                    logging.info(f"🔄 [ID {query.get('id')}] Plan commercial déjà généré - ignoré")
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
                    
                    # 2. Mise à jour des requêtes avec les résultats commerciaux
                    results_by_id = {r['query_id']: r for r in results if r.get('status') == 'success'}
                    updated_count = 0
                    
                    for i, query in enumerate(current_data.get('queries', [])):
                        query_id = query.get('id')
                        if query_id in results_by_id:
                            result = results_by_id[query_id]
                            
                            # Mise à jour avec validation des données commerciales
                            if result.get('selected_angle') and result.get('article_plan'):
                                query['selected_differentiating_angle'] = result['selected_angle']
                                query['generated_article_plan'] = result['article_plan']
                                query['plan_generation_status'] = 'completed'
                                query['last_updated'] = result.get('timestamp', 'unknown')
                                
                                # Extraction des métriques du plan commercial
                                plan = result['article_plan']
                                query['article_type'] = plan.get('article_type', 'definitional')
                                query['commercial_optimization'] = plan.get('commercial_optimization', {})
                                query['commercial_ratio'] = plan.get('commercial_ratio', 0.4)
                                
                                # SUPPRESSION DES DONNÉES SÉMANTIQUES APRÈS GÉNÉRATION DU PLAN
                                current_data['queries'][i] = self.clean_semantic_data(query)
                                
                                updated_count += 1
                                commercial_ratio = plan.get('commercial_ratio', 0) * 100
                                logging.info(f"✅ [ID {query_id}] Plan commercial {plan.get('article_type', 'definitional')} ajouté ({commercial_ratio:.0f}% commercial)")
                            else:
                                logging.warning(f"⚠️ [ID {query_id}] Données commerciales incomplètes, ignoré")
                    
                    if updated_count == 0:
                        logging.warning("⚠️ Aucune donnée commerciale valide à sauvegarder")
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
                    
                    logging.info(f"✅ Sauvegarde atomique commerciale terminée avec succès")
                    logging.info(f"📈 {updated_count} requêtes mises à jour avec plans commerciaux")
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
                
                logging.error(f"❌ Erreur dans la sauvegarde atomique commerciale: {e}")
                logging.error(f"📁 Chemin: {CONSIGNE_FILE}")
                logging.error(f"📁 Dossier parent existe: {os.path.exists(os.path.dirname(CONSIGNE_FILE))}")
                logging.error(f"📁 Fichier original existe: {os.path.exists(CONSIGNE_FILE)}")
                raise
        
        # Exécution de la sauvegarde dans un thread pour éviter de bloquer l'event loop
        try:
            loop = asyncio.get_event_loop()
            success = await loop.run_in_executor(None, _atomic_save)
            
            if success:
                logging.info("🎉 Sauvegarde commerciale thread-safe complétée avec succès")
            else:
                raise Exception("La sauvegarde commerciale a échoué")
                
        except Exception as e:
            logging.error(f"❌ Erreur lors de la sauvegarde commerciale thread-safe: {e}")
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
            logging.error(f"💥 Erreur lors du traitement commercial de la requête ID {query_id}: {e}")
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
            
            logging.info(f"🚀 Traitement parallèle commercial de {len(processable_queries)} requêtes")
            
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
            
            logging.info(f"🎉 Traitement parallèle commercial terminé - Succès: {len(successful)}, Échecs: {len(failed)}")
            
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
            logging.error(f"💥 Erreur lors du traitement commercial en lot: {e}")
            return {
                'error': str(e),
                'status': 'failed'
            }
    
    def display_single_query_summary(self, query_id: int, query_text: str, selected_angle: str, 
                                   article_plan: Dict) -> None:
        """Affiche un résumé pour une requête individuelle avec focus commercial"""
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
        
        # Affichage de l'intégration du highlight
        intro_notes = article_plan.get('introduction_notes', {})
        if intro_notes:
            print(f"\n   🔗 INTÉGRATION COMMERCIALE:")
            print(f"      • Stratégie lien: {intro_notes.get('highlight_integration', 'Non définie')[:50]}...")
            print(f"      • Ancre suggérée: {intro_notes.get('suggested_anchor_text', 'Non définie')}")
            print(f"      • Hook commercial: {intro_notes.get('commercial_hook', 'Non défini')[:50]}...")
        
        # Affichage des sections avec focus commercial
        sections = article_plan.get('sections', [])
        print(f"\n   📊 SECTIONS AVEC FOCUS COMMERCIAL: {len(sections)}")
        
        commercial_sections = 0
        for i, section in enumerate(sections, 1):
            title = section.get('section_title', 'Titre non défini')
            content_type = section.get('content_type', 'informational')
            commercial_integration = section.get('commercial_integration', 'none')
            
            if content_type == 'commercial':
                commercial_sections += 1
                commercial_info = f" [💰 COMMERCIAL - {commercial_integration.upper()}]"
            else:
                commercial_info = f" [📖 Informatif - {commercial_integration}]"
            
            print(f"      {i}. {title[:35]}{'...' if len(title) > 35 else ''}{commercial_info}")
            
            if i == 3 and len(sections) > 3:
                print(f"      ... et {len(sections) - 3} autres sections")
                break
        
        # Affichage du CTA
        cta = article_plan.get('call_to_action', {})
        if cta:
            print(f"\n   🎯 CALL-TO-ACTION:")
            print(f"      • Titre: {cta.get('cta_title', 'Non défini')}")
            print(f"      • Objectif: {cta.get('conversion_goal', 'Non défini')}")
        
        # Affichage des métriques commerciales
        commercial_opt = article_plan.get('commercial_optimization', {})
        if commercial_opt:
            print(f"\n   💼 OPTIMISATION COMMERCIALE:")
            print(f"      • Taux de conversion cible: {commercial_opt.get('target_conversion_rate', 0)*100:.0f}%")
            print(f"      • Points de conversion: {commercial_opt.get('conversion_points', 0)}")
            print(f"      • Sections commerciales: {len(commercial_opt.get('commercial_sections', []))}")
            print(f"      • CTA inclus: {'✅' if commercial_opt.get('cta_included') else '❌'}")
        
        print(f"\n💾 ✅ Sauvegardé avec optimisations commerciales")
        print("="*70 + "\n")
    
    def display_batch_summary(self, successful: List[Dict], failed: List[Dict], total: int) -> None:
        """Affiche un résumé du traitement en lot commercial"""
        print("\n" + "="*85)
        print("           RÉSUMÉ DU TRAITEMENT EN LOT - PLANS COMMERCIAUX OPTIMISÉS")
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
            
            print(f"\n📊 TYPES D'ARTICLES COMMERCIAUX GÉNÉRÉS:")
            for article_type, count in article_types.items():
                print(f"   • {article_type}: {count} articles")
            
            print(f"\n🏷️ SCHEMAS COMMERCIAUX UTILISÉS:")
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
            for result in failed:
                query_id = result.get('query_id', 'Unknown')
                error = result.get('error', 'Erreur inconnue')
                print(f"   • ID {query_id}: {error[:50]}{'...' if len(error) > 50 else ''}")
        
        print(f"\n💾 SAUVEGARDE:")
        print(f"   ✅ Fichier consigne.json mis à jour")
        print(f"   ✅ Nouvelles clés ajoutées pour chaque requête traitée:")
        print(f"      - selected_differentiating_angle")
        print(f"      - generated_article_plan (avec focus commercial)")
        print(f"      - article_type (howto, comparative, definitional)")
        print(f"      - schema_type (HowTo, FAQPage, Article, etc.)")
        print(f"      - commercial_optimization (métriques commerciales)")
        print(f"      - commercial_ratio (40% par défaut)")
        print(f"      - plan_generation_status")
        
        print("\n✨ FONCTIONNALITÉS COMMERCIALES:")
        print(f"   • Focus commercial 60% informatif / 40% commercial")
        print(f"   • 3 types d'articles optimisés: HowTo, Comparative, Definitional")
        print(f"   • Structure du général au spécifique avec intégration commerciale")
        print(f"   • Call-to-Action intégré dans chaque plan")
        print(f"   • Sections commerciales clairement identifiées")
        print(f"   • Opportunités de conversion naturelles")
        
        print("\n🔧 WORKFLOW COMMERCIAL OPTIMISÉ:")
        print(f"   1. Détection automatique de la langue (FR/EN)")
        print(f"   2. Sélection d'angle avec potentiel commercial")
        print(f"   3. Détermination du schema orienté conversion")
        print(f"   4. Génération du plan avec ratio commercial respecté")
        print(f"   5. Intégration de CTA et points de conversion")
        
        print("\n⚡ GAIN DE TEMPS:")
        estimated_sequential_time = total * 35  # 35s par requête simplifiée
        estimated_parallel_time = max(12, total * 35 / MAX_CONCURRENT_LLM)  # En parallèle
        time_saved = estimated_sequential_time - estimated_parallel_time
        print(f"   • Temps estimé séquentiel: {estimated_sequential_time//60}min {estimated_sequential_time%60}s")
        print(f"   • Temps parallélisé: {estimated_parallel_time//60}min {estimated_parallel_time%60}s")
        print(f"   • Gain de temps: ~{time_saved//60}min {time_saved%60}s")
        
        print("\n" + "="*85)
        print("Traitement en lot commercial avec plans optimisés conversion terminé !")
        print("="*85 + "\n")

# === Fonctions principales asynchrones ===
async def main_single_query_async(query_id: int):
    """Traite une seule requête par son ID (async)"""
    try:
        generator = ParallelConsignePlanGenerator()
        result = await generator.process_single_query(query_id)
        
        if result['status'] == 'success':
            article_type = result.get('article_plan', {}).get('article_type', 'definitional')
            commercial_ratio = result.get('article_plan', {}).get('commercial_ratio', 0.4) * 100
            print(f"🎉 Plan commercial {article_type} ({commercial_ratio:.0f}% commercial) généré pour requête ID {query_id}!")
            return True
        else:
            print(f"❌ Erreur: {result.get('error', 'Erreur inconnue')}")
            return False
            
    except KeyboardInterrupt:
        print("\n⚠️ Génération commerciale interrompue par l'utilisateur")
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
            print(f"🎉 Traitement parallélisé commercial terminé! {result.get('successful', 0)} requêtes traitées.")
            return True
        else:
            print(f"❌ Erreur: {result.get('error', 'Erreur inconnue')}")
            return False
            
    except KeyboardInterrupt:
        print("\n⚠️ Génération commerciale interrompue par l'utilisateur")
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
    
    print("🚀 Générateur de Plans d'Articles SEO Commerciaux Optimisés")
    print("="*85)
    print(f"📁 Dossier de travail: {BASE_DIR}")
    if CONSIGNE_FILE:
        print(f"📁 Fichier consigne: {os.path.basename(CONSIGNE_FILE)}")
        print(f"📁 Fichier existe: {os.path.exists(CONSIGNE_FILE)}")
    else:
        print("📁 Fichier consigne: ❌ Non trouvé")
    print("="*85)
    print("✨ FONCTIONNALITÉS COMMERCIALES:")
    print("   • 3 types d'articles optimisés: HowTo, Comparative, Definitional")
    print("   • Ratio fixe: 60% informatif / 40% commercial")
    print("   • Structure du général au spécifique avec intégration commerciale")
    print("   • Call-to-Action automatique dans chaque plan")
    print("   • Support multilingue FR/EN avec adaptation commerciale")
    print("   • Sections commerciales clairement identifiées")
    print("="*85)
    print("📚 INSTALLATION REQUISE:")
    print("   • pip install langdetect")
    print("   • Variables d'environnement: OPENAI_API_KEY")
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
        print(f"Mode: Traitement parallélisé commercial de toutes les requêtes ({MAX_CONCURRENT_LLM} simultanées)")
        return main_all_queries()

# === Point d'entrée ===
if __name__ == "__main__":
    # Configuration pour Windows
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    
    success = main()
    exit(0 if success else 1)