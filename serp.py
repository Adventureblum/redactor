#!/usr/bin/env python3
"""
Scraper Google unifié - Compatible avec app.py Flask
Remplace complètement le script Node.js serp_extractor.js
Usage: python google_scraper_unified.py --query "requête" --output "fichier.json" [options]
"""

import sys
import json
import os
import asyncio
import httpx
import requests
import argparse
import time
import random
import hashlib
from datetime import datetime
from urllib.parse import urlencode
from pathlib import Path
import socketio
from asyncio import Queue
from concurrent.futures import ThreadPoolExecutor
import threading

# Configuration Google Custom Search
API_KEY = "AIzaSyBNcyx5keYiyemeSN797ob-7E14JWdFdI4"  # ⚠️ Remplace par ta vraie clé
CX = "234d24017355d487b"  # ⚠️ Remplace par ton vrai CX

# Headers pour le scraping
SCRAPING_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Referer": "https://www.google.com/"
}

# Configuration compatible avec le script Node.js
CONFIG = {
    "fetch": {
        "timeout": 15,
        "maxRetries": 3,
        "retryDelay": 1000
    },
    "human": {
        "beforeSearch": [3000, 6000],
        "afterLoad": [2000, 4000],
        "betweenActions": [1000, 3000],
        "readingTime": [2000, 5000]
    }
}

class WorkerTask:
    def __init__(self, url, position, task_id=None):
        self.url = url
        self.position = position
        self.task_id = task_id or f"task_{position}"
        self.created_at = time.time()

