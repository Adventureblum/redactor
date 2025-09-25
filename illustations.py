import os
import sys
import json
import glob
import asyncio
import time
from pathlib import Path
from typing import Dict, Any, List
from concurrent.futures import ThreadPoolExecutor
from openai import OpenAI

MODEL_NAME = "gpt-5-nano"
TEMPERATURE = 1
INFOGRAPHIC_TYPES = ["processus", "comparaison", "chiffres_clefs", "timeline", "boucle", "pyramide"]


def find_latest_consigne() -> Path:
    base = Path(__file__).resolve().parent
    static = base / "static"
    files = sorted(static.glob("consigne*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        print(f"❌ Aucun consigne*.json trouvé dans {static}")
        sys.exit(1)
    return files[0]


def load_json(p: Path) -> Dict[str, Any]:
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(p: Path, data: Dict[str, Any]) -> None:
    with p.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


def call_llm_for_article(full_generated_content: Dict[str, Any]) -> Dict[str, Any]:
    """
    Envoie tout le generated_content au LLM.
    Retour attendu :
    {
      "decisions": [
        {
          "section_key": "...",
          "choice": "photo|infographie|none",
          "subtype": "processus|comparaison|chiffres_clefs|timeline|boucle|pyramide",
          "photo": {"prompt":"...","alt":"...","legende":"..."},
          "etapes": [ {"titre":"...","texte":"..."} ],
          "avant": [ {"libelle":"...","valeur":"..."} ],
          "apres": [ {"libelle":"...","valeur":"..."} ],
          "amelioration": {"valeur":"...","libelle":"..."},
          "kpis": [ {"valeur":"...","libelle":"..."} ],
          "evenements": [ {"date":"...","titre":"...","description":"..."} ],
          "points": [ {"titre":"..."} ],
          "centre": "...",
          "niveaux": [ {"titre":"...","texte":"..."} ]
        }
      ]
    }
    """
    client = OpenAI()

    sys_prompt = (
        f"""
Tu es un assistant éditorial spécialisé dans la visualisation de données.

MISSION : Analyser le contenu fourni et sélectionner le type de visualisation le plus pertinent pour CHAQUE section.

## ÉTAPES D'ANALYSE

1. **LECTURE STRATÉGIQUE** : Identifie d'abord les structures naturelles du contenu
2. **DÉTECTION DE PATTERNS** : Recherche ces indicateurs clés :
   - Séquences temporelles → timeline
   - Étapes séquentielles → processus  
   - Comparaisons binaires → comparaison
   - Données quantifiées → chiffres_clefs
   - Cycles/répétitions → boucle
   - Hiérarchies/niveaux → pyramide

3. **VALIDATION** : Vérifie que tu peux remplir TOUS les champs requis avec le contenu disponible

## TYPES D'INFOGRAPHIES ET CRITÈRES DE SÉLECTION

### 🔄 PROCESSUS (Template 1)
**Quand utiliser :** Étapes séquentielles, méthodes, procédures
**Indicateurs textuels :** "étapes", "d'abord", "ensuite", "puis", "enfin", "méthode", "processus"
**Minimum requis :** 3-6 étapes avec titre et description détaillée

### ⚖️ COMPARAISON (Template 2)  
**Quand utiliser :** Comparaisons avant/après, évolutions, améliorations
**Indicateurs textuels :** "avant/après", "vs", "contre", "comparé à", "amélioration", "progression"
**Minimum requis :** 3+ éléments "avant" ET 3+ éléments "après" avec valeurs quantifiées

### 📊 CHIFFRES_CLEFS (Template 3)
**Quand utiliser :** Statistiques, pourcentages, données chiffrées importantes  
**Indicateurs textuels :** "%", "statistiques", "chiffres", "données", nombres proéminents
**Minimum requis :** 3+ KPIs avec valeurs et libellés explicites (pas de placeholders)

### 📅 TIMELINE
**Quand utiliser :** Évolutions chronologiques, historiques, plannings
**Indicateurs textuels :** dates, "évolution", "historique", "chronologie", années
**Minimum requis :** 3+ événements avec dates précises

### 🔄 BOUCLE  
**Quand utiliser :** Cycles récurrents, processus circulaires, améliorations continues
**Indicateurs textuels :** "cycle", "boucle", "continu", "récurrent", "répéter"
**Minimum requis :** Centre défini + 4+ étapes circulaires

### 🔺 PYRAMIDE
**Quand utiliser :** Hiérarchies, priorités, niveaux d'importance
**Indicateurs textuels :** "hiérarchie", "niveaux", "priorité", "fondamental à avancé"
**Minimum requis :** 3+ niveaux avec importance décroissante/croissante

## RÈGLES DE VALIDATION STRICTES

❌ **INTERDICTIONS :**
- Listes vides ou avec un seul élément
- Placeholders génériques ("Étape 1", "Valeur X")  
- Contenus insuffisants pour remplir les champs

✅ **SI TU NE PEUX PAS REMPLIR CORRECTEMENT :**
- Choisis 'photo' avec prompt descriptif détaillé
- Ou 'none' si aucune visualisation n'est pertinente

FORMAT JSON STRICT UNIQUEMENT :
{{
  "decisions": [
    {{
      "section_key": "introduction|section_1|...|conclusion",
      "choice": "photo|infographie|none",
      "subtype": "processus|comparaison|chiffres_clefs|timeline|boucle|pyramide",
      "photo": {{"prompt":"...","alt":"...","legende":"..."}},
      "etapes": [ {{"titre":"...","texte":"..."}} ],
      "avant": [ {{"libelle":"...","valeur":"..."}} ],
      "apres": [ {{"libelle":"...","valeur":"..."}} ],
      "amelioration": {{"valeur":"...","libelle":"..."}},
      "kpis": [ {{"valeur":"...","libelle":"..."}} ],
      "evenements": [ {{"date":"...","titre":"...","description":"..."}} ],
      "points": [ {{"titre":"..."}} ],
      "centre": "...",
      "niveaux": [ {{"titre":"...","texte":"..."}} ]
    }}
  ]
}}
""".strip()
    )

    user_message = {
        "role": "user",
        "content": "Voici le generated_content complet :\n" + json.dumps(full_generated_content, ensure_ascii=False)
    }

    resp = client.chat.completions.create(
        model=MODEL_NAME,
        temperature=TEMPERATURE,
        messages=[{"role": "system", "content": sys_prompt}, user_message],
        response_format={"type": "json_object"},
    )
    content = (resp.choices[0].message.content or "").strip()
    try:
        return json.loads(content)
    except Exception:
        # En cas de JSON invalide, on renvoie une structure neutre
        return {"decisions": []}



def to_output_items(decisions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for d in decisions:
        key = d.get("section_key", "")
        choice = (d.get("choice") or "").lower()
        if choice == "photo":
            ph = d.get("photo", {})
            out.append({
                "section": key,
                "photo": {
                    "prompt": ph.get("prompt", ""),
                    "alt": ph.get("alt", ""),
                    "legende": ph.get("legende", "")
                }
            })
        elif choice == "infographie":
            subtype = d.get("subtype", "").lower()
            data = {"sous_type": subtype}
            if subtype == "processus":
                data["etapes"] = d.get("etapes", [])
            elif subtype == "comparaison":
                data["avant"] = d.get("avant", [])
                data["apres"] = d.get("apres", [])
                data["amelioration"] = d.get("amelioration", {})
            elif subtype == "chiffres_clefs":
                data["kpis"] = d.get("kpis", [])
            elif subtype == "timeline":
                data["evenements"] = d.get("evenements", [])
            elif subtype == "boucle":
                data["centre"] = d.get("centre", "")
                data["points"] = d.get("points", [])
            elif subtype == "pyramide":
                data["niveaux"] = d.get("niveaux", [])
            out.append({"section": key, "infographie": data})
    return out


def process_article(q: Dict[str, Any]) -> None:
    gc = q.get("generated_content")
    if not isinstance(gc, dict):
        return
    result = call_llm_for_article(gc)
    items = to_output_items(result.get("decisions", []))
    if items:
        q["illustrations"] = {"illustrations": items}


async def process_article_async(q: Dict[str, Any]) -> bool:
    """
    Version asynchrone du traitement d'article pour parallélisation
    """
    try:
        query_id = q.get('id', 'N/A')
        print(f"   📊 Traitement illustrations pour ID {query_id}...")
        
        gc = q.get("generated_content")
        if not isinstance(gc, dict):
            print(f"   ⚠️  Pas de generated_content valide pour ID {query_id}")
            return False
        
        # Appel async avec ThreadPoolExecutor pour l'API OpenAI
        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor() as executor:
            result = await loop.run_in_executor(
                executor, 
                call_llm_for_article, 
                gc
            )
        
        items = to_output_items(result.get("decisions", []))
        if items:
            q["illustrations"] = {"illustrations": items}
            print(f"   ✅ Illustrations générées pour ID {query_id} ({len(items)} éléments)")
            return True
        else:
            print(f"   ℹ️  Aucune illustration nécessaire pour ID {query_id}")
            return True
    except Exception as e:
        print(f"   ❌ Erreur lors du traitement ID {query_id}: {e}")
        return False


class OptimizedIllustrationsProcessor:
    """
    Processeur optimisé pour le traitement parallèle des illustrations
    Basé sur la méthode d'OptimizedArticleOrchestrator
    """
    
    def __init__(self, max_concurrent: int = 10):
        self.max_concurrent = max_concurrent
    
    async def process_queries_parallel(self, queries: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Traite les requêtes en parallèle avec semaphore pour limiter la concurrence
        """
        if not queries:
            print("❌ Aucune requête à traiter")
            return {"success_count": 0, "total_count": 0, "errors": []}
        
        print(f"🚀 Lancement du traitement parallèle de {len(queries)} requêtes...")
        start_time = time.time()
        
        # Créer un semaphore pour limiter les requêtes concurrentes
        semaphore = asyncio.Semaphore(self.max_concurrent)
        
        async def process_with_semaphore(query):
            async with semaphore:
                return await process_article_async(query)
        
        # Lancer toutes les tâches en parallèle
        tasks = [process_with_semaphore(query) for query in queries]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        elapsed_time = time.time() - start_time
        
        # Traitement des résultats
        success_count = 0
        error_count = 0
        errors = []
        
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                error_count += 1
                errors.append(f"Query ID {queries[i].get('id', i)}: {result}")
                print(f"❌ Erreur: {result}")
            elif result:
                success_count += 1
            else:
                error_count += 1
        
        print(f"⚡ Traitement parallèle terminé en {elapsed_time:.2f}s")
        print(f"✅ Succès: {success_count}/{len(queries)}")
        print(f"❌ Échecs: {error_count}/{len(queries)}")
        
        if error_count > 0:
            print("📝 Erreurs détaillées:")
            for error in errors:
                print(f"   {error}")
        
        return {
            "success_count": success_count,
            "total_count": len(queries),
            "error_count": error_count,
            "errors": errors,
            "elapsed_time": elapsed_time
        }
    
    def process_optimized(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Point d'entrée pour le traitement optimisé
        """
        queries = data.get("queries", [])
        
        # Filtrer seulement les requêtes avec generated_content
        queries_to_process = [
            q for q in queries 
            if "generated_content" in q and isinstance(q.get("generated_content"), dict)
        ]
        
        if not queries_to_process:
            print("❌ Aucune requête avec generated_content trouvée")
            return {"success_count": 0, "total_count": 0, "errors": []}
        
        print(f"📋 {len(queries_to_process)} requêtes avec generated_content détectées")
        
        try:
            return asyncio.run(self.process_queries_parallel(queries_to_process))
        except Exception as e:
            print(f"❌ Erreur lors du traitement optimisé: {e}")
            print("🔄 Fallback vers traitement séquentiel...")
            return self.process_sequential_fallback(queries_to_process)
    
    def process_sequential_fallback(self, queries: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Traitement séquentiel de fallback en cas d'erreur avec le traitement parallèle
        """
        success_count = 0
        errors = []
        
        for q in queries:
            try:
                query_id = q.get('id', 'N/A')
                print(f"→ Traitement séquentiel article {query_id}")
                process_article(q)
                success_count += 1
            except Exception as e:
                errors.append(f"Query ID {q.get('id', 'N/A')}: {e}")
        
        return {
            "success_count": success_count,
            "total_count": len(queries),
            "error_count": len(errors),
            "errors": errors,
            "elapsed_time": 0
        }


def main():
    if not os.getenv("OPENAI_API_KEY"):
        print("❌ OPENAI_API_KEY manquante.")
        sys.exit(1)

    # Gestion de l'aide
    if len(sys.argv) > 1 and sys.argv[1] in ['--help', '-h']:
        print("🎨 GÉNÉRATEUR D'ILLUSTRATIONS - Aide")
        print("=" * 50)
        print("Usage: python illustations.py [OPTIONS]")
        print()
        print("Options disponibles:")
        print("  --parallel, -p   : Traitement parallèle optimisé (jusqu'à 10 requêtes simultanées)")
        print("  --help, -h       : Afficher cette aide")
        print("  (sans option)    : Mode séquentiel classique")
        print()
        print("Le mode parallèle est recommandé pour traiter de nombreuses requêtes rapidement.")
        return

    print("🎨 GÉNÉRATEUR D'ILLUSTRATIONS")
    print("=" * 50)
    
    # Gestion des arguments pour le mode parallèle
    use_parallel = len(sys.argv) > 1 and sys.argv[1] in ['--parallel', '-p']
    
    if use_parallel:
        print("⚡ Mode parallèle activé (optimisé)")
    else:
        print("🐌 Mode séquentiel classique")
        print("💡 Utilisez --parallel ou -p pour le mode optimisé")
    
    consigne_path = find_latest_consigne()
    data = load_json(consigne_path)
    
    start_time = time.time()
    
    if use_parallel:
        # Traitement parallèle optimisé
        processor = OptimizedIllustrationsProcessor(max_concurrent=10)
        results = processor.process_optimized(data)
        
        print(f"\n📊 Résultats du traitement parallèle:")
        print(f"   ✅ Succès: {results['success_count']}/{results['total_count']}")
        print(f"   ❌ Échecs: {results['error_count']}/{results['total_count']}")
        if results.get('elapsed_time', 0) > 0:
            print(f"   ⏱️  Temps parallèle: {results['elapsed_time']:.2f}s")
            estimated_sequential = results['total_count'] * 3  # Estimation 3s par requête
            print(f"   🚀 Gain estimé: {estimated_sequential - results['elapsed_time']:.1f}s")
    else:
        # Traitement séquentiel classique (comportement original)
        processed_count = 0
        for q in data.get("queries", []):
            if "generated_content" in q:
                print(f"→ Traitement article {q.get('id')}")
                process_article(q)
                processed_count += 1
        
        elapsed_time = time.time() - start_time
        print(f"\n📊 Traitement séquentiel terminé:")
        print(f"   ✅ {processed_count} articles traités")
        print(f"   ⏱️  Temps total: {elapsed_time:.2f}s")
    
    # Sauvegarde unique après tous les traitements
    save_json(consigne_path, data)
    total_time = time.time() - start_time
    print(f"\n💾 Illustrations sauvegardées dans {consigne_path.name}")
    print(f"⏱️  Temps total avec sauvegarde: {total_time:.2f}s")


if __name__ == "__main__":
    main()