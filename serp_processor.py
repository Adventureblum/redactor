#!/usr/bin/env python3

import json
import subprocess
import os
import sys
import time
from pathlib import Path
import hashlib
import argparse
import glob

class SerpSingleProcessor:
    def __init__(self, consigne_file: str = None, 
                 js_script: str = "serp_extractor.js",
                 output_dir: str = "results",
                 processed_file: str = "processed_queries.json"):
        """
        Processeur SERP - Une requête par exécution
        
        Args:
            consigne_file: Chemin vers le fichier consigne.json (None pour auto-détection)
            js_script: Nom du script JavaScript à exécuter
            output_dir: Dossier de sortie pour les résultats
            processed_file: Fichier pour traquer les requêtes déjà traitées
        """
        self.consigne_file = self._find_consigne_file(consigne_file)
        self.js_script = js_script
        self.output_dir = Path(output_dir)
        self.processed_file = processed_file
        
        # Créer le dossier de sortie s'il n'existe pas
        self.output_dir.mkdir(exist_ok=True)
    
    def _find_consigne_file(self, consigne_file: str = None) -> str:
        """
        Trouve automatiquement le fichier de consigne dans le dossier static
        
        Args:
            consigne_file: Chemin spécifique ou None pour auto-détection
            
        Returns:
            str: Chemin vers le fichier de consigne trouvé
            
        Raises:
            FileNotFoundError: Si aucun fichier de consigne n'est trouvé
        """
        if consigne_file:
            # Si un fichier spécifique est fourni, l'utiliser
            return consigne_file
        
        # Chercher les fichiers consigne dans le dossier static
        consigne_pattern = "static/consigne*.json"
        consigne_files = glob.glob(consigne_pattern)
        
        if not consigne_files:
            raise FileNotFoundError(f"❌ Aucun fichier de consigne trouvé dans le dossier static/ (pattern: {consigne_pattern})")
        
        if len(consigne_files) == 1:
            found_file = consigne_files[0]
            print(f"📁 Fichier de consigne détecté: {found_file}")
            return found_file
        
        # Si plusieurs fichiers trouvés, prendre le plus récent
        consigne_files.sort(key=os.path.getmtime, reverse=True)
        most_recent = consigne_files[0]
        print(f"📁 Plusieurs fichiers de consigne trouvés, utilisation du plus récent: {most_recent}")
        print(f"   Autres fichiers ignorés: {', '.join(consigne_files[1:])}")
        return most_recent
    
    def _load_processed_queries(self) -> set:
        """Charge la liste des requêtes déjà traitées"""
        if os.path.exists(self.processed_file):
            try:
                with open(self.processed_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    processed = set(data.get('processed_queries', []))
                    print(f"📋 {len(processed)} requêtes déjà traitées")
                    return processed
            except Exception as e:
                print(f"⚠️ Erreur lecture fichier processed: {e}")
                return set()
        return set()
    
    def _save_processed_query(self, query_hash: str, query_id: int, query_text: str):
        """Ajoute une requête à la liste des traitées"""
        processed_queries = self._load_processed_queries()
        processed_queries.add(query_hash)
        
        # Charger les détails existants
        details = {}
        if os.path.exists(self.processed_file):
            try:
                with open(self.processed_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    details = data.get('query_details', {})
            except:
                pass
        
        # Ajouter les détails de cette requête
        details[query_hash] = {
            'id': query_id,
            'text': query_text,
            'processed_at': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        
        # Sauvegarder
        data = {
            'processed_queries': list(processed_queries),
            'query_details': details,
            'last_updated': time.strftime('%Y-%m-%d %H:%M:%S'),
            'total_processed': len(processed_queries)
        }
        
        try:
            with open(self.processed_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            print(f"💾 Requête marquée comme traitée: {query_hash[:8]}...")
        except Exception as e:
            print(f"⚠️ Erreur sauvegarde: {e}")
    
    def _generate_query_hash(self, query_text: str) -> str:
        """Génère un hash unique pour une requête"""
        return hashlib.md5(query_text.lower().strip().encode('utf-8')).hexdigest()
    
    def _generate_output_filename(self, query_id: int, query_text: str) -> str:
        """Génère le nom de fichier de sortie"""
        clean_text = "".join(c for c in query_text if c.isalnum() or c in (' ', '-', '_')).strip()
        clean_text = clean_text.replace(' ', '_')[:40]
        return f"serp_{query_id:03d}_{clean_text}.json"
    
    def load_consigne(self) -> dict:
        """Charge le fichier consigne.json"""
        if not os.path.exists(self.consigne_file):
            raise FileNotFoundError(f"❌ Fichier consigne introuvable: {self.consigne_file}")
        
        try:
            with open(self.consigne_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                queries_count = len(data.get('queries', []))
                print(f"📄 Consigne chargée: {queries_count} requêtes")
                return data
        except Exception as e:
            raise Exception(f"❌ Erreur chargement consigne: {e}")
    
    def check_requirements(self) -> bool:
        """Vérifie que tous les prérequis sont présents"""
        # Vérifier le script JS
        if not os.path.exists(self.js_script):
            print(f"❌ Script JS introuvable: {self.js_script}")
            return False
        
        # Vérifier Node.js
        try:
            result = subprocess.run(['node', '--version'], 
                                  capture_output=True, text=True, timeout=5)
            if result.returncode != 0:
                print("❌ Node.js non disponible")
                return False
            print(f"✅ Node.js: {result.stdout.strip()}")
        except Exception as e:
            print(f"❌ Erreur Node.js: {e}")
            return False
        
        # Vérifier si playwright est installé
        try:
            result = subprocess.run(['node', '-e', 'require("playwright")'], 
                                  capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                print("✅ Playwright installé")
                
                # Test rapide du script JS
                print("🔧 Test rapide du script JS...")
                test_result = subprocess.run([
                    'node', self.js_script, '--help'
                ], capture_output=True, text=True, timeout=10)
                
                if test_result.returncode == 0:
                    print("✅ Script JS fonctionnel")
                    return True
                else:
                    print(f"❌ Script JS défaillant: {test_result.stderr}")
                    return False
            else:
                print("❌ Playwright non installé")
                print("💡 Installez-le avec: npm install playwright && npx playwright install")
                return False
        except Exception as e:
            print(f"❌ Erreur vérification Playwright: {e}")
            return False
    
    def debug_environment(self):
        """Debug des différences d'environnement"""
        print(f"\n🔍 DEBUG ENVIRONNEMENT")
        print(f"{'='*50}")
        print(f"📁 Répertoire de travail: {os.getcwd()}")
        print(f"🐍 Python: {sys.version}")
        print(f"📋 Variables d'environnement importantes:")
        
        important_vars = ['PATH', 'NODE_PATH', 'DISPLAY', 'HOME', 'USER']
        for var in important_vars:
            value = os.environ.get(var, 'NON DÉFINI')
            print(f"   {var}: {value}")
        
        # Test de commande directe vs subprocess
        print(f"\n🧪 Test Node.js direct vs subprocess:")
        try:
            # Test direct
            direct_result = subprocess.run(['node', '--version'], 
                                         capture_output=True, text=True)
            print(f"   Direct: {direct_result.stdout.strip()}")
            
            # Test avec environnement
            env = os.environ.copy()
            env_result = subprocess.run(['node', '--version'], 
                                      capture_output=True, text=True, env=env)
            print(f"   Avec env: {env_result.stdout.strip()}")
            
        except Exception as e:
            print(f"   ❌ Erreur: {e}")
    
    def test_js_script_directly(self, query_text: str = "test", verbose: bool = True):
        """Test le script JS directement pour comparer"""
        print(f"\n🧪 TEST DIRECT DU SCRIPT JS")
        print(f"{'='*50}")
        
        cmd = [
            'node', self.js_script,
            '--query', query_text,
            '--max-results', '1',
            '--output', 'test_direct.json'
        ]
        
        if verbose:
            cmd.append('--verbose')
        
        try:
            print(f"🚀 Commande: {' '.join(cmd)}")
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
                encoding='utf-8',
                env=os.environ.copy(),
                cwd=os.getcwd()
            )
            
            print(f"📋 Code de retour: {result.returncode}")
            print(f"📤 Stdout: {result.stdout[:500]}{'...' if len(result.stdout) > 500 else ''}")
            
            if result.stderr:
                print(f"📥 Stderr: {result.stderr[:500]}{'...' if len(result.stderr) > 500 else ''}")
            
            return result.returncode == 0
            
        except Exception as e:
            print(f"❌ Exception: {e}")
            return False
    
    def get_next_query(self):
        """Récupère la prochaine requête non traitée"""
        consigne = self.load_consigne()
        processed_queries = self._load_processed_queries()
        
        for query in consigne['queries']:
            query_hash = self._generate_query_hash(query['text'])
            
            if query_hash not in processed_queries:
                return query
        
        return None
    
    def process_single_query(self, max_results: int = 3, verbose: bool = False, no_delay: bool = False, custom_delay: int = None) -> bool:
        """
        Traite une seule requête (la prochaine non traitée)
        
        Returns:
            bool: True si une requête a été traitée, False si toutes sont déjà traitées
        """
        # Vérifier les prérequis
        if not self.check_requirements():
            return False
        
        # Récupérer la prochaine requête
        next_query = self.get_next_query()
        
        if not next_query:
            print("🎉 Toutes les requêtes ont été traitées !")
            return False
        
        query_id = next_query['id']
        query_text = next_query['text']
        query_hash = self._generate_query_hash(query_text)
        
        print(f"\n🎯 Traitement de la requête #{query_id}")
        print(f"📝 Texte: '{query_text}'")
        print(f"🔑 Hash: {query_hash[:12]}...")
        
        # Générer le nom de fichier de sortie
        output_filename = self._generate_output_filename(query_id, query_text)
        output_path = self.output_dir / output_filename
        
        # Construire la commande avec environnement préservé
        cmd = [
            'node', self.js_script,
            '--query', query_text,
            '--output', str(output_path),
            '--max-results', str(max_results)
        ]
        
        if verbose:
            cmd.append('--verbose')
        
        # Préserver l'environnement (important pour DISPLAY, etc.)
        env = os.environ.copy()
        env['NODE_ENV'] = 'production'
        
        # Gérer le délai anti-détection
        if not no_delay:
            if custom_delay is not None:
                delay = custom_delay
                print(f"⏱️ Délai personnalisé: {delay}s...")
            else:
                # Ajouter un délai raisonnable pour éviter la détection (entre 5s et 15s)
                import random
                delay = random.randint(5, 15)
                print(f"⏱️ Délai anti-détection: {delay}s...")
            time.sleep(delay)
        else:
            print("⚡ Délai anti-détection désactivé")
        
        # Exécuter le script JS
        try:
            print(f"🚀 Exécution: node {self.js_script} --query \"{query_text}\" ...")
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minutes max
                encoding='utf-8',
                env=env,  # Utiliser l'environnement préservé
                cwd=os.getcwd()  # S'assurer du bon répertoire de travail
            )
            
            if result.returncode == 0:
                print(f"✅ Extraction réussie !")
                print(f"📁 Fichier de sortie: {output_filename}")
                
                # Marquer comme traitée
                self._save_processed_query(query_hash, query_id, query_text)
                
                if verbose and result.stdout:
                    print(f"📋 Sortie détaillée:\n{result.stdout}")
                
                return True
            else:
                print(f"❌ Erreur lors de l'extraction")
                print(f"💥 Code de retour: {result.returncode}")
                if result.stderr:
                    print(f"📋 Erreur: {result.stderr}")
                if result.stdout:
                    print(f"📋 Sortie: {result.stdout}")
                return False
                
        except subprocess.TimeoutExpired:
            print(f"⏰ Timeout (5 minutes) atteint pour la requête")
            return False
        except Exception as e:
            print(f"💥 Exception: {e}")
            return False
    
    def show_status(self):
        """Affiche le statut des requêtes"""
        try:
            consigne = self.load_consigne()
            processed_queries = self._load_processed_queries()
            
            total_queries = len(consigne['queries'])
            processed_count = len(processed_queries)
            remaining_count = total_queries - processed_count
            
            print(f"\n📊 STATUT DES REQUÊTES")
            print(f"{'='*50}")
            print(f"📋 Total des requêtes: {total_queries}")
            print(f"✅ Requêtes traitées: {processed_count}")
            print(f"⏳ Requêtes restantes: {remaining_count}")
            print(f"📈 Progression: {(processed_count/total_queries)*100:.1f}%")
            
            if remaining_count > 0:
                next_query = self.get_next_query()
                if next_query:
                    print(f"🎯 Prochaine requête: #{next_query['id']} - '{next_query['text']}'")
            
        except Exception as e:
            print(f"❌ Erreur lors de l'affichage du statut: {e}")

def main():
    parser = argparse.ArgumentParser(description='Processeur SERP - Une requête par exécution')
    parser.add_argument('--max-results', '-n', type=int, default=3, 
                       help='Nombre max de résultats par requête (défaut: 3)')
    parser.add_argument('--verbose', '-v', action='store_true', 
                       help='Mode verbeux')
    parser.add_argument('--status', '-s', action='store_true', 
                       help='Afficher le statut et quitter')
    parser.add_argument('--consigne', default=None,
                       help='Chemin vers le fichier consigne.json (auto-détection si non spécifié)')
    parser.add_argument('--js-script', default='serp_extractor.js',
                       help='Nom du script JavaScript')
    parser.add_argument('--output-dir', default='results',
                       help='Dossier de sortie')
    parser.add_argument('--debug', '-d', action='store_true', 
                       help='Mode debug environnement')
    parser.add_argument('--test-js', action='store_true', 
                       help='Tester le script JS directement')
    parser.add_argument('--no-delay', action='store_true',
                       help='Désactiver le délai anti-détection')
    parser.add_argument('--delay', type=int, default=None,
                       help='Délai personnalisé en secondes (défaut: 5-15s aléatoire)')
    
    args = parser.parse_args()
    
    # Initialiser le processeur
    processor = SerpSingleProcessor(
        consigne_file=args.consigne,
        js_script=args.js_script,
        output_dir=args.output_dir
    )
    
    print("🎭 Processeur SERP - Une requête par exécution")
    print("=" * 50)
    
    try:
        if args.debug:
            processor.debug_environment()
        elif args.test_js:
            processor.test_js_script_directly()
        elif args.status:
            processor.show_status()
        else:
            success = processor.process_single_query(
                max_results=args.max_results,
                verbose=args.verbose,
                no_delay=args.no_delay,
                custom_delay=args.delay
            )
            
            if success:
                print("\n✅ Requête traitée avec succès !")
                processor.show_status()
            else:
                print("\n❌ Aucune requête traitée")
                processor.show_status()
                
    except KeyboardInterrupt:
        print("\n⏹️ Arrêt demandé par l'utilisateur")
        sys.exit(1)
    except Exception as e:
        print(f"\n💥 Erreur fatale: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()