#!/usr/bin/env python3
"""
Script LangChain - Orchestrateur d'Illustration d'Articles
Analyse les sections d'articles et génère des prompts d'illustration
Version compatible avec la structure de données existante
"""

import json
import os
import sys
import glob
import time
from typing import Dict, List, Any, Optional, Tuple
from pathlib import Path
from dataclasses import dataclass

# Imports LangChain (versions récentes)
from langchain_openai import ChatOpenAI
from langchain.agents import initialize_agent, AgentType
from langchain.memory import ConversationBufferMemory
from langchain.prompts import PromptTemplate
from langchain.chains import LLMChain
from langchain_core.tools import BaseTool
from langchain_core.callbacks import CallbackManagerForToolRun


@dataclass
class IllustrationDecision:
    """Structure pour stocker la décision d'illustration"""
    should_illustrate: bool
    illustration_type: str
    justification: str
    section_key: str
    section_title: str


@dataclass
class ImagePrompt:
    """Structure pour stocker les prompts d'image générés"""
    prompt: str
    title: str
    alt_text: str
    caption: str
    style: str
    format_type: str


@dataclass
class InfographicPayload:
    """Structure pour stocker les spécifications d'infographie"""
    type: str
    steps: int
    titles: List[str]
    contents: List[str]
    style: str
    format: str


def _is_allowed_type(s: str) -> bool:
    s = (s or "").lower().strip()
    if s == "photo":
        return True
    if s.startswith("infographie:"):
        sub = s.split(":", 1)[1]
        return sub in {"boucle","chiffres_clefs","comparaison","processus","pyramide","timeline"}
    return False


def enforce_infographic_limits(infographic_type: str, titles: List[str], contents: List[str]) -> Tuple[List[str], List[str]]:
    """Applique les limites de longueur selon le type d'infographie"""
    
    # Limites par type d'infographie
    limits = {
        "boucle": {"title": 25, "content": 80},
        "chiffres_clefs": {"title": 30, "content": 60},
        "comparaison": {"title": 35, "content": 100},
        "processus": {"title": 30, "content": 90},
        "pyramide": {"title": 25, "content": 70},
        "timeline": {"title": 40, "content": 120}
    }
    
    # Extraction du sous-type
    sub_type = infographic_type.split(":", 1)[1] if ":" in infographic_type else infographic_type
    limit = limits.get(sub_type, {"title": 30, "content": 100})
    
    # Application des limites
    limited_titles = []
    limited_contents = []
    
    for title in titles:
        if len(title) > limit["title"]:
            # Troncature intelligente sur un espace
            truncated = title[:limit["title"]]
            last_space = truncated.rfind(' ')
            if last_space > limit["title"] * 0.7:  # Si on peut couper sur un espace pas trop loin
                truncated = truncated[:last_space]
            limited_titles.append(truncated + "...")
        else:
            limited_titles.append(title)
    
    for content in contents:
        if len(content) > limit["content"]:
            # Troncature intelligente sur un espace
            truncated = content[:limit["content"]]
            last_space = truncated.rfind(' ')
            if last_space > limit["content"] * 0.7:  # Si on peut couper sur un espace pas trop loin
                truncated = truncated[:last_space]
            limited_contents.append(truncated + "...")
        else:
            limited_contents.append(content)
    
    return limited_titles, limited_contents


