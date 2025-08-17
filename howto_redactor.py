import os
import json
import openai
from langchain_openai import ChatOpenAI
from langchain.agents import initialize_agent, Tool
from langchain.schema import AgentAction, AgentFinish

openai.api_key = os.environ["OPENAI_API_KEY"]

# 🔧 Initialisation du LLM
llm = ChatOpenAI(temperature=0.7, model="gpt-4o")

# ================================
# 🎯 Analyse du type de tutoriel
# ================================

def analyze_tutorial_type(topic):
    prompt = f"""Analyse le sujet "{topic}" et détermine le type de tutoriel le plus approprié.
    
    Réponds UNIQUEMENT avec un JSON contenant :
    {{
        "type": "technique|créatif|lifestyle|business|éducation|santé|autre",
        "complexity": "débutant|intermédiaire|avancé",
        "duration": "5-15 min|30-60 min|1-3 heures|plusieurs jours|long terme",
        "category": "manuel|intellectuel|pratique|créatif",
        "needs_tools": true/false,
        "step_type": "séquentiel|flexible|modulaire"
    }}"""
    
    response = llm.predict(prompt)
    try:
        return json.loads(response.strip())
    except:
        return {
            "type": "autre",
            "complexity": "intermédiaire", 
            "duration": "30-60 min",
            "category": "pratique",
            "needs_tools": False,
            "step_type": "séquentiel"
        }

# ================================
# 🎯 Génération adaptative de contenu
# ================================

def generate_intro(topic, analysis):
    prompt = f"""Rédige une introduction engageante pour un tutoriel "{topic}".
    
    Contexte du tutoriel :
    - Type : {analysis['type']}
    - Niveau : {analysis['complexity']}
    - Durée estimée : {analysis['duration']}
    - Catégorie : {analysis['category']}
    
    L'introduction doit :
    - Expliquer pourquoi ce sujet est important/utile
    - Définir qui peut bénéficier de ce tutoriel
    - Donner une vue d'ensemble de ce qui sera appris
    - Inclure la durée estimée et le niveau de difficulté
    - Adapter le ton au type de tutoriel (technique, créatif, lifestyle, etc.)
    
    Utilise un ton approprié à la catégorie et au public cible."""
    return llm.predict(prompt)

def generate_prerequisites(topic, analysis):
    if not analysis.get('needs_tools', False) and analysis['complexity'] == 'débutant':
        prompt = f"""Pour le tutoriel "{topic}" (niveau {analysis['complexity']}), 
        explique brièvement les connaissances de base nécessaires ou indique si aucun prérequis n'est nécessaire.
        Reste concis et rassurant."""
    else:
        prompt = f"""Liste les prérequis pour "{topic}" (type: {analysis['type']}, niveau: {analysis['complexity']}).
        
        Inclus selon le contexte :
        - Connaissances/compétences préalables
        - Outils, matériel ou logiciels nécessaires
        - Temps à prévoir
        - Espace/environnement requis
        - Budget approximatif si applicable
        
        Adapte le contenu au type de tutoriel et sois précis mais accessible."""
    return llm.predict(prompt)

def generate_adaptive_steps(topic, analysis):
    if analysis['step_type'] == 'séquentiel':
        prompt = f"""Décompose "{topic}" en étapes chronologiques claires.
        Type: {analysis['type']}, Durée: {analysis['duration']}, Niveau: {analysis['complexity']}
        
        Crée 4-8 étapes qui DOIVENT être suivies dans l'ordre.
        Chaque étape doit être un titre d'action clair."""
        
    elif analysis['step_type'] == 'modulaire':
        prompt = f"""Décompose "{topic}" en modules indépendants.
        Type: {analysis['type']}, Durée: {analysis['duration']}, Niveau: {analysis['complexity']}
        
        Crée 5-7 modules qui peuvent être abordés séparément ou dans un ordre flexible.
        Chaque module doit couvrir un aspect spécifique."""
        
    else:  # flexible
        prompt = f"""Décompose "{topic}" en aspects clés à maîtriser.
        Type: {analysis['type']}, Durée: {analysis['duration']}, Niveau: {analysis['complexity']}
        
        Crée 4-6 sections qui peuvent être explorées selon les besoins et intérêts.
        Chaque section doit traiter un domaine important."""
    
    prompt += "\n\nRetourne seulement la liste des titres, sans numérotation."
    
    response = llm.predict(prompt)
    return [line.strip("-• \n") for line in response.strip().split("\n") if line.strip()]

