#!/usr/bin/env python3

import asyncio
import aiohttp
import json
import sys
import argparse
import random
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode, quote_plus
import platform
import re
from typing import Dict, List, Optional, Tuple

try:
    from playwright.async_api import async_playwright
    import playwright
except ImportError:
    print("❌ Playwright requis. Installez avec: pip install playwright")
    print("Puis exécutez: playwright install chromium")
    sys.exit(1)

# Vérification de la version Python
if sys.version_info < (3, 8):
    print(f"❌ Ce script nécessite Python 3.8+")
    print(f"Version actuelle: {sys.version}")
    sys.exit(1)

# Configuration exactement identique au script Node.js
CONFIG = {
    "browser": {
        "headless": True,  # Changé pour éviter la détection
        "args": [
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-gpu',
            '--disable-dev-shm-usage',
            '--disable-blink-features=AutomationControlled',
            '--disable-web-security',
            '--disable-features=VizDisplayCompositor',
            # Nouveaux arguments stealth
            '--disable-background-timer-throttling',
            '--disable-backgrounding-occluded-windows',
            '--disable-renderer-backgrounding',
            '--disable-features=TranslateUI',
            '--disable-ipc-flooding-protection',
            '--no-first-run',
            '--no-default-browser-check',
            '--no-pings',
            '--password-store=basic',
            '--use-mock-keychain',
            '--disable-component-extensions-with-background-pages',
            '--disable-default-apps',
            '--mute-audio'
        ]
    },
    "context": {
        "viewport": {"width": 1366, "height": 768},  # Taille plus commune
        "user_agent": 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
        "locale": 'fr-FR',
        "timezone_id": 'Europe/Paris',
        "permissions": [],
        "extra_http_headers": {
            'Accept-Language': 'fr-FR,fr;q=0.9,en;q=0.8',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache',
            'Sec-Ch-Ua': '"Google Chrome";v="119", "Chromium";v="119", "Not?A_Brand";v="24"',
            'Sec-Ch-Ua-Mobile': '?0',
            'Sec-Ch-Ua-Platform': '"Linux"',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Upgrade-Insecure-Requests': '1'
        }
    },
    "page": {
        "timeout": 45000,  # Augmenté
        "navigation_timeout": 45000
    },
    "fetch": {
        "timeout": 15000,
        "max_retries": 3,
        "retry_delay": 1000,
        "headers": {
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'fr-FR,fr;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate',  # Supprimé 'br' pour éviter Brotli
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Cache-Control': 'no-cache'
        }
    },
    "search": {
        "base_url": 'https://www.google.com/search',
        "language": 'fr',
        "wait_until": 'networkidle'
    },
    # Configuration pour les délais humains
    "delays": {
        "between_actions": [1000, 3000],  # Délai aléatoire entre actions
        "before_search": [2000, 4000],    # Délai avant la recherche
        "after_load": [3000, 6000]        # Délai après chargement
    }
}

# Logger global
VERBOSE_MODE = False

def random_delay(min_val: int, max_val: int) -> int:
    """Fonction pour générer un délai aléatoire (en millisecondes)."""
    return random.randint(min_val, max_val)

def log_error(error: Exception, context: str) -> None:
    """Log d'erreur structuré identique au Node.js."""
    try:
        playwright_version = playwright.__version__
    except:
        playwright_version = "unknown"
    
    error_data = {
        "error": True,
        "context": context,
        "message": str(error),
        "stack": str(error.__traceback__)[:200] if error.__traceback__ else None,
        "timestamp": datetime.now().isoformat(),
        "python_version": sys.version.split()[0],
        "playwright_version": playwright_version
    }
    print(json.dumps(error_data))

def log_info(message: str, data: Optional[Dict] = None) -> None:
    """Log d'information (mode verbeux uniquement)."""
    if not VERBOSE_MODE:
        return
    
    log_entry = {
        "level": "info",
        "message": message,
        "timestamp": datetime.now().isoformat()
    }
    if data:
        log_entry["data"] = data
    print(json.dumps(log_entry))

