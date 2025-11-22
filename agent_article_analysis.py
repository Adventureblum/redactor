#!/usr/bin/env python3
"""
AGENT 1: Analyse d'articles
Analyse les articles individuels avec DeepSeek
"""

import os
import asyncio
import json
import re
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from langchain_deepseek import ChatDeepSeek


async def analyze_articles(articles):
    """Analyse tous les articles en parallèle"""
    print(f"   Analyse de {len(articles)} articles en parallèle...")
    
    # Initialiser le LLM
    llm = ChatDeepSeek(
        model="deepseek-chat",
        api_key=os.getenv("DEEPSEEK_KEY"),
        max_tokens=3000,
        temperature=0.1,
        timeout=120
    )
    
    executor = ThreadPoolExecutor(max_workers=100)
    
    # Charger le prompt
    script_dir = os.path.dirname(os.path.abspath(__file__))
    prompt_file = os.path.join(script_dir, "prompts", "fr", "article_analysis_fr.txt")
    with open(prompt_file, 'r', encoding='utf-8') as f:
        article_prompt = f.read().strip()
    
    async def analyze_one(article):
        """Analyse un article"""
        variables_section = f"""

Variables d'entrée pour l'analyse :
- Position: {article['position']}
- Titre: {article['title']}
- Contenu: {article['content'][:15000]}

Analyser maintenant cet article selon les instructions XML ci-dessus."""
        
        prompt = article_prompt + variables_section
        full_prompt = f"""You are an expert SEO content analyst. Always respond in valid JSON format.

{prompt}

IMPORTANT: Your response MUST be in valid JSON format only, no additional text or markdown."""
        
        # Appel LLM
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(executor, lambda: llm.invoke(full_prompt))
        response_text = response.content.strip()
        
        # Parser JSON
        result = parse_json(response_text)
        if not result:
            result = {"pertinence_requete": {"score": 0.5, "justification": "Parsing failed"}, "parsing_error": True}
        
        result['article_id'] = article['id']
        result['timestamp'] = datetime.now().isoformat()
        result['validation_report'] = {
            'validated': not result.get('parsing_error', False),
            'quality_score': 1.0 if not result.get('parsing_error', False) else 0.5,
            'parsing_successful': not result.get('parsing_error', False)
        }
        
        return result
    
    # Analyser tous les articles en parallèle
    tasks = [analyze_one(article) for article in articles]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Filtrer les résultats valides
    valid_results = [r for r in results if not isinstance(r, Exception) and r is not None]
    
    print(f"   ✅ {len(valid_results)} articles analysés")
    return valid_results


def parse_json(response_text):
    """Parse JSON de manière robuste"""
    try:
        if response_text.startswith('```json'):
            response_text = response_text.replace('```json', '').replace('```', '').strip()
        elif response_text.startswith('```'):
            response_text = response_text.replace('```', '').strip()
        
        try:
            return json.loads(response_text)
        except json.JSONDecodeError:
            pass
        
        cleaned = response_text.strip()
        cleaned = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', cleaned)
        cleaned = re.sub(r'[\u2018\u2019]', "'", cleaned)
        cleaned = re.sub(r'[\u201C\u201D]', '"', cleaned)
        
        start = cleaned.find('{')
        end = cleaned.rfind('}') + 1
        if start != -1 and end > start:
            json_text = cleaned[start:end]
            try:
                return json.loads(json_text)
            except json.JSONDecodeError:
                pass
        
        return None
    except Exception:
        return None