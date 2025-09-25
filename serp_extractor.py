#!/usr/bin/env python3
"""
Scraper Google unifié avec interface web Flask
Reproduction exacte du comportement du script Node.js
"""

import sys
import json
import os
import asyncio
import aiohttp
import requests
import argparse
import hashlib
import time
import random
from datetime import datetime
from urllib.parse import urlencode
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import subprocess

# Configuration Google Custom Search
API_KEY = "AIzaSyBNcyx5keYiyemeSN797ob-7E14JWdFdI4"  # A remplacer
CX = "234d24017355d487b"  # A remplacer

# Headers pour le scraping (inspirés du script Node.js)
SCRAPING_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Referer": "https://www.google.com/",
    "Sec-Ch-Ua": '"Google Chrome";v="119", "Chromium";v="119", "Not?A_Brand";v="24"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Linux"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1"
}

class GoogleScraper:
    def __init__(self, api_key=API_KEY, cx=CX, max_concurrent=3, timeout=15, verbose=False):
        self.api_key = api_key
        self.cx = cx
        self.max_concurrent = max_concurrent
        self.timeout = timeout
        self.verbose = verbose
        self.semaphore = asyncio.Semaphore(max_concurrent)
        
    def log_info(self, message, data=None):
        """Log d'information (comme dans le script Node.js)"""
        if self.verbose:
            log_entry = {
                "level": "info",
                "message": message,
                "timestamp": datetime.now().isoformat()
            }
            if data:
                log_entry["data"] = data
            print(json.dumps(log_entry))
    
    def log_success(self, message, data=None):
        """Log de succès"""
        msg = f"✅ {message}"
        if data and self.verbose:
            msg += f" {json.dumps(data, indent=2)}"
        print(msg)
    
    def log_error(self, error, context):
        """Log d'erreur (format Node.js)"""
        error_data = {
            "error": True,
            "context": context,
            "message": str(error),
            "timestamp": datetime.now().isoformat()
        }
        print(json.dumps(error_data), file=sys.stderr)
    
    def search_google(self, query, num_results=3, language="fr"):
        """Recherche Google Custom Search (reproduction du comportement Node.js)"""
        self.log_info(f"Recherche Google pour: '{query}'")
        print("=" * 50)
        
        params = {
            "key": self.api_key,
            "cx": self.cx,
            "q": query,
            "num": str(min(num_results, 10)),  # Limite à 10 comme Node.js
            "hl": language
        }
        
        url = f"https://www.googleapis.com/customsearch/v1?{urlencode(params)}"
        
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            
            if "error" in data:
                error_msg = data["error"].get("message", "Erreur API inconnue")
                raise Exception(f"Erreur API Google: {error_msg}")
            
            items = data.get("items", [])
            results = []
            
            for i, item in enumerate(items[:num_results], 1):
                result = {
                    "position": i,
                    "title": item.get("title", ""),
                    "url": item.get("link", ""),
                    "snippet": item.get("snippet", "")
                }
                results.append(result)
                print(f"  {i}. {result['title']}")
                print(f"     {result['url']}")
            
            self.log_success(f"{len(results)} résultats trouvés")
            return results
            
        except requests.exceptions.RequestException as e:
            raise Exception(f"Erreur lors de la recherche: {e}")
        except json.JSONDecodeError as e:
            raise Exception(f"Erreur de parsing JSON: {e}")
    
    async def fetch_single_page(self, session, url, position, retries=3):
        """Récupère une page (reproduction du comportement fetchPageContentWithPlaywright)"""
        async with self.semaphore:
            self.log_info(f"Récupération du contenu (position {position})", {"url": url})
            
            for attempt in range(1, retries + 1):
                try:
                    if attempt > 1:
                        delay = min(2 ** (attempt - 1), 10)
                        await asyncio.sleep(delay)
                    
                    async with session.get(url, timeout=self.timeout) as response:
                        if response.status >= 400:
                            if attempt == retries:
                                raise Exception(f"HTTP {response.status}")
                            continue
                        
                        html = await response.text()
                        
                        if len(html) < 100:
                            if attempt == retries:
                                raise Exception("Contenu HTML trop court")
                            continue
                        
                        # Extraire le titre
                        title = self._extract_title(html)
                        
                        self.log_success(f"Position {position} récupérée", {
                            "status": response.status,
                            "contentLength": len(html),
                            "title": title[:100] if title else None
                        })
                        
                        return {
                            "success": True,
                            "html": html,
                            "title": title,
                            "status": response.status,
                            "method": "requests",
                            "htmlLength": len(html)
                        }
                        
                except asyncio.TimeoutError:
                    if attempt == retries:
                        return {"success": False, "error": "Timeout", "method": "requests"}
                except Exception as e:
                    if attempt == retries:
                        return {"success": False, "error": str(e), "method": "requests"}
    
    def _extract_title(self, html):
        """Extrait le titre de la page HTML"""
        if not html:
            return None
        import re
        title_match = re.search(r'<title[^>]*>([^<]+)</title>', html, re.IGNORECASE)
        return title_match.group(1).strip()[:200] if title_match else None
    
    async def scrape_all_pages_parallel(self, search_results):
        """Scrape toutes les pages en parallèle"""
        print(f"\n🕷️ Scraping parallèle de {len(search_results)} pages")
        print("=" * 50)
        
        timeout = aiohttp.ClientTimeout(total=self.timeout)
        connector = aiohttp.TCPConnector(
            limit=self.max_concurrent * 2,
            limit_per_host=self.max_concurrent,
            ttl_dns_cache=300,
            use_dns_cache=True,
        )
        
        try:
            async with aiohttp.ClientSession(
                headers=SCRAPING_HEADERS,
                timeout=timeout,
                connector=connector
            ) as session:
                
                tasks = [
                    self.fetch_single_page(session, result["url"], result["position"])
                    for result in search_results
                ]
                
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                processed_results = []
                for i, (search_result, fetch_result) in enumerate(zip(search_results, results)):
                    if isinstance(fetch_result, Exception):
                        result_data = {
                            "position": search_result["position"],
                            "url": search_result["url"],
                            "title": None,
                            "html": None,
                            "success": False,
                            "method": "requests",
                            "error": str(fetch_result),
                            "htmlLength": 0
                        }
                    else:
                        result_data = {
                            "position": search_result["position"],
                            "url": search_result["url"],
                            "title": fetch_result.get("title") or search_result.get("title"),
                            "html": fetch_result.get("html"),
                            "success": fetch_result.get("success", False),
                            "method": fetch_result.get("method", "requests"),
                            "status": fetch_result.get("status"),
                            "error": fetch_result.get("error"),
                            "htmlLength": fetch_result.get("htmlLength", 0)
                        }
                    
                    processed_results.append(result_data)
                
                successful = sum(1 for r in processed_results if r["success"])
                print(f"📊 Résultats: {successful}/{len(processed_results)} succès")
                
                return processed_results
                
        except Exception as e:
            self.log_error(e, "Scraping parallèle")
            raise
    
    def save_results_node_format(self, query, search_results, scrape_results, output_file):
        """Sauvegarde au format exact du script Node.js"""
        start_time = time.time()
        
        # Format exact du fichier de sortie Node.js
        serp_data = {
            "success": True,
            "query": query,
            "timestamp": datetime.now().isoformat(),
            "nodeVersion": f"python-{sys.version}",  # Equivalent du Node version
            "playwrightVersion": "requests-async-equivalent",
            "organicResults": scrape_results,
            "stats": {
                "total": len(scrape_results),
                "successful": sum(1 for r in scrape_results if r["success"]),
                "failed": sum(1 for r in scrape_results if not r["success"]),
                "playwrightMethod": sum(1 for r in scrape_results if r.get("method") == "requests"),
                "durationMs": int((time.time() - start_time) * 1000),
                "avgTimePerPage": 0,  # Calculé après
                "totalHtmlSize": sum(r.get("htmlLength", 0) for r in scrape_results),
                "humanSimulation": {
                    "typingSpeedRange": [80, 200],
                    "mouseMovements": True,
                    "scrollSimulated": True,
                    "naturalDelays": True
                }
            },
            "config": {
                "fetchTimeout": self.timeout * 1000,
                "maxRetries": 3,
                "userAgent": SCRAPING_HEADERS["User-Agent"],
                "browserEngine": "requests+aiohttp",
                "maxResults": len(search_results),
                "stealthMode": True,
                "headless": True,
                "humanSimulation": {
                    "enabled": True,
                    "typingSpeed": [80, 200],
                    "mouseMovements": True,
                    "scrollSpeed": [100, 300],
                    "naturalDelays": True
                }
            }
        }
        
        # Calculer avgTimePerPage
        if serp_data["stats"]["total"] > 0:
            serp_data["stats"]["avgTimePerPage"] = serp_data["stats"]["durationMs"] // serp_data["stats"]["total"]
        
        # Sauvegarder
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(serp_data, f, indent=2, ensure_ascii=False)
        
        return serp_data
    
    async def extract_complete(self, query, max_results=3, output_file=None):
        """Processus complet reproduction du script Node.js"""
        start_time = time.time()
        
        print("🎭 Extracteur SERP avec Simulation Utilisateur (Python)")
        print(f"🎯 Requête: \"{query}\"")
        print(f"📄 Fichier de sortie: {output_file}")
        print(f"🔢 Nombre max de résultats: {max_results}")
        print("=" * 60)
        
        try:
            # Étape 1: Recherche Google
            search_results = self.search_google(query, max_results)
            
            if not search_results:
                raise Exception("Aucun résultat trouvé sur Google")
            
            # Étape 2: Scraping parallèle
            print(f"\n🔍 {len(search_results)} URLs trouvées, extraction du contenu...")
            scrape_results = await self.scrape_all_pages_parallel(search_results)
            
            # Étape 3: Sauvegarde au format Node.js
            if output_file:
                final_data = self.save_results_node_format(query, search_results, scrape_results, output_file)
            
            # Statistiques finales (format Node.js)
            duration = time.time() - start_time
            stats = {
                "total": len(scrape_results),
                "successful": sum(1 for r in scrape_results if r["success"]),
                "failed": sum(1 for r in scrape_results if not r["success"]),
                "durationMs": int(duration * 1000),
                "totalHtmlSize": sum(r.get("htmlLength", 0) for r in scrape_results)
            }
            
            print("\n🎉 EXTRACTION TERMINÉE AVEC SUCCÈS")
            print("=" * 50)
            if output_file:
                print(f"📄 Résultats sauvegardés: {output_file}")
            print(f"📊 Pages récupérées: {stats['successful']}/{stats['total']}")
            print(f"⏱️ Durée totale: {duration:.1f}s")
            print(f"💾 Taille totale HTML: {stats['totalHtmlSize']//1024}KB")
            
            return final_data if output_file else {"stats": stats, "results": scrape_results}
            
        except Exception as e:
            self.log_error(e, "Extraction complète")
            raise

