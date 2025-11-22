#!/usr/bin/env python3
"""
Orchestrateur Pipeline SEO
Coordonne l'exécution séquentielle des 4 agents
"""

import sys
import os
import json
import asyncio
from datetime import datetime

# Import des agents
from agent_article_analysis import analyze_articles
from agent_synthesis import generate_syntheses
from agent_angle_selection import select_angles
from agent_searchbase import generate_searchbase_documents


def parse_args():
    """Parse les arguments de ligne de commande"""
    mode = "optimized"
    consignes_file = None
    
    i = 1
    while i < len(sys.argv):
        arg = sys.argv[i]
        if arg == "--legacy":
            mode = "legacy"
        elif arg == "--optimized":
            mode = "optimized"
        elif arg == "--file" and i + 1 < len(sys.argv):
            consignes_file = sys.argv[i + 1]
            i += 1
        elif arg == "--query" and i + 1 < len(sys.argv):
            query = sys.argv[i + 1]
            consignes_file = f"static/consignesrun/consignes_{query}.json"
            i += 1
        elif not arg.startswith('--'):
            consignes_file = arg
        i += 1
    
    if not consignes_file:
        # Auto-détection
        consignes_dir = "static/consignesrun"
        if os.path.exists(consignes_dir):
            consignes_files = [f for f in os.listdir(consignes_dir) 
                             if f.startswith('consignes_') and f.endswith('.json')]
            if consignes_files:
                consignes_file = os.path.join(consignes_dir, sorted(consignes_files)[0])
    
    return mode, consignes_file


def load_data(filepath):
    """Charge les données depuis le fichier de consignes"""
    print(f"📁 Chargement des données: {filepath}")
    
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    queries = data['queries']
    articles = []
    groups_queries = {}
    
    for query_idx, query_data in enumerate(queries):
        query = query_data.get('text', '').strip()
        groups_queries[query_idx] = query
        
        position_data = query_data.get('serp_data', {}).get('position_data', {})
        
        for position_key, position_info in position_data.items():
            position = int(position_key.split('_')[1])
            
            url = position_info.get('url', '').strip()
            title = position_info.get('title', '').strip()
            
            # Construire le contenu
            content_dict = position_info.get('content', {})
            content_parts = []
            
            if 'h1' in content_dict and content_dict['h1']:
                content_parts.append(f"# {content_dict['h1']}")
            
            sorted_keys = sorted(content_dict.keys(),
                               key=lambda x: (int(x.split('_')[1]) if '_' in x and x.split('_')[1].isdigit() else 9999))
            
            for key in sorted_keys:
                value = content_dict.get(key)
                if not value or len(str(value).strip()) < 10:
                    continue
                
                value_str = str(value).strip()
                
                if key.startswith('h1'):
                    continue
                elif key.startswith('h2'):
                    content_parts.append(f"\n## {value_str}")
                elif key.startswith('h3'):
                    content_parts.append(f"\n### {value_str}")
                elif key.startswith('h4'):
                    content_parts.append(f"\n#### {value_str}")
                elif key.startswith('p'):
                    content_parts.append(value_str)
            
            content = "\n\n".join(content_parts)
            word_count = len(content.split()) if content else 0
            
            words_count_json = int(position_info.get('words_count', 0))
            authority_score = float(position_info.get('domain_authority', {}).get('authority_score', 0))
            
            article = {
                'id': f"query_{query_idx}_position_{position}",
                'position': position,
                'url': url,
                'title': title,
                'content': content,
                'word_count': word_count,
                'analysis_group': query_idx,
                'query': query,
                'words_count_json': words_count_json,
                'authority_score': authority_score
            }
            articles.append(article)
    
    print(f"✅ {len(articles)} articles chargés, {len(groups_queries)} groupes")
    return articles, groups_queries


def save_results(group_results, query, main_query):
    """Sauvegarde les résultats d'un groupe"""
    import re
    
    def sanitize(q):
        return re.sub(r'[^\w\-_]', '', q.lower().replace(' ', '_')).strip('_')
    
    main_folder = f"requetes/{sanitize(main_query)}"
    query_folder = f"{main_folder}/{sanitize(query)}"
    os.makedirs(query_folder, exist_ok=True)
    
    filename = f"{sanitize(query)}.json"
    output_path = f"{query_folder}/{filename}"
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(group_results, f, ensure_ascii=False, indent=2)
    
    # Version simplifiée
    simplified = {
        "meta": group_results.get("meta", {}),
        "syntheses_strategiques": {
            k: v for k, v in group_results.items() 
            if k.startswith("synthese_strategique_")
        },
        "angle_select": group_results.get("angle_select", {})
    }
    
    simplified_path = output_path.replace('.json', '_simplified.json')
    with open(simplified_path, 'w', encoding='utf-8') as f:
        json.dump(simplified, f, ensure_ascii=False, indent=2)
    
    # Searchbase
    searchbase_data = group_results.get('searchbase_data', {})
    if searchbase_data and not searchbase_data.get('parsing_error', False):
        searchbase_path = f"{query_folder}/{sanitize(query)}_searchbase.json"
        searchbase_output = {
            "meta": {
                "requete_cible": query,
                "requete_principale": main_query,
                "date_generation": datetime.now().isoformat(),
                "agent_version": "searchbase-v2.2",
                "type": "document_collecte_donnees"
            },
            "collecte_donnees": searchbase_data
        }
        with open(searchbase_path, 'w', encoding='utf-8') as f:
            json.dump(searchbase_output, f, ensure_ascii=False, indent=2)
    
    print(f"✅ Résultats sauvegardés: {output_path}")


