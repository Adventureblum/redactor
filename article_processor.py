#!/usr/bin/env python3
"""
Générateur de Contenu d'Articles - Version DeepSeek
Lit la clé 'generated_plan' et génère le contenu complet dans 'generated_content'
Compatible avec la structure de données existante (queries + generated_plan → generated_content)
"""

import json
import os
import sys
import glob
import time
from typing import Dict, List, Any, Optional
from pathlib import Path
import requests

# Chargement des variables d'environnement depuis .env si le fichier existe
def load_env_file():
    env_file = Path('.env')
    if env_file.exists():
        with open(env_file, 'r') as f:
            for line in f:
                if '=' in line and not line.startswith('#'):
                    key, value = line.strip().split('=', 1)
                    os.environ[key] = value.strip('"').strip("'")

load_env_file()


class DeepSeekClient:
    """Client pour l'API DeepSeek avec gestion d'erreurs avancée"""
    
    def __init__(self, api_key: str, model: str = "deepseek-reasoner"):
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
    
    def chat_completions_create(self, messages: List[Dict], temperature: float = 0.1, max_tokens: int = 20480):
        """Effectue un appel à l'API chat completions de DeepSeek avec retry logic"""
        url = f"{self.base_url}/chat/completions"
        data = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "presence_penalty": 0,      # ← AJOUTEZ ÇA
            "frequency_penalty": 0,     # ← ET ÇA
            "stream": False
        }
        
        max_retries = 3
        retry_delay = 1
        
        for attempt in range(max_retries):
            try:
                response = requests.post(url, headers=self.headers, json=data, timeout=180)
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
    """Gestionnaire des prompts - charge uniquement les fichiers YAML existants"""
    
    def __init__(self, prompts_dir: str = "prompts"):
        self.prompts_dir = Path(prompts_dir)
        if not self.prompts_dir.exists():
            raise FileNotFoundError(f"Le dossier {prompts_dir} n'existe pas. Créez-le avec vos fichiers de prompts.")
        self._ensure_content_prompt_exists()
    
    def _ensure_content_prompt_exists(self):
        """Vérifie que le prompt de génération de contenu existe"""
        # Chercher d'abord .md puis .txt
        content_prompt_yaml = self.prompts_dir / "content_generator.md"
        content_prompt_txt = self.prompts_dir / "content_generator.txt"
        
        if content_prompt_yaml.exists():
            self.content_prompt_file = "content_generator.md"
            print(f"📝 Prompt chargé: {content_prompt_yaml}")
        elif content_prompt_txt.exists():
            self.content_prompt_file = "content_generator.txt"
            print(f"📝 Prompt chargé: {content_prompt_txt}")
        else:
            print(f"❌ Fichier prompt manquant: {content_prompt_yaml} ou {content_prompt_txt}")
            print("💡 Créez le fichier prompts/content_generator.yaml ou prompts/content_generator.txt")
            print("📄 Le prompt doit générer le contenu complet basé sur le plan")
            raise FileNotFoundError(f"Prompt requis non trouvé: {content_prompt_yaml} ou {content_prompt_txt}")
    
    def load_prompt(self, prompt_file: str) -> str:
        """Charge un prompt depuis un fichier"""
        prompt_path = self.prompts_dir / prompt_file
        if not prompt_path.exists():
            raise FileNotFoundError(f"Fichier prompt non trouvé: {prompt_path}")
        return prompt_path.read_text(encoding='utf-8')
    
    def load_yaml_prompts(self, template_vars: Dict[str, Any]) -> tuple:
        """Charge et sépare les prompts système et utilisateur depuis YAML"""
        import yaml
        
        prompt_content = self.load_prompt(self.content_prompt_file)
        
        try:
            # Parse le YAML
            prompt_data = yaml.safe_load(prompt_content)
            
            # Récupère le prompt système
            system_prompt = prompt_data.get('system_prompt', '')
            
            # Récupère et formate le prompt utilisateur
            user_template = prompt_data.get('user_prompt_template', '')
            user_prompt = user_template.format(**template_vars)
            
            return system_prompt, user_prompt
            
        except yaml.YAMLError as e:
            print(f"❌ Erreur YAML dans {self.content_prompt_file}: {e}")
            # Fallback: traiter comme un template simple
            return "", prompt_content.format(**template_vars)
        except KeyError as e:
            missing_var = str(e).strip("'")
            print(f"⚠️  Variable manquante dans le prompt: {missing_var}")
            print(f"Variables disponibles: {list(template_vars.keys())}")
            return "", prompt_content
    
    def format_content_prompt(self, template_vars: Dict[str, Any]) -> str:
        """Formate le prompt de contenu avec les variables données (compatibilité)"""
        template = self.load_prompt(self.content_prompt_file)
        
        try:
            return template.format(**template_vars)
        except KeyError as e:
            missing_var = str(e).strip("'")
            print(f"⚠️  Variable manquante dans le prompt: {missing_var}")
            print(f"Variables disponibles: {list(template_vars.keys())}")
            # Retourner le template non formaté plutôt que planter
            return template


def _find_consigne_file() -> str:
    """Trouve automatiquement le fichier de consigne dans le dossier static"""
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