class IllustrationAnalyzerTool(BaseTool):
    """Agent spécialisé dans l'analyse des sections pour déterminer les besoins d'illustration"""
    
    name: str = "illustration_analyzer"
    description: str = "Analyse une section d'article et décide si elle doit être illustrée"
    
    # Attributs de classe pour stocker llm et chain
    _llm = None
    _chain = None
    
    @classmethod
    def create_with_llm(cls, llm):
        """Factory method pour créer l'outil avec un LLM"""
        tool = cls()
        cls._llm = llm
        
        analysis_template = PromptTemplate(
            input_variables=["section_content", "section_title"],
            template="""Tu es expert en design éditorial.
Analyse la section et choisis le MEILLEUR type d'illustration.

SECTION:
Titre: {section_title}
Contenu: {section_content}

Règles rapides:
- Concept/processus abstrait ou à étapes → infographie:processus (ex-«schéma»)
- Données/KPI/comparatif → infographie:chiffres_clefs ou infographie:comparaison (ex-«graphique»)
- Hiérarchie → infographie:pyramide
- Cycle → infographie:boucle
- Repères temporels → infographie:timeline
- Si l'émotion/ambiance prime → photo
- Si décoratif → ne pas illustrer

Types AUTORISÉS UNIQUEMENT:
- "photo"
- "infographie:<boucle|chiffres_clefs|comparaison|processus|pyramide|timeline>"

Réponds en JSON STRICT:
{
  "should_illustrate": true/false,
  "illustration_type": "photo" ou "infographie:<sous-type>",
  "justification": "explication concise",
  "key_concept": "concept principal",
  "visual_priority": "high/medium/low"
}
"""
        )

        cls._chain = LLMChain(llm=llm, prompt=analysis_template)
        return tool
    
    def _run(self, section_content: str, section_title: str = "", run_manager: Optional[CallbackManagerForToolRun] = None) -> str:
        """Analyse une section et retourne la décision d'illustration"""
        try:
            result = self._chain.invoke({
                "section_content": section_content,
                "section_title": section_title
            })
            # Extraction du contenu de la réponse
            if hasattr(result, 'content'):
                return result.content
            elif isinstance(result, dict) and 'text' in result:
                return result['text']
            else:
                return str(result)
        except Exception as e:
            return f"Erreur lors de l'analyse: {str(e)}"


class ImagePromptGeneratorTool(BaseTool):
    """Agent spécialisé dans la génération de prompts d'image détaillés"""
    
    name: str = "image_prompt_generator"
    description: str = "Génère des prompts détaillés pour la création d'images d'illustration"
    
    # Attributs de classe pour stocker llm et chain
    _llm = None
    _chain = None
    
    @classmethod
    def create_with_llm(cls, llm):
        """Factory method pour créer l'outil avec un LLM"""
        tool = cls()
        cls._llm = llm
        
        prompt_template = PromptTemplate(
            input_variables=["section_content", "section_title", "illustration_type", "key_concept"],
            template="""Tu es un expert en direction artistique et en génération de prompts pour l'IA.
Crée un prompt détaillé pour générer une image d'illustration basée sur les informations suivantes :

SECTION À ILLUSTRER:
Titre: {section_title}
Contenu: {section_content}
Type d'illustration souhaité: {illustration_type}
Concept clé: {key_concept}

INSTRUCTIONS:
1. Crée un prompt précis et détaillé pour un générateur d'image IA
2. Inclus le style visuel approprié au contenu
3. Spécifie les éléments techniques (composition, couleurs, ambiance)
4. Génère un titre accrocheur pour l'image
5. Rédige un texte alternatif descriptif pour l'accessibilité
6. Crée une légende explicative qui enrichit le contenu

RÉPONSE ATTENDUE (format JSON strict):
{{
    "image_prompt": "prompt détaillé pour générateur d'image IA",
    "title": "titre accrocheur pour l'image",
    "alt_text": "description accessible de l'image",
    "caption": "légende explicative qui enrichit le contenu",
    "style": "style visuel recommandé",
    "format": "format d'image recommandé (horizontal/vertical/carré)",
    "technical_specs": "spécifications techniques (résolution, style, etc.)"
}}"""
        )
        cls._chain = LLMChain(llm=llm, prompt=prompt_template)
        return tool
    
    def _run(self, section_content: str, section_title: str = "", illustration_type: str = "", 
             key_concept: str = "", run_manager: Optional[CallbackManagerForToolRun] = None) -> str:
        """Génère un prompt d'image détaillé"""
        try:
            result = self._chain.invoke({
                "section_content": section_content,
                "section_title": section_title,
                "illustration_type": illustration_type,
                "key_concept": key_concept
            })
            # Extraction du contenu de la réponse
            if hasattr(result, 'content'):
                return result.content
            elif isinstance(result, dict) and 'text' in result:
                return result['text']
            else:
                return str(result)
        except Exception as e:
            return f"Erreur lors de la génération du prompt: {str(e)}"


