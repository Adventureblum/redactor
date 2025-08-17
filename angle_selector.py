# angle_selector_refactored.py

import os
import sys
import json
import glob
import time
from pathlib import Path
from typing import List, Dict, Any, Optional
import requests


class DeepSeekClient:
    def __init__(self, api_key: str, model: str = "deepseek-chat"):
        self.api_key = api_key
        self.model = model
        self.base_url = "https://api.deepseek.com/v1"
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

    def chat(self, system_prompt: str, user_prompt: str, temperature: float = 0.7, max_tokens: int = 2000):
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False
        }

        response = requests.post(f"{self.base_url}/chat/completions", headers=self.headers, json=payload)
        response.raise_for_status()
        return response.json()


class PromptLoader:
    def __init__(self, prompts_dir: str):
        self.prompts_dir = Path(prompts_dir)
        self.system_prompt = self._load("angle_selector_system.txt")

    def _load(self, filename: str) -> str:
        path = self.prompts_dir / filename
        if not path.exists():
            raise FileNotFoundError(f"Prompt manquant : {filename}")
        return path.read_text(encoding='utf-8')


class AngleSelector:
    def __init__(self, consigne_path: str, deepseek_key: str, prompts_dir: str):
        self.consigne_path = consigne_path
        self.deepseek = DeepSeekClient(deepseek_key)
        self.prompts = PromptLoader(prompts_dir)
        self.consigne_data = self._load_consigne()

    def _load_consigne(self) -> Dict:
        with open(self.consigne_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def _save_consigne(self):
        with open(self.consigne_path, 'w', encoding='utf-8') as f:
            json.dump(self.consigne_data, f, ensure_ascii=False, indent=4)

    def list_queries(self) -> List[Dict[str, Any]]:
        queries = []
        for query in self.consigne_data.get("queries", []):
            has_angles = 'differentiating_angles' in query
            has_analysis = 'angle_analysis' in query
            angles_count = len(query.get('differentiating_angles', []))

            if has_analysis:
                status = "🟢 Analysé"
            elif has_angles and angles_count > 0:
                status = f"🟡 {angles_count} angles prêts"
            else:
                status = "🔴 Pas d'angles"

            queries.append({
                'id': query['id'],
                'text': query['text'],
                'status': status,
                'has_angles': has_angles,
                'has_analysis': has_analysis
            })
        return queries

    def select_query_ids(self) -> List[int]:
        queries = self.list_queries()

        print("\n📋 Requêtes disponibles :")
        for q in queries:
            print(f"ID {q['id']:2d} | {q['status']} | {q['text']}")

        print("\n💡 Sélectionnez les requêtes à analyser :")
        print("- ID unique : 5")
        print("- Plusieurs IDs : 1,3,5")
        print("- Plage : 1-5")
        print("- 'all' pour toutes non-analysées avec angles")
        print("- 'q' pour quitter")

        while True:
            user_input = input("\n🎯 Votre sélection : ").strip().lower()

            if user_input == 'q':
                print("👋 Sortie.")
                sys.exit(0)

            if user_input == 'all':
                return [q['id'] for q in queries if q['has_angles'] and not q['has_analysis']]

            try:
                if '-' in user_input:
                    start, end = map(int, user_input.split('-'))
                    return list(range(start, end + 1))
                elif ',' in user_input:
                    return [int(x.strip()) for x in user_input.split(',')]
                else:
                    return [int(user_input)]
            except Exception:
                print("❌ Format invalide. Réessayez.")

    def process_query(self, query_id: int):
        query = next((q for q in self.consigne_data["queries"] if q.get("id") == query_id), None)
        if not query or not query.get("differentiating_angles"):
            print(f"⚠️ Requête {query_id} non exploitable.")
            return

        system_prompt = self.prompts.system_prompt
        user_prompt = self._build_user_prompt(query)

        print(f"\n📤 Envoi à DeepSeek pour requête ID {query_id} : {query['text']}")
        try:
            response = self.deepseek.chat(system_prompt, user_prompt)
            content = response['choices'][0]['message']['content'].strip()

            if content.startswith("```json"):
                content = content[7:].strip()
            if content.endswith("```"):
                content = content[:-3].strip()

            result = json.loads(content)
            query["angle_analysis"] = result
            query["analysis_method"] = "deepseek_angle_selector_dual_prompt"
            self._save_consigne()
            print(f"✅ Résultat enregistré : {result.get('angle_recommande')} ({result.get('score_total')})")

        except Exception as e:
            print(f"❌ Erreur lors de l'analyse : {e}")

    def _build_user_prompt(self, query: Dict[str, Any]) -> str:
        angles = query.get("differentiating_angles", [])
        requete = query.get("text", "")
        angles_formates = "\n".join(f"- {a}" for a in angles)
        return (
            f"Requête cible : {requete}\n"
            f"Angles proposés à analyser :\n{angles_formates}"
        )

    def process_batch(self, ids: List[int]):
        print(f"\n🔁 Traitement de {len(ids)} requête(s) : {ids}")
        for query_id in ids:
            self.process_query(query_id)


if __name__ == "__main__":
    deepseek_key = os.getenv("DEEPSEEK_KEY")
    if not deepseek_key:
        print("❌ Clé API DeepSeek manquante dans les variables d'environnement.")
        sys.exit(1)

    static_dir = Path("static")
    consigne_files = sorted(static_dir.glob("consigne*.json"), key=os.path.getmtime, reverse=True)
    if not consigne_files:
        print("❌ Aucun fichier consigne trouvé dans le dossier static/")
        sys.exit(1)

    latest_consigne = consigne_files[0]
    selector = AngleSelector(str(latest_consigne), deepseek_key, prompts_dir="prompts")

    ids_to_process = selector.select_query_ids()
    selector.process_batch(ids_to_process)
