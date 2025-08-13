#!/usr/bin/env python3
"""
Script DeepSeek Modulaire - Orchestrateur d'Agents
Compatible avec la structure de données existante (queries + generated_article_plan)
Version adaptée de LangChain vers DeepSeek API
"""

import json
import os
import sys
import glob
import time
from typing import Dict, List, Any, Optional
from pathlib import Path
import requests


class DeepSeekClient:
    """Client pour l'API DeepSeek avec gestion d'erreurs avancée"""
    
    def __init__(self, api_key: str, model: str = "bsoner"):
        if not api_key:
            raise ValueError("Clé API DeepSeek manquante")
        self.api_key = api_key
        self.model = model
        self.base_url = "https://api.deepseek.com/v1"
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        # Statistiques d'usage
        self.total_tokens_used = 0
        self.total_requests = 0
    
    def chat_completions_create(self, messages: List[Dict], temperature: float = 0.7, max_tokens: int = 3000):
        """Effectue un appel à l'API chat completions de DeepSeek avec retry logic"""
        url = f"{self.base_url}/chat/completions"
        data = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False
        }
        
        max_retries = 3
        retry_delay = 1
        
        for attempt in range(max_retries):
            try:
                response = requests.post(url, headers=self.headers, json=data, timeout=60)
                response.raise_for_status()
                
                result = response.json()
                
                # Tracking des tokens
                usage = result.get('usage', {})
                tokens_used = usage.get('total_tokens', 0)
                self.total_tokens_used += tokens_used
                self.total_requests += 1
                
                return result
                
            except requests.exceptions.RequestException as e:
                if attempt < max_retries - 1:
                    print(f"   ⚠️  Tentative {attempt + 1} échouée, retry dans {retry_delay}s...")
                    time.sleep(retry_delay)
                    retry_delay *= 2
                else:
                    raise Exception(f"Erreur lors de l'appel à l'API DeepSeek après {max_retries} tentatives: {e}")
    
    def get_usage_stats(self) -> Dict[str, int]:
        """Retourne les statistiques d'usage"""
        return {
            "total_tokens": self.total_tokens_used,
            "total_requests": self.total_requests
        }


class PromptManager:
    """Gestionnaire des prompts - charge uniquement les fichiers existants"""
    
    def __init__(self, prompts_dir: str = "prompts"):
        self.prompts_dir = Path(prompts_dir)
        if not self.prompts_dir.exists():
            raise FileNotFoundError(f"Le dossier {prompts_dir} n'existe pas. Créez-le avec vos fichiers de prompts.")
    
    def load_prompt(self, prompt_file: str) -> str:
        """Charge un prompt depuis un fichier"""
        prompt_path = self.prompts_dir / prompt_file
        if not prompt_path.exists():
            raise FileNotFoundError(f"Fichier prompt non trouvé: {prompt_path}")
        return prompt_path.read_text(encoding='utf-8')


def _find_consigne_file() -> str:
    """Trouve automatiquement le fichier de consigne dans le dossier static (même logique que votre script)"""
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    STATIC_DIR = os.path.join(BASE_DIR, "static")
    
    consigne_pattern = os.path.join(STATIC_DIR, "consigne*.json")
    consigne_files = glob.glob(consigne_pattern)
    
    if not consigne_files:
        raise FileNotFoundError(f"❌ Aucun fichier de consigne trouvé dans {STATIC_DIR}/ (pattern: consigne*.json)")
    
    if len(consigne_files) == 1:
        found_file = consigne_files[0]
        print(f"📁 Fichier de consigne détecté: {os.path.basename(found_file)}")
        return found_file
    
    # Si plusieurs fichiers trouvés, prendre le plus récent
    consigne_files.sort(key=os.path.getmtime, reverse=True)
    most_recent = consigne_files[0]
    print(f"📁 Plusieurs fichiers de consigne trouvés, utilisation du plus récent: {os.path.basename(most_recent)}")
    return most_recent