class InfographicSpecGeneratorTool(BaseTool):
    """Agent spécialisé dans la génération de spécifications d'infographie"""
    
    name: str = "infographic_spec_generator"
    description: str = "Génère des spécifications détaillées pour la création d'infographies"
    
    # Attributs de classe pour stocker llm et chain
    _llm = None
    _chain = None
    
    @classmethod
    def create_with_llm(cls, llm):
        """Factory method pour créer l'outil avec un LLM"""
        tool = cls()
        cls._llm = llm
        
        spec_template = PromptTemplate(
            input_variables=["section_content", "section_title", "illustration_type", "key_concept"],
            template="""Tu es un expert en création d'infographies.
Génère les spécifications pour une infographie basée sur le contenu suivant :

SECTION À ILLUSTRER:
Titre: {section_title}
Contenu: {section_content}
Type d'infographie: {illustration_type}
Concept clé: {key_concept}

RÈGLES STRICTES:
- Maximum 6 étapes/éléments
- Titres courts et percutants
- Contenus concis et informatifs
- Respecter le type demandé

RÉPONSE ATTENDUE (format JSON strict):
{{
    "type": "{illustration_type}",
    "steps": nombre_d_etapes,
    "titles": ["titre1", "titre2", ...],
    "contents": ["contenu1", "contenu2", ...],
    "style": "style visuel recommandé",
    "format": "format recommandé (horizontal/vertical/carré)"
}}"""
        )
        cls._chain = LLMChain(llm=llm, prompt=spec_template)
        return tool
    
    def _run(self, section_content: str, section_title: str = "", illustration_type: str = "", 
             key_concept: str = "", run_manager: Optional[CallbackManagerForToolRun] = None) -> str:
        """Génère des spécifications d'infographie"""
        try:
            result = self._chain.invoke({
                "section_content": section_content,
                "section_title": section_title,
                "illustration_type": illustration_type,
                "key_concept": key_concept
            })
            # Extraction du contenu de la réponse
            if hasattr(result, 'content'):
                return result.content
            elif isinstance(result, dict) and 'text' in result:
                return result['text']
            else:
                return str(result)
        except Exception as e:
            return f"Erreur lors de la génération des spécifications: {str(e)}"


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


