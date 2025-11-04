#!/usr/bin/env python3
"""
Test script pour vérifier les fonctionnalités du script seotheme.py
"""

import os
import asyncio
from seotheme import SEOContentAnalyzer, auto_detect_consignes_file, parse_command_line_args

def test_language_detection():
    """Test de la détection de langue"""
    print("=== TEST 1: Détection de langue ===")

    try:
        analyzer = SEOContentAnalyzer()
        print(f"✅ Langue détectée: {analyzer.language}")
        print(f"✅ Prompt d'analyse: {len(analyzer.article_prompt)} caractères")
        print(f"✅ Prompt de synthèse: {len(analyzer.synthesis_prompt)} caractères")
    except Exception as e:
        print(f"❌ Erreur: {e}")

def test_auto_detection():
    """Test de l'auto-détection de fichiers"""
    print("\n=== TEST 2: Auto-détection de fichiers ===")

    try:
        file = auto_detect_consignes_file()
        print(f"✅ Fichier auto-détecté: {file}")
        print(f"✅ Fichier existe: {os.path.exists(file)}")
    except Exception as e:
        print(f"❌ Erreur: {e}")

def test_command_line_parsing():
    """Test du parsing des arguments de ligne de commande"""
    print("\n=== TEST 3: Parsing des arguments ===")

    # Sauvegarder sys.argv
    import sys
    original_argv = sys.argv.copy()

    try:
        # Test 1: Mode par défaut
        sys.argv = ['seotheme.py']
        mode, file = parse_command_line_args()
        print(f"✅ Mode défaut: {mode}, Fichier: {file}")

        # Test 2: Query spécifique
        sys.argv = ['seotheme.py', '--query', 'production_video']
        mode, file = parse_command_line_args()
        print(f"✅ Mode query: {mode}, Fichier: {file}")

        # Test 3: Fichier spécifique
        sys.argv = ['seotheme.py', '--file', 'static/consignesrun/consignes_production_video.json']
        mode, file = parse_command_line_args()
        print(f"✅ Mode file: {mode}, Fichier: {file}")

    except Exception as e:
        print(f"❌ Erreur: {e}")
    finally:
        # Restaurer sys.argv
        sys.argv = original_argv

async def test_analyzer_initialization():
    """Test d'initialisation de l'analyseur avec différents fichiers"""
    print("\n=== TEST 4: Initialisation de l'analyseur ===")

    try:
        # Test avec auto-détection
        file = auto_detect_consignes_file()
        analyzer = SEOContentAnalyzer()

        print(f"✅ Analyseur initialisé")
        print(f"✅ Langue: {analyzer.language}")

        # Test de chargement des données (sans traiter)
        if os.path.exists(file):
            print(f"✅ Fichier de consignes accessible: {file}")
        else:
            print(f"❌ Fichier de consignes non accessible: {file}")

    except Exception as e:
        print(f"❌ Erreur: {e}")

def main():
    """Fonction principale de test"""
    print("🧪 TESTS DE FONCTIONNALITÉ - SEOTHEME.PY")
    print("=" * 50)

    test_language_detection()
    test_auto_detection()
    test_command_line_parsing()

    # Test asynchrone
    asyncio.run(test_analyzer_initialization())

    print("\n" + "=" * 50)
    print("🎉 Tests terminés!")

if __name__ == "__main__":
    main()