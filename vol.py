#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Google Custom Search - Analyseur d'Autorité de Domaine pour rankscore_dom.json
Analyse les domaines depuis les URLs du fichier rankscore_dom.json
"""

import requests
import sys
import argparse
import json
import whois
import os
import asyncio
import aiohttp
from datetime import datetime
from dotenv import load_dotenv
from urllib.parse import urlparse
# Configuration API (remplace par tes vraies clés)

load_dotenv()

API_KEY = os.getenv('API_KEY')
CSE_ID = os.getenv('CSE_ID')

if not API_KEY or not CSE_ID:
    raise ValueError("API_KEY et CSE_ID doivent être définis dans le fichier .env")


class DomainAuthorityAnalyzer:
    
    def __init__(self, api_key=API_KEY, cse_id=CSE_ID, max_concurrent=5):
        self.api_key = api_key
        self.cse_id = cse_id
        self.analysis_data = []
        self.max_concurrent = max_concurrent
        self.session = None
        self.semaphore = None

    def load_rankscore_data(self, filepath: str = "rankscore_dom.json"):
        """Charge les données depuis le fichier rankscore_dom.json"""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # Structure rankscore_dom.json:
            # data['analyses'] - Liste des analyses
            # analysis['query'] - Requête de l'analyse
            # analysis['results'] - Liste des résultats
            # result['position'] - Position SERP
            # result['url'] - URL du site
            # result['title'] - Titre

            analyses = data.get('analyses', [])
            urls_found = []

            for analysis_idx, analysis in enumerate(analyses):
                query = analysis.get('query', '')
                results = analysis.get('results', [])

                for result in results:
                    position = result.get('position', 0)
                    url = result.get('url', '')
                    title = result.get('title', '')

                    if url:
                        # Extraire le domaine de l'URL
                        parsed_url = urlparse(url)
                        domain = parsed_url.netloc.replace('www.', '')

                        urls_found.append({
                            'analysis_idx': analysis_idx,
                            'position': position,
                            'url': url,
                            'domain': domain,
                            'title': title,
                            'query': query
                        })

            self.analysis_data = urls_found
            print(f"✅ {len(self.analysis_data)} URLs chargées depuis {filepath}")
            return True

        except Exception as e:
            print(f"❌ Erreur chargement: {e}")
            import traceback
            traceback.print_exc()
            return False

    def extract_domain_from_url(self, url):
        """Extrait le domaine principal d'une URL"""
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.replace('www.', '')
            return domain
        except:
            return url

    async def __aenter__(self):
        """Context manager pour gestion async des sessions"""
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30),
            connector=aiohttp.TCPConnector(limit=100, limit_per_host=10)
        )
        self.semaphore = asyncio.Semaphore(self.max_concurrent)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Fermeture propre de la session"""
        if self.session:
            await self.session.close()
    
    def get_domain_age(self, domain):
        """Récupère l'âge du domaine en années via WHOIS"""
        try:
            w = whois.whois(domain)
            creation_date = w.creation_date
            
            if isinstance(creation_date, list):
                creation_date = creation_date[0]
            
            if creation_date:
                age_years = (datetime.now() - creation_date).days / 365.25
                return max(0, age_years)
                
        except Exception as e:
            print(f"Erreur WHOIS pour {domain}: {e}")
        
        return None
    
    async def get_search_count(self, query):
        """Effectue une requête Google Custom Search asynchrone et retourne le nombre de résultats"""
        url = "https://www.googleapis.com/customsearch/v1"
        params = {
            'key': self.api_key,
            'cx': self.cse_id,
            'q': query,
            'num': 1,
            'fields': 'searchInformation(totalResults,searchTime)'
        }

        async with self.semaphore:  # Limiter la concurrence
            try:
                async with self.session.get(url, params=params) as response:
                    if response.status != 200:
                        text = await response.text()
                        print(f"Erreur HTTP {response.status}: {text}")
                        return None

                    data = await response.json()

                    if 'error' in data:
                        error_msg = data['error'].get('message', 'Erreur inconnue')
                        print(f"Erreur API: {error_msg}")
                        return None

                    search_info = data.get('searchInformation', {})
                    total_results = search_info.get('totalResults')
                    search_time = search_info.get('searchTime', 0)

                    return {
                        'count': int(total_results) if total_results else 0,
                        'search_time': float(search_time)
                    }

            except Exception as e:
                print(f"Erreur requête pour '{query}': {e}")
                return None
    
    async def analyze_domain(self, domain):
        """Analyse complète d'un domaine de manière asynchrone"""
        print(f"Recherche des pages indexées pour: {domain}")

        # 1. Pages totales indexées
        base_query = f"site:{domain}"

        # 2. Contenu récent - lancer les deux requêtes en parallèle
        fresh_query = f"site:{domain} after:2023"

        # Exécuter les requêtes API en parallèle
        total_result, fresh_result = await asyncio.gather(
            self.get_search_count(base_query),
            self.get_search_count(fresh_query),
            return_exceptions=True
        )

        # Vérifier les erreurs
        if isinstance(total_result, Exception) or not total_result or total_result['count'] == 0:
            print(f"Aucun résultat trouvé pour {domain}")
            return None

        if isinstance(fresh_result, Exception):
            fresh_result = None

        fresh_count = fresh_result['count'] if fresh_result else 0
        total_count = total_result['count']

        # 3. Âge du domaine (synchrone car WHOIS est généralement bloquant)
        domain_age = self.get_domain_age(domain)

        # 4. Calculs
        freshness_ratio = fresh_count / total_count if total_count > 0 else 0

        return {
            'domain': domain,
            'indexed_pages': total_count,
            'fresh_content_2023': fresh_count,
            'freshness_ratio': round(freshness_ratio, 3),
            'search_time': total_result['search_time'],
            'domain_age_years': round(domain_age, 1) if domain_age else None,
            'query_used': base_query
        }
    
    def classify_domain_size(self, count):
        """Classifie la taille du domaine"""
        if count > 1000000:
            return "Giant (1M+ pages)"
        elif count > 100000:
            return "Large (100k+ pages)"
        elif count > 10000:
            return "Established (10k+ pages)"
        elif count > 1000:
            return "Medium (1k+ pages)"
        elif count > 100:
            return "Small (100+ pages)"
        else:
            return "Very Small (<100 pages)"
    
    def get_activity_level(self, fresh_count):
        """Détermine le niveau d'activité basé sur le volume absolu"""
        if fresh_count >= 300:
            return "Très dynamique"
        elif fresh_count >= 150:
            return "Actif"
        elif fresh_count >= 50:
            return "Modérément actif"
        elif fresh_count >= 20:
            return "Peu actif"
        elif fresh_count >= 5:
            return "Quasi-inactif"
        else:
            return "Abandonné"
    
    def calculate_authority_score(self, data):
        """Calcule le score d'autorité composite"""
        indexed_count = data['indexed_pages']
        domain_age = data.get('domain_age_years')
        fresh_count = data['fresh_content_2023']
        domain_name = data['domain']
        
        # Score pages indexées (0-60 points)
        if indexed_count > 1000000:
            base_score = 60
        elif indexed_count > 100000:
            base_score = 50
        elif indexed_count > 10000:
            base_score = 40
        elif indexed_count > 1000:
            base_score = 25
        elif indexed_count > 100:
            base_score = 15
        else:
            base_score = 8
        
        # Bonus âge (0-20 points)
        age_bonus = 0
        if domain_age:
            if domain_age >= 20:
                age_bonus = 20
            elif domain_age >= 15:
                age_bonus = 16
            elif domain_age >= 10:
                age_bonus = 12
            elif domain_age >= 5:
                age_bonus = 8
            elif domain_age >= 2:
                age_bonus = 4
            else:
                age_bonus = 2
        
        # Bonus activité récente (0-15 points) - approche absolue
        if fresh_count >= 300:
            activity_bonus = 15
        elif fresh_count >= 150:
            activity_bonus = 12
        elif fresh_count >= 50:
            activity_bonus = 8
        elif fresh_count >= 20:
            activity_bonus = 5
        elif fresh_count >= 5:
            activity_bonus = 2
        else:
            activity_bonus = 0
        
        # Bonus domaines géants (0-5 points)
        giant_domains = ['google.com', 'linkedin.com', 'microsoft.com', 'amazon.com', 'apple.com', 'youtube.com']
        giant_bonus = 5 if any(giant in domain_name.lower() for giant in giant_domains) else 0
        
        # Malus volume faible (réalité du web - petits sites généralement non-compétitifs)
        volume_malus = 0
        if indexed_count < 100:
            volume_malus = -8  # Micro-sites généralement abandonnés ou de faible qualité
        elif indexed_count < 500:
            volume_malus = -5  # Petits sites souvent peu sérieux
        elif indexed_count < 1000:
            volume_malus = -2  # Sites modestes mais potentiellement viables
        
        total_score = base_score + age_bonus + activity_bonus + giant_bonus + volume_malus
        return max(total_score, 5)  # Score minimum de 5
    
    def print_analysis(self, data):
        """Affiche l'analyse formatée"""
        domain = data['domain']
        count = data['indexed_pages']
        fresh_count = data['fresh_content_2023']
        freshness_ratio = data['freshness_ratio']
        domain_age = data.get('domain_age_years')
        search_time = data['search_time']
        
        classification = self.classify_domain_size(count)
        activity_level = self.get_activity_level(fresh_count)
        authority_score = self.calculate_authority_score(data)
        
        print(f"\n{'='*60}")
        print(f"ANALYSE D'AUTORITÉ COMPLÈTE - {domain.upper()}")
        print(f"{'='*60}")
        print(f"Pages indexées visibles: {count:,}")
        print(f"Contenu récent (depuis 2023): {fresh_count:,} pages")
        print(f"Ratio de fraîcheur: {freshness_ratio:.1%}")
        print(f"Âge du domaine: {domain_age:.1f} ans" if domain_age else "Âge du domaine: Non disponible")
        print(f"Temps de recherche: {search_time}s")
        print(f"Classification: {classification}")
        print(f"Score d'autorité composite: {authority_score}/100")
        
        # Décomposition du score
        base_score = 60 if count > 1000000 else 50 if count > 100000 else 40 if count > 10000 else 25 if count > 1000 else 15 if count > 100 else 8
        age_bonus = 20 if domain_age and domain_age >= 20 else 16 if domain_age and domain_age >= 15 else 12 if domain_age and domain_age >= 10 else 8 if domain_age and domain_age >= 5 else 4 if domain_age and domain_age >= 2 else 2 if domain_age else 0
        activity_bonus = 15 if fresh_count >= 300 else 12 if fresh_count >= 150 else 8 if fresh_count >= 50 else 5 if fresh_count >= 20 else 2 if fresh_count >= 5 else 0
        
        print(f"  ├─ Score pages indexées: {base_score}/60")
        print(f"  ├─ Bonus âge domaine: {age_bonus}/20")
        print(f"  └─ Bonus activité récente: {activity_bonus}/15")
        
        print(f"État d'activité: {activity_level}")
        
        print(f"\nRequêtes utilisées:")
        print(f"  - Indexation: {data['query_used']}")
        print(f"  - Fraîcheur: site:{domain} after:2023")
        
        # Contexte concurrentiel
        print(f"\nContexte concurrentiel:")
        if authority_score >= 85:
            print("- Domaine quasi-imbattable (autorité maximale)")
        elif authority_score >= 70:
            print("- Concurrent très fort, nécessite stratégie avancée")
        elif authority_score >= 55:
            print("- Concurrent établi, compétition faisable avec effort")
        elif authority_score >= 35:
            print("- Concurrent moyen, opportunité de dépassement réaliste")
        elif authority_score >= 20:
            print("- Concurrent faible, dépassement probable avec contenu qualité")
        else:
            print("- Concurrent très faible, facilement dépassable")
        
        # Recommandations tactiques
        print(f"\nRecommandations tactiques:")
        if fresh_count < 20:
            print("- Opportunité: Concurrent peu actif, fenêtre pour dominer par volume récent")
        elif fresh_count < 50:
            print("- Stratégie: Concurrent modérément actif, maintenir rythme 50+ pages/2ans")
        elif fresh_count >= 150:
            print("- Attention: Concurrent très productif, bataille d'endurance nécessaire")
        
        if domain_age and domain_age > 15 and fresh_count < 50:
            print("- Signal: Vieux domaine sous-exploité, opportunité de modernisation")
        
        if fresh_count > 100 and authority_score > 50:
            print("- Alerte: Concurrent établi ET dynamique, prioriser qualité sur quantité")

    def save_authority_analysis_to_rankscore(self, analysis_results, filepath: str = "rankscore_dom.json"):
        """Sauvegarde les résultats d'analyse d'autorité dans le fichier rankscore_dom.json existant"""
        try:
            # Charger le fichier existant
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # Créer un mapping des résultats par analysis_idx et position
            authority_map = {}
            for result in analysis_results:
                key = f"{result['analysis_idx']}_{result['position']}"
                authority_map[key] = result

            # Ajouter les données d'autorité aux analyses existantes
            analyses = data.get('analyses', [])

            for analysis_idx, analysis in enumerate(analyses):
                results = analysis.get('results', [])

                for result in results:
                    position = result.get('position', 0)
                    key = f"{analysis_idx}_{position}"

                    if key in authority_map:
                        authority_data = authority_map[key]

                        # Ajouter les données d'autorité après la clé 'content'
                        result['domain_authority'] = {
                            'domain': authority_data['domain'],
                            'indexed_pages': authority_data['indexed_pages'],
                            'fresh_content_2023': authority_data['fresh_content_2023'],
                            'freshness_ratio': authority_data['freshness_ratio'],
                            'domain_age_years': authority_data.get('domain_age_years'),
                            'authority_score': authority_data['authority_score'],
                            'classification': authority_data['classification'],
                            'activity_level': authority_data['activity_level'],
                            'search_time': authority_data['search_time'],
                            'analysis_timestamp': authority_data['analysis_timestamp']
                        }

            # Mettre à jour le timestamp
            data['last_updated'] = datetime.now().isoformat()

            # Sauvegarder le fichier
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            print(f"💾 Résultats d'autorité sauvegardés dans {filepath}")
            return True

        except Exception as e:
            print(f"❌ Erreur sauvegarde: {e}")
            import traceback
            traceback.print_exc()
            return False

    async def analyze_all_domains(self):
        """Analyse tous les domaines chargés depuis rankscore_dom.json de manière asynchrone"""
        if not self.analysis_data:
            print("❌ Aucune donnée chargée. Utilisez load_rankscore_data() d'abord.")
            return []

        print(f"\n{'='*60}")
        print(f"🚀 ANALYSE D'AUTORITÉ DE DOMAINE ASYNCHRONE")
        print(f"{'='*60}")
        print(f"Total des URLs à analyser: {len(self.analysis_data)}")
        print(f"Concurrence maximale: {self.max_concurrent}")

        results = []
        processed_domains = {}  # Cache des domaines déjà analysés

        # Regrouper par domaine unique pour éviter les analyses redondantes
        domain_groups = {}
        for item in self.analysis_data:
            domain = item['domain']
            if domain not in domain_groups:
                domain_groups[domain] = []
            domain_groups[domain].append(item)

        # Créer les tâches d'analyse pour les domaines uniques
        async def analyze_single_domain(domain, items):
            """Analyse un seul domaine et applique le résultat à tous ses items"""
            try:
                print(f"\n🔍 Analyse en cours: {domain}")
                domain_analysis = await self.analyze_domain(domain)

                if domain_analysis:
                    # Enrichir avec les métadonnées communes
                    base_result = {
                        **domain_analysis,
                        'classification': self.classify_domain_size(domain_analysis['indexed_pages']),
                        'authority_score': self.calculate_authority_score(domain_analysis),
                        'activity_level': self.get_activity_level(domain_analysis['fresh_content_2023']),
                        'analysis_timestamp': datetime.now().isoformat()
                    }

                    # Créer un résultat pour chaque position/query de ce domaine
                    domain_results = []
                    for item in items:
                        enhanced_result = base_result.copy()
                        enhanced_result.update({
                            'analysis_idx': item['analysis_idx'],
                            'position': item['position'],
                            'url': item['url'],
                            'title': item['title'],
                            'query': item['query']
                        })
                        domain_results.append(enhanced_result)

                    # Affichage du résumé
                    print(f"✅ {domain}")
                    print(f"   Pages indexées: {base_result['indexed_pages']:,}")
                    print(f"   Score d'autorité: {base_result['authority_score']}/100")
                    print(f"   Classification: {base_result['classification']}")
                    print(f"   Positions SERP: {[item['position'] for item in items]}")

                    return domain_results
                else:
                    print(f"❌ Échec de l'analyse pour {domain}")
                    return []

            except Exception as e:
                print(f"❌ Erreur lors de l'analyse de {domain}: {e}")
                return []

        # Lancer les analyses en parallèle avec contrôle de concurrence
        print(f"\n🚀 Lancement de {len(domain_groups)} analyses en parallèle...")

        # Créer toutes les tâches d'analyse
        tasks = [
            analyze_single_domain(domain, items)
            for domain, items in domain_groups.items()
        ]

        # Exécuter avec gather pour traiter en parallèle
        domain_results_list = await asyncio.gather(*tasks, return_exceptions=True)

        # Collecter tous les résultats
        for domain_results in domain_results_list:
            if isinstance(domain_results, Exception):
                print(f"❌ Erreur d'analyse: {domain_results}")
                continue
            results.extend(domain_results)

        print(f"\n{'='*60}")
        print(f"📊 RÉSUMÉ GLOBAL")
        print(f"{'='*60}")
        print(f"URLs analysées: {len(results)}")
        print(f"Domaines uniques: {len(domain_groups)}")

        return results