def log_success(message: str, data: Optional[Dict] = None) -> None:
    """Log de succès."""
    output = f"✅ {message}"
    if data and VERBOSE_MODE:
        output += f" {json.dumps(data, indent=2, ensure_ascii=False)}"
    print(output)

def log_warning(message: str, data: Optional[Dict] = None) -> None:
    """Log d'avertissement."""
    output = f"⚠️  {message}"
    if data and VERBOSE_MODE:
        output += f" {json.dumps(data, indent=2, ensure_ascii=False)}"
    print(output)

async def setup_stealth_mode(page) -> None:
    """Configuration du mode stealth identique au Node.js."""
    await page.add_init_script("""
        () => {
            // Supprimer les traces de webdriver
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined,
            });
            
            // Masquer les plugins de détection
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5],
            });
            
            // Simuler les langues du navigateur
            Object.defineProperty(navigator, 'languages', {
                get: () => ['fr-FR', 'fr', 'en-US', 'en'],
            });
            
            // Masquer l'automation
            if (window.chrome) {
                delete window.chrome.loadTimes;
                delete window.chrome.csi;
                delete window.chrome.app;
            }
            
            // Simuler les permissions
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications' ?
                    Promise.resolve({ state: Notification.permission }) :
                    originalQuery(parameters)
            );
        }
    """)