class ContentGenerator:
    """Générateur de contenu d'articles - Version DeepSeek"""
    
    def __init__(self, 
                 model_name: str = "deepseek-reasoner",
                 temperature: float = 0.1,
                 prompts_dir: str = "prompts"):
        
        # Initialisation du client DeepSeek
        deepseek_key = os.getenv('DEEPSEEK_KEY')
        if not deepseek_key:
            raise ValueError("Variable d'environnement DEEPSEEK_KEY manquante")
        
        self.llm = DeepSeekClient(deepseek_key, model_name)
        self.prompt_manager = PromptManager(prompts_dir)
        self.temperature = temperature
        
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
        """Liste toutes les requêtes disponibles avec leur statut de plans"""
        queries = []
        for query in self.consigne_data.get('queries', []):
            has_plan = 'generated_plan' in query
            has_content = 'generated_content' in query
            
            if has_content:
                status = "🟢 Contenu généré"
            elif has_plan:
                status = "🟡 Plan prêt"
            else:
                status = "🔴 Pas de plan"
            
            # Calcul du nombre de mots estimé du plan
            estimated_words = 0
            if has_plan:
                plan = query.get('generated_plan', {})
                estimated_words = plan.get('meta', {}).get('word_count_target', query.get('word_count', 1000))
            
            queries.append({
                'id': query['id'],
                'text': query['text'],
                'status': status,
                'has_plan': has_plan,
                'has_content': has_content,
                'estimated_words': estimated_words
            })
        return queries
    
    def select_queries_to_process(self) -> List[int]:
        """Interface utilisateur pour sélectionner les requêtes à traiter"""
        queries = self.list_available_queries()
        
        print("\n📋 REQUÊTES DISPONIBLES POUR GÉNÉRATION DE CONTENU:")
        print("=" * 90)
        for q in queries:
            words_info = f"~{q['estimated_words']} mots" if q['estimated_words'] > 0 else ""
            print(f"ID {q['id']:2d} | {q['status']} | {words_info:>12} | {q['text']}")
        
        print("\n💡 Instructions:")
        print("- Tapez un ID pour générer une seule requête: 5")
        print("- Tapez plusieurs IDs séparés par des virgules: 1,3,5")
        print("- Tapez une plage d'IDs: 1-5")
        print("- Tapez 'all' pour générer toutes les requêtes avec plan")
        print("- Tapez 'q' pour quitter")
        
        while True:
            user_input = input("\n🎯 Votre sélection: ").strip().lower()
            
            if user_input == 'q':
                print("👋 Au revoir!")
                sys.exit(0)
            
            if user_input == 'all':
                return [q['id'] for q in queries if q['has_plan'] and not q['has_content']]
            
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
    
    def generate_content_for_query(self, query_id: int) -> Optional[str]:
        """Génère le contenu complet pour une requête spécifique"""
        query_data = self.get_query_data(query_id)
        if not query_data:
            print(f"❌ Requête {query_id} non trouvée")
            return None
        
        generated_plan = query_data.get('generated_plan', {})
        if not generated_plan:
            print(f"❌ Requête {query_id} sans plan généré")
            return None
        
        print(f"\n📝 GÉNÉRATION DE CONTENU pour ID {query_id}: '{query_data['text']}'")
        
        # Extraction des informations du plan
        meta_info = generated_plan.get('meta', {})
        structure = generated_plan.get('structure', {})
        word_count_target = meta_info.get('word_count_target', query_data.get('word_count', 1000))
        
        print(f"   🎯 Objectif: {word_count_target} mots")
        print(f"   📄 Sections: {len([k for k in structure.keys() if k.startswith('section_')])} + intro/conclusion")
        
        # Préparation des variables pour le prompt
        template_vars = {
            'requete': query_data['text'],
            'plan_complet': json.dumps(generated_plan, ensure_ascii=False, indent=2),
            'word_count_target': word_count_target,
            'meta_title': meta_info.get('title', query_data['text']),
            'meta_description': meta_info.get('description', ''),
            'primary_keywords': ', '.join(meta_info.get('primary_keywords', [])),
            'structure_json': json.dumps(structure, ensure_ascii=False, indent=2),
            'data_exploitation_summary': generated_plan.get('data_exploitation_summary', ''),
            'agent_response_data': json.dumps(query_data.get('agent_response', {}), ensure_ascii=False, indent=2)
        }

        # Accès au plan prévisionnel
        plan_config = query_data.get("plan", {})
        intro_length = plan_config.get("introduction", {}).get("longueur", "")
        dev_sections = plan_config.get("developpement", {}).get("nombre_sections", "")
        words_per_section = plan_config.get("developpement", {}).get("mots_par_section", "")
        conclusion_length = plan_config.get("conclusion", {}).get("longueur", "")

        # Ajout des variables personnalisées
        template_vars.update({
            'angle_recommande': query_data.get('angle_recommande', ''),
            'word_count': query_data.get('word_count', ''),
            'intro_length': intro_length,
            'dev_sections': dev_sections,
            'words_per_section': words_per_section,
            'conclusion_length': conclusion_length
        })

        # Récupération des prompts système et utilisateur séparés
        system_prompt, user_prompt = self.prompt_manager.load_yaml_prompts(template_vars)
        
        # Construction des messages avec prompt système séparé
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})
        
        # 👉 Affichage des prompts dans le terminal
        print("\n📤 PROMPTS ENVOYÉS À DEEPSEEK:")
        print("=" * 60)
        if system_prompt:
            print(f"SYSTEM: {system_prompt[:200]}...")
            print("-" * 60)
        print(f"USER: {user_prompt[:300]}...")
        print("=" * 60)
                
        try:
            print("   🤖 Génération en cours avec DeepSeek...")
            response = self.llm.chat_completions_create(
                messages=messages,
                temperature=self.temperature,
                max_tokens=20480  # ← Changez de 20000 à 20480
            )
            
            content = response['choices'][0]['message']['content'].strip()
            usage = response.get('usage', {})
            tokens_used = usage.get('total_tokens', 0)
            
            print(f"   💰 Tokens utilisés: {tokens_used}")
            
            # Calcul du nombre de mots généré
            word_count = len(content.split())
            print(f"   📊 Contenu généré: {word_count} mots")
            
            # Vérification de l'atteinte de l'objectif
            completion_rate = (word_count / word_count_target) * 100
            print(f"   📈 Objectif atteint: {completion_rate:.1f}%")
            
            return content
                
        except Exception as e:
            print(f"❌ Erreur lors de la génération: {e}")
            return None
    
    def process_queries(self, query_ids: List[int]):
        """Traite une liste de requêtes pour la génération de contenu"""
        print(f"\n📝 GÉNÉRATION DE CONTENU POUR {len(query_ids)} REQUÊTE(S): {query_ids}")
        
        successful = 0
        total_words_generated = 0
        initial_tokens = self.llm.total_tokens_used
        
        for query_id in query_ids:
            try:
                generated_content = self.generate_content_for_query(query_id)
                
                if generated_content:
                    # Calcul des mots
                    word_count = len(generated_content.split())
                    total_words_generated += word_count
                    
                    # Intégration dans consigne.json
                    for query in self.consigne_data['queries']:
                        if query['id'] == query_id:
                            query['generated_content'] = generated_content
                            query['final_word_count'] = word_count
                            query['generation_method'] = 'deepseek_content_generator'
                            query['content_generated_at'] = time.strftime("%Y-%m-%d %H:%M:%S")
                            break
                    
                    print(f"   ✅ Contenu généré avec succès ({word_count} mots)")
                    successful += 1
                else:
                    print(f"   ❌ Échec génération pour ID {query_id}")
                    
            except Exception as e:
                print(f"   ❌ Erreur lors de la génération ID {query_id}: {e}")
        
        # Sauvegarde finale
        try:
            self.save_consigne()
            print(f"\n💾 Fichier {self.consigne_path} mis à jour avec succès!")
            print(f"📊 Résultats: {successful}/{len(query_ids)} requêtes traitées avec succès")
            print(f"📝 Total mots générés: {total_words_generated}")
            
            # Statistiques d'usage DeepSeek
            final_stats = self.llm.get_usage_stats()
            tokens_used_session = final_stats['total_tokens'] - initial_tokens
            print(f"🔢 Tokens utilisés cette session: {tokens_used_session}")
            print(f"📈 Total tokens utilisés: {final_stats['total_tokens']}")
            print(f"🔄 Total requêtes API: {final_stats['total_requests']}")
            
            if successful > 0:
                avg_tokens_per_word = tokens_used_session / total_words_generated if total_words_generated > 0 else 0
                print(f"⚡ Efficacité: {avg_tokens_per_word:.2f} tokens/mot généré")
            
        except Exception as e:
            print(f"❌ Erreur lors de la sauvegarde: {e}")