def generate_step_content(step_title, topic, analysis, step_number, total_steps):
    base_prompt = f"""Rédige le contenu pour "{step_title}" du tutoriel "{topic}".
    
    Contexte :
    - Type de tutoriel : {analysis['type']}
    - Niveau : {analysis['complexity']}
    - Étape {step_number} sur {total_steps}
    - Organisation : {analysis['step_type']}
    
    Le contenu doit inclure :
    """
    
    if analysis['type'] == 'technique':
        specific_prompt = """
        - Instructions techniques précises
        - Commandes, codes ou procédures exactes
        - Vérifications à effectuer
        - Erreurs techniques courantes à éviter"""
        
    elif analysis['type'] == 'créatif':
        specific_prompt = """
        - Techniques créatives et inspiration
        - Conseils artistiques et esthétiques
        - Variations possibles
        - Encouragement à l'expérimentation"""
        
    elif analysis['type'] == 'lifestyle':
        specific_prompt = """
        - Conseils pratiques pour le quotidien
        - Adaptations selon les situations personnelles
        - Bénéfices pour le bien-être
        - Astuces pour maintenir l'habitude"""
        
    elif analysis['type'] == 'business':
        specific_prompt = """
        - Stratégies concrètes et méthodes
        - Indicateurs de performance à suivre
        - Risques et comment les gérer
        - Exemples de mise en pratique"""
        
    elif analysis['type'] == 'éducation':
        specific_prompt = """
        - Concepts clés à retenir
        - Méthodes d'apprentissage efficaces
        - Exercices ou mises en pratique
        - Ressources pour approfondir"""
        
    elif analysis['type'] == 'santé':
        specific_prompt = """
        - Consignes de sécurité importantes
        - Signaux d'alerte à surveiller
        - Adaptations selon les profils
        - Recommandations de suivi"""
        
    else:  # autre
        specific_prompt = """
        - Instructions claires et détaillées
        - Conseils pratiques
        - Points d'attention importants
        - Exemples concrets"""
    
    full_prompt = base_prompt + specific_prompt + f"""
    
    Adapte le vocabulaire au niveau {analysis['complexity']} et utilise 200-300 mots.
    Ton : professionnel mais accessible, encourageant."""
    
    return llm.predict(full_prompt)

def generate_adaptive_bonus_content(topic, analysis):
    if analysis['type'] in ['technique', 'business']:
        section_title = "🔧 Dépannage et optimisation"
        prompt = f"""Pour "{topic}" (type {analysis['type']}), identifie les problèmes courants et leurs solutions.
        Inclus aussi des conseils d'optimisation avancée.
        Format : problème → solution pratique."""
        
    elif analysis['type'] in ['créatif', 'lifestyle']:
        section_title = "💡 Inspiration et variations"
        prompt = f"""Pour "{topic}" (type {analysis['type']}), propose des idées créatives et des variations.
        Inclus des sources d'inspiration et des façons de personnaliser l'approche."""
        
    elif analysis['type'] == 'éducation':
        section_title = "📚 Ressources et approfondissement"
        prompt = f"""Pour "{topic}", suggère des ressources pour aller plus loin.
        Inclus des méthodes d'auto-évaluation et des pistes d'approfondissement."""
        
    elif analysis['type'] == 'santé':
        section_title = "⚠️ Précautions et suivi"
        prompt = f"""Pour "{topic}", liste les précautions importantes et les signes de suivi.
        Rappelle quand consulter un professionnel."""
        
    else:
        section_title = "💡 Conseils avancés"
        prompt = f"""Pour "{topic}", propose des conseils avancés et des astuces d'expert.
        Inclus des optimisations et des erreurs à éviter."""
    
    content = llm.predict(prompt)
    return {"title": section_title, "content": content}