async def get_google_results(query: str, max_results: int, stealth_mode: bool = True) -> List[str]:
    """Récupération des résultats Google avec Playwright (reproduction exacte du Node.js)."""
    async with async_playwright() as p:
        browser = None
        context = None
        page = None
        
        try:
            log_info('Lancement du navigateur Playwright avec mode stealth')
            
            launch_options = {
                "headless": CONFIG["browser"]["headless"],
                "args": CONFIG["browser"]["args"]
            }
            
            # Support pour CHROME_BIN comme dans Node.js
            import os
            if os.environ.get('CHROME_BIN'):
                launch_options["executable_path"] = os.environ['CHROME_BIN']
            
            browser = await p.chromium.launch(**launch_options)
            
            context = await browser.new_context(
                viewport=CONFIG["context"]["viewport"],
                user_agent=CONFIG["context"]["user_agent"],
                locale=CONFIG["context"]["locale"],
                timezone_id=CONFIG["context"]["timezone_id"],
                permissions=CONFIG["context"]["permissions"],
                extra_http_headers=CONFIG["context"]["extra_http_headers"]
            )
            
            # Bloquer les ressources inutiles pour plus de rapidité
            await context.route('**/*.{png,jpg,jpeg,gif,svg,css,woff,woff2}', lambda route: route.abort())
            
            page = await context.new_page()
            
            # Appliquer le mode stealth
            if stealth_mode:
                await setup_stealth_mode(page)
                log_info('Mode stealth activé')
            
            page.set_default_timeout(CONFIG["page"]["timeout"])
            page.set_default_navigation_timeout(CONFIG["page"]["navigation_timeout"])
            
            log_info('Navigation vers Google.com avec délai humain')
            await page.goto('https://www.google.com', 
                           wait_until='domcontentloaded',
                           timeout=CONFIG["page"]["navigation_timeout"])
            
            # Délai humain après chargement
            initial_delay = random_delay(*CONFIG["delays"]["after_load"])
            log_info(f'Délai humain initial: {initial_delay}ms')
            await page.wait_for_timeout(initial_delay)
            
            # Accepter les cookies avec plus de réalisme (COPIE EXACTE du Node.js)
            try:
                cookie_selectors = [
                    'button:has-text("Tout accepter")',
                    'button:has-text("J\'accepte")',
                    '#L2AGLb',
                    'button[aria-label="Tout accepter"]',
                    'button:text("Accept all")'  # Changé contains en text pour Playwright Python
                ]
                
                cookie_accepted = False
                for selector in cookie_selectors:
                    try:
                        await page.wait_for_selector(selector, timeout=3000)
                        await page.wait_for_timeout(random_delay(500, 1500))  # Délai avant clic
                        await page.click(selector)
                        await page.wait_for_timeout(random_delay(1000, 2000))  # Délai après clic
                        log_info('Cookies acceptés')
                        cookie_accepted = True
                        break
                    except:
                        continue
                
                if not cookie_accepted:
                    log_info('Pas de popup de cookies détecté')
            except:
                log_info('Gestion des cookies échouée')
            
            # Délai avant recherche
            search_delay = random_delay(*CONFIG["delays"]["before_search"])
            log_info(f'Délai avant recherche: {search_delay}ms')
            await page.wait_for_timeout(search_delay)
            
            search_url = f"{CONFIG['search']['base_url']}?q={quote_plus(query)}&hl={CONFIG['search']['language']}&gl=fr"
            log_info('Navigation vers la page de résultats', {"search_url": search_url})
            
            await page.goto(search_url,
                           wait_until='networkidle',
                           timeout=CONFIG["page"]["navigation_timeout"])
            
            # Délai après chargement des résultats
            results_delay = random_delay(2000, 4000)
            log_info(f'Délai après chargement des résultats: {results_delay}ms')
            await page.wait_for_timeout(results_delay)
            
            # Vérifier si reCAPTCHA ou blocage
            page_content = await page.content()
            if any(keyword in page_content for keyword in ['reCAPTCHA', 'robot', 'captcha']):
                log_warning('reCAPTCHA détecté - prise de screenshot')
                await page.screenshot(path='recaptcha_detected.png', full_page=False)
                raise Exception('reCAPTCHA détecté - changez d\'IP ou attendez')
            
            # Extraction des URLs (reproduction exacte du JavaScript)
            urls = await page.evaluate(f"""
                (maxResults) => {{
                    // Essayer plusieurs sélecteurs pour les résultats
                    const selectors = [
                        'div[class="MjjYud"] a',
                        'div.g a',
                        'div[data-hveid] a',
                        '.rc a',
                        'h3 a'
                    ];
                    
                    let elements = [];
                    for (const selector of selectors) {{
                        elements = Array.from(document.querySelectorAll(selector));
                        if (elements.length > 0) {{
                            console.log(`Sélecteur fonctionnel: ${{selector}}, ${{elements.length}} éléments trouvés`);
                            break;
                        }}
                    }}
                    
                    const urls = elements
                        .slice(0, maxResults * 2) // Prendre plus d'éléments au cas où
                        .map(a => a.href)
                        .filter(url => url && url.startsWith('http') && !url.includes('google.com') && !url.includes('youtube.com'))
                        .slice(0, maxResults); // Limiter au nombre demandé
                    
                    console.log('URLs extraites:', urls);
                    return urls;
                }}
            """, max_results)
            
            if len(urls) == 0:
                log_warning('Aucune URL trouvée, capture d\'écran pour debug')
                try:
                    await page.screenshot(path='debug_google_results.png', full_page=True)
                    log_info('Screenshot complet sauvegardé: debug_google_results.png')
                    
                    # Sauvegarder aussi le HTML pour debug
                    html = await page.content()
                    with open('debug_page.html', 'w', encoding='utf-8') as f:
                        f.write(html)
                    log_info('HTML de debug sauvegardé: debug_page.html')
                except Exception as screenshot_error:
                    log_warning('Impossible de faire le screenshot', {"error": str(screenshot_error)})
            
            log_success('URLs extraites avec Playwright', {
                "count": len(urls), 
                "urls": urls if VERBOSE_MODE else urls[:2]
            })
            return urls
            
        except Exception as error:
            log_error(error, 'Récupération des résultats Google avec Playwright')
            raise
        finally:
            if page:
                await page.close()
            if context:
                await context.close()
            if browser:
                await browser.close()

