#!/usr/bin/env node

const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

// Vérification de la version Node.js pour fetch natif
const nodeVersion = process.version;
const majorVersion = parseInt(nodeVersion.slice(1).split('.')[0]);

if (majorVersion < 18) {
  console.error('❌ Ce script nécessite Node.js 18+ pour fetch natif');
  console.error(`Version actuelle: ${nodeVersion}`);
  console.error('Mettez à jour Node.js ou utilisez une version compatible');
  process.exit(1);
}

// Configuration améliorée avec mode stealth
const CONFIG = {
  browser: {
    headless: true, // Changé pour éviter la détection
    args: [
      '--no-sandbox',
      '--disable-setuid-sandbox',
      '--disable-gpu',
      '--disable-dev-shm-usage',
      '--disable-blink-features=AutomationControlled',
      '--disable-web-security',
      '--disable-features=VizDisplayCompositor',
      // Nouveaux arguments stealth
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
  context: {
    viewport: { width: 1366, height: 768 }, // Taille plus commune
    userAgent: 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
    locale: 'fr-FR',
    timezoneId: 'Europe/Paris',
    permissions: [],
    extraHTTPHeaders: {
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
  page: {
    timeout: 45000, // Augmenté
    navigationTimeout: 45000
  },
  fetch: {
    timeout: 15000,
    maxRetries: 3,
    retryDelay: 1000,
    headers: {
      'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
      'Accept-Language': 'fr-FR,fr;q=0.9,en;q=0.8',
      'Accept-Encoding': 'gzip, deflate, br',
      'Connection': 'keep-alive',
      'Upgrade-Insecure-Requests': '1',
      'Sec-Fetch-Dest': 'document',
      'Sec-Fetch-Mode': 'navigate',
      'Sec-Fetch-Site': 'none',
      'Cache-Control': 'no-cache'
    }
  },
  search: {
    baseUrl: 'https://www.google.com/search',
    language: 'fr',
    waitUntil: 'networkidle'
  },
  // Configuration pour les délais humains
  delays: {
    betweenActions: [1000, 3000], // Délai aléatoire entre actions
    beforeSearch: [2000, 4000],   // Délai avant la recherche
    afterLoad: [3000, 6000]       // Délai après chargement
  }
};

// Fonction pour générer un délai aléatoire
function randomDelay(min, max) {
  return Math.floor(Math.random() * (max - min + 1)) + min;
}

// Configuration du mode stealth
async function setupStealthMode(page) {
  await page.addInitScript(() => {
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
  });
}

// Gestion des arguments de ligne de commande
function parseArguments() {
  const args = process.argv.slice(2);
  
  // Afficher l'aide
  if (args.includes('--help') || args.includes('-h') || args.length === 0) {
    showHelp();
    process.exit(0);
  }
  
  let query = '';
  let outputFile = 'serp_corpus.json';
  let maxResults = 3;
  let verbose = false;
  let stealthMode = true; // Nouveau paramètre
  
  for (let i = 0; i < args.length; i++) {
    const arg = args[i];
    
    switch (arg) {
      case '--query':
      case '-q':
        if (i + 1 < args.length) {
          query = args[++i];
        } else {
          console.error('❌ Erreur: --query nécessite une valeur');
          process.exit(1);
        }
        break;
        
      case '--output':
      case '-o':
        if (i + 1 < args.length) {
          outputFile = args[++i];
        } else {
          console.error('❌ Erreur: --output nécessite une valeur');
          process.exit(1);
        }
        break;
        
      case '--max-results':
      case '-n':
        if (i + 1 < args.length) {
          const num = parseInt(args[++i]);
          if (isNaN(num) || num < 1 || num > 10) {
            console.error('❌ Erreur: --max-results doit être un nombre entre 1 et 10');
            process.exit(1);
          }
          maxResults = num;
        } else {
          console.error('❌ Erreur: --max-results nécessite une valeur');
          process.exit(1);
        }
        break;
        
      case '--verbose':
      case '-v':
        verbose = true;
        break;
        
      case '--no-stealth':
        stealthMode = false;
        break;
        
      case '--headless':
        CONFIG.browser.headless = true;
        break;
        
      default:
        // Si ce n'est pas une option, considérer comme partie de la requête
        if (!arg.startsWith('-')) {
          if (!query) {
            query = arg;
          } else {
            query += ' ' + arg;
          }
        } else {
          console.error(`❌ Option inconnue: ${arg}`);
          console.error('Utilisez --help pour voir les options disponibles');
          process.exit(1);
        }
        break;
    }
  }
  
  if (!query.trim()) {
    console.error('❌ Erreur: Aucune requête spécifiée');
    console.error('Utilisez --help pour voir les options disponibles');
    process.exit(1);
  }
  
  return {
    query: query.trim(),
    outputFile,
    maxResults,
    verbose,
    stealthMode
  };
}

function showHelp() {
  console.log(`
🎭 Extracteur SERP avec Playwright + Fetch Natif (Version Anti-Détection)
===========================================================================

USAGE:
  node script.js [OPTIONS] [REQUÊTE]
  node script.js --query "votre requête" [OPTIONS]

OPTIONS:
  -q, --query REQUÊTE      Requête de recherche (obligatoire)
  -o, --output FICHIER     Fichier de sortie (défaut: serp_corpus.json)
  -n, --max-results NUM    Nombre max de résultats (1-10, défaut: 3)
  -v, --verbose            Mode verbeux avec logs détaillés
  --headless               Mode headless (défaut: visible pour éviter détection)
  --no-stealth             Désactiver le mode stealth
  -h, --help               Afficher cette aide

EXEMPLES:
  node script.js "intelligence artificielle"
  node script.js --query "Node.js tutorial" --output results.json
  node script.js -q "Python vs JavaScript" -n 5 -v
  node script.js --query "web scraping" --max-results 3 --verbose --headless

NOUVEAUTÉS:
  ✅ Mode stealth activé par défaut (évite les reCAPTCHA)
  ✅ Délais humains aléatoires
  ✅ Headers réalistes mis à jour
  ✅ Navigateur visible par défaut (moins suspect)
  ✅ User-Agent Linux moderne

SORTIE:
  Le script génère un fichier JSON contenant:
  - Les URLs des résultats Google
  - Le contenu HTML des pages
  - Les métadonnées et statistiques
  - Les informations de debug
`);
}

// Logger amélioré avec support du mode verbeux
let VERBOSE_MODE = false;

function logError(error, context) {
  console.error(JSON.stringify({
    error: true,
    context,
    message: error.message,
    stack: error.stack?.split('\n').slice(0, 3).join('\n'),
    timestamp: new Date().toISOString(),
    nodeVersion: process.version,
    playwrightVersion: require('playwright/package.json').version
  }));
}

function logInfo(message, data = null) {
  if (!VERBOSE_MODE) return;
  
  const logEntry = {
    level: 'info',
    message,
    timestamp: new Date().toISOString()
  };
  if (data) logEntry.data = data;
  console.log(JSON.stringify(logEntry));
}

function logSuccess(message, data = null) {
  console.log(`✅ ${message}`, data && VERBOSE_MODE ? JSON.stringify(data, null, 2) : '');
}

function logWarning(message, data = null) {
  console.log(`⚠️  ${message}`, data && VERBOSE_MODE ? JSON.stringify(data, null, 2) : '');
}

// Récupération des résultats Google avec Playwright (version améliorée)
async function getGoogleResults(query, maxResults, stealthMode = true) {
  let browser = null;
  let context = null;
  let page = null;
  
  try {
    logInfo('Lancement du navigateur Playwright avec mode stealth');
    
    const launchOptions = {
      headless: CONFIG.browser.headless,
      args: CONFIG.browser.args
    };
    
    if (process.env.CHROME_BIN) {
      launchOptions.executablePath = process.env.CHROME_BIN;
    }
    
    browser = await chromium.launch(launchOptions);
    
    context = await browser.newContext({
      ...CONFIG.context,
      extraHTTPHeaders: {
        ...CONFIG.context.extraHTTPHeaders
      }
    });
    
    // Bloquer les ressources inutiles pour plus de rapidité
    await context.route('**/*.{png,jpg,jpeg,gif,svg,css,woff,woff2}', route => route.abort());
    
    page = await context.newPage();
    
    // Appliquer le mode stealth
    if (stealthMode) {
      await setupStealthMode(page);
      logInfo('Mode stealth activé');
    }
    
    page.setDefaultTimeout(CONFIG.page.timeout);
    page.setDefaultNavigationTimeout(CONFIG.page.navigationTimeout);
    
    logInfo('Navigation vers Google.com avec délai humain');
    await page.goto('https://www.google.com', { 
      waitUntil: 'domcontentloaded',
      timeout: CONFIG.page.navigationTimeout 
    });
    
    // Délai humain après chargement
    const initialDelay = randomDelay(...CONFIG.delays.afterLoad);
    logInfo(`Délai humain initial: ${initialDelay}ms`);
    await page.waitForTimeout(initialDelay);
    
    // Accepter les cookies avec plus de réalisme
    try {
      const cookieSelectors = [
        'button:has-text("Tout accepter")',
        'button:has-text("J\'accepte")',
        '#L2AGLb',
        'button[aria-label="Tout accepter"]',
        'button:contains("Accept all")'
      ];
      
      let cookieAccepted = false;
      for (const selector of cookieSelectors) {
        try {
          await page.waitForSelector(selector, { timeout: 3000 });
          await page.waitForTimeout(randomDelay(500, 1500)); // Délai avant clic
          await page.click(selector);
          await page.waitForTimeout(randomDelay(1000, 2000)); // Délai après clic
          logInfo('Cookies acceptés');
          cookieAccepted = true;
          break;
        } catch {
          continue;
        }
      }
      
      if (!cookieAccepted) {
        logInfo('Pas de popup de cookies détecté');
      }
    } catch {
      logInfo('Gestion des cookies échouée');
    }
    
    // Délai avant recherche
    const searchDelay = randomDelay(...CONFIG.delays.beforeSearch);
    logInfo(`Délai avant recherche: ${searchDelay}ms`);
    await page.waitForTimeout(searchDelay);
    
    const searchUrl = `${CONFIG.search.baseUrl}?q=${encodeURIComponent(query)}&hl=${CONFIG.search.language}&gl=fr`;
    logInfo('Navigation vers la page de résultats', { searchUrl });
    
    await page.goto(searchUrl, {
      waitUntil: 'networkidle',
      timeout: CONFIG.page.navigationTimeout
    });
    
    // Délai après chargement des résultats
    const resultsDelay = randomDelay(2000, 4000);
    logInfo(`Délai après chargement des résultats: ${resultsDelay}ms`);
    await page.waitForTimeout(resultsDelay);
    
    // Vérifier si reCAPTCHA ou blocage
    const pageContent = await page.content();
    if (pageContent.includes('reCAPTCHA') || pageContent.includes('robot') || pageContent.includes('captcha')) {
      logWarning('reCAPTCHA détecté - prise de screenshot');
      await page.screenshot({ path: 'recaptcha_detected.png', fullPage: false });
      throw new Error('reCAPTCHA détecté - changez d\'IP ou attendez');
    }
    
    const urls = await page.evaluate((maxResults) => {
      // Essayer plusieurs sélecteurs pour les résultats
      const selectors = [
        'div[class="MjjYud"] a',
        'div.g a',
        'div[data-hveid] a',
        '.rc a',
        'h3 a'
      ];
      
      let elements = [];
      for (const selector of selectors) {
        elements = Array.from(document.querySelectorAll(selector));
        if (elements.length > 0) {
          console.log(`Sélecteur fonctionnel: ${selector}, ${elements.length} éléments trouvés`);
          break;
        }
      }
      
      const urls = elements
        .slice(0, maxResults * 2) // Prendre plus d'éléments au cas où
        .map(a => a.href)
        .filter(url => url && url.startsWith('http') && !url.includes('google.com') && !url.includes('youtube.com'))
        .slice(0, maxResults); // Limiter au nombre demandé
      
      console.log('URLs extraites:', urls);
      return urls;
    }, maxResults);
    
    if (urls.length === 0) {
      logWarning('Aucune URL trouvée, capture d\'écran pour debug');
      try {
        await page.screenshot({ path: 'debug_google_results.png', fullPage: true });
        logInfo('Screenshot complet sauvegardé: debug_google_results.png');
        
        // Sauvegarder aussi le HTML pour debug
        const html = await page.content();
        await fs.promises.writeFile('debug_page.html', html, 'utf-8');
        logInfo('HTML de debug sauvegardé: debug_page.html');
      } catch (screenshotError) {
        logWarning('Impossible de faire le screenshot', { error: screenshotError.message });
      }
    }
    
    logSuccess('URLs extraites avec Playwright', { count: urls.length, urls: VERBOSE_MODE ? urls : urls.slice(0, 2) });
    return urls;
    
  } catch (error) {
    logError(error, 'Récupération des résultats Google avec Playwright');
    throw error;
  } finally {
    if (page) await page.close();
    if (context) await context.close();
    if (browser) await browser.close();
  }
}

// Récupération du contenu HTML avec fetch natif (inchangé)
async function fetchPageContent(url, retryCount = 0) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), CONFIG.fetch.timeout);
  
  try {
    logInfo(`Récupération du contenu avec fetch (tentative ${retryCount + 1})`, { url });
    
    const response = await fetch(url, {
      signal: controller.signal,
      headers: {
        ...CONFIG.fetch.headers,
        'User-Agent': CONFIG.context.userAgent,
        'Referer': 'https://www.google.com/'
      },
      redirect: 'follow',
      mode: 'cors'
    });
    
    clearTimeout(timeoutId);
    
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }
    
    const contentType = response.headers.get('content-type') || '';
    if (!contentType.includes('text/html') && !contentType.includes('text/plain')) {
      logWarning('Content-Type non HTML détecté', { contentType, url });
    }
    
    const html = await response.text();
    
    if (!html || html.length < 100) {
      throw new Error('Contenu HTML trop court ou vide');
    }
    
    logSuccess('Contenu récupéré avec fetch', { 
      url: VERBOSE_MODE ? url : url.substring(0, 50) + '...', 
      status: response.status,
      contentLength: html.length,
      contentType 
    });
    
    return {
      success: true,
      html,
      status: response.status,
      contentType,
      url: response.url,
      method: 'fetch'
    };
  } catch (error) {
    clearTimeout(timeoutId);
    
    if (retryCount < CONFIG.fetch.maxRetries && isRetryableError(error)) {
      const delay = CONFIG.fetch.retryDelay * Math.pow(2, retryCount);
      logInfo(`Retry fetch dans ${delay}ms`, { url, error: error.message, retryCount });
      
      await new Promise(resolve => setTimeout(resolve, delay));
      return fetchPageContent(url, retryCount + 1);
    }
    
    logError(error, `Récupération fetch de ${url} après ${retryCount + 1} tentatives`);
    return {
      success: false,
      html: null,
      error: error.message,
      url,
      method: 'fetch'
    };
  }
}

