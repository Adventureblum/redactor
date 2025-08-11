
import os
import json
import glob
from openai import OpenAI
from pathlib import Path

class SemanticPlanGenerator:
    def __init__(self) -> None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise EnvironmentError("La variable d'environnement OPENAI_API_KEY n'est pas définie.")
        self.client = OpenAI(api_key=api_key)

    def generate_plan(self, query_data: dict) -> dict:
        """
        Génère un plan sémantique pour une requête spécifique
        """
        # Préparation des données d'entrée pour l'IA
        input_data = {
            "id": query_data.get("id"),
            "text": query_data.get("text"),
            "word_count": query_data.get("word_count"),
            "top_keywords": query_data.get("top_keywords"),
            "differentiating_angles": query_data.get("differentiating_angles", []),
            "semantic_analysis": query_data.get("semantic_analysis", {}),
            "agent_response": query_data.get("agent_response", {}),
            "plan": query_data.get("plan", {})
        }

        prompt_input = json.dumps(input_data, ensure_ascii=False, indent=2)

        response = self.client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": (
                        f"""Tu es un expert en content marketing qui crée des guides HowTo ultra-performants basés sur des DONNÉES FACTUELLES et STATISTIQUES EXCLUSIVES.

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
- "L'outil qui génère +{benchmark_ROI}% selon notre étude exclusive..."
- "Mes clients qui utilisent X obtiennent {résultat_chiffré} en moyenne..."
- "La méthode qui surperforme de {comparatif_concurrence}% vs la concurrence..."
- "Le framework testé sur {échantillon} utilisateurs avec {taux_succès}% de réussite..."

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

                    )
                },
                {
                    "role": "user",
                    "content": prompt_input
                }
            ],
            response_format={"type": "text"},
            temperature=1,
            max_tokens=7548,
            top_p=1,
            frequency_penalty=0.0,
            presence_penalty=0.0
        )

        if response.choices and response.choices[0].message.content:
            try:
                return json.loads(response.choices[0].message.content)
            except json.JSONDecodeError:
                return {"plan": response.choices[0].message.content}
        else:
            raise ValueError("Réponse vide de l'API")

def find_consigne_file():
    """
    Trouve le fichier consigneXX.json dans le dossier static
    """
    static_dir = "static"
    current_dir = os.getcwd()
    print(f"Répertoire courant: {current_dir}")
    print(f"Recherche dans le dossier: {static_dir}")
    
    # Vérifier si le dossier static existe
    if not os.path.exists(static_dir):
        raise FileNotFoundError(f"Le dossier '{static_dir}' n'existe pas dans {current_dir}")
    
    # Chercher les fichiers dans le dossier static
    pattern = os.path.join(static_dir, "consigne*.json")
    files = glob.glob(pattern)
    print(f"Fichiers trouvés avec le pattern '{pattern}': {files}")
    
    if not files:
        # Debug: afficher tous les fichiers JSON dans static
        all_json_files = glob.glob(os.path.join(static_dir, "*.json"))
        print(f"Tous les fichiers JSON dans {static_dir}: {all_json_files}")
        raise FileNotFoundError(f"Aucun fichier consigne*.json trouvé dans le dossier {static_dir}")
    
    if len(files) > 1:
        print(f"Plusieurs fichiers trouvés: {files}")
        selected_file = max(files, key=os.path.getctime)
        print(f"Utilisation du plus récent: {selected_file}")
        return selected_file
    
    return files[0]

def main():
    try:
        # Trouver le fichier consigne
        input_file = find_consigne_file()
        print(f"Fichier trouvé: {input_file}")
        
        # Charger les données
        with open(input_file, "r", encoding="utf-8") as file:
            data = json.load(file)

        generator = SemanticPlanGenerator()
        
        # Traiter chaque requête dans la liste "queries"
        if "queries" in data and isinstance(data["queries"], list):
            # Filtrer les requêtes qui ont la clé top_keywords
            valid_queries = [q for q in data["queries"] if "top_keywords" in q]
            skipped_queries = [q for q in data["queries"] if "top_keywords" not in q]
            
            print(f"Requêtes trouvées: {len(data['queries'])}")
            print(f"Requêtes avec top_keywords: {len(valid_queries)}")
            print(f"Requêtes ignorées (sans top_keywords): {len(skipped_queries)}")
            
            if skipped_queries:
                print("Requêtes ignorées:")
                for query in skipped_queries:
                    print(f"  - ID {query.get('id', 'N/A')}: '{query.get('text', 'N/A')}'")
                print()
            
            for i, query in enumerate(valid_queries):
                print(f"Génération du plan pour la requête {i+1}/{len(valid_queries)}: '{query.get('text', 'N/A')}'")
                
                try:
                    # Vérifier si un plan existe déjà
                    if "generated_plan" in query:
                        print(f"⚠️  Un plan existe déjà pour cette requête, il sera écrasé")
                    
                    # Générer le plan pour cette requête
                    plan_data = generator.generate_plan(query)
                    
                    # Ajouter le plan généré à la requête
                    query["generated_plan"] = plan_data
                    
                    print(f"✅ Plan généré avec succès pour: '{query.get('text', 'N/A')}'")
                    
                except Exception as e:
                    print(f"❌ Erreur lors de la génération du plan pour '{query.get('text', 'N/A')}': {str(e)}")
                    query["generated_plan"] = {"error": str(e)}
        
        # Sauvegarder le fichier modifié
        with open(input_file, "w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)

        print(f"\n🎉 Tous les plans ont été générés et sauvegardés dans {input_file}")
        print(f"Nombre de requêtes valides traitées: {len([q for q in data.get('queries', []) if 'top_keywords' in q])}")
        print(f"Nombre total de requêtes dans le fichier: {len(data.get('queries', []))}")

    except FileNotFoundError as e:
        print(f"❌ Erreur : {str(e)}")
    except json.JSONDecodeError:
        print(f"❌ Erreur : Le fichier contient une erreur JSON.")
    except Exception as e:
        print(f"❌ Erreur lors de l'appel à l'API ou du traitement des données : {str(e)}")

if __name__ == "__main__":
    main()