class ArticleOrchestrator:
    """Orchestrateur principal des agents de rédaction - Version DeepSeek"""
    
    def __init__(self, 
                 model_name: str = "deepseek-reasoner",
                 temperature: float = 0.1,
                 prompts_dir: str = "prompts"):
        
        # 🎯 MÉTHODE SIMPLIFIÉE - Variables d'environnement uniquement
        deepseek_key = os.getenv('DEEPSEEK_KEY')
        if not deepseek_key:
            print("❌ Variable d'environnement DEEPSEEK_KEY manquante.")
            print("💡 Pour définir la variable:")
            print("   Linux/Mac: export DEEPSEEK_KEY='votre_clé_ici'")
            print("   Windows:   set DEEPSEEK_KEY=votre_clé_ici")
            sys.exit(1)
        
        self.llm = DeepSeekClient(deepseek_key, model_name)
        self.prompt_manager = PromptManager(prompts_dir)
        self.temperature = temperature
        
        # Configuration des agents (fichiers de prompts)
        self.agent_prompts = {
            "introduction": "introduction.txt",
            "section": "section.txt", 
            "cta_section": "cta_section.txt",
            "conclusion": "conclusion.txt"
        }
        
        # État partagé pour la cohérence
        self.context_history = []
        self.generated_content = {}
        
        # Chargement automatique du fichier consigne
        self.consigne_path = _find_consigne_file()
        self.consigne_data = self.load_consigne()
    
    def load_consigne(self) -> Dict:
        """Charge le fichier consigne.json"""
        try:
            with open(self.consigne_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            print(f"❌ Fichier {self.consigne_path} non trouvé.")
            sys.exit(1)
        except json.JSONDecodeError as e:
            print(f"❌ Erreur JSON dans {self.consigne_path}: {e}")
            sys.exit(1)
    
    def save_consigne(self):
        """Sauvegarde le fichier consigne.json"""
        with open(self.consigne_path, 'w', encoding='utf-8') as f:
            json.dump(self.consigne_data, f, ensure_ascii=False, indent=4)
    
    def get_query_data(self, query_id: int) -> Optional[Dict]:
        """Récupère les données d'une requête par son ID"""
        for query in self.consigne_data.get('queries', []):
            if query['id'] == query_id:
                return query
        return None
    
    def list_available_queries(self) -> List[Dict]:
        """Liste toutes les requêtes disponibles avec leur statut"""
        queries = []
        for query in self.consigne_data.get('queries', []):
            has_plan = 'generated_plan' in query  # Correction: clé correcte
            has_article = 'generated_content' in query  # Notre système de contenu généré
            status = "🟢 Complet" if has_article else "🟡 Plan prêt" if has_plan else "🔴 Non traité"
            queries.append({
                'id': query['id'],
                'text': query['text'],
                'status': status,
                'has_plan': has_plan,
                'has_article': has_article
            })
        return queries
    
    def select_queries_to_process(self) -> List[int]:
        """Interface utilisateur pour sélectionner les requêtes à traiter (même logique que votre script)"""
        queries = self.list_available_queries()
        
        print("\n📋 REQUÊTES DISPONIBLES:")
        print("=" * 80)
        for q in queries:
            print(f"ID {q['id']:2d} | {q['status']} | {q['text']}")
        
        print("\n💡 Instructions:")
        print("- Tapez un ID pour traiter une seule requête: 5")
        print("- Tapez plusieurs IDs séparés par des virgules: 1,3,5")
        print("- Tapez une plage d'IDs: 1-5")
        print("- Tapez 'all' pour traiter toutes les requêtes avec plan")
        print("- Tapez 'q' pour quitter")
        
        while True:
            user_input = input("\n🎯 Votre sélection: ").strip().lower()
            
            if user_input == 'q':
                print("👋 Au revoir!")
                sys.exit(0)
            
            if user_input == 'all':
                return [q['id'] for q in queries if q['has_plan'] and not q['has_article']]
            
            try:
                selected_ids = []
                
                # Gestion des plages (1-5)
                if '-' in user_input and user_input.count('-') == 1:
                    start, end = map(int, user_input.split('-'))
                    selected_ids = list(range(start, end + 1))
                
                # Gestion des listes (1,3,5)
                elif ',' in user_input:
                    selected_ids = [int(x.strip()) for x in user_input.split(',')]
                
                # ID unique
                else:
                    selected_ids = [int(user_input)]
                
                # Validation
                valid_ids = [q['id'] for q in queries]
                invalid_ids = [id for id in selected_ids if id not in valid_ids]
                
                if invalid_ids:
                    print(f"❌ IDs invalides: {invalid_ids}")
                    continue
                
                # Vérification des plans
                no_plan_ids = [id for id in selected_ids 
                              if not any(q['id'] == id and q['has_plan'] for q in queries)]
                
                if no_plan_ids:
                    print(f"⚠️  Les IDs suivants n'ont pas de plan généré: {no_plan_ids}")
                    continue_anyway = input("Continuer quand même? (y/N): ").lower() == 'y'
                    if not continue_anyway:
                        continue
                
                return selected_ids
                
            except ValueError:
                print("❌ Format invalide. Utilisez des nombres, des virgules ou des tirets.")
    
    def call_agent(self, agent_name: str, context: Dict[str, Any]) -> str:
        """Appelle un agent avec son prompt et contexte - Version DeepSeek"""
        prompt_file = self.agent_prompts[agent_name]
        system_prompt = self.prompt_manager.load_prompt(prompt_file)

        # Si le contexte contient déjà previous_content, inutile de le doubler
        context_str = json.dumps(context, ensure_ascii=False, indent=2)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Données à traiter:\n{context_str}"}
        ]



        # Debug pour voir exactement ce qui est envoyé
        print("\n=== 📤 PROMPT ENVOYÉ À L'AGENT:", agent_name, "===")
        for msg in messages:
            print(f"[{msg['role'].upper()}] {msg['content']}\n")
        print("=== FIN PROMPT ===\n")

        response = self.llm.chat_completions_create(
            messages=messages,
            temperature=self.temperature,
            max_tokens=3000
        )

        content = response['choices'][0]['message']['content']
        usage = response.get('usage', {})
        tokens_used = usage.get('total_tokens', 0)

        print(f"   💰 Agent {agent_name} - Tokens: {tokens_used}")

        return content
    
    def _get_first_section_title(self, structure: Dict) -> str:
        """Récupère le titre de la première section"""
        section_keys = sorted([k for k in structure.keys() if k.startswith("section_")])
        if section_keys:
            return structure[section_keys[0]].get("title", "Suite de l'article")
        return "Suite de l'article"
    
    def _get_next_section_title(self, structure: Dict, section_keys: List[str], current_index: int) -> str:
        """Récupère le titre de la section suivante"""
        if current_index + 1 < len(section_keys):
            next_key = section_keys[current_index + 1]
            return structure[next_key].get("title", "Section suivante")
        elif "conclusion" in structure:
            return "Conclusion"
        return "Fin de l'article"
    
    def execute_orchestration_for_query(self, query_id: int):
        """Exécution de l'orchestration pour une requête spécifique"""
        query_data = self.get_query_data(query_id)
        if not query_data or 'generated_plan' not in query_data:  # Correction: clé correcte
            print(f"❌ Requête {query_id} sans plan généré")
            return False
        
        print(f"\n🎼 ORCHESTRATION pour ID {query_id}: '{query_data['text']}'")
        
        # Récupération du plan (structure correcte)
        plan = query_data['generated_plan']
        
        # Réinitialisation du contexte pour cette requête
        self.context_history = []
        self.generated_content = {}
        
        generated_content = {}
        
        # 1. Agent Introduction
        print("   📝 Agent Introduction...")
        intro_context = {
            "title": plan.get('title', query_data['text']),
            "data_exploitation_summary": plan.get('data_exploitation_summary', ''),
            "introduction": plan.get('structure', {}).get('introduction', {}),
            "query_text": query_data['text'],
            "next_section": self._get_first_section_title(plan.get('structure', {})),
            "word_count": query_data.get('plan', {}).get('introduction', {}).get('longueur', 150)
        }
        
        intro_content = self.call_agent("introduction", intro_context)
        generated_content["introduction"] = intro_content
        self.context_history.append(intro_content)
        print("   ✅ Introduction générée")
        
        # 2. Sections
        sections_content = []
        structure = plan.get('structure', {})
        
        # Récupération des sections (format section_1, section_2, etc.)
        section_keys = sorted([key for key in structure.keys() if key.startswith('section_')])
        
        for i, section_key in enumerate(section_keys):
            section_data = structure[section_key]
            print(f"   📝 Section {i+1}/{len(section_keys)}: '{section_data.get('title', f'Section {i+1}')}'...")
            
            # Déterminer le type d'agent selon la présence de CTA
            agent_name = "cta_section" if 'cta_hint' in section_data else "section"
            
            section_context = {
                "current_section": section_data,
                "section_index": i,
                "total_sections": len(section_keys),
                "query_text": query_data['text'],
                "previous_content": self.context_history[-1] if self.context_history else "",
                "next_section_title": self._get_next_section_title(structure, section_keys, i)
            }
            
            if agent_name == "cta_section":
                # Ajouter des données produit si disponibles
                section_context["products_services"] = self.consigne_data.get("products_services", [])
            
            section_content = self.call_agent(agent_name, section_context)
            sections_content.append(section_content)
            generated_content[f"section_{i+1}"] = section_content
            self.context_history.append(section_content)
            print(f"   ✅ Section {i+1} générée")
        
        # 3. Agent Conclusion
        print("   📝 Agent Conclusion...")
        conclusion_context = {
            "conclusion": structure.get('conclusion', {}),
            "query_text": query_data['text'],
            "all_previous_content": "\n---\n".join(self.context_history),
            "word_count": query_data.get('plan', {}).get('conclusion', {}).get('longueur', 100)
        }
        
        conclusion_content = self.call_agent("conclusion", conclusion_context)
        generated_content["conclusion"] = conclusion_content
        print("   ✅ Conclusion générée")
        
        # 4. Sauvegarde dans la structure de données
        query_data['generated_content'] = generated_content
        query_data['orchestration_completed'] = True
        query_data['generation_method'] = 'deepseek_orchestrator'
        
        # Calcul du nombre de mots total
        total_text = " ".join([intro_content] + sections_content + [conclusion_content])
        query_data['final_word_count'] = len(total_text.split())
        
        # Ajout des statistiques d'usage DeepSeek
        usage_stats = self.llm.get_usage_stats()
        query_data['deepseek_usage'] = usage_stats
        
        print(f"   ✅ Article orchestré ({query_data['final_word_count']} mots)")
        return True
    
    def process_queries(self, query_ids: List[int]):
        """Traite une liste de requêtes avec l'orchestrateur"""
        print(f"\n🎼 ORCHESTRATION DE {len(query_ids)} REQUÊTE(S): {query_ids}")
        
        successful = 0
        initial_tokens = self.llm.total_tokens_used
        
        for query_id in query_ids:
            try:
                if self.execute_orchestration_for_query(query_id):
                    successful += 1
                else:
                    print(f"   ❌ Échec orchestration pour ID {query_id}")
                    
            except Exception as e:
                print(f"   ❌ Erreur lors de l'orchestration ID {query_id}: {e}")
        
        # Sauvegarde finale
        try:
            self.save_consigne()
            print(f"\n💾 Fichier {self.consigne_path} mis à jour avec succès!")
            print(f"📊 Résultats: {successful}/{len(query_ids)} requêtes traitées avec succès")
            
            # Statistiques d'usage DeepSeek
            final_stats = self.llm.get_usage_stats()
            tokens_used_session = final_stats['total_tokens'] - initial_tokens
            print(f"🔢 Tokens utilisés cette session: {tokens_used_session}")
            print(f"📈 Total tokens utilisés: {final_stats['total_tokens']}")
            print(f"🔄 Total requêtes API: {final_stats['total_requests']}")
            
        except Exception as e:
            print(f"❌ Erreur lors de la sauvegarde: {e}")


