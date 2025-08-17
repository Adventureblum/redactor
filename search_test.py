# run_saved_prompt_interactif.py
# -*- coding: utf-8 -*-
import os
import sys
import time
import json
import re
from openai import OpenAI

PROMPT_ID = "pmpt_6880b85244388194931adba72102ad0e0566462e25146fc8"
MODEL = "gpt-4o"
JSON_FILE = "resultats_recherche.json"

def ensure_api_key() -> str:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("❌ Erreur: la variable d'environnement OPENAI_API_KEY est absente.", file=sys.stderr)
        sys.exit(1)
    return api_key

def main():
    api_key = ensure_api_key()
    client = OpenAI(api_key=api_key)

    print("=== Terminal Recherche Web (via Prompt Sauvegardé) ===\n")

    while True:
        query = input("🔎 Votre requête (ou 'q' pour quitter): ")
        if query.lower() in ["q", "quit", "exit"]:
            print("Fin de session.")
            break

        try:
            # Étape 1 : lancement de la requête
            response = client.responses.create(
                prompt={"id": PROMPT_ID, "version": "4"},
                model=MODEL,
                input=[{
                    "type": "message",
                    "role": "user",
                    "content": query
                }],
                stream=False
            )

            # Étape 2 : attendre la complétion
            while True:
                updated = client.responses.retrieve(response.id)
                if updated.status == "completed":
                    break
                elif updated.status in ["failed", "cancelled"]:
                    print(f"❌ L'exécution a échoué ({updated.status}).")
                    return
                time.sleep(1)

            # Étape 3 : affichage brut (debug)
            print("\n=== RÉPONSE GPT BRUTE ===")
            print(json.dumps(updated.model_dump(), indent=2, ensure_ascii=False))

            # Étape 4 : extraction texte et JSON
            for out in updated.output:
                if out.type == "message" and out.content:
                    content_text = out.content[0].text
                    print("\n📄 Réponse GPT:\n", content_text)

                    # extraction bloc JSON entre ```json ... ```
                    match = re.search(r"```json\n(.*?)```", content_text, re.DOTALL)
                    if match:
                        json_str = match.group(1)
                        try:
                            data = json.loads(json_str)

                            # Charger les résultats existants
                            if os.path.exists(JSON_FILE):
                                with open(JSON_FILE, "r", encoding="utf-8") as f:
                                    try:
                                        existing = json.load(f)
                                        if not isinstance(existing, list):
                                            existing = [existing]
                                    except json.JSONDecodeError:
                                        existing = []
                            else:
                                existing = []

                            existing.append(data)

                            with open(JSON_FILE, "w", encoding="utf-8") as f:
                                json.dump(existing, f, indent=2, ensure_ascii=False)
                            print(f"✅ Résultat ajouté à '{JSON_FILE}' ({len(existing)} total)")
                        except json.JSONDecodeError as err:
                            print("❌ JSON invalide :", err)
                    else:
                        print("⚠️ Aucun bloc JSON détecté dans la réponse.")
                    break
            else:
                print("❌ Aucune réponse texte trouvée.")

        except Exception as e:
            print("Erreur :", str(e))

if __name__ == "__main__":
    main()