// Vérification si l'erreur est "retryable"
function isRetryableError(error) {
  const retryableErrors = [
    'AbortError',
    'TimeoutError',
    'ECONNRESET',
    'ECONNREFUSED',
    'ETIMEDOUT',
    'ENOTFOUND',
    'ENETUNREACH'
  ];
  
  const retryableStatus = [408, 429, 500, 502, 503, 504];
  
  return (
    retryableErrors.some(code => error.message.includes(code)) ||
    error.name === 'AbortError' ||
    (error.status && retryableStatus.includes(error.status))
  );
}

// Fallback avec Playwright pour les pages problématiques
async function fetchWithPlaywright(url) {
  let browser = null;
  let context = null;
  let page = null;
  
  try {
    logInfo('Fallback Playwright pour récupération de contenu', { url });
    
    browser = await chromium.launch({
      headless: true,
      args: CONFIG.browser.args
    });
    
    context = await browser.newContext({
      ...CONFIG.context,
      extraHTTPHeaders: {
        ...CONFIG.context.extraHTTPHeaders,
        'Referer': 'https://www.google.com/'
      }
    });
    
    await context.route('**/*.{png,jpg,jpeg,gif,svg,css,woff,woff2,ico}', route => route.abort());
    
    page = await context.newPage();
    page.setDefaultTimeout(CONFIG.page.timeout);
    
    const response = await page.goto(url, { 
      waitUntil: CONFIG.search.waitUntil,
      timeout: CONFIG.page.navigationTimeout 
    });
    
    if (response && response.ok()) {
      await page.waitForLoadState('networkidle');
      
      const html = await page.content();
      const title = await page.title();
      
      logSuccess('Playwright fallback réussi', { 
        url: VERBOSE_MODE ? url : url.substring(0, 50) + '...', 
        htmlLength: html.length,
        title: title.substring(0, 100) 
      });
      
      return { 
        success: true, 
        html, 
        title, 
        status: response.status(),
        method: 'playwright' 
      };
    }
    
    return { success: false, html: null, method: 'playwright' };
  } catch (error) {
    logError(error, `Playwright fallback pour ${url}`);
    return { 
      success: false, 
      html: null, 
      error: error.message, 
      method: 'playwright' 
    };
  } finally {
    if (page) await page.close();
    if (context) await context.close();
    if (browser) await browser.close();
  }
}