def main():
    """Point d'entrée principal"""
    print("🎼 GÉNÉRATEUR D'ARTICLES - ORCHESTRATEUR DEEPSEEK")
    print("=" * 60)
    print("📝 Compatible avec la structure de données existante")
    print("🚀 Utilise l'API DeepSeek pour la génération de contenu")
    
    # ❌ SUPPRIMER ce bloc (déjà géré dans __init__)
    # Vérification de la clé API DeepSeek
    if not os.getenv('DEEPSEEK_KEY'):
        print("❌ Variable d'environnement DEEPSEEK_KEY manquante.")
        print("Ajoutez votre clé API DeepSeek:")
        print("export DEEPSEEK_KEY='your-api-key-here'")
        print("Ou créez un fichier .env avec: DEEPSEEK_KEY=your-api-key-here")
        sys.exit(1)
    
    try:
        orchestrator = ArticleOrchestrator(
            model_name="deepseek-chat",
            temperature=0.7
        )
        
        # Sélection et traitement
        selected_ids = orchestrator.select_queries_to_process()
        if selected_ids:
            orchestrator.process_queries(selected_ids)
        else:
            print("ℹ️  Aucune requête sélectionnée.")
            
    except KeyboardInterrupt:
        print("\n\n⏹️  Arrêt demandé par l'utilisateur.")
    except Exception as e:
        print(f"\n❌ Erreur inattendue: {e}")
        raise


if __name__ == "__main__":
    main()