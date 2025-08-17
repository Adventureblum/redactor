import os
import json
import logging
import asyncio
import re
from typing import Dict
from langchain_openai import ChatOpenAI
from langchain.schema import SystemMessage, HumanMessage
from langdetect import detect

# Configuration
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

api_key = os.getenv('OPENAI_API_KEY')
if not api_key:
    raise ValueError("OPENAI_API_KEY non trouvée dans les variables d'environnement")

class SchemaDetectorAgent:
    """Agent spécialisé dans la détermination du schéma Schema.org optimal"""
    
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
    
    def get_schema_detection_prompt(self, query_data: Dict, article_intent: str, selected_angle: str, lang: str) -> str:
        """Génère le prompt de détection de schéma selon la langue"""
        
        if lang == 'fr':
            return f"""Tu es un expert en Schema.org et optimisation SEO commercial. Détermine le schema principal le plus approprié pour cet article à visée commerciale.

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
        else:
            return f"""You are a Schema.org and commercial SEO optimization expert. Determine the most appropriate main schema for this commercial-focused article.

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
    
    def get_system_message(self, lang: str) -> str:
        """Retourne le message système selon la langue"""
        if lang == 'fr':
            return "Tu es un expert en Schema.org spécialisé dans l'optimisation SEO commerciale."
        else:
            return "You are a Schema.org expert specialized in commercial SEO optimization."
    
    def extract_schema_from_response(self, response: str) -> str:
        """Extrait le nom du schema depuis la réponse du LLM"""
        # Recherche du pattern "Schema recommandé: [SCHEMA]" ou "Recommended schema: [SCHEMA]"
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
    
    async def determine_schema(self, query_data: Dict, article_intent: str, selected_angle: str) -> str:
        """Détermine le schéma Schema.org optimal pour l'article"""
        
        # Détection de la langue
        lang = self.detect_language(query_data.get('text', ''))
        logging.info(f"🌐 [ID {self.query_id}] Langue détectée: {lang.upper()}")
        
        # Génération du prompt
        schema_prompt = self.get_schema_detection_prompt(query_data, article_intent, selected_angle, lang)
        system_message = self.get_system_message(lang)
        
        messages = [
            SystemMessage(content=system_message),
            HumanMessage(content=schema_prompt)
        ]
        
        logging.info(f"🏷️ [ID {self.query_id}] Détermination du schema principal commercial...")
        
        # Appel à OpenAI
        response = await asyncio.get_event_loop().run_in_executor(
            None, self.llm.invoke, messages
        )
        
        # Extraction du schema depuis la réponse
        response_content = response.content.strip()
        schema_type = self.extract_schema_from_response(response_content)
        
        logging.info(f"✅ [ID {self.query_id}] Schema commercial déterminé: {schema_type}")
        logging.info(f"📝 [ID {self.query_id}] Justification: {response_content}")
        
        return schema_type

# Fonction principale pour tester l'agent
async def main():
    """Fonction de test"""
    # Exemple de données de test
    test_query_data = {
        'id': 1,
        'text': 'comment optimiser son référencement naturel'
    }
    
    article_intent = 'howto'
    selected_angle = 'Guide SEO technique pour développeurs avec focus commercial'
    
    # Test de l'agent
    agent = SchemaDetectorAgent(query_id=1)
    schema_type = await agent.determine_schema(test_query_data, article_intent, selected_angle)
    
    print(f"Schema déterminé: {schema_type}")

if __name__ == "__main__":
    asyncio.run(main())