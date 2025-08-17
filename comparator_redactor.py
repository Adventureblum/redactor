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
# 🎯 Prompts comparatifs
# ================================

def generate_intro(option_a, option_b):
    prompt = f"""Rédige une introduction engageante et optimisée SEO pour un article comparant : {option_a} et {option_b}.
    Présente les deux options, explique pourquoi cette comparaison est pertinente, et annonce les points clés abordés dans l’article.
    Utilise un ton professionnel et informatif adapté à un blog de comparaison."""
    return llm.predict(prompt)

def generate_section_titles(option_a, option_b):
    prompt = f"""Propose 4 titres de sections (H2) pour structurer un article comparatif entre {option_a} et {option_b}.
    Ces titres doivent permettre une comparaison claire, utile et équilibrée. Retourne seulement une liste sans numérotation."""
    response = llm.predict(prompt)
    return [line.strip("-• \n") for line in response.strip().split("\n") if line.strip()]

def generate_section(title, option_a, option_b):
    prompt = f"""Rédige une section comparative d’environ 200 mots sur le thème : "{title}", en comparant {option_a} et {option_b}.
    Analyse objectivement les avantages et inconvénients de chaque option. Utilise un ton clair, structuré et informatif."""
    return llm.predict(prompt)

def generate_conclusion(option_a, option_b):
    prompt = f"""Rédige une conclusion pour un article comparatif entre {option_a} et {option_b}.
    Résume les principaux points abordés et aide le lecteur à choisir selon ses besoins. Termine par un appel à l'action."""
    return llm.predict(prompt)

# ================================
# 🤖 Génération de l'article comparatif
# ================================

def create_comparative_article(option_a, option_b):
    subject = f"Comparatif entre {option_a} et {option_b}"
    print("🔍 Génération du plan comparatif...")
    section_titles = generate_section_titles(option_a, option_b)

    print("✍️ Rédaction de l’introduction...")
    intro = generate_intro(option_a, option_b)

    print("📚 Rédaction des sections comparatives...")
    sections = []
    for title in section_titles:
        print(f"➡️  Section : {title}")
        content = generate_section(title, option_a, option_b)
        sections.append({"title": title, "content": content})

    print("✅ Rédaction de la conclusion...")
    conclusion = generate_conclusion(option_a, option_b)

    return {
        "title": subject,
        "intro": intro,
        "sections": sections,
        "conclusion": conclusion
    }

# ================================
# 🧪 Main
# ================================

def main():
    option_a = input("🔹 Première option à comparer (A) : ")
    option_b = input("🔸 Deuxième option à comparer (B) : ")

    article = create_comparative_article(option_a, option_b)

    # Nom du fichier
    filename = f"comparatif_{option_a.lower().replace(' ', '_')}_vs_{option_b.lower().replace(' ', '_')}.json"
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(article, f, ensure_ascii=False, indent=4)

    print(f"\n📝 Article comparatif généré avec succès : {filename}")

if __name__ == "__main__":
    main()
