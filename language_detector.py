import os
import json
import logging
import subprocess
import sys
from typing import Dict, Optional, List
from pathlib import Path
import re

# Configuration du logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class LanguageDetector:
    """Détecteur de langue pour les fichiers de consigne"""
    
    def __init__(self, base_dir: str = None):
        self.base_dir = Path(base_dir) if base_dir else Path(__file__).parent
        
        # Patterns pour détecter la langue
        self.french_patterns = [
            r'\b(comment|recharger|voiture|électrique|pourquoi|brancher)\b',
            r'\b(le|la|les|des|une|du|de|et|avec|pour|sur)\b',
            r'\b(être|avoir|faire|aller|voir|savoir|pouvoir)\b'
        ]
        
        self.english_patterns = [
            r'\b(how|to|charge|electric|car|why|connect)\b',
            r'\b(the|and|or|with|for|on|in|at|by)\b',
            r'\b(is|are|was|were|have|has|had|do|does)\b'
        ]
    
    def detect_language_from_system_file(self) -> Optional[str]:
        """Détecte la langue depuis le fichier system.json"""
        system_file = self.base_dir / "system.json"
        
        try:
            if system_file.exists():
                with open(system_file, 'r', encoding='utf-8') as f:
                    system_data = json.load(f)
                    language = system_data.get('language', '').lower()
                    
                    if language in ['fr', 'french', 'français']:
                        logging.info(f"Langue détectée depuis system.json: français")
                        return 'fr'
                    elif language in ['en', 'english', 'anglais']:
                        logging.info(f"Langue détectée depuis system.json: anglais")
                        return 'en'
                    else:
                        logging.warning(f"Langue non reconnue dans system.json: {language}")
            else:
                logging.info("Fichier system.json non trouvé")
                
        except Exception as e:
            logging.error(f"Erreur lors de la lecture de system.json: {e}")
        
        return None
    
    def detect_language_from_text(self, texts: List[str]) -> str:
        """Détecte la langue depuis une liste de textes"""
        if not texts:
            return 'en'  # Défaut anglais
        
        # Joindre tous les textes
        combined_text = ' '.join(texts).lower()
        
        # Compter les matches pour chaque langue
        french_score = 0
        english_score = 0
        
        for pattern in self.french_patterns:
            french_score += len(re.findall(pattern, combined_text, re.IGNORECASE))
        
        for pattern in self.english_patterns:
            english_score += len(re.findall(pattern, combined_text, re.IGNORECASE))
        
        # Déterminer la langue
        if french_score > english_score:
            detected = 'fr'
        elif english_score > french_score:
            detected = 'en'
        else:
            # En cas d'égalité, vérifier quelques mots clés spécifiques
            if any(word in combined_text for word in ['comment', 'pourquoi', 'voiture']):
                detected = 'fr'
            elif any(word in combined_text for word in ['how', 'why', 'electric']):
                detected = 'en'
            else:
                detected = 'en'  # Défaut
        
        logging.info(f"Scores de détection - Français: {french_score}, Anglais: {english_score}")
        logging.info(f"Langue détectée depuis les textes: {'français' if detected == 'fr' else 'anglais'}")
        
        return detected
    
    def extract_texts_from_consigne(self, consigne_data: Dict) -> List[str]:
        """Extrait tous les textes du fichier consigne pour analyse"""
        texts = []
        
        # Récupérer les textes des requêtes
        for query in consigne_data.get('queries', []):
            text = query.get('text', '')
            if text:
                texts.append(text)
        
        # Récupérer d'autres textes si disponibles
        main_query = consigne_data.get('main_query', '')
        if main_query:
            texts.append(main_query)
        
        return texts
    
    def determine_language(self, consigne_file: str) -> str:
        """Détermine la langue à utiliser"""
        
        # 1. Essayer de détecter depuis system.json
        system_lang = self.detect_language_from_system_file()
        if system_lang:
            return system_lang
        
        # 2. Analyser le contenu du fichier consigne
        try:
            with open(consigne_file, 'r', encoding='utf-8') as f:
                consigne_data = json.load(f)
            
            texts = self.extract_texts_from_consigne(consigne_data)
            return self.detect_language_from_text(texts)
            
        except Exception as e:
            logging.error(f"Erreur lors de l'analyse du fichier consigne: {e}")
            return 'en'  # Défaut anglais