// Extraction du titre depuis le HTML
function extractTitle(html) {
  if (!html) return null;
  const titleMatch = html.match(/<title[^>]*>([^<]+)<\/title>/i);
  return titleMatch ? titleMatch[1].trim().substring(0, 200) : null;
}

// Fonction principale d'extraction
async function extractWithHybridApproach(query, maxResults, outputFile, stealthMode) {
  const startTime = Date.now();
  
  try {
    logInfo('Début de l\'extraction avec Playwright + Fetch (mode stealth)', { query, maxResults, stealthMode });
    
    const urls = await getGoogleResults(query, maxResults, stealthMode);
    
    if (urls.length === 0) {
      throw new Error('Aucun résultat trouvé sur Google');
    }
    
    console.log(`🔍 ${urls.length} URLs trouvées, extraction du contenu...`);
    const results = [];
    
    for (let i = 0; i < urls.length; i++) {
      const url = urls[i];
      console.log(`\n🔄 Traitement ${i + 1}/${urls.length}: ${url.substring(0, 60)}...`);
      
      let content = await fetchPageContent(url);
      
      if (!content.success) {
        console.log(`🔄 Fallback vers Playwright...`);
        const playwrightResult = await fetchWithPlaywright(url);
        content = {
          ...playwrightResult,
          title: playwrightResult.title || extractTitle(playwrightResult.html)
        };
      }
      
      if (content.success && !content.title) {
        content.title = extractTitle(content.html);
      }
      
      results.push({
        position: i + 1,
        url,
        title: content.title,
        html: content.html,
        success: content.success,
        method: content.method,
        status: content.status || null,
        error: content.error || null,
        htmlLength: content.html ? content.html.length : 0
      });
      
      if (content.success) {
        console.log(`✅ Récupéré via ${content.method} (${Math.round((content.html?.length || 0) / 1024)}KB)`);
      } else {
        console.log(`❌ Échec: ${content.error}`);
      }
      
      // Délai entre les pages pour paraître plus humain
      if (i < urls.length - 1) {
        const pageDelay = randomDelay(1000, 3000);
        console.log(`⏱️ Délai entre pages: ${pageDelay}ms`);
        await new Promise(resolve => setTimeout(resolve, pageDelay));
      }
    }
    
    const endTime = Date.now();
    const duration = endTime - startTime;
    
    const stats = {
      total: results.length,
      successful: results.filter(r => r.success).length,
      failed: results.filter(r => !r.success).length,
      fetchMethod: results.filter(r => r.method === 'fetch').length,
      playwrightMethod: results.filter(r => r.method === 'playwright').length,
      durationMs: duration,
      avgTimePerPage: Math.round(duration / results.length),
      totalHtmlSize: results.reduce((acc, r) => acc + (r.htmlLength || 0), 0)
    };
    
    const serpData = {
      success: true,
      query,
      timestamp: new Date().toISOString(),
      nodeVersion: process.version,
      playwrightVersion: require('playwright/package.json').version,
      organicResults: results,
      stats,
      config: {
        fetchTimeout: CONFIG.fetch.timeout,
        maxRetries: CONFIG.fetch.maxRetries,
        userAgent: CONFIG.context.userAgent,
        browserEngine: 'chromium',
        maxResults,
        stealthMode,
        headless: CONFIG.browser.headless
      }
    };
    
    // Sauvegarde
    await fs.promises.writeFile(outputFile, JSON.stringify(serpData, null, 2), 'utf-8');
    
    logSuccess('Extraction terminée avec succès', stats);
    
    return serpData;
    
  } catch (error) {
    logError(error, 'Extraction hybride avec Playwright');
    throw error;
  }
}