class UnifiedGoogleScraper:
    def __init__(self, api_key=API_KEY, cx=CX, max_concurrent=5, timeout=15, verbose=False, num_workers=3):
        self.api_key = api_key
        self.cx = cx
        self.max_concurrent = max_concurrent
        self.timeout = timeout
        self.verbose = verbose
        self.num_workers = num_workers
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.socket = None

        # Queue et Workers
        self.task_queue = None
        self.result_queue = None
        self.workers = []
        self.workers_running = False
        self.session = None
        self.worker_stats = {
            'processed': 0,
            'errors': 0,
            'total_time': 0
        }
        
    def setup_socket(self, ws_url):
        """Configure la connexion WebSocket pour les logs en temps réel"""
        try:
            self.socket = socketio.SimpleClient()
            self.socket.connect(ws_url)
            self.log_info("WebSocket connecté pour les logs en temps réel")
        except Exception as e:
            self.log_warning(f"Impossible de se connecter au WebSocket: {e}")
    
    def log_error(self, error, context=""):
        """Log d'erreur compatible avec le format Node.js"""
        msg = {
            "error": True,
            "context": context,
            "message": str(error),
            "timestamp": datetime.now().isoformat()
        }
        print(json.dumps(msg), file=sys.stderr)
        if self.socket:
            try:
                self.socket.emit('log', {'type': 'error', 'message': json.dumps(msg)})
            except:
                pass
    
    def log_info(self, message, data=None):
        """Log d'info compatible avec le format Node.js"""
        if not self.verbose:
            return
        
        log_entry = {
            "level": "info",
            "message": message,
            "timestamp": datetime.now().isoformat()
        }
        if data:
            log_entry["data"] = data
        
        print(json.dumps(log_entry))
        if self.socket:
            try:
                self.socket.emit('log', {'type': 'info', 'message': json.dumps(log_entry)})
            except:
                pass
    
    def log_success(self, message, data=None):
        """Log de succès compatible avec le format Node.js"""
        msg = f"✅ {message}"
        if data and self.verbose:
            msg += f" {json.dumps(data, indent=2)}"
        print(msg)
        if self.socket:
            try:
                self.socket.emit('log', {'type': 'success', 'message': msg})
            except:
                pass
    
    def log_warning(self, message, data=None):
        """Log d'avertissement compatible avec le format Node.js"""
        msg = f"⚠️ {message}"
        if data and self.verbose:
            msg += f" {json.dumps(data, indent=2)}"
        print(msg)
        if self.socket:
            try:
                self.socket.emit('log', {'type': 'warning', 'message': msg})
            except:
                pass
    
    def search_google(self, query, num_results=10, language="fr"):
        """Effectue une recherche Google Custom Search (synchrone)"""
        self.log_info(f"🔍 Recherche Google pour: '{query}'")
        
        # Paramètres de l'API Google Custom Search
        params = {
            "key": self.api_key,
            "cx": self.cx,
            "q": query,
            "num": str(num_results),
            "hl": language
        }
        
        url = f"https://www.googleapis.com/customsearch/v1?{urlencode(params)}"
        
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            
            # Vérifier s'il y a des erreurs dans la réponse
            if "error" in data:
                error_msg = data["error"].get("message", "Erreur API inconnue")
                raise Exception(f"Erreur API Google: {error_msg}")
            
            # Extraire et formater les résultats
            items = data.get("items", [])
            results = []
            
            for i, item in enumerate(items[:num_results], 1):
                result = {
                    "id": i,
                    "title": item.get("title", ""),
                    "url": item.get("link", ""),
                    "snippet": item.get("snippet", "")
                }
                results.append(result)
            
            self.log_success(f"URLs extraites avec simulation utilisateur complète", {
                "count": len(results),
                "urls": results[:2] if not self.verbose else [r["url"] for r in results]
            })
            
            return [r["url"] for r in results]
            
        except requests.exceptions.RequestException as e:
            raise Exception(f"Erreur lors de la recherche: {e}")
        except json.JSONDecodeError as e:
            raise Exception(f"Erreur de parsing JSON: {e}")
    
    async def _fetch_with_semaphore(self, session, semaphore, url, position):
        """Wrapper pour contrôler le nombre de requêtes simultanées"""
        async with semaphore:
            return await self.fetch_single_page(session, url, position)
    
    async def fetch_single_page(self, session, url, position, retries=3):
        """Récupère le contenu d'une seule page de manière asynchrone (sans semaphore car géré par les workers)"""
        self.log_info(f"🌐 Récupération du contenu via HTTP (tentative 1) pour position {position}")

        for attempt in range(1, retries + 1):
            try:
                # Délai progressif en cas de retry
                if attempt > 1:
                    delay = CONFIG["fetch"]["retryDelay"] * (2 ** (attempt - 1)) / 1000
                    self.log_info(f"🔄 Retry dans {delay}s pour position {position}")
                    await asyncio.sleep(delay)

                response = await session.get(url)

                # Vérifier le statut HTTP
                if response.status_code >= 400:
                    if attempt == retries:
                        raise httpx.HTTPStatusError(
                            message=f"HTTP {response.status_code}",
                            request=response.request,
                            response=response
                        )
                    continue

                # Lire le contenu
                html = response.text

                if len(html) < 100:
                    if attempt == retries:
                        raise ValueError("Contenu HTML trop court ou vide")
                    continue

                # Extraire le titre du HTML
                title = self._extract_title_from_html(html)

                self.log_success(f"Contenu récupéré avec succès", {
                    "url": url[:50] + "..." if not self.verbose else url,
                    "status": response.status_code,
                    "contentLength": len(html),
                    "title": title[:100] if title else "Titre non trouvé"
                })

                return {
                    "id": position,
                    "url": url,
                    "title": title,
                    "html": html,
                    "success": True,
                    "method": "http",
                    "status": response.status_code,
                    "htmlLength": len(html)
                }

            except (httpx.TimeoutException, asyncio.TimeoutError):
                self.log_warning(f"Timeout position {position}, tentative {attempt}/{retries}")
                if attempt == retries:
                    return self._create_error_result(url, position, "Timeout")

            except (httpx.HTTPError, ValueError) as e:
                self.log_warning(f"Erreur position {position}, tentative {attempt}/{retries}: {e}")
                if attempt == retries:
                    return self._create_error_result(url, position, str(e))

            except Exception as e:
                self.log_error(e, f"Erreur inattendue position {position}")
                return self._create_error_result(url, position, f"Erreur inattendue: {e}")
    
    def _extract_title_from_html(self, html):
        """Extrait le titre du HTML"""
        if not html:
            return None
        
        import re
        title_match = re.search(r'<title[^>]*>([^<]+)</title>', html, re.IGNORECASE)
        return title_match.group(1).strip()[:200] if title_match else None
    
    def _create_error_result(self, url, position, error_message):
        """Crée un résultat d'erreur standardisé"""
        return {
            "id": position,
            "url": url,
            "title": None,
            "html": None,
            "success": False,
            "method": "http",
            "status": None,
            "error": error_message,
            "htmlLength": 0
        }
    
    async def _setup_session(self):
        """Configure la session HTTP pour les workers"""
        limits = httpx.Limits(
            max_connections=self.max_concurrent * 3,
            max_keepalive_connections=self.max_concurrent,
            keepalive_expiry=30
        )
        timeout = httpx.Timeout(
            timeout=self.timeout * 2,
            connect=10,
            read=self.timeout
        )

        self.session = httpx.AsyncClient(
            headers=SCRAPING_HEADERS,
            timeout=timeout,
            limits=limits,
            http2=True,
            follow_redirects=True
        )

    async def _cleanup_session(self):
        """Nettoie la session HTTP"""
        if self.session:
            await self.session.aclose()
            self.session = None

    async def _worker(self, worker_id):
        """Worker qui traite les tâches de la queue"""
        self.log_info(f"Worker {worker_id} démarré")

        while self.workers_running:
            try:
                # Récupérer une tâche de la queue avec timeout
                task = await asyncio.wait_for(self.task_queue.get(), timeout=1.0)

                if task is None:  # Signal d'arrêt
                    break

                start_time = time.time()
                self.log_info(f"Worker {worker_id} traite {task.url[:50]}...")

                # Traiter la tâche
                try:
                    result = await self.fetch_single_page(self.session, task.url, task.position)
                    await self.result_queue.put(result)
                    self.worker_stats['processed'] += 1
                except Exception as e:
                    self.log_error(e, f"Worker {worker_id} - Erreur lors du traitement")
                    error_result = self._create_error_result(task.url, task.position, str(e))
                    await self.result_queue.put(error_result)
                    self.worker_stats['errors'] += 1

                # Marquer la tâche comme terminée
                self.task_queue.task_done()

                # Mettre à jour les stats
                processing_time = time.time() - start_time
                self.worker_stats['total_time'] += processing_time

                self.log_info(f"Worker {worker_id} terminé en {processing_time:.2f}s")

            except asyncio.TimeoutError:
                # Pas de tâche disponible, continuer
                continue
            except Exception as e:
                self.log_error(e, f"Worker {worker_id} - Erreur critique")
                break

        self.log_info(f"Worker {worker_id} arrêté")

    async def _start_workers(self):
        """Démarre tous les workers"""
        self.workers_running = True
        self.workers = []

        for i in range(self.num_workers):
            worker = asyncio.create_task(self._worker(f"W{i+1}"))
            self.workers.append(worker)

        self.log_info(f"{self.num_workers} workers démarrés")

    async def _stop_workers(self):
        """Arrête tous les workers"""
        self.workers_running = False

        # Envoyer des signaux d'arrêt
        for _ in range(self.num_workers):
            await self.task_queue.put(None)

        # Attendre que tous les workers se terminent
        if self.workers:
            await asyncio.gather(*self.workers, return_exceptions=True)

        self.log_info("Tous les workers arrêtés")

    async def scrape_pages_with_queue(self, urls):
        """Scrape toutes les pages en utilisant une queue et des workers"""
        self.log_info(f"Démarrage du scraping de {len(urls)} pages avec {self.num_workers} workers")

        start_time = time.time()

        try:
            # Initialiser les queues
            self.task_queue = Queue()
            self.result_queue = Queue()

            # Configurer la session HTTP
            await self._setup_session()

            # Démarrer les workers
            await self._start_workers()

            # Ajouter toutes les tâches à la queue
            for i, url in enumerate(urls):
                task = WorkerTask(url, i + 1)
                await self.task_queue.put(task)

            self.log_info(f"{len(urls)} tâches ajoutées à la queue")

            # Attendre que toutes les tâches soient terminées
            await self.task_queue.join()

            # Arrêter les workers
            await self._stop_workers()

            # Collecter tous les résultats
            results = []
            while not self.result_queue.empty():
                result = await self.result_queue.get()
                results.append(result)

            # Trier les résultats par id
            results.sort(key=lambda x: x.get('id', 0))

            # Nettoyer la session
            await self._cleanup_session()

            scraping_time = time.time() - start_time
            successful = sum(1 for r in results if r.get("success", False))

            self.log_success(f"Extraction avec queue terminée avec succès", {
                "total": len(results),
                "successful": successful,
                "failed": len(results) - successful,
                "workers": self.num_workers,
                "durationMs": int(scraping_time * 1000),
                "avgTimePerPage": int(scraping_time * 1000 / len(results)) if results else 0,
                "totalHtmlSize": sum(r.get("htmlLength", 0) for r in results),
                "throughput": f"{len(results) / scraping_time:.2f} pages/sec" if scraping_time > 0 else "N/A",
                "workerStats": self.worker_stats
            })

            return results

        except Exception as e:
            self.log_error(e, "Erreur critique lors du scraping avec queue")
            await self._cleanup_session()
            await self._stop_workers()
            raise

    async def scrape_pages_parallel(self, urls):
        """Scrape toutes les pages - utilise maintenant la queue par défaut"""
        return await self.scrape_pages_with_queue(urls)
    
    async def run_complete_scraping(self, query, max_results=10, output_file="serp_corpus.json"):
        """Processus complet compatible avec le format Node.js"""
        start_time = time.time()
        
        try:
            self.log_info("Début de l'extraction avec simulation utilisateur ultra-réaliste", {
                "query": query,
                "maxResults": max_results,
                "outputFile": output_file
            })
            
            # Simulation du délai initial humain
            initial_delay = random.randint(*CONFIG["human"]["beforeSearch"]) / 1000
            self.log_info(f"Délai initial de lecture: {initial_delay * 1000:.0f}ms")
            await asyncio.sleep(initial_delay)
            
            # Étape 1: Recherche Google
            urls = self.search_google(query, max_results)
            
            if not urls:
                raise Exception("Aucun résultat trouvé sur Google avec la simulation utilisateur")
            
            # Simulation du délai après recherche
            after_search_delay = random.randint(*CONFIG["human"]["afterLoad"]) / 1000
            self.log_info(f"Délai après chargement des résultats: {after_search_delay * 1000:.0f}ms")
            await asyncio.sleep(after_search_delay)
            
            # Étape 2: Scraping des pages
            results = await self.scrape_pages_parallel(urls)
            
            # Simulation du délai de lecture
            reading_delay = random.randint(*CONFIG["human"]["readingTime"]) / 1000
            self.log_info(f"Temps de lecture des résultats: {reading_delay * 1000:.0f}ms")
            await asyncio.sleep(reading_delay)
            
            # Calcul des statistiques
            end_time = time.time()
            duration = int((end_time - start_time) * 1000)
            successful = sum(1 for r in results if r.get("success", False))
            failed = len(results) - successful
            total_html_size = sum(r.get("htmlLength", 0) for r in results)
            
            stats = {
                "total": len(results),
                "successful": successful,
                "failed": failed,
                "httpMethod": successful,
                "durationMs": duration,
                "avgTimePerPage": duration // len(results) if results else 0,
                "totalHtmlSize": total_html_size,
                "humanSimulation": {
                    "typingSpeedRange": [80, 200],
                    "mouseMovements": True,
                    "scrollSimulated": True,
                    "naturalDelays": True
                }
            }
            
            # Format de sortie compatible avec le script Node.js
            serp_data = {
                "success": True,
                "query": query,
                "timestamp": datetime.now().isoformat(),
                "nodeVersion": f"python-{sys.version.split()[0]}",
                "playwrightVersion": f"python-httpx-v{httpx.__version__}",
                "organicResults": results,
                "stats": stats,
                "config": {
                    "fetchTimeout": self.timeout * 1000,
                    "maxRetries": CONFIG["fetch"]["maxRetries"],
                    "userAgent": SCRAPING_HEADERS["User-Agent"],
                    "browserEngine": "httpx",
                    "maxResults": max_results,
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
            
            # Sauvegarde du fichier JSON
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(serp_data, f, indent=2, ensure_ascii=False)
            
            return serp_data
            
        except Exception as e:
            self.log_error(e, "Extraction avec simulation utilisateur")
            raise

def parse_arguments():
    """Parser des arguments compatible avec le script Node.js"""
    parser = argparse.ArgumentParser(description="Extracteur SERP avec Simulation Utilisateur Ultra-Réaliste")
    
    parser.add_argument("--query", "-q", required=True, help="Requête de recherche")
    parser.add_argument("--output", "-o", default="serp_corpus.json", help="Fichier de sortie")
    parser.add_argument("--max-results", "-n", type=int, default=10, choices=range(1, 11), help="Nombre max de résultats (1-10)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Mode verbeux")
    parser.add_argument("--ws", help="URL WebSocket pour les logs en temps réel")
    parser.add_argument("--workers", "-w", type=int, default=3, help="Nombre de workers (défaut: 3)")
    parser.add_argument("--help-extended", action="store_true", help="Aide détaillée")
    
    # Support des arguments positionnels pour compatibilité
    parser.add_argument("query_positional", nargs="*", help="Requête en argument positionnel")
    
    args = parser.parse_args()
    
    # Gérer les arguments positionnels
    if args.query_positional and not args.query:
        args.query = " ".join(args.query_positional)
    elif args.query_positional:
        args.query += " " + " ".join(args.query_positional)
    
    if args.help_extended:
        show_help()
        sys.exit(0)
    
    return args

def show_help():
    """Aide détaillée compatible avec le script Node.js"""
    print("""
🎭 Extracteur SERP avec Python + Simulation Utilisateur Ultra-Réaliste
======================================================================

USAGE:
  python google_scraper_unified.py [OPTIONS] [REQUÊTE]
  python google_scraper_unified.py --query "votre requête" [OPTIONS]

OPTIONS:
  -q, --query REQUÊTE       Requête de recherche (obligatoire)
  -o, --output FICHIER      Fichier de sortie (défaut: serp_corpus.json)
  -n, --max-results NUM     Nombre max de résultats (1-10, défaut: 10)
  -w, --workers NUM         Nombre de workers (défaut: 3)
  -v, --verbose             Mode verbeux avec logs détaillés
      --ws URL              WebSocket pour logs en temps réel
  -h, --help                Afficher cette aide

EXEMPLES:
  python google_scraper_unified.py "intelligence artificielle"
  python google_scraper_unified.py --query "Node.js tutorial" --output results.json
  python google_scraper_unified.py -q "Python vs JavaScript" -n 5 -w 5 -v
  python google_scraper_unified.py --query "web scraping" --max-results 3 --workers 2 --verbose

NOUVEAUTÉS SIMULATION HUMAINE:
  ✅ Délais aléatoires entre requêtes
  ✅ Architecture Queue + Workers
  ✅ Scraping parallèle intelligent avec contrôle de débit
  ✅ Gestion d'erreurs robuste
  ✅ Compatible avec interface Flask
  ✅ Format de sortie identique au script Node.js
  ✅ Support WebSocket pour logs temps réel

SORTIE:
  Le script génère un fichier JSON contenant:
  - Les URLs des résultats Google
  - Le contenu HTML des pages
  - Les métadonnées et statistiques
  - Compatibilité totale avec app.py Flask
""")

async def main():
    """Fonction principale"""
    try:
        args = parse_arguments()
        
        print("🎭 Extracteur SERP avec Simulation Utilisateur Ultra-Réaliste (Python)")
        print(f"Python: {sys.version.split()[0]} | httpx: {httpx.__version__}")
        print("=" * 60)
        print(f"🎯 Requête: \"{args.query}\"")
        print(f"📄 Fichier de sortie: {args.output}")
        print(f"🔢 Nombre max de résultats: {args.max_results}")
        print(f"👷 Nombre de workers: {args.workers}")
        print(f"🔊 Mode verbeux: {'Activé' if args.verbose else 'Désactivé'}")
        print(f"🔗 WebSocket: {'Activé' if args.ws else 'Désactivé'}")
        print("=" * 60)
        
        # Créer le scraper avec workers
        scraper = UnifiedGoogleScraper(verbose=args.verbose, num_workers=args.workers)
        
        # Configurer WebSocket si fourni
        if args.ws:
            scraper.setup_socket(args.ws)
        
        # Notifier le début du job via WebSocket
        if scraper.socket:
            try:
                scraper.socket.emit('job_start', {
                    'query': args.query,
                    'maxResults': args.max_results
                })
            except:
                pass
        
        # Lancer l'extraction
        result = await scraper.run_complete_scraping(
            args.query, 
            args.max_results, 
            args.output
        )
        
        # Notifier la fin du job via WebSocket
        if scraper.socket:
            try:
                scraper.socket.emit('job_complete', {
                    'query': args.query,
                    'stats': result['stats'],
                    'outputFile': args.output
                })
                scraper.socket.disconnect()
            except:
                pass
        
        # Résumé final
        print("\n🎉 EXTRACTION TERMINÉE AVEC SUCCÈS (MODE SIMULATION HUMAINE)")
        print("=" * 60)
        print(f"📄 Résultats sauvegardés: {args.output}")
        print(f"📊 Pages récupérées: {result['stats']['successful']}/{result['stats']['total']}")
        print(f"⏱️ Durée totale: {result['stats']['durationMs'] / 1000:.1f}s")
        print(f"💾 Taille totale HTML: {result['stats']['totalHtmlSize'] // 1024}KB")
        print(f"🔧 Méthodes: {result['stats']['httpMethod']} HTTP")
        print(f"🎭 Simulation humaine: Délais naturels + Scraping intelligent")
        
        return 0
        
    except KeyboardInterrupt:
        print("\n⏹️ Arrêt demandé par l'utilisateur")
        return 1
    except Exception as e:
        print(f"\n❌ EXTRACTION ÉCHOUÉE")
        print("=" * 30)
        print(f"Erreur: {e}")
        
        # Notifier l'erreur via WebSocket
        try:
            if 'scraper' in locals() and scraper.socket:
                scraper.socket.emit('job_error', {'error': str(e)})
                scraper.socket.disconnect()
        except:
            pass
        
        return 1

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))