async def fetch_page_content(session: aiohttp.ClientSession, url: str, retry_count: int = 0) -> Dict:
    """Récupération du contenu HTML avec aiohttp (équivalent fetch natif)."""
    try:
        log_info(f'Récupération du contenu avec aiohttp (tentative {retry_count + 1})', {"url": url})
        
        headers = {
            **CONFIG["fetch"]["headers"],
            'User-Agent': CONFIG["context"]["user_agent"],
            'Referer': 'https://www.google.com/'
        }
        
        timeout = aiohttp.ClientTimeout(total=CONFIG["fetch"]["timeout"] / 1000)  # Conversion en secondes
        
        async with session.get(url, headers=headers, timeout=timeout, allow_redirects=True) as response:
            if not response.ok:
                raise Exception(f'HTTP {response.status}: {response.reason}')
            
            content_type = response.headers.get('content-type', '')
            if not any(ct in content_type for ct in ['text/html', 'text/plain']):
                log_warning('Content-Type non HTML détecté', {"content_type": content_type, "url": url})
            
            html = await response.text()
            
            # Décoder les entités HTML si nécessaire
            import html as html_parser
            if '&#' in html or '&amp;' in html or '&lt;' in html:
                try:
                    html = html_parser.unescape(html)
                    log_info("Entités HTML décodées")
                except Exception as decode_error:
                    log_warning(f"Erreur décodage entités HTML: {decode_error}")
            
            if not html or len(html) < 100:
                raise Exception('Contenu HTML trop court ou vide')
            
            log_success('Contenu récupéré avec aiohttp', {
                "url": url[:50] + '...' if not VERBOSE_MODE else url,
                "status": response.status,
                "content_length": len(html),
                "content_type": content_type
            })
            
            return {
                "success": True,
                "html": html,
                "status": response.status,
                "content_type": content_type,
                "url": str(response.url),
                "method": "aiohttp"
            }
            
    except Exception as error:
        if retry_count < CONFIG["fetch"]["max_retries"] and is_retryable_error(error):
            delay = (CONFIG["fetch"]["retry_delay"] * (2 ** retry_count)) / 1000  # Conversion en secondes
            log_info(f'Retry aiohttp dans {delay * 1000:.0f}ms', {
                "url": url, 
                "error": str(error), 
                "retry_count": retry_count
            })
            
            await asyncio.sleep(delay)
            return await fetch_page_content(session, url, retry_count + 1)
        
        log_error(error, f'Récupération aiohttp de {url} après {retry_count + 1} tentatives')
        return {
            "success": False,
            "html": None,
            "error": str(error),
            "url": url,
            "method": "aiohttp"
        }

def is_retryable_error(error: Exception) -> bool:
    """Vérification si l'erreur est 'retryable' (identique au Node.js)."""
    retryable_errors = [
        'AbortError',
        'TimeoutError', 
        'ECONNRESET',
        'ECONNREFUSED',
        'ETIMEDOUT',
        'ENOTFOUND',
        'ENETUNREACH',
        'Connection timeout',
        'Server disconnected'
    ]
    
    # Erreurs non-retryable (passage direct au fallback)
    non_retryable_errors = [
        'brotli',
        'Can not decode content-encoding',
        'SSL',
        'certificate'
    ]
    
    retryable_status = [408, 429, 500, 502, 503, 504]
    
    error_message = str(error).lower()
    
    # Si erreur Brotli ou SSL, pas de retry -> fallback direct
    if any(err in error_message for err in non_retryable_errors):
        return False
    
    return (
        any(code in error_message for code in retryable_errors) or
        type(error).__name__ == 'TimeoutError' or
        (hasattr(error, 'status') and error.status in retryable_status)
    )