async def run_optimized(articles, groups_queries, main_query):
    """Mode optimisé: tout en parallèle"""
    print(f"\n{'='*60}")
    print(f"🚀 MODE OPTIMISÉ - PARALLÈLE TOTAL")
    print(f"{'='*60}")
    
    start_time = datetime.now()
    
    # AGENT 1: Analyse articles
    print(f"\n📝 AGENT 1: Analyse des articles")
    analyses = await analyze_articles(articles)
    
    # Grouper par analysis_group
    grouped_results = {}
    for result in analyses:
        article_id = result.get('article_id', '')
        if 'query_' in article_id:
            group_id = int(article_id.split('_')[1])
            if group_id not in grouped_results:
                grouped_results[group_id] = []
            grouped_results[group_id].append(result)
    
    # AGENT 2: Synthèses
    print(f"\n📊 AGENT 2: Génération des synthèses stratégiques")
    syntheses = await generate_syntheses(grouped_results, groups_queries)
    
    # AGENT 3: Angles
    print(f"\n🎯 AGENT 3: Sélection des angles optimaux")
    angles = await select_angles(syntheses, groups_queries)
    
    # AGENT 4: Searchbase
    print(f"\n📋 AGENT 4: Génération des documents searchbase")
    searchbase_data = await generate_searchbase_documents(syntheses, angles, groups_queries)
    
    # Construction et sauvegarde des résultats
    print(f"\n💾 Sauvegarde des résultats")
    for group_id, group_analyses in grouped_results.items():
        query = groups_queries.get(group_id, "")
        
        group_result = {
            "meta": {
                "requete_cible": query,
                "analysis_group_id": group_id,
                "date_analyse": start_time.isoformat(),
                "articles_analyses": len([a for a in articles if a['analysis_group'] == group_id]),
                "articles_reussis": len(group_analyses),
                "agent_version": "v2.2-optimized-with-angle-selector",
                "language": "fr"
            },
            "analyses_individuelles": group_analyses,
            f"synthese_strategique_analysis_{group_id}": syntheses.get(group_id, {}),
            "angle_select": angles.get(group_id, {}),
            "searchbase_data": searchbase_data.get(group_id, {})
        }
        
        save_results(group_result, query, main_query)
    
    duration = (datetime.now() - start_time).total_seconds()
    print(f"\n✅ Pipeline terminé en {duration:.2f}s")


async def run_legacy(articles, groups_queries, main_query):
    """Mode legacy: séquentiel par groupe"""
    print(f"\n{'='*60}")
    print(f"🚀 MODE LEGACY - SÉQUENTIEL PAR GROUPE")
    print(f"{'='*60}")
    
    start_time = datetime.now()
    
    for group_id, query in groups_queries.items():
        print(f"\n{'='*80}")
        print(f"🚀 TRAITEMENT DU GROUPE {group_id}: {query}")
        print(f"{'='*80}")
        
        # Filtrer les articles du groupe
        group_articles = [a for a in articles if a['analysis_group'] == group_id]
        
        # AGENT 1: Analyse articles du groupe
        print(f"\n📝 AGENT 1: Analyse des {len(group_articles)} articles")
        group_analyses = await analyze_articles(group_articles)
        
        # AGENT 2: Synthèse du groupe
        print(f"\n📊 AGENT 2: Génération de la synthèse stratégique")
        synthesis = await generate_syntheses({group_id: group_analyses}, {group_id: query})
        
        # AGENT 3: Angle du groupe
        print(f"\n🎯 AGENT 3: Sélection de l'angle optimal")
        angle = await select_angles(synthesis, {group_id: query})
        
        # AGENT 4: Searchbase du groupe
        print(f"\n📋 AGENT 4: Génération du document searchbase")
        searchbase = await generate_searchbase_documents(synthesis, angle, {group_id: query})
        
        # Sauvegarde
        group_result = {
            "meta": {
                "requete_cible": query,
                "analysis_group_id": group_id,
                "date_analyse": start_time.isoformat(),
                "articles_analyses": len(group_articles),
                "articles_reussis": len(group_analyses),
                "agent_version": "v2.2-with-angle-selector",
                "language": "fr"
            },
            "analyses_individuelles": group_analyses,
            f"synthese_strategique_analysis_{group_id}": synthesis.get(group_id, {}),
            "angle_select": angle.get(group_id, {}),
            "searchbase_data": searchbase.get(group_id, {})
        }
        
        save_results(group_result, query, main_query)
    
    duration = (datetime.now() - start_time).total_seconds()
    print(f"\n✅ Pipeline terminé en {duration:.2f}s")


async def main():
    """Point d'entrée principal"""
    print(f"🚀 ORCHESTRATEUR PIPELINE SEO")
    print(f"{'='*60}")
    
    # Validation DEEPSEEK_KEY
    if not os.getenv("DEEPSEEK_KEY"):
        print("❌ DEEPSEEK_KEY manquante")
        sys.exit(1)
    
    # Parse arguments
    mode, consignes_file = parse_args()
    
    if not consignes_file or not os.path.exists(consignes_file):
        print("❌ Fichier de consignes introuvable")
        sys.exit(1)
    
    print(f"📄 Fichier: {consignes_file}")
    print(f"🔧 Mode: {mode}")
    
    # Extraire la requête principale
    filename = os.path.basename(consignes_file)
    main_query = filename[10:-5]  # Enlever 'consignes_' et '.json'
    
    # Charger les données
    articles, groups_queries = load_data(consignes_file)
    
    # Exécuter selon le mode
    if mode == "optimized":
        await run_optimized(articles, groups_queries, main_query)
    else:
        await run_legacy(articles, groups_queries, main_query)


if __name__ == "__main__":
    asyncio.run(main())