def generate_adaptive_conclusion(topic, analysis):
    prompt = f"""Rédige une conclusion pour le tutoriel "{topic}".
    
    Contexte :
    - Type : {analysis['type']}
    - Niveau : {analysis['complexity']}
    - Durée : {analysis['duration']}
    
    La conclusion doit :
    - Féliciter et encourager le lecteur
    - Résumer les bénéfices acquis
    - Proposer des étapes suivantes adaptées au type de tutoriel
    - Inclure un appel à l'action approprié
    
    Adapte le ton et les recommandations au contexte spécifique."""
    return llm.predict(prompt)

# ================================
# 🤖 Génération d'article adaptatif
# ================================

def create_adaptive_howto_article(topic):
    print("🧠 Analyse du type de tutoriel...")
    analysis = analyze_tutorial_type(topic)
    
    print(f"📊 Tutoriel identifié : {analysis['type']} | {analysis['complexity']} | {analysis['duration']}")
    
    title = f"Comment {topic} : Guide {analysis['complexity']}"
    
    print("✍️ Génération de l'introduction...")
    intro = generate_intro(topic, analysis)
    
    print("📋 Génération des prérequis...")
    prerequisites = generate_prerequisites(topic, analysis)
    
    print("🗂️ Structuration des étapes...")
    step_titles = generate_adaptive_steps(topic, analysis)
    total_steps = len(step_titles)
    
    print(f"📝 Rédaction de {total_steps} étapes...")
    steps = []
    for i, step_title in enumerate(step_titles, 1):
        print(f"➡️  {analysis['step_type'].title()} {i}/{total_steps} : {step_title}")
        content = generate_step_content(step_title, topic, analysis, i, total_steps)
        steps.append({
            "step_number": i,
            "title": step_title,
            "content": content
        })
    
    print("🌟 Génération du contenu bonus...")
    bonus_content = generate_adaptive_bonus_content(topic, analysis)
    
    print("✅ Rédaction de la conclusion...")
    conclusion = generate_adaptive_conclusion(topic, analysis)
    
    return {
        "title": title,
        "topic": topic,
        "analysis": analysis,
        "intro": intro,
        "prerequisites": prerequisites,
        "steps": steps,
        "bonus_section": bonus_content,
        "conclusion": conclusion,
        "metadata": {
            "total_steps": total_steps,
            "tutorial_type": analysis['type'],
            "complexity_level": analysis['complexity'],
            "estimated_duration": analysis['duration'],
            "step_organization": analysis['step_type'],
            "article_type": "adaptive_how_to"
        }
    }

# ================================
# 📄 Export HTML adaptatif
# ================================