async def fetch_with_playwright(url: str) -> Dict:
    """Fallback avec Playwright pour les pages problématiques (identique au Node.js)."""
    async with async_playwright() as p:
        browser = None
        context = None
        page = None
        
        try:
            log_info('Fallback Playwright pour récupération de contenu', {"url": url})
            
            browser = await p.chromium.launch(
                headless=True,
                args=CONFIG["browser"]["args"]
            )
            
            context = await browser.new_context(
                viewport=CONFIG["context"]["viewport"],
                user_agent=CONFIG["context"]["user_agent"],
                locale=CONFIG["context"]["locale"],
                timezone_id=CONFIG["context"]["timezone_id"],
                permissions=CONFIG["context"]["permissions"],
                extra_http_headers={
                    **CONFIG["context"]["extra_http_headers"],
                    'Referer': 'https://www.google.com/'
                }
            )
            
            await context.route('**/*.{png,jpg,jpeg,gif,svg,css,woff,woff2,ico}', lambda route: route.abort())
            
            page = await context.new_page()
            page.set_default_timeout(CONFIG["page"]["timeout"])
            
            response = await page.goto(url, 
                                     wait_until=CONFIG["search"]["wait_until"],
                                     timeout=CONFIG["page"]["navigation_timeout"])
            
            if response and response.ok:
                await page.wait_for_load_state('networkidle')
                
                html = await page.content()
                title = await page.title()
                
                log_success('Playwright fallback réussi', {
                    "url": url[:50] + '...' if not VERBOSE_MODE else url,
                    "html_length": len(html),
                    "title": title[:100]
                })
                
                return {
                    "success": True,
                    "html": html,
                    "title": title,
                    "status": response.status,
                    "method": "playwright"
                }
            
            return {"success": False, "html": None, "method": "playwright"}
            
        except Exception as error:
            log_error(error, f'Playwright fallback pour {url}')
            return {
                "success": False,
                "html": None,
                "error": str(error),
                "method": "playwright"
            }
        finally:
            if page:
                await page.close()
            if context:
                await context.close()
            if browser:
                await browser.close()

def extract_title(html: Optional[str]) -> Optional[str]:
    """Extraction du titre depuis le HTML (identique au Node.js)."""
    if not html:
        return None
    
    import html as html_parser
    
    title_match = re.search(r'<title[^>]*>([^<]+)</title>', html, re.IGNORECASE)
    if title_match:
        title = title_match.group(1).strip()
        # Décoder les entités HTML (&#039; -> ', &amp; -> &, etc.)
        title = html_parser.unescape(title)
        return title[:200]
    return None

async def extract_with_hybrid_approach(query: str, max_results: int, output_file: str, stealth_mode: bool) -> Dict:
    """Fonction principale d'extraction (reproduction exacte du Node.js)."""
    start_time = time.time() * 1000  # Temps en millisecondes comme Node.js
    
    try:
        log_info('Début de l\'extraction avec Playwright + aiohttp (mode stealth)', {
            "query": query, 
            "max_results": max_results, 
            "stealth_mode": stealth_mode
        })
        
        urls = await get_google_results(query, max_results, stealth_mode)
        
        if len(urls) == 0:
            raise Exception('Aucun résultat trouvé sur Google')
        
        print(f'🔍 {len(urls)} URLs trouvées, extraction du contenu...')
        results = []
        
        # Configuration aiohttp
        connector = aiohttp.TCPConnector(limit=10, limit_per_host=3)
        timeout = aiohttp.ClientTimeout(total=CONFIG["fetch"]["timeout"] / 1000)
        
        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            for i, url in enumerate(urls):
                print(f'\n🔄 Traitement {i + 1}/{len(urls)}: {url[:60]}...')
                
                content = await fetch_page_content(session, url)
                
                if not content["success"]:
                    print('🔄 Fallback vers Playwright...')
                    playwright_result = await fetch_with_playwright(url)
                    content = {
                        **playwright_result,
                        "title": playwright_result.get("title") or extract_title(playwright_result.get("html"))
                    }
                
                if content["success"] and not content.get("title"):
                    content["title"] = extract_title(content["html"])
                
                results.append({
                    "position": i + 1,
                    "url": url,
                    "title": content.get("title"),
                    "html": content.get("html"),
                    "success": content["success"],
                    "method": content["method"],
                    "status": content.get("status"),
                    "error": content.get("error"),
                    "html_length": len(content["html"]) if content.get("html") else 0
                })
                
                if content["success"]:
                    size_kb = len(content.get("html", "")) / 1024
                    print(f'✅ Récupéré via {content["method"]} ({size_kb:.0f}KB)')
                else:
                    print(f'❌ Échec: {content.get("error")}')
                
                # Délai entre les pages pour paraître plus humain
                if i < len(urls) - 1:
                    page_delay = random_delay(1000, 3000)
                    print(f'⏱️ Délai entre pages: {page_delay}ms')
                    await asyncio.sleep(page_delay / 1000)  # Conversion en secondes
        
        end_time = time.time() * 1000
        duration = end_time - start_time
        
        stats = {
            "total": len(results),
            "successful": len([r for r in results if r["success"]]),
            "failed": len([r for r in results if not r["success"]]),
            "aiohttp_method": len([r for r in results if r["method"] == "aiohttp"]),
            "playwright_method": len([r for r in results if r["method"] == "playwright"]),
            "duration_ms": int(duration),
            "avg_time_per_page": int(duration / len(results)),
            "total_html_size": sum(r["html_length"] for r in results)
        }
        
        try:
            playwright_version = playwright.__version__
        except:
            playwright_version = "unknown"
        
        serp_data = {
            "success": True,
            "query": query,
            "timestamp": datetime.now().isoformat(),
            "python_version": sys.version.split()[0],
            "playwright_version": playwright_version,
            "organic_results": results,
            "stats": stats,
            "config": {
                "fetch_timeout": CONFIG["fetch"]["timeout"],
                "max_retries": CONFIG["fetch"]["max_retries"],
                "user_agent": CONFIG["context"]["user_agent"],
                "browser_engine": "chromium",
                "max_results": max_results,
                "stealth_mode": stealth_mode,
                "headless": CONFIG["browser"]["headless"]
            }
        }
        
        # Sauvegarde
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(serp_data, f, indent=2, ensure_ascii=False)
        
        log_success('Extraction terminée avec succès', stats)
        return serp_data
        
    except Exception as error:
        log_error(error, 'Extraction hybride avec Playwright')
        raise