class ScriptRunner:
    """Gestionnaire d'exécution des scripts selon la langue"""
    
    def __init__(self, base_dir: str = None):
        self.base_dir = Path(base_dir) if base_dir else Path(__file__).parent
        
        # Noms des scripts par défaut (à ajuster selon vos noms de fichiers)
        self.scripts = {
            'fr': 'serp_semantic_batch_fr.py',  # Nom du script français
            'en': 'serp_semantic_batch_en.py'   # Nom du script anglais
        }
    
    def find_script_file(self, language: str) -> Optional[Path]:
        """Trouve le fichier script correspondant à la langue"""
        script_name = self.scripts.get(language)
        if not script_name:
            return None
        
        script_path = self.base_dir / script_name
        
        if script_path.exists():
            return script_path
        
        # Essayer avec des variantes de noms
        possible_names = [
            f"serp_processor_{language}.py",
            f"processor_{language}.py",
            f"batch_processor_{language}.py",
            f"semantic_processor_{language}.py"
        ]
        
        for name in possible_names:
            alt_path = self.base_dir / name
            if alt_path.exists():
                logging.info(f"Script trouvé avec nom alternatif: {name}")
                return alt_path
        
        return None
    
    def run_script(self, language: str) -> bool:
        """Exécute le script correspondant à la langue"""
        script_file = self.find_script_file(language)
        
        if not script_file:
            logging.error(f"Script non trouvé pour la langue: {language}")
            logging.info(f"Scripts recherchés: {list(self.scripts.values())}")
            return False
        
        try:
            logging.info(f"Exécution du script: {script_file.name}")
            
            # Exécuter le script Python
            result = subprocess.run(
                [sys.executable, str(script_file)],
                cwd=str(self.base_dir),
                capture_output=True,
                text=True,
                timeout=3600  # Timeout de 1 heure
            )
            
            # Afficher la sortie
            if result.stdout:
                print("=== SORTIE DU SCRIPT ===")
                print(result.stdout)
            
            if result.stderr:
                print("=== ERREURS DU SCRIPT ===")
                print(result.stderr)
            
            if result.returncode == 0:
                logging.info(f"Script exécuté avec succès (code: {result.returncode})")
                return True
            else:
                logging.error(f"Script terminé avec erreur (code: {result.returncode})")
                return False
                
        except subprocess.TimeoutExpired:
            logging.error("Le script a dépassé le timeout d'exécution (1 heure)")
            return False
        except Exception as e:
            logging.error(f"Erreur lors de l'exécution du script: {e}")
            return False

def find_consigne_file(base_dir: Path) -> Optional[Path]:
    """Trouve automatiquement le fichier de consigne"""
    
    # Chercher dans le dossier static
    static_dir = base_dir / "static"
    if static_dir.exists():
        consigne_files = list(static_dir.glob("consigne*.json"))
        if consigne_files:
            # Prendre le plus récent
            most_recent = max(consigne_files, key=os.path.getmtime)
            logging.info(f"Fichier consigne trouvé: {most_recent.name}")
            return most_recent
    
    # Chercher dans le répertoire racine
    consigne_files = list(base_dir.glob("consigne*.json"))
    if consigne_files:
        most_recent = max(consigne_files, key=os.path.getmtime)
        logging.info(f"Fichier consigne trouvé: {most_recent.name}")
        return most_recent
    
    return None

def main():
    """Fonction principale"""
    try:
        logging.info("=== DÉMARRAGE DU DÉTECTEUR DE LANGUE ===")
        
        base_dir = Path(__file__).parent
        
        # 1. Trouver le fichier consigne
        consigne_file = find_consigne_file(base_dir)
        if not consigne_file:
            logging.error("Aucun fichier consigne*.json trouvé")
            return False
        
        # 2. Détecter la langue
        detector = LanguageDetector(base_dir)
        language = detector.determine_language(str(consigne_file))
        
        logging.info(f"🌍 Langue détectée: {'Français' if language == 'fr' else 'Anglais'} ({language})")
        
        # 3. Exécuter le script approprié
        runner = ScriptRunner(base_dir)
        success = runner.run_script(language)
        
        if success:
            logging.info("=== TRAITEMENT TERMINÉ AVEC SUCCÈS ===")
            return True
        else:
            logging.error("=== ÉCHEC DU TRAITEMENT ===")
            return False
            
    except KeyboardInterrupt:
        logging.info("Traitement interrompu par l'utilisateur")
        return False
    except Exception as e:
        logging.error(f"Erreur critique: {e}")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)