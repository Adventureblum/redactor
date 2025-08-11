import os
import json
import logging
import asyncio
from typing import Dict
from langchain_openai import ChatOpenAI
from langchain.schema import SystemMessage, HumanMessage
from langdetect import detect

# Configuration
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

api_key = os.getenv('OPENAI_API_KEY')
if not api_key:
    raise ValueError("OPENAI_API_KEY non trouvée dans les variables d'environnement")

class PlanGeneratorAgent:
    """Agent spécialisé dans la génération de plans d'articles commerciaux data-driven"""
    
    def __init__(self, query_id: int):
        self.query_id = query_id
        self.llm = ChatOpenAI(
            model="gpt-4o",
            temperature=0.7,
            api_key=api_key
        )
    
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
    
    def format_base_data(self, query_data: Dict, lang: str) -> Dict:
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
        nb_sections = plan_info.get(dev_key, {}).get(sections_key, 3)
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
    
    def get_data_driven_prompt(self, query_data: Dict, selected_angle: str, highlight_url: str, base_data: Dict) -> str:
        """Génère le prompt data-driven complet (prompt hardcodé)"""
        
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
    
    def get_system_message(self, article_intent: str, schema_type: str, commercial_ratio: float, informational_ratio: float, lang: str) -> str:
        """Génère le message système selon les paramètres"""
        
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
        
        return f"""Your objective: Create a specialized {article_intent.upper()} article outline with commercial focus (60% informational / 40% commercial).

Expected output format:
{{
  "SEO Title": "",
  "article_type": "{article_intent}",
  "schema_type": "{schema_type}",
  "commercial_ratio": {commercial_ratio},
  "informational_ratio": {informational_ratio},
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
    "template": "guide_step_by_step",
    "structure_emphasis": "sequential_steps_with_conversion",
    "commercial_sections": ["liste des sections commerciales"],
    "conversion_points": ["points de conversion identifiés"]
  }}
}}

Article Type Guidelines:
- {article_intent}: sequential_steps_with_conversion
- Required sections: introduction, prerequisites, steps, commercial_integration, conclusion, cta
- Commercial ratio: {commercial_ratio*100}%
- Organization: General to Specific with commercial integration

Restrictions:
• Propose only titles and subtitles
• Clearly mark commercial vs informational sections
• Include natural conversion opportunities
• No additional textual content
{language_instruction}
{commercial_note}"""
    
    def validate_commercial_plan(self, plan_json: Dict, commercial_ratio: float, query_data: Dict, schema_type: str) -> Dict:
        """Valide le plan généré avec focus commercial"""
        validated_plan = plan_json.copy()
        
        # S'assurer que les champs obligatoires sont présents
        if 'article_type' not in validated_plan:
            validated_plan['article_type'] = 'howto_data_driven'
        
        if 'schema_type' not in validated_plan:
            validated_plan['schema_type'] = schema_type
        
        # Ajouter les ratios commerciaux
        if 'commercial_ratio' not in validated_plan:
            validated_plan['commercial_ratio'] = commercial_ratio
        
        if 'informational_ratio' not in validated_plan:
            validated_plan['informational_ratio'] = 1 - commercial_ratio
        
        # Valider les sections commerciales
        sections = validated_plan.get('sections', [])
        commercial_count = sum(1 for section in sections if section.get('content_type') == 'commercial')
        total_sections = len(sections)
        
        if total_sections > 0:
            actual_commercial_ratio = commercial_count / total_sections
            validated_plan['calculated_commercial_ratio'] = actual_commercial_ratio
            
            # Avertissement si le ratio n'est pas respecté
            if abs(actual_commercial_ratio - commercial_ratio) > 0.1:
                logging.warning(f"⚠️ [ID {self.query_id}] Ratio commercial calculé ({actual_commercial_ratio:.1%}) diffère du cible ({commercial_ratio:.1%})")
        
        return validated_plan
    
    def create_commercial_fallback_plan(self, query_data: Dict, article_intent: str, highlight_url: str, schema_type: str, lang: str) -> Dict:
        """Crée un plan de fallback commercial en cas d'erreur"""
        
        commercial_ratio = 0.4
        
        if lang == 'fr':
            return {
                "SEO Title": f"Guide {query_data.get('text', 'sujet')} - Plan commercial généré automatiquement",
                "article_type": article_intent,
                "schema_type": schema_type,
                "commercial_ratio": commercial_ratio,
                "informational_ratio": 1 - commercial_ratio,
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
                    "template": "guide_step_by_step",
                    "structure_emphasis": "sequential_steps_with_conversion",
                    "commercial_sections": ["Solutions et recommandations"],
                    "conversion_points": ["CTA final", "Recommandations outils"]
                }
            }
        else:
            return {
                "SEO Title": f"{query_data.get('text', 'topic')} Guide - Automatically Generated Commercial Plan",
                "article_type": article_intent,
                "schema_type": schema_type,
                "commercial_ratio": commercial_ratio,
                "informational_ratio": 1 - commercial_ratio,
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
                    "template": "guide_step_by_step",
                    "structure_emphasis": "sequential_steps_with_conversion",
                    "commercial_sections": ["Solutions and Recommendations"],
                    "conversion_points": ["Final CTA", "Tool recommendations"]
                }
            }
    
    async def generate_plan(self, query_data: Dict, selected_angle: str, highlight_url: str, article_intent: str, schema_type: str) -> Dict:
        """Génère le plan d'article commercial complet"""
        
        # Détection de la langue
        lang = self.detect_language(query_data.get('text', ''))
        logging.info(f"🌐 [ID {self.query_id}] Langue détectée: {lang.upper()}")
        
        # Configuration commerciale
        commercial_ratio = 0.4
        informational_ratio = 0.6
        
        # Formatage des données de base
        base_data = self.format_base_data(query_data, lang)
        
        # Génération du prompt data-driven
        data_driven_prompt = self.get_data_driven_prompt(query_data, selected_angle, highlight_url, base_data)
        
        # Message système
        system_message = self.get_system_message(article_intent, schema_type, commercial_ratio, informational_ratio, lang)
        
        messages = [
            SystemMessage(content=system_message),
            HumanMessage(content=data_driven_prompt)
        ]
        
        logging.info(f"🏗️ [ID {self.query_id}] Génération du plan commercial {article_intent}...")
        
        # Appel à OpenAI
        response = await asyncio.get_event_loop().run_in_executor(
            None, self.llm.invoke, messages
        )
        
        try:
            # Tentative de parsing du JSON
            plan_content = response.content.strip()
            
            # Nettoyage du contenu si nécessaire
            if plan_content.startswith('```json'):
                plan_content = plan_content.replace('```json', '').replace('```', '').strip()
            
            plan_json = json.loads(plan_content)
            
            # Validation du plan commercial
            validated_plan = self.validate_commercial_plan(plan_json, commercial_ratio, query_data, schema_type)
            
            logging.info(f"✅ [ID {self.query_id}] Plan commercial {article_intent} généré")
            return validated_plan
            
        except json.JSONDecodeError as e:
            logging.error(f"❌ [ID {self.query_id}] Erreur de parsing JSON: {e}")
            logging.error(f"Contenu reçu: {response.content}")
            
            # Fallback: structure basique commerciale
            fallback_plan = self.create_commercial_fallback_plan(query_data, article_intent, highlight_url, schema_type, lang)
            return fallback_plan

