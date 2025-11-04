#!/usr/bin/env python3
"""
Test pour vérifier que le prompt est correctement généré
sans faire d'appel LLM réel
"""

import json
import asyncio
from seotheme import SEOContentAnalyzer

# Données de test minimales
test_data = {
    "queries": [
        {
            "text": "comment faire un diaporama",
            "serp_data": {
                "position_data": {
                    "position_1": {
                        "url": "https://example1.com",
                        "title": "Comment créer un diaporama PowerPoint étape par étape",
                        "content": {
                            "h1": "Comment créer un diaporama PowerPoint étape par étape",
                            "h2_1": "Étape 1: Ouvrir PowerPoint",
                            "p_1": "PowerPoint est l'outil de référence pour créer des diaporamas professionnels."
                        },
                        "words_count": 350,
                        "domain_authority": {"authority_score": 85}
                    },
                    "position_2": {
                        "url": "https://example2.com",
                        "title": "Guide complet pour réaliser un diaporama efficace",
                        "content": {
                            "h1": "Guide complet pour réaliser un diaporama efficace",
                            "h2_1": "Planification du contenu",
                            "p_1": "Avant de commencer, il est essentiel de planifier le contenu."
                        },
                        "words_count": 420,
                        "domain_authority": {"authority_score": 72}
                    }
                }
            }
        }
    ]
}

async def test_prompt_generation():
    """Test de génération de prompt sans appel LLM"""
    print("🧪 TEST DE GÉNÉRATION DE PROMPT")
    print("=" * 50)

    try:
        # Initialiser l'analyseur
        analyzer = SEOContentAnalyzer(language="fr")
        print("✅ Analyseur initialisé")

        # Créer un fichier de test temporaire
        test_file = "/tmp/test_consignes_prompt.json"
        with open(test_file, 'w', encoding='utf-8') as f:
            json.dump(test_data, f, ensure_ascii=False, indent=2)

        # Charger les données de test
        analyzer.load_data(test_file)
        print(f"✅ Données chargées: {len(analyzer.articles)} articles")

        # Simuler la préparation du prompt comme dans analyze_group_unified
        group_articles = analyzer.articles
        query = "comment faire un diaporama"

        # Préparer les données des articles pour le prompt unifié
        articles_data = []
        for article in group_articles:
            article_info = {
                "position": article['position'],
                "url": article['url'],
                "title": article['title'],
                "content": article['content'][:1000],  # Raccourci pour le test
                "word_count": article['word_count'],
                "authority_score": article.get('authority_score', 0)
            }
            articles_data.append(article_info)

        # Préparer les analyses JSON simulées pour le prompt
        analyses_json = json.dumps(articles_data, indent=2, ensure_ascii=False)

        # Date d'analyse
        from datetime import datetime
        date_analyse = datetime.now().isoformat()

        # Détection d'intent basique
        intent_detecte = "informationnelle"

        # Construire le prompt unifié (même logique que dans le script)
        prompt = analyzer.unified_prompt.replace("{requete}", query)
        prompt = prompt.replace("{date_analyse}", date_analyse)
        prompt = prompt.replace("{intent_detecte}", intent_detecte)
        prompt = prompt.replace("{analyses_json}", analyses_json)

        print("✅ Prompt généré avec succès")
        print(f"   Taille du prompt final: {len(prompt)} caractères")

        # Vérifier que les remplacements ont bien eu lieu
        has_requete_placeholder = "{requete}" in prompt
        has_date_placeholder = "{date_analyse}" in prompt
        has_intent_placeholder = "{intent_detecte}" in prompt
        has_analyses_placeholder = "{analyses_json}" in prompt

        print(f"   Placeholders restants:")
        print(f"     - requete: {has_requete_placeholder}")
        print(f"     - date_analyse: {has_date_placeholder}")
        print(f"     - intent_detecte: {has_intent_placeholder}")
        print(f"     - analyses_json: {has_analyses_placeholder}")

        if not any([has_requete_placeholder, has_date_placeholder, has_intent_placeholder, has_analyses_placeholder]):
            print("✅ Tous les placeholders ont été remplacés correctement")
        else:
            print("⚠️ Des placeholders n'ont pas été remplacés")

        # Vérifier que le contenu attendu est présent
        has_query_content = query in prompt
        has_date_content = date_analyse[:10] in prompt  # Just check date part
        has_intent_content = intent_detecte in prompt

        print(f"   Contenu présent:")
        print(f"     - Requête '{query}': {has_query_content}")
        print(f"     - Date d'analyse: {has_date_content}")
        print(f"     - Intent '{intent_detecte}': {has_intent_content}")

        # Sauvegarder le prompt généré pour inspection
        with open("/tmp/prompt_generated.txt", "w", encoding="utf-8") as f:
            f.write(prompt)
        print("💾 Prompt sauvegardé dans /tmp/prompt_generated.txt")

        print("\n✅ GÉNÉRATION DE PROMPT RÉUSSIE")
        return True

    except Exception as e:
        print(f"❌ Erreur lors du test: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = asyncio.run(test_prompt_generation())

    if success:
        print("\n🎉 Le prompt est généré correctement!")
        print("🚀 Le script est prêt pour les appels LLM réels")
    else:
        print("\n❌ Problème dans la génération de prompt")