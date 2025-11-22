#!/usr/bin/env python3
"""
AGENT 2: Synthèses stratégiques
Génère les synthèses stratégiques à partir des analyses d'articles
"""

import os
import asyncio
import json
import re
from concurrent.futures import ThreadPoolExecutor
from langchain_deepseek import ChatDeepSeek


async def generate_syntheses(grouped_results, groups_queries):
    """Génère toutes les synthèses en parallèle"""
    print(f"   Génération de {len(grouped_results)} synthèses en parallèle...")
    
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
    prompt_file = os.path.join(script_dir, "prompts", "fr", "strategic_synthesis_fr.txt")
    with open(prompt_file, 'r', encoding='utf-8') as f:
        synthesis_prompt = f.read().strip()
    
    async def generate_one(group_id, group_analyses, query):
        """Génère une synthèse"""
        analyses_text = json.dumps(group_analyses, indent=2, ensure_ascii=False)
        
        variables_section = f"""

Variables d'entrée pour la synthèse :
- Requête cible: {query}
- Analyses des articles concurrents: {analyses_text[:20000]}

Effectuer maintenant la synthèse stratégique selon les instructions XML ci-dessus."""
        
        prompt = synthesis_prompt + variables_section
        full_prompt = f"""You are an expert SEO strategist. Always respond in valid JSON format.

{prompt}

IMPORTANT: Your response MUST be in valid JSON format only, no additional text or markdown."""
        
        # Appel LLM
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(executor, lambda: llm.invoke(full_prompt))
        response_text = response.content.strip()
        
        # Parser JSON
        result = parse_json(response_text)
        if not result:
            result = {"analyse_angles_concurrentiels": {"angles_dominants": [], "angles_emergents": []}, "parsing_error": True}
        
        return result
    
    # Générer toutes les synthèses en parallèle
    tasks = []
    for group_id, group_analyses in grouped_results.items():
        query = groups_queries.get(group_id, "")
        tasks.append((group_id, generate_one(group_id, group_analyses, query)))
    
    results = await asyncio.gather(*[task for _, task in tasks])
    
    # Associer les résultats aux group_ids
    syntheses = {}
    for i, (group_id, _) in enumerate(tasks):
        syntheses[group_id] = results[i]
    
    print(f"   ✅ {len(syntheses)} synthèses générées")
    return syntheses


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