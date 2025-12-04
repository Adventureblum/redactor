#!/usr/bin/env python3
"""
Mini SEO Semantic Analyzer
Auto-detect consignes file in static/consignesrun
"""

import json
import os
import asyncio
from langchain_deepseek import ChatDeepSeek


# ============================================================
#     AUTO-DETECTION DU FICHIER CONSIGNES
# ============================================================

def auto_detect_consignes():
    folder = "static/consignesrun"

    if not os.path.exists(folder):
        raise FileNotFoundError(f"Dossier introuvable : {folder}")

    files = [
        f for f in os.listdir(folder)
        if f.startswith("consignes_") and f.endswith(".json")
    ]

    if not files:
        raise FileNotFoundError(
            f"Aucun fichier consignes_*.json trouvé dans {folder}"
        )

    # On prend le premier trié (comme ton script original)
    file_path = os.path.join(folder, sorted(files)[0])

    print(f"📄 Fichier consignes détecté automatiquement : {file_path}")
    return file_path


# ============================================================
#               LECTURE DU FICHIER CONSIGNES
# ============================================================

def load_top3_articles(consignes_file: str):
    """Charge uniquement les 3 premières positions de chaque requête."""
    with open(consignes_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    articles = []

    for q_index, query_block in enumerate(data["queries"]):
        query_text = query_block.get("text", "").strip()
        positions = query_block.get("serp_data", {}).get("position_data", {})

        for pos in [1, 2, 3]:
            key = f"position_{pos}"
            if key not in positions:
                continue

            info = positions[key]
            title = info.get("title", "")
            url = info.get("url", "")
            content_dict = info.get("content", {})

            # reconstruction du contenu
            parts = []
            if "h1" in content_dict:
                parts.append("# " + content_dict["h1"])

            for k in sorted(content_dict.keys()):
                val = str(content_dict[k]).strip()
                if not val:
                    continue
                if k.startswith("h2"):
                    parts.append("## " + val)
                elif k.startswith("h3"):
                    parts.append("### " + val)
                elif k.startswith("p"):
                    parts.append(val)

            content = "\n\n".join(parts)

            article = {
                "id": f"query_{q_index}_position_{pos}",
                "position": pos,
                "title": title,
                "url": url,
                "content": content,
                "query": query_text,
                "analysis_group": q_index,
                "word_count": len(content.split()),
                "authority_score": info.get("domain_authority", {}).get("authority_score", 0),
                "words_count_json": info.get("words_count", 0)
            }

            articles.append(article)

    print(f"📌 {len(articles)} articles chargés (top 3 positions)")
    return articles


# ============================================================
#                    CHARGEMENT PROMPT SEMANTIC
# ============================================================

def load_semantic_prompt():
    path = os.path.join(os.path.dirname(__file__), "prompts", "semantic.txt")
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip()


# ============================================================
#                    AGENT SEMANTIC
# ============================================================

class SemanticAnalyzer:
    def __init__(self):
        self.llm = ChatDeepSeek(
            model="deepseek-chat",
            api_key=os.environ["DEEPSEEK_KEY"],
            max_tokens=3000,
            temperature=0.1
        )
        self.prompt = load_semantic_prompt()

    async def analyze_article(self, article):
        print(f"🔍 Analyse P{article['position']} : {article['title'][:50]}")

        user_vars = f"""
Position: {article['position']}
Titre: {article['title']}
Contenu: {article['content'][:15000]}
Requête: {article['query']}
Word count: {article['word_count']}
Authority score: {article['authority_score']}
"""

        full_prompt = f"""{self.prompt}

=== VARIABLES ===
{user_vars}

IMPORTANT : réponse en JSON strict uniquement.
"""

        res = await asyncio.get_event_loop().run_in_executor(
            None, lambda: self.llm.invoke(full_prompt)
        )

        return {
            "article_id": article["id"],
            "raw_response": res.content
        }


# ============================================================
#                     PIPELINE PRINCIPAL
# ============================================================

async def run_pipeline(consignes_file=None):

    # Si aucun fichier fourni → auto-detection
    if not consignes_file:
        consignes_file = auto_detect_consignes()

    articles = load_top3_articles(consignes_file)
    analyzer = SemanticAnalyzer()

    tasks = [analyzer.analyze_article(a) for a in articles]
    results = await asyncio.gather(*tasks)

    out = "semantic_results.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n💾 Résultats sauvegardés dans {out}")


if __name__ == "__main__":
    asyncio.run(run_pipeline())