def show_help():
    """Affichage de l'aide (identique au Node.js)."""
    help_text = """
🎭 Extracteur SERP avec Playwright + aiohttp (Version Anti-Détection)
=====================================================================

USAGE:
  python script.py [OPTIONS] [REQUÊTE]
  python script.py --query "votre requête" [OPTIONS]

OPTIONS:
  -q, --query REQUÊTE      Requête de recherche (obligatoire)
  -o, --output FICHIER     Fichier de sortie (défaut: serp_corpus.json)
  -n, --max-results NUM    Nombre max de résultats (1-10, défaut: 3)
  -v, --verbose            Mode verbeux avec logs détaillés
  --headless               Mode headless (défaut: visible pour éviter détection)
  --no-stealth             Désactiver le mode stealth
  -h, --help               Afficher cette aide

EXEMPLES:
  python script.py "intelligence artificielle"
  python script.py --query "Python tutorial" --output results.json
  python script.py -q "Python vs JavaScript" -n 5 -v
  python script.py --query "web scraping" --max-results 3 --verbose --headless

NOUVEAUTÉS:
  ✅ Mode stealth activé par défaut (évite les reCAPTCHA)
  ✅ Délais humains aléatoires
  ✅ Headers réalistes mis à jour
  ✅ Navigateur visible par défaut (moins suspect)
  ✅ User-Agent Linux moderne
  ✅ aiohttp pour les requêtes HTTP rapides

SORTIE:
  Le script génère un fichier JSON contenant:
  - Les URLs des résultats Google
  - Le contenu HTML des pages
  - Les métadonnées et statistiques
  - Les informations de debug
"""
    print(help_text)