class ArticleIllustrationOrchestrator:
    """Orchestrateur principal pour l'analyse et l'illustration d'articles"""
    
    def __init__(self, 
                 model_name: str = "gpt-4o",
                 temperature: float = 0.3):
        
        # Vérification de la clé API OpenAI
        openai_key = os.getenv('OPENAI_API_KEY')
        if not openai_key:
            print("❌ Variable d'environnement OPENAI_API_KEY manquante.")
            print("💡 Pour définir la variable:")
            print("   Linux/Mac: export OPENAI_API_KEY='votre_clé_ici'")
            print("   Windows:   set OPENAI_API_KEY=votre_clé_ici")
            sys.exit(1)
        
        # Initialisation du LLM
        self.llm = ChatOpenAI(
            model=model_name,
            temperature=temperature,
            openai_api_key=openai_key
        )
        
        # Initialisation des agents avec factory methods
        self.analyzer_tool = IllustrationAnalyzerTool.create_with_llm(self.llm)
        self.generator_tool = ImagePromptGeneratorTool.create_with_llm(self.llm)
        self.infographic_tool = InfographicSpecGeneratorTool.create_with_llm(self.llm)
        
        # Configuration de l'agent orchestrateur
        tools = [self.analyzer_tool, self.generator_tool, self.infographic_tool]
        
        # Mémoire pour maintenir le contexte
        self.memory = ConversationBufferMemory(
            memory_key="chat_history",
            return_messages=True
        )
        
        # Prompt pour l'orchestrateur
        orchestrator_prompt = """Tu es un orchestrateur d'illustration d'articles. 
        Tu coordonnes l'analyse des sections d'articles et la génération de prompts d'illustration.
        
        Utilise les outils disponibles pour :
        1. Analyser chaque section avec l'illustration_analyzer
        2. Générer des prompts détaillés avec l'image_prompt_generator pour les sections à illustrer
        3. Générer des spécifications d'infographie avec l'infographic_spec_generator
        
        Fournis un rapport complet et structuré de tes analyses."""
        
        # Initialisation de l'agent
        self.agent = initialize_agent(
            tools=tools,
            llm=self.llm,
            agent=AgentType.OPENAI_FUNCTIONS,
            memory=self.memory,
            verbose=True,
            agent_kwargs={
                "system_message": orchestrator_prompt
            }
        )
        
        # Flag pour la génération d'images pour infographies
        self.generate_image_for_infographics = False  # infographie => pas de prompt image
        
        # Chargement du fichier consigne
        self.consigne_path = _find_consigne_file()
        self.consigne_data = self.load_consigne()
        
        # Stockage des résultats
        self.illustration_decisions = []
        self.generated_prompts = []
    
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
        """Sauvegarde le fichier consigne.json avec les illustrations"""
        with open(self.consigne_path, 'w', encoding='utf-8') as f:
            json.dump(self.consigne_data, f, ensure_ascii=False, indent=4)
    
    def get_query_data(self, query_id: int) -> Optional[Dict]:
        """Récupère les données d'une requête par son ID"""
        for query in self.consigne_data.get('queries', []):
            if query['id'] == query_id:
                return query
        return None
    
    def list_available_articles(self) -> List[Dict]:
        """Liste tous les articles avec contenu généré"""
        articles = []
        for query in self.consigne_data.get('queries', []):
            has_content = 'generated_content' in query
            if has_content:
                articles.append({
                    'id': query['id'],
                    'text': query['text'],
                    'sections_count': len([k for k in query['generated_content'].keys() 
                                         if k.startswith('section_')]),
                    'has_illustrations': 'illustrations' in query
                })
        return articles
    
    def extract_sections_from_article(self, query_data: Dict) -> List[Tuple[str, str, str]]:
        """Extrait les sections d'un article généré"""
        sections = []
        generated_content = query_data.get('generated_content', {})
        
        # Introduction
        if 'introduction' in generated_content:
            sections.append(('introduction', 'Introduction', generated_content['introduction']))
        
        # Sections numérotées
        section_keys = sorted([k for k in generated_content.keys() if k.startswith('section_')])
        for section_key in section_keys:
            # Extraction du titre depuis le contenu HTML si possible
            content = generated_content[section_key]
            title = self._extract_title_from_content(content) or f"Section {section_key.split('_')[1]}"
            sections.append((section_key, title, content))
        
        # Conclusion
        if 'conclusion' in generated_content:
            sections.append(('conclusion', 'Conclusion', generated_content['conclusion']))
        
        return sections
    
    def _extract_title_from_content(self, content: str) -> Optional[str]:
        """Extrait le titre d'une section depuis son contenu HTML"""
        import re
        # Recherche des balises h3, h2, etc.
        match = re.search(r'<h[1-6][^>]*>([^<]+)</h[1-6]>', content)
        if match:
            return match.group(1).strip()
        return None
    
    def analyze_section(self, section_key: str, section_title: str, section_content: str) -> IllustrationDecision:
        """Analyse une section avec l'agent analyzer"""
        print(f"   🔍 Analyse de la section: {section_title}")
        
        try:
            # Appel de l'outil d'analyse
            analysis_result = self.analyzer_tool._run(
                section_content=section_content,
                section_title=section_title
            )
            
            # Nettoyage du résultat (suppression des backticks markdown)
            cleaned_result = analysis_result.strip()
            if cleaned_result.startswith('```json'):
                cleaned_result = cleaned_result[7:]  # Supprime ```json
            if cleaned_result.endswith('```'):
                cleaned_result = cleaned_result[:-3]  # Supprime ```
            cleaned_result = cleaned_result.strip()
            
            # Parse du résultat JSON
            try:
                analysis_data = json.loads(cleaned_result)
                
                # Validation du type autorisé
                t = (analysis_data.get('illustration_type') or "").strip().lower()
                if not _is_allowed_type(t):
                    print(f"     ⚠️ Type non autorisé renvoyé par le LLM: {t}")
                    return IllustrationDecision(False, "", "Type non autorisé", section_key, section_title)
                
                decision = IllustrationDecision(
                    should_illustrate=analysis_data.get('should_illustrate', False),
                    illustration_type=analysis_data.get('illustration_type', ''),
                    justification=analysis_data.get('justification', ''),
                    section_key=section_key,
                    section_title=section_title
                )
                print(f"     → Décision: {'✅ Illustrer' if decision.should_illustrate else '❌ Ne pas illustrer'}")
                return decision
                
            except json.JSONDecodeError as e:
                print(f"     ⚠️ Erreur de parsing JSON: {cleaned_result[:100]}...")
                print(f"     ⚠️ Erreur détaillée: {e}")
                return IllustrationDecision(
                    should_illustrate=False,
                    illustration_type="",
                    justification="Erreur d'analyse JSON",
                    section_key=section_key,
                    section_title=section_title
                )
                
        except Exception as e:
            print(f"     ❌ Erreur lors de l'analyse: {e}")
            return IllustrationDecision(
                should_illustrate=False,
                illustration_type="",
                justification=f"Erreur: {str(e)}",
                section_key=section_key,
                section_title=section_title
            )
    
    def generate_image_prompt(self, decision: IllustrationDecision, section_content: str) -> Optional[ImagePrompt]:
        """Génère un prompt d'image détaillé pour une section"""
        if not decision.should_illustrate:
            return None
        
        print(f"   🎨 Génération du prompt pour: {decision.section_title}")
        
        try:
            # Extraction du concept clé depuis la justification
            key_concept = self._extract_key_concept(decision.justification)
            
            # Appel de l'outil de génération
            prompt_result = self.generator_tool._run(
                section_content=section_content,
                section_title=decision.section_title,
                illustration_type=decision.illustration_type,
                key_concept=key_concept
            )
            
            # Nettoyage du résultat (suppression des backticks markdown)
            cleaned_result = prompt_result.strip()
            if cleaned_result.startswith('```json'):
                cleaned_result = cleaned_result[7:]  # Supprime ```json
            if cleaned_result.endswith('```'):
                cleaned_result = cleaned_result[:-3]  # Supprime ```
            cleaned_result = cleaned_result.strip()
            
            # Parse du résultat JSON
            try:
                prompt_data = json.loads(cleaned_result)
                image_prompt = ImagePrompt(
                    prompt=prompt_data.get('image_prompt', ''),
                    title=prompt_data.get('title', ''),
                    alt_text=prompt_data.get('alt_text', ''),
                    caption=prompt_data.get('caption', ''),
                    style=prompt_data.get('style', ''),
                    format_type=prompt_data.get('format', 'horizontal')
                )
                print(f"     → Prompt généré: {len(image_prompt.prompt)} caractères")
                return image_prompt
                
            except json.JSONDecodeError as e:
                print(f"     ⚠️ Erreur de parsing JSON prompt: {cleaned_result[:100]}...")
                print(f"     ⚠️ Erreur détaillée: {e}")
                return None
                
        except Exception as e:
            print(f"     ❌ Erreur lors de la génération: {e}")
            return None
    
    def generate_infographic_payload(self, decision: IllustrationDecision, section_content: str) -> Optional[Dict]:
        """Génère une payload infographie pour une section"""
        if not decision.should_illustrate:
            return None
        
        print(f"   📊 Génération de l'infographie pour: {decision.section_title}")
        
        try:
            # Extraction du concept clé depuis la justification
            key_concept = self._extract_key_concept(decision.justification)
            
            # Appel de l'outil de génération d'infographie
            spec_result = self.infographic_tool._run(
                section_content=section_content,
                section_title=decision.section_title,
                illustration_type=decision.illustration_type,
                key_concept=key_concept
            )
            
            # Nettoyage du résultat (suppression des backticks markdown)
            cleaned_result = spec_result.strip()
            if cleaned_result.startswith('```json'):
                cleaned_result = cleaned_result[7:]  # Supprime ```json
            if cleaned_result.endswith('```'):
                cleaned_result = cleaned_result[:-3]  # Supprime ```
            cleaned_result = cleaned_result.strip()
            
            # Parse du résultat JSON
            try:
                spec_data = json.loads(cleaned_result)
                
                # Application des limites de longueur
                titles = spec_data.get('titles', [])
                contents = spec_data.get('contents', [])
                limited_titles, limited_contents = enforce_infographic_limits(
                    decision.illustration_type, titles, contents
                )
                
                # Construction de la payload finale
                payload = {
                    'type': decision.illustration_type,
                    'steps': len(limited_titles),
                    'style': spec_data.get('style', ''),
                    'format': spec_data.get('format', 'horizontal')
                }
                
                # Ajout des titres et contenus avec numérotation
                for i, (title, content) in enumerate(zip(limited_titles, limited_contents), 1):
                    payload[f'title{i}'] = title
                    payload[f'content{i}'] = content
                
                print(f"     → Infographie générée: {payload['steps']} étapes")
                return payload
                
            except json.JSONDecodeError as e:
                print(f"     ⚠️ Erreur de parsing JSON infographie: {cleaned_result[:100]}...")
                print(f"     ⚠️ Erreur détaillée: {e}")
                return None
                
        except Exception as e:
            print(f"     ❌ Erreur lors de la génération de l'infographie: {e}")
            return None
    
    def _extract_key_concept(self, justification: str) -> str:
        """Extrait le concept clé de la justification"""
        # Simple extraction basée sur des mots-clés
        import re
        concepts = re.findall(r'concept[^.]*?([^.]+)', justification, re.IGNORECASE)
        if concepts:
            return concepts[0].strip()
        return "concept principal"
    
    def process_article_illustrations(self, query_id: int) -> bool:
        """Traite toutes les sections d'un article pour l'illustration"""
        query_data = self.get_query_data(query_id)
        if not query_data or 'generated_content' not in query_data:
            print(f"❌ Requête {query_id} sans contenu généré")
            return False
        
        print(f"\n🎨 ANALYSE D'ILLUSTRATION pour ID {query_id}: '{query_data['text']}'")
        
        # Extraction des sections
        sections = self.extract_sections_from_article(query_data)
        print(f"   📄 {len(sections)} sections trouvées")
        
        # Analyse de chaque section
        decisions = []
        prompts = []
        
        for section_key, section_title, section_content in sections:
            # Analyse de la section
            decision = self.analyze_section(section_key, section_title, section_content)
            decisions.append(decision)
            
            if not decision.should_illustrate:
                continue

            itype = (decision.illustration_type or "").strip().lower()

            if itype == "photo":
                # → seulement prompt image
                prompt = self.generate_image_prompt(decision, section_content)
                if prompt:
                    prompts.append((section_key, prompt))

            elif itype.startswith("infographie:"):
                # → seulement payload infographie
                infopayload = self.generate_infographic_payload(decision, section_content)
                if infopayload:
                    if 'illustrations' not in query_data:
                        query_data['illustrations'] = {}
                    if 'infographics' not in query_data['illustrations']:
                        query_data['illustrations']['infographics'] = []
                    query_data['illustrations']['infographics'].append({
                        'section_key': section_key,
                        'section_title': decision.section_title,
                        **infopayload
                    })
            else:
                print(f"     ⚠️ Type non autorisé ignoré: {itype}")
        
        # Sauvegarde des résultats pour les photos
        if prompts:
            illustrations_data = {
                'analysis_completed': True,
                'total_sections': len(sections),
                'sections_to_illustrate': len([d for d in decisions if d.should_illustrate]),
                'decisions': [
                    {
                        'section_key': d.section_key,
                        'section_title': d.section_title,
                        'should_illustrate': d.should_illustrate,
                        'illustration_type': d.illustration_type,
                        'justification': d.justification
                    }
                    for d in decisions
                ],
                'generated_prompts': [
                    {
                        'section_key': section_key,
                        'prompt': prompt.prompt,
                        'title': prompt.title,
                        'alt_text': prompt.alt_text,
                        'caption': prompt.caption,
                        'style': prompt.style,
                        'format': prompt.format_type
                    }
                    for section_key, prompt in prompts
                ]
            }
            
            if 'illustrations' not in query_data:
                query_data['illustrations'] = {}
            query_data['illustrations'].update(illustrations_data)
        
        infographics_count = len(query_data.get('illustrations', {}).get('infographics', []))
        photos_count = len(prompts)
        
        print(f"   ✅ Analyse terminée: {photos_count} photos + {infographics_count} infographies à créer")
        return True
    
    def select_articles_to_process(self) -> List[int]:
        """Interface utilisateur pour sélectionner les articles à traiter"""
        articles = self.list_available_articles()
        
        if not articles:
            print("❌ Aucun article avec contenu généré trouvé.")
            return []
        
        print("\n📋 ARTICLES DISPONIBLES POUR ILLUSTRATION:")
        print("=" * 80)
        for article in articles:
            status = "🖼️ Illustré" if article['has_illustrations'] else "📝 Prêt"
            print(f"ID {article['id']:2d} | {status} | {article['sections_count']} sections | {article['text']}")
        
        print("\n💡 Instructions:")
        print("- Tapez un ID pour traiter un seul article: 5")
        print("- Tapez plusieurs IDs séparés par des virgules: 1,3,5")
        print("- Tapez 'all' pour traiter tous les articles")
        print("- Tapez 'q' pour quitter")
        
        while True:
            user_input = input("\n🎯 Votre sélection: ").strip().lower()
            
            if user_input == 'q':
                print("👋 Au revoir!")
                sys.exit(0)
            
            if user_input == 'all':
                return [a['id'] for a in articles]
            
            try:
                if ',' in user_input:
                    selected_ids = [int(x.strip()) for x in user_input.split(',')]
                else:
                    selected_ids = [int(user_input)]
                
                # Validation
                valid_ids = [a['id'] for a in articles]
                invalid_ids = [id for id in selected_ids if id not in valid_ids]
                
                if invalid_ids:
                    print(f"❌ IDs invalides: {invalid_ids}")
                    continue
                
                return selected_ids
                
            except ValueError:
                print("❌ Format invalide. Utilisez des nombres ou des virgules.")
    
    def process_multiple_articles(self, article_ids: List[int]):
        """Traite plusieurs articles pour l'illustration"""
        print(f"\n🎨 TRAITEMENT DE {len(article_ids)} ARTICLE(S): {article_ids}")
        
        successful = 0
        
        for article_id in article_ids:
            try:
                if self.process_article_illustrations(article_id):
                    successful += 1
                else:
                    print(f"   ❌ Échec traitement pour ID {article_id}")
                    
            except Exception as e:
                print(f"   ❌ Erreur lors du traitement ID {article_id}: {e}")
        
        # Sauvegarde finale
        try:
            self.save_consigne()
            print(f"\n💾 Fichier {self.consigne_path} mis à jour avec succès!")
            print(f"📊 Résultats: {successful}/{len(article_ids)} articles traités avec succès")
            
        except Exception as e:
            print(f"❌ Erreur lors de la sauvegarde: {e}")


