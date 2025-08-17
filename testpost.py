# openai_web_search_debug.py
import os, sys, json, argparse
from typing import Any, Dict
from openai import OpenAI

DEFAULT_SCHEMA = {
  "query": "[REQUÊTE UTILISATEUR EN TEXTE ORIGINAL]",
  "summary": "Résumé orienté content marketing avec les 2-3 statistiques les plus percutantes pour accrocher le lecteur [LANGUE DE LA REQUÊTE]",
  "shock_statistics": [
    {
      "statistic": "68% des entreprises échouent à...",
      "source_credibility": "Étude McKinsey 2024 sur 10,000 entreprises",
      "usage_potential": "Accroche d'introduction pour créer l'urgence",
      "context": "Contexte précis de la mesure",
      "url": "https://exemple.com/source"
    }
  ]
}

def extract_text(resp) -> str:
    # Responses API: output_text quand dispo
    if hasattr(resp, "output_text") and resp.output_text:
        return resp.output_text
    # fallback générique (en fonction de la version SDK)
    try:
        return resp.output[0].content[0].text
    except Exception:
        return str(resp)

def extract_json_or_braces(s: str) -> dict:
    try:
        return json.loads(s)
    except Exception:
        start, end = s.find("{"), s.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = s[start:end+1]
            return json.loads(candidate)
        raise ValueError("Impossible d'extraire un JSON valide.")

def print_tool_debug(resp) -> None:
    """Affiche ce que l’outil web_search a vraiment renvoyé (URLs, titres…)."""
    # Selon le SDK, les tool calls/outputs sont dans resp.output[...] ou resp.tools / resp.steps
    # On tente plusieurs chemins courants.
    any_found = False

    def _print_hit(hit, idx):
        title = hit.get("title") or hit.get("name") or "(sans titre)"
        url = hit.get("url") or hit.get("link") or "(sans url)"
        snippet = hit.get("content") or hit.get("snippet") or ""
        print(f"  [{idx}] {title}\n      {url}\n      {snippet[:200]}")

    # 1) steps + tool executions (nouveau SDK)
    steps = getattr(resp, "steps", []) or []
    for s in steps:
        if getattr(s, "type", "") == "tool_execution" and getattr(s, "tool", "") == "web_search":
            any_found = True
            print("\n🧪 DEBUG — web_search exécuté (via steps):")
            out = getattr(s, "output", None)
            if isinstance(out, dict):
                results = out.get("results") or out.get("data") or []
                for i, r in enumerate(results, 1):
                    _print_hit(r, i)

    # 2) tool calls/outputs “classiques” dans output
    outputs = getattr(resp, "output", []) or []
    for block in outputs:
        if getattr(block, "type", "") == "tool_result" and getattr(block, "tool_name", "") == "web_search":
            any_found = True
            print("\n🧪 DEBUG — web_search exécuté (via output tool_result):")
            try:
                payload = block.content[0].input  # selon SDK
            except Exception:
                payload = getattr(block, "content", None)
            if isinstance(payload, dict):
                results = payload.get("results") or payload.get("data") or []
                for i, r in enumerate(results, 1):
                    _print_hit(r, i)
            elif isinstance(payload, list):
                for i, r in enumerate(payload, 1):
                    if isinstance(r, dict):
                        _print_hit(r, i)

    if not any_found:
        print("\n🧪 DEBUG — Aucune exécution de web_search détectée (le modèle a peut-être répondu sans chercher).")

def main():
    p = argparse.ArgumentParser()
    p.add_argument("query", help="Votre requête (texte)")
    p.add_argument("--model", default="gpt-4o-mini", help="Modèle (ex: gpt-4o, gpt-4o-mini)")
    p.add_argument("--force-web", action="store_true", help="Forcer l'usage de l'outil web_search")
    p.add_argument("--raw", action="store_true", help="Afficher la sortie brute si parsing JSON échoue")
    args = p.parse_args()

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("Erreur: OPENAI_API_KEY non défini")
        sys.exit(1)

    client = OpenAI(api_key=api_key)

    system = (
        "Tu es un expert en content marketing. "
        "Utilise la recherche web pour sourcer et vérifier. "
        "Réponds UNIQUEMENT en JSON valide. "
        "La langue de sortie = langue de la requête. "
        "Chaque élément de 'shock_statistics' DOIT inclure un champ 'url' pointant vers la source exacte."
    )

    schema_block = json.dumps(DEFAULT_SCHEMA, ensure_ascii=False, indent=2)

    tool_choice = "auto"
    if args.force_web:
        # Force l’appel de l’outil (quand c’est supporté)
        tool_choice = {"type": "web_search"}

    resp = client.responses.create(
        model=args.model,
        tools=[{"type": "web_search"}],
        tool_choice=tool_choice,
        input=[
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": (
                    f"Requête utilisateur:\n{args.query}\n\n"
                    "Contraintes:\n"
                    "- Utilise l'outil de web search pour trouver des données actuelles et sourcées (avec URL).\n"
                    "- Ne renvoie que du JSON strictement conforme au modèle ci-dessous.\n"
                    "- Les statistiques doivent être chiffrées, récentes (2023+), avec éditeur/étude + année + URL exacte."
                ),
            },
            {"role": "user", "content": "Modèle JSON à respecter STRICTEMENT :\n" + schema_block},
        ],
        # Exemple d’options possibles (si dispo sur ton compte) :
        # web_search_options={"max_results": 8}
    )

    # === DEBUG: affiche les résultats bruts du web_search ===
    print_tool_debug(resp)

    # === Rendu final JSON ===
    text = extract_text(resp)
    try:
        data = extract_json_or_braces(text)
        # S'assure d'inclure la requête originale si manquante
        if isinstance(data, dict) and "query" not in data:
            data["query"] = args.query
        print("\n=== SORTIE JSON ===")
        print(json.dumps(data, ensure_ascii=False, indent=2))
    except Exception as e:
        print("\n⚠️ Parsing JSON impossible :", e)
        if args.raw:
            print("\n--- Sortie brute ---")
            print(text)
        sys.exit(2)

if __name__ == "__main__":
    main()