def generate_adaptive_html(article_data, filename, output_filename=None):
    analysis = article_data['analysis']
    
    # Couleurs selon le type
    color_schemes = {
        'technique': {'primary': '#2c3e50', 'secondary': '#3498db', 'accent': '#e74c3c'},
        'créatif': {'primary': '#8e44ad', 'secondary': '#e74c3c', 'accent': '#f39c12'},
        'lifestyle': {'primary': '#27ae60', 'secondary': '#2ecc71', 'accent': '#f1c40f'},
        'business': {'primary': '#34495e', 'secondary': '#95a5a6', 'accent': '#e67e22'},
        'éducation': {'primary': '#2980b9', 'secondary': '#3498db', 'accent': '#9b59b6'},
        'santé': {'primary': '#e74c3c', 'secondary': '#ec7063', 'accent': '#f8c471'},
        'autre': {'primary': '#7f8c8d', 'secondary': '#95a5a6', 'accent': '#bdc3c7'}
    }
    
    colors = color_schemes.get(analysis['type'], color_schemes['autre'])
    
    # Icônes selon le type
    type_icons = {
        'technique': '🔧', 'créatif': '🎨', 'lifestyle': '🌟',
        'business': '💼', 'éducation': '📚', 'santé': '💊', 'autre': '📝'
    }
    
    icon = type_icons.get(analysis['type'], '📝')
    
    html_content = f"""<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{article_data['title']}</title>
    <style>
        body {{ 
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; 
            max-width: 900px; margin: 0 auto; padding: 20px; 
            line-height: 1.7; color: #333; background: #fafafa;
        }}
        .header {{ background: linear-gradient(135deg, {colors['primary']}, {colors['secondary']}); 
                   color: white; padding: 30px; border-radius: 15px; margin-bottom: 30px; text-align: center; }}
        h1 {{ margin: 0; font-size: 2.2em; }}
        .tutorial-info {{ background: rgba(255,255,255,0.2); padding: 15px; border-radius: 10px; margin-top: 20px; }}
        .tutorial-info span {{ background: rgba(255,255,255,0.3); padding: 5px 10px; border-radius: 15px; margin: 5px; display: inline-block; }}
        
        h2 {{ color: {colors['primary']}; margin-top: 40px; border-bottom: 2px solid {colors['secondary']}; padding-bottom: 10px; }}
        
        .section {{ background: white; padding: 25px; margin: 20px 0; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
        .prerequisites {{ border-left: 4px solid {colors['accent']}; }}
        
        .step {{ background: white; padding: 25px; margin: 20px 0; border-radius: 10px; 
                 box-shadow: 0 2px 10px rgba(0,0,0,0.1); border-left: 4px solid {colors['secondary']}; }}
        .step-header {{ display: flex; align-items: center; margin-bottom: 15px; }}
        .step-number {{ 
            background: linear-gradient(135deg, {colors['primary']}, {colors['secondary']});
            color: white; width: 40px; height: 40px; border-radius: 50%; 
            display: flex; align-items: center; justify-content: center; 
            margin-right: 15px; font-weight: bold; font-size: 1.2em;
        }}
        .step-title {{ font-size: 1.3em; font-weight: 600; color: {colors['primary']}; }}
        
        .bonus-section {{ background: linear-gradient(135deg, #f8f9fa, #e9ecef); 
                         border: 2px solid {colors['accent']}; border-radius: 10px; padding: 25px; }}
        .conclusion {{ background: linear-gradient(135deg, {colors['primary']}, {colors['secondary']}); 
                      color: white; border-radius: 10px; padding: 25px; }}
        
        .complexity-badge {{ 
            background: {colors['accent']}; color: white; padding: 5px 15px; 
            border-radius: 20px; font-size: 0.9em; display: inline-block; margin: 10px 0;
        }}
        
        @media (max-width: 768px) {{
            body {{ padding: 10px; }}
            .header {{ padding: 20px; }}
            h1 {{ font-size: 1.8em; }}
            .step {{ padding: 15px; }}
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>{icon} {article_data['title']}</h1>
        <div class="tutorial-info">
            <span>📊 {analysis['type'].title()}</span>
            <span>⏱️ {analysis['duration']}</span>
            <span>🎯 {analysis['complexity'].title()}</span>
            <span>📋 {analysis['step_type'].title()}</span>
        </div>
    </div>

    <div class="section">
        <h2>🚀 Introduction</h2>
        <p>{article_data['intro']}</p>
    </div>

    <div class="section prerequisites">
        <h2>🎯 Prérequis</h2>
        <p>{article_data['prerequisites']}</p>
    </div>

    <h2>📝 Guide étape par étape</h2>
"""
    
    for step in article_data['steps']:
        html_content += f"""
    <div class="step">
        <div class="step-header">
            <span class="step-number">{step['step_number']}</span>
            <span class="step-title">{step['title']}</span>
        </div>
        <div class="step-content">
            <p>{step['content']}</p>
        </div>
    </div>
"""
    
    html_content += f"""
    <div class="bonus-section">
        <h2>{article_data['bonus_section']['title']}</h2>
        <p>{article_data['bonus_section']['content']}</p>
    </div>

    <div class="conclusion">
        <h2>🎉 Conclusion</h2>
        <p>{article_data['conclusion']}</p>
    </div>
</body>
</html>"""
    
    html_filename = output_filename if output_filename else filename.replace('.json', '.html')
    with open(html_filename, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    return html_filename

# ================================
# 🧪 Main
# ================================

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Générateur d'articles 'How To' adaptatif")
    parser.add_argument("--input", type=str, help="Fichier JSON d'entrée avec les données")
    parser.add_argument("--output", type=str, help="Fichier HTML de sortie")
    parser.add_argument("--topic", type=str, help="Sujet du tutoriel")
    
    args = parser.parse_args()
    
    if args.input:
        # Mode fichier d'entrée
        try:
            with open(args.input, 'r', encoding='utf-8') as f:
                input_data = json.load(f)
            
            # Extraction du sujet depuis les données d'entrée
            topic = input_data.get('title', input_data.get('section_title', input_data.get('query', 'tutoriel')))
            
        except Exception as e:
            print(f"❌ Erreur lecture fichier {args.input}: {e}")
            return
    elif args.topic:
        topic = args.topic
    else:
        # Mode interactif original
        print("🎯 Générateur d'articles 'How To' adaptatif")
        print("=" * 50)
        print("🔍 Ce générateur s'adapte automatiquement à votre sujet !")
        print()
        
        # Exemples pour inspiration
        print("💡 Exemples de sujets :")
        examples = [
            "créer une application mobile",
            "méditer au quotidien", 
            "lancer son entreprise",
            "apprendre le piano",
            "optimiser son CV",
            "cultiver des légumes",
            "gérer son stress"
        ]
        for i, example in enumerate(examples, 1):
            print(f"   {i}. {example}")
        print()
        
        topic = input("📝 Votre sujet de tutoriel : ")
    
    if not topic.strip():
        print("❌ Veuillez saisir un sujet valide.")
        return
    
    print(f"\n🚀 Génération de l'article adaptatif sur '{topic}'...")
    article = create_adaptive_howto_article(topic)

    # Génération du nom de fichier sécurisé
    safe_topic = "".join(c for c in topic.lower() if c.isalnum() or c in (' ', '-', '_')).replace(' ', '_')
    
    if args.output:
        html_filename = args.output
        json_filename = args.output.replace('.html', '.json') if args.output.endswith('.html') else f"{args.output}.json"
    else:
        json_filename = f"howto_{safe_topic}.json"
        html_filename = f"howto_{safe_topic}.html"
    
    # Sauvegarde JSON
    with open(json_filename, "w", encoding="utf-8") as f:
        json.dump(article, f, ensure_ascii=False, indent=4)

    print(f"\n📄 Article JSON généré : {json_filename}")
    
    # Génération HTML
    html_filename = generate_adaptive_html(article, json_filename, html_filename)
    print(f"🌐 Version HTML générée : {html_filename}")
    
    # Résumé
    print(f"\n✅ Tutoriel '{topic}' généré avec succès !")
    print("📊 Caractéristiques détectées :")
    print(f"   • Type : {article['analysis']['type']}")
    print(f"   • Niveau : {article['analysis']['complexity']}")
    print(f"   • Durée : {article['analysis']['duration']}")
    print(f"   • Organisation : {article['analysis']['step_type']}")
    print(f"   • Nombre d'étapes : {article['metadata']['total_steps']}")

if __name__ == "__main__":
    main()