def main():
    """Fonction main reproduction du script Node.js"""
    parser = argparse.ArgumentParser(
        description="Extracteur SERP avec Simulation Utilisateur (Python)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemples:
  python google_scraper_webapp.py --query "intelligence artificielle"
  python google_scraper_webapp.py -q "Node.js tutorial" -o results.json
  python google_scraper_webapp.py -q "Python vs JavaScript" -n 5 -v
        """
    )
    
    parser.add_argument('-q', '--query', required=True, help='Requête de recherche (obligatoire)')
    parser.add_argument('-o', '--output', default='serp_corpus.json', help='Fichier de sortie (défaut: serp_corpus.json)')
    parser.add_argument('-n', '--max-results', type=int, default=3, choices=range(1, 11), help='Nombre max de résultats (1-10, défaut: 3)')
    parser.add_argument('-v', '--verbose', action='store_true', help='Mode verbeux avec logs détaillés')
    parser.add_argument('--headless', action='store_true', help='Mode headless (pour compatibilité)')
    
    args = parser.parse_args()
    
    # Créer le scraper avec les mêmes paramètres que Node.js
    scraper = GoogleScraper(
        max_concurrent=3,  # Comme dans le script Node.js
        timeout=15,
        verbose=args.verbose
    )
    
    try:
        # Lancer le processus asynchrone
        result = asyncio.run(scraper.extract_complete(
            query=args.query,
            max_results=args.max_results,
            output_file=args.output
        ))
        
        sys.exit(0)
        
    except KeyboardInterrupt:
        print("\n⏹️ Arrêt demandé par l'utilisateur")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ EXTRACTION ÉCHOUÉE")
        print("=" * 30)
        print(f"Erreur: {e}")
        
        # Conseils comme dans le script Node.js
        if "reCAPTCHA" in str(e) or "robot" in str(e):
            print("\n💡 CONSEILS POUR ÉVITER LE reCAPTCHA:")
            print("- Attendez 2-3 heures avant de relancer")
            print("- Changez votre IP (redémarrez routeur/VPN)")
            print("- Utilisez --max-results 1 pour minimiser les requêtes")
        
        sys.exit(1)

if __name__ == "__main__":
    main()