def parse_arguments():
    """Gestion des arguments de ligne de commande (identique au Node.js)."""
    args = sys.argv[1:]
    
    # Afficher l'aide
    if '--help' in args or '-h' in args or len(args) == 0:
        show_help()
        sys.exit(0)
    
    query = ''
    output_file = 'serp_corpus.json'
    max_results = 3
    verbose = False
    stealth_mode = True
    
    i = 0
    while i < len(args):
        arg = args[i]
        
        if arg in ['--query', '-q']:
            if i + 1 < len(args):
                query = args[i + 1]
                i += 1
            else:
                print('❌ Erreur: --query nécessite une valeur')
                sys.exit(1)
        elif arg in ['--output', '-o']:
            if i + 1 < len(args):
                output_file = args[i + 1]
                i += 1
            else:
                print('❌ Erreur: --output nécessite une valeur')
                sys.exit(1)
        elif arg in ['--max-results', '-n']:
            if i + 1 < len(args):
                try:
                    num = int(args[i + 1])
                    if num < 1 or num > 10:
                        raise ValueError()
                    max_results = num
                    i += 1
                except ValueError:
                    print('❌ Erreur: --max-results doit être un nombre entre 1 et 10')
                    sys.exit(1)
            else:
                print('❌ Erreur: --max-results nécessite une valeur')
                sys.exit(1)
        elif arg in ['--verbose', '-v']:
            verbose = True
        elif arg == '--no-stealth':
            stealth_mode = False
        elif arg == '--headless':
            CONFIG["browser"]["headless"] = True
        else:
            # Si ce n'est pas une option, considérer comme partie de la requête
            if not arg.startswith('-'):
                if not query:
                    query = arg
                else:
                    query += ' ' + arg
            else:
                print(f'❌ Option inconnue: {arg}')
                print('Utilisez --help pour voir les options disponibles')
                sys.exit(1)
        
        i += 1
    
    if not query.strip():
        print('❌ Erreur: Aucune requête spécifiée')
        print('Utilisez --help pour voir les options disponibles')
        sys.exit(1)
    
    return {
        "query": query.strip(),
        "output_file": output_file,
        "max_results": max_results,
        "verbose": verbose,
        "stealth_mode": stealth_mode
    }

async def main():
    """Point d'entrée principal (reproduction exacte du Node.js)."""
    global VERBOSE_MODE
    
    try:
        options = parse_arguments()
        VERBOSE_MODE = options["verbose"]
        
        try:
            playwright_version = playwright.__version__
        except:
            playwright_version = "unknown"
        
        print('🎭 Extracteur SERP avec Playwright + aiohttp (Anti-Détection)')
        print(f'Python: {sys.version.split()[0]} | Playwright: {playwright_version}')
        print('=====================================================')
        print(f'🎯 Requête: "{options["query"]}"')
        print(f'📄 Fichier de sortie: {options["output_file"]}')
        print(f'🔢 Nombre max de résultats: {options["max_results"]}')
        print(f'🔊 Mode verbeux: {"Activé" if options["verbose"] else "Désactivé"}')
        print(f'🥷 Mode stealth: {"Activé" if options["stealth_mode"] else "Désactivé"}')
        print(f'👁️ Mode headless: {"Activé" if CONFIG["browser"]["headless"] else "Désactivé"}')
        print('=====================================================')
        
        result = await extract_with_hybrid_approach(
            options["query"], 
            options["max_results"], 
            options["output_file"], 
            options["stealth_mode"]
        )
        
        print('\n🎉 EXTRACTION TERMINÉE AVEC SUCCÈS')
        print('==================================')
        print(f'📄 Résultats sauvegardés: {options["output_file"]}')
        print(f'📊 Pages récupérées: {result["stats"]["successful"]}/{result["stats"]["total"]}')
        print(f'⏱️  Durée totale: {result["stats"]["duration_ms"] / 1000:.0f}s')
        print(f'💾 Taille totale HTML: {result["stats"]["total_html_size"] / 1024:.0f}KB')
        print(f'🔧 Méthodes: {result["stats"]["aiohttp_method"]} aiohttp, {result["stats"]["playwright_method"]} playwright')
        
        sys.exit(0)
        
    except Exception as error:
        log_error(error, 'Processus principal')
        print('\n❌ EXTRACTION ÉCHOUÉE')
        print('====================')
        print('Consultez les logs ci-dessus pour plus de détails.')
        
        # Si reCAPTCHA détecté, donner des conseils
        if 'reCAPTCHA' in str(error) or 'robot' in str(error):
            print('\n💡 CONSEILS POUR ÉVITER LE reCAPTCHA:')
            print('- Attendez quelques heures avant de relancer')
            print('- Changez votre IP (redémarrez votre routeur/VPN)')
            print('- Utilisez --headless pour un mode plus discret')
            print('- Réduisez --max-results à 1 ou 2')
        
        sys.exit(1)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Arrêt demandé par l'utilisateur")
        sys.exit(0)
    except Exception as e:
        print(f"\n💥 Erreur critique: {e}")
        sys.exit(1)