async def main_async():
    """Fonction principale asynchrone"""
    parser = argparse.ArgumentParser(
        description="Analyseur d'autorité de domaine ASYNC - Fonctionne avec rankscore_dom.json",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Modes d'utilisation:

1. Mode rankscore asynchrone (défaut):
  python vol.py --rankscore --concurrent 10
  -> Analyse tous les domaines depuis rankscore_dom.json en parallèle

2. Mode domaine unique (legacy):
  python vol.py linkedin.com
  python vol.py blog.waalaxy.com --json
  python vol.py example.com --verbose

3. Paramètres optionnels:
  --file FICHIER        Spécifier un fichier rankscore différent
  --concurrent N        Nombre de requêtes simultanées (défaut: 5)
  --json               Sortie JSON pour mode domaine unique
  --verbose            Mode verbeux
        """
    )

    parser.add_argument('domain', nargs='?', help='Nom de domaine à analyser (mode legacy)')
    parser.add_argument('--rankscore', action='store_true', default=True,
                       help='Analyser depuis rankscore_dom.json (mode par défaut)')
    parser.add_argument('--file', default='rankscore_dom.json',
                       help='Fichier rankscore à utiliser (défaut: rankscore_dom.json)')
    parser.add_argument('--concurrent', type=int, default=5,
                       help='Nombre de requêtes simultanées (défaut: 5)')
    parser.add_argument('--json', action='store_true', help='Sortie en format JSON (mode legacy)')
    parser.add_argument('--verbose', '-v', action='store_true', help='Mode verbeux')

    args = parser.parse_args()

    try:
        # Mode rankscore asynchrone (par défaut)
        if args.rankscore and not args.domain:
            print(f"🔧 Mode rankscore ASYNC - Analyse depuis {args.file}")
            print(f"⚡ Concurrence: {args.concurrent} requêtes simultanées")

            # Créer l'analyseur avec contexte async
            async with DomainAuthorityAnalyzer(max_concurrent=args.concurrent) as analyzer:
                # Charger les données
                if not analyzer.load_rankscore_data(args.file):
                    print("❌ Impossible de charger les données")
                    sys.exit(1)

                # Mesurer le temps d'exécution
                start_time = datetime.now()

                # Analyser tous les domaines en parallèle
                results = await analyzer.analyze_all_domains()

                end_time = datetime.now()
                duration = (end_time - start_time).total_seconds()

                if not results:
                    print("❌ Aucun résultat obtenu")
                    sys.exit(1)

                # Sauvegarder dans rankscore_dom.json
                if analyzer.save_authority_analysis_to_rankscore(results, args.file):
                    print(f"\n✅ Analyse terminée avec succès!")
                    print(f"📊 {len(results)} analyses sauvegardées dans {args.file}")
                    print(f"⏱️  Temps d'exécution: {duration:.2f} secondes")
                    print(f"⚡ Vitesse: {len(results)/duration:.2f} analyses/seconde")
                else:
                    print("❌ Erreur lors de la sauvegarde")
                    sys.exit(1)

        # Mode legacy - domaine unique (avec session async)
        elif args.domain:
            print(f"🔧 Mode domaine unique - Analyse de {args.domain}")

            # Nettoyer le domaine
            domain = args.domain.replace('https://', '').replace('http://', '').replace('www.', '').strip('/')

            async with DomainAuthorityAnalyzer(max_concurrent=1) as analyzer:
                # Analyser le domaine
                result = await analyzer.analyze_domain(domain)

                if not result:
                    print("Échec de l'analyse")
                    sys.exit(1)

                if args.json:
                    # Sortie JSON
                    enhanced_result = result.copy()
                    enhanced_result['classification'] = analyzer.classify_domain_size(result['indexed_pages'])
                    enhanced_result['authority_score'] = analyzer.calculate_authority_score(result)
                    enhanced_result['activity_level'] = analyzer.get_activity_level(result['fresh_content_2023'])
                    print(json.dumps(enhanced_result, indent=2))
                else:
                    # Affichage formaté
                    analyzer.print_analysis(result)

        else:
            print("❌ Utilisation: python vol.py [--rankscore] ou python vol.py <domain>")
            parser.print_help()
            sys.exit(1)

    except KeyboardInterrupt:
        print(f"\nAnalyse interrompue par l'utilisateur")
        sys.exit(1)
    except Exception as e:
        print(f"Erreur: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

def main():
    """Point d'entrée synchrone qui lance la version asynchrone"""
    try:
        # Vérifier si aiohttp est installé
        import aiohttp
        asyncio.run(main_async())
    except ImportError:
        print("❌ Module 'aiohttp' manquant. Installez-le avec: pip install aiohttp")
        print("🔄 Basculement vers le mode synchrone...")
        # Fallback vers une version synchrone simplifiée si besoin
        sys.exit(1)

if __name__ == "__main__":
    main()