def main():
    """Point d'entrée principal"""
    print("🎨 GÉNÉRATEUR D'ILLUSTRATIONS D'ARTICLES - ORCHESTRATEUR LANGCHAIN")
    print("=" * 70)
    print("🤖 Analyse automatique des sections et génération de prompts d'illustration")
    print("🔗 Utilise LangChain avec des agents spécialisés")
    
    # Vérification de la clé API OpenAI
    if not os.getenv('OPENAI_API_KEY'):
        print("❌ Variable d'environnement OPENAI_API_KEY manquante.")
        print("Ajoutez votre clé API OpenAI:")
        print("export OPENAI_API_KEY='your-api-key-here'")
        sys.exit(1)
    
    try:
        orchestrator = ArticleIllustrationOrchestrator(
            model_name="gpt-4o",
            temperature=0.3
        )
        
        # Sélection et traitement
        selected_ids = orchestrator.select_articles_to_process()
        if selected_ids:
            orchestrator.process_multiple_articles(selected_ids)
        else:
            print("ℹ️  Aucun article sélectionné.")
            
    except KeyboardInterrupt:
        print("\n\n⏹️  Arrêt demandé par l'utilisateur.")
    except Exception as e:
        print(f"\n❌ Erreur inattendue: {e}")
        raise


if __name__ == "__main__":
    main()