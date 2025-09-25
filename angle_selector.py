# angle_selector_refactored.py

import os
import sys
import json
import glob
import time
import asyncio
import aiohttp
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

    async def chat_async(self, system_prompt: str, user_prompt: str, temperature: float = 0.7, max_tokens: int = 2000, timeout: int = 30):
        """Version asynchrone pour le traitement en parallèle"""
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

        timeout_obj = aiohttp.ClientTimeout(total=timeout)
        async with aiohttp.ClientSession(timeout=timeout_obj) as session:
            async with session.post(
                f"{self.base_url}/chat/completions", 
                headers=self.headers, 
                json=payload
            ) as response:
                response.raise_for_status()
                return await response.json()


class PromptLoader:
    def __init__(self, prompts_dir: str):
        self.prompts_dir = Path(prompts_dir)
        self.system_prompt = self._load("angle_selector_system.md")

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

    def get_ready_queries(self) -> List[int]:
        """Trouve automatiquement toutes les requêtes prêtes à être traitées"""
        queries = self.list_queries()
        ready_ids = [q['id'] for q in queries if q['has_angles'] and not q['has_analysis']]
        return ready_ids

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
        print("- 'auto' pour traitement automatique en batch")
        print("- 'parallel' pour traitement parallèle (comme serp_semantic_batch.py)")
        print("- 'q' pour quitter")

        while True:
            user_input = input("\n🎯 Votre sélection : ").strip().lower()

            if user_input == 'q':
                print("👋 Sortie.")
                sys.exit(0)

            if user_input == 'all':
                return [q['id'] for q in queries if q['has_angles'] and not q['has_analysis']]
            
            if user_input == 'auto':
                return self.get_ready_queries()
            
            if user_input == 'parallel':
                ready_ids = self.get_ready_queries()
                if ready_ids:
                    print(f"\n🚀 Lancement du traitement parallèle pour {len(ready_ids)} requête(s)")
                    asyncio.run(self.process_batch_parallel(ready_ids, max_concurrent=3))
                    return []
                else:
                    print("✅ Aucune requête prête à traiter.")
                    return []

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

    async def process_query_async(self, query_id: int) -> bool:
        """Version asynchrone pour le traitement en parallèle"""
        query = next((q for q in self.consigne_data["queries"] if q.get("id") == query_id), None)
        if not query or not query.get("differentiating_angles"):
            print(f"⚠️ Requête {query_id} non exploitable.")
            return False

        system_prompt = self.prompts.system_prompt
        user_prompt = self._build_user_prompt(query)

        print(f"\n📤 Envoi async à DeepSeek pour requête ID {query_id} : {query['text'][:50]}...")
        try:
            response = await self.deepseek.chat_async(system_prompt, user_prompt)
            content = response['choices'][0]['message']['content'].strip()

            if content.startswith("```json"):
                content = content[7:].strip()
            if content.endswith("```"):
                content = content[:-3].strip()

            result = json.loads(content)
            query["angle_analysis"] = result
            query["analysis_method"] = "deepseek_angle_selector_parallel"
            print(f"✅ Résultat async reçu pour ID {query_id} : {result.get('angle_recommande')} ({result.get('score_total')})")
            return True

        except Exception as e:
            print(f"❌ Erreur async pour requête {query_id} : {e}")
            return False

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

    def process_all_ready(self):
        """Traite automatiquement toutes les requêtes prêtes à être analysées"""
        ready_ids = self.get_ready_queries()
        if not ready_ids:
            print("✅ Aucune requête prête à traiter (toutes déjà analysées ou sans angles).")
            return
        
        print(f"\n🎯 Détection automatique de {len(ready_ids)} requête(s) prête(s) à traiter : {ready_ids}")
        confirmation = input("Procéder au traitement automatique ? (o/n) : ").strip().lower()
        
        if confirmation in ['o', 'oui', 'y', 'yes']:
            self.process_batch(ready_ids)
            print(f"✅ Traitement batch terminé pour {len(ready_ids)} requête(s).")
        else:
            print("⏸️ Traitement annulé par l'utilisateur.")

    def process_all_ready_automatic(self):
        """Traite automatiquement toutes les requêtes prêtes sans confirmation (comme serp_semantic_batch.py)"""
        ready_ids = self.get_ready_queries()
        if not ready_ids:
            print("✅ Aucune requête prête à traiter (toutes déjà analysées ou sans angles).")
            return
        
        print(f"\n🎯 Traitement automatique de {len(ready_ids)} requête(s) prête(s) : {ready_ids}")
        self.process_batch(ready_ids)
        print(f"✅ Traitement batch automatique terminé pour {len(ready_ids)} requête(s).")

    async def process_batch_parallel(self, ids: List[int], max_concurrent: int = 3):
        """Traite les requêtes en parallèle comme serp_semantic_batch.py"""
        if not ids:
            print("✅ Aucune requête à traiter.")
            return
        
        print(f"\n🚀 Traitement parallèle de {len(ids)} requête(s) : {ids}")
        print(f"📊 Concurrence maximale: {max_concurrent} requêtes simultanées")
        
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def process_with_semaphore(query_id: int):
            async with semaphore:
                return await self.process_query_async(query_id)
        
        # Lancement de toutes les tâches en parallèle
        tasks = [process_with_semaphore(query_id) for query_id in ids]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Compilation des résultats
        success_count = 0
        for i, (query_id, result) in enumerate(zip(ids, results)):
            if isinstance(result, Exception):
                print(f"❌ Erreur pour requête {query_id}: {result}")
            elif result:
                success_count += 1
        
        # Sauvegarde groupée après tous les traitements
        self._save_consigne()
        
        print(f"\n📊 Résultats du traitement parallèle:")
        print(f"   ✅ Succès: {success_count}/{len(ids)}")
        print(f"   ❌ Échecs: {len(ids) - success_count}/{len(ids)}")
        
        return success_count

    async def process_all_ready_parallel(self, max_concurrent: int = 3):
        """Version parallèle complète comme serp_semantic_batch.py"""
        ready_ids = self.get_ready_queries()
        if not ready_ids:
            print("✅ Aucune requête prête à traiter (toutes déjà analysées ou sans angles).")
            return 0
        
        print(f"\n🚀 Détection automatique de {len(ready_ids)} requête(s) prête(s)")
        print(f"🎯 Traitement parallèle automatique activé (max {max_concurrent} concurrent)")
        
        success_count = await self.process_batch_parallel(ready_ids, max_concurrent)
        print(f"✅ Traitement parallèle terminé: {success_count}/{len(ready_ids)} succès")
        
        return success_count