# Fonction principale pour tester l'agent
async def main():
    """Fonction de test"""
    # Exemple de données de test
    test_query_data = {
        'id': 1,
        'text': 'comment optimiser son référencement naturel',
        'word_count': 2000,
        'top_keywords': 'SEO, référencement, optimisation, Google, SERP',
        'plan': {
            'introduction': {'longueur': 300},
            'developpement': {'nombre_sections': 4, 'mots_par_section': 400},
            'conclusion': {'longueur': 200}
        },
        'agent_response': {
            'shock_stats': [
                {'statistic': '75% des sites web ne dépassent jamais la première page Google', 'source_credibility': 'Étude SEMrush 2024'},
                {'statistic': 'Le SEO génère 1000% plus de trafic que les réseaux sociaux', 'source_credibility': 'BrightEdge Research'}
            ],
            'expert_insights': [
                {'insight': 'Le contenu de qualité reste le facteur #1 du classement Google', 'authority_source': 'John Mueller, Google'},
                {'insight': 'Les sites optimisés techniquement ont 53% plus de chances de ranker', 'authority_source': 'Moz State of SEO'}
            ],
            'benchmark_data': [
                {'metric': 'Temps de chargement moyen des top 10 : 1.65s', 'sample_size': '1M de sites analysés'},
                {'metric': 'Taux de clic position 1 : 28.5%', 'sample_size': 'Données Google Analytics'}
            ],
            'market_trends': [
                {'trend': 'Croissance du mobile-first indexing : +40% en 2024', 'future_projection': '+60% en 2025'},
                {'trend': 'Importance croissante de Core Web Vitals', 'future_projection': 'Facteur critique en 2025'}
            ],
            'competitive_landscape': [
                {'comparison_point': 'Sites avec blog vs sans blog', 'quantified_difference': '+434% de pages indexées'},
                {'comparison_point': 'SEO technique vs contenu seul', 'quantified_difference': '+67% de trafic organique'}
            ],
            'sources': [
                {'title': 'Google Search Quality Guidelines', 'source_type': 'Documentation officielle', 'publication_date': '2024'},
                {'title': 'State of SEO Report', 'source_type': 'Étude sectorielle', 'publication_date': '2024'}
            ],
            'credibility_boosters': [
                'Certifié Google Analytics & Search Console',
                '500+ audits SEO réalisés',
                'Consultant SEO depuis 2018'
            ],
            'content_angles': [
                'Approche technique pour développeurs',
                'Stratégie SEO pour e-commerce',
                'SEO local pour PME'
            ],
            'hook_potential': {
                'intro_hooks': ['Statistique choquante sur l\'échec SEO', 'Révélation d\'algorithme Google'],
                'authority_signals': ['Citation John Mueller', 'Données exclusives Google'],
                'social_proof': ['Résultats clients', 'Certifications officielles']
            }
        }
    }
    
    selected_angle = 'Guide SEO technique pour développeurs avec focus ROI commercial'
    highlight_url = 'https://example.com/seo-audit-complet'
    article_intent = 'howto'
    schema_type = 'HowTo'
    
    # Test de l'agent
    agent = PlanGeneratorAgent(query_id=1)
    plan = await agent.generate_plan(test_query_data, selected_angle, highlight_url, article_intent, schema_type)
    
    print(f"Plan généré:")
    print(json.dumps(plan, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    asyncio.run(main())