def main():
    """Point d'entrée principal"""
    print("📝 GÉNÉRATEUR DE CONTENU D'ARTICLES - DEEPSEEK")
    print("=" * 60)
    print("✍️  Génère le contenu complet basé sur les plans existants")
    print("🎯 Compatible avec la structure de données existante")
    
    # Vérification de la clé API DeepSeek
    if not os.getenv('DEEPSEEK_KEY'):
        print("❌ Variable d'environnement DEEPSEEK_KEY manquante.")
        print("Ajoutez votre clé API DeepSeek:")
        print("export DEEPSEEK_KEY='your-api-key-here'")
        print("Ou créez un fichier .env avec: DEEPSEEK_KEY=your-api-key-here")
        sys.exit(1)
    
    try:
        generator = ContentGenerator(
            model_name="deepseek-reasoner",
            temperature=0.1
        )
        
        # Sélection et traitement
        selected_ids = generator.select_queries_to_process()
        if selected_ids:
            generator.process_queries(selected_ids)
        else:
            print("ℹ️  Aucune requête sélectionnée.")
            
    except KeyboardInterrupt:
        print("\n\n⏹️  Arrêt demandé par l'utilisateur.")
    except Exception as e:
        print(f"\n❌ Erreur inattendue: {e}")
        raise


if __name__ == "__main__":
    main()