def main():
    """Fonction principale avec options de traitement"""
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
    print(f"📁 Fichier de consigne détecté: {latest_consigne.name}")
    
    selector = AngleSelector(str(latest_consigne), deepseek_key, prompts_dir="prompts")

    # Vérifier si des arguments en ligne de commande sont fournis
    if len(sys.argv) > 1:
        if sys.argv[1] == "--batch" or sys.argv[1] == "-b":
            print("\n🤖 Mode batch avec confirmation activé")
            selector.process_all_ready()
            return
        elif sys.argv[1] == "--auto" or sys.argv[1] == "-a":
            print("\n🤖 Mode batch automatique complet activé (séquentiel)")
            selector.process_all_ready_automatic()
            return
        elif sys.argv[1] == "--parallel" or sys.argv[1] == "-p":
            print("\n🚀 Mode batch parallèle activé (comme serp_semantic_batch.py)")
            asyncio.run(selector.process_all_ready_parallel(max_concurrent=3))
            return
        elif sys.argv[1] == "--help" or sys.argv[1] == "-h":
            print("\nOptions disponibles :")
            print("  --batch, -b      : Traitement automatique avec confirmation des requêtes prêtes")
            print("  --auto, -a       : Traitement automatique séquentiel sans confirmation")
            print("  --parallel, -p   : Traitement automatique parallèle (comme serp_semantic_batch.py)")
            print("  --help, -h       : Afficher cette aide")
            print("  (sans option)    : Mode interactif")
            return

    # Mode interactif par défaut
    ids_to_process = selector.select_query_ids()
    selector.process_batch(ids_to_process)


if __name__ == "__main__":
    main()