// Point d'entrée principal
(async () => {
  try {
    const options = parseArguments();
    VERBOSE_MODE = options.verbose;
    
    console.log(`🎭 Extracteur SERP avec Playwright + Fetch Natif (Anti-Détection)`);
    console.log(`Node.js: ${process.version} | Playwright: ${require('playwright/package.json').version}`);
    console.log('=====================================================');
    console.log(`🎯 Requête: "${options.query}"`);
    console.log(`📄 Fichier de sortie: ${options.outputFile}`);
    console.log(`🔢 Nombre max de résultats: ${options.maxResults}`);
    console.log(`🔊 Mode verbeux: ${options.verbose ? 'Activé' : 'Désactivé'}`);
    console.log(`🥷 Mode stealth: ${options.stealthMode ? 'Activé' : 'Désactivé'}`);
    console.log(`👁️ Mode headless: ${CONFIG.browser.headless ? 'Activé' : 'Désactivé'}`);
    console.log('=====================================================');
    
    const result = await extractWithHybridApproach(options.query, options.maxResults, options.outputFile, options.stealthMode);
    
    console.log('\n🎉 EXTRACTION TERMINÉE AVEC SUCCÈS');
    console.log('==================================');
    console.log(`📄 Résultats sauvegardés: ${options.outputFile}`);
    console.log(`📊 Pages récupérées: ${result.stats.successful}/${result.stats.total}`);
    console.log(`⏱️  Durée totale: ${Math.round(result.stats.durationMs / 1000)}s`);
    console.log(`💾 Taille totale HTML: ${Math.round(result.stats.totalHtmlSize / 1024)}KB`);
    console.log(`🔧 Méthodes: ${result.stats.fetchMethod} fetch, ${result.stats.playwrightMethod} playwright`);
    
    process.exit(0);
  } catch (error) {
    logError(error, 'Processus principal');
    console.log('\n❌ EXTRACTION ÉCHOUÉE');
    console.log('====================');
    console.log('Consultez les logs ci-dessus pour plus de détails.');
    
    // Si reCAPTCHA détecté, donner des conseils
    if (error.message.includes('reCAPTCHA') || error.message.includes('robot')) {
      console.log('\n💡 CONSEILS POUR ÉVITER LE reCAPTCHA:');
      console.log('- Attendez quelques heures avant de relancer');
      console.log('- Changez votre IP (redémarrez votre routeur/VPN)');
      console.log('- Utilisez --headless pour un mode plus discret');
      console.log('- Réduisez --max-results à 1 ou 2');
    }
    
    process.exit(1);
  }
})();