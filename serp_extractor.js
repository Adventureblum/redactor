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

// Configuration améliorée avec mode stealth ultra-réaliste
const CONFIG = {
  browser: {
    headless: false, // Mode visible par défaut pour éviter détection
    args: [
      '--no-sandbox',
      '--disable-setuid-sandbox',
      '--disable-gpu',
      '--disable-dev-shm-usage',
      '--disable-blink-features=AutomationControlled',
      '--disable-web-security',
      '--disable-features=VizDisplayCompositor',
      // Arguments stealth avancés
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
      '--mute-audio',
      '--disable-extensions',
      '--disable-plugins',
      '--disable-images', // Accélère le chargement
      '--disable-javascript-harmony-shipping'
    ]
  },
  context: {
    viewport: { width: 1366, height: 768 },
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
    timeout: 60000, // Augmenté pour la saisie lente
    navigationTimeout: 60000
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
  // Configuration pour simulation utilisateur ultra-réaliste
  human: {
    typingSpeed: [80, 200],        // Vitesse de frappe en ms par caractère
    pauseBetweenWords: [200, 800], // Pause entre mots
    scrollSpeed: [100, 300],       // Vitesse de scroll
    mouseMovements: true,          // Mouvements de souris aléatoires
    beforeSearch: [3000, 6000],    // Délai avant recherche
    afterLoad: [2000, 4000],       // Délai après chargement
    betweenActions: [1000, 3000],  // Délai entre actions
    readingTime: [2000, 5000]      // Temps de "lecture" des résultats
  }
};

// Fonction pour générer un délai aléatoire
function randomDelay(min, max) {
  return Math.floor(Math.random() * (max - min + 1)) + min;
}

// Configuration du mode stealth ultra-avancé
async function setupAdvancedStealthMode(page) {
  await page.addInitScript(() => {
    // Supprimer toutes les traces de webdriver et automation
    Object.defineProperty(navigator, 'webdriver', {
      get: () => undefined,
    });
    
    // Masquer les plugins de détection
    Object.defineProperty(navigator, 'plugins', {
      get: () => [{
        name: 'Chrome PDF Plugin',
        filename: 'internal-pdf-viewer',
        description: 'Portable Document Format'
      }, {
        name: 'Chromium PDF Plugin',
        filename: 'internal-pdf-viewer',
        description: 'Portable Document Format'
      }],
    });
    
    // Simuler les langues du navigateur de façon plus réaliste
    Object.defineProperty(navigator, 'languages', {
      get: () => ['fr-FR', 'fr', 'en-US', 'en'],
    });
    
    // Masquer l'automation Chrome
    if (window.chrome) {
      delete window.chrome.loadTimes;
      delete window.chrome.csi;
      delete window.chrome.app;
    }
    
    // Supprimer les variables d'automation
    delete window.cdc_adoQpoasnfa76pfcZLmcfl_Array;
    delete window.cdc_adoQpoasnfa76pfcZLmcfl_Promise;
    delete window.cdc_adoQpoasnfa76pfcZLmcfl_Symbol;
    
    // Simuler les permissions de façon plus réaliste
    const originalQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) => (
      parameters.name === 'notifications' ?
        Promise.resolve({ state: Notification.permission }) :
        originalQuery(parameters)
    );
    
    // Simuler la mémoire disponible
    Object.defineProperty(navigator, 'deviceMemory', {
      get: () => 8,
    });
    
    // Simuler le nombre de coeurs CPU
    Object.defineProperty(navigator, 'hardwareConcurrency', {
      get: () => 4,
    });
    
    // Masquer les propriétés spécifiques à Playwright
    delete window.playwright;
    delete window.__playwright;
  });
}

// Simulation de mouvements de souris naturels
async function simulateMouseMovements(page) {
  if (!CONFIG.human.mouseMovements) return;
  
  try {
    // Mouvements aléatoires de souris pour simuler un utilisateur réel
    for (let i = 0; i < 3; i++) {
      const x = randomDelay(100, 1200);
      const y = randomDelay(100, 600);
      await page.mouse.move(x, y);
      await page.waitForTimeout(randomDelay(200, 800));
    }
  } catch (error) {
    // Ignorer les erreurs de mouvement de souris
  }
}

// Simulation de frappe humaine ultra-réaliste
async function typeHumanLike(page, selector, text) {
  await page.click(selector);
  await page.waitForTimeout(randomDelay(300, 800));
  
  // Effacer le contenu existant
  await page.keyboard.down('Control');
  await page.keyboard.press('KeyA');
  await page.keyboard.up('Control');
  await page.keyboard.press('Backspace');
  await page.waitForTimeout(randomDelay(200, 500));
  
  const words = text.split(' ');
  
  for (let i = 0; i < words.length; i++) {
    const word = words[i];
    
    // Taper chaque caractère du mot
    for (let j = 0; j < word.length; j++) {
      const char = word[j];
      await page.keyboard.type(char);
      
      // Délai variable selon le caractère
      let delay = randomDelay(...CONFIG.human.typingSpeed);
      
      // Délais plus longs pour certains caractères (simulation erreurs de frappe)
      if ('aeiou'.includes(char.toLowerCase())) {
        delay = randomDelay(60, 150); // Voyelles plus rapides
      } else if ('qwerty'.includes(char.toLowerCase())) {
        delay = randomDelay(100, 250); // Consonnes communes
      }
      
      await page.waitForTimeout(delay);
    }
    
    // Pause entre les mots (sauf pour le dernier mot)
    if (i < words.length - 1) {
      await page.keyboard.type(' ');
      await page.waitForTimeout(randomDelay(...CONFIG.human.pauseBetweenWords));
    }
  }
  
  // Pause avant d'appuyer sur Entrée
  await page.waitForTimeout(randomDelay(1000, 2500));
}

// Simulation de scroll naturel
async function simulateNaturalScroll(page) {
  try {
    // Scroll progressif comme un utilisateur réel
    const scrollSteps = randomDelay(2, 5);
    const viewportHeight = await page.evaluate(() => window.innerHeight);
    const scrollDistance = Math.floor(viewportHeight / scrollSteps);
    
    for (let i = 0; i < scrollSteps; i++) {
      await page.evaluate((distance) => {
        window.scrollBy(0, distance);
      }, scrollDistance);
      
      await page.waitForTimeout(randomDelay(...CONFIG.human.scrollSpeed));
    }
    
    // Temps de "lecture" des résultats
    await page.waitForTimeout(randomDelay(...CONFIG.human.readingTime));
  } catch (error) {
    // Ignorer les erreurs de scroll
  }
}

// Gestion des arguments de ligne de commande (inchangé)
function parseArguments() {
  const args = process.argv.slice(2);
  
  if (args.includes('--help') || args.includes('-h') || args.length === 0) {
    showHelp();
    process.exit(0);
  }
  
  let query = '';
  let outputFile = 'serp_corpus.json';
  let maxResults = 3;
  let verbose = false;
  let stealthMode = true;
  
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
        CONFIG.browser.headless = false;
        break;
        
      default:
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
🎭 Extracteur SERP avec Playwright + Simulation Utilisateur Ultra-Réaliste
==========================================================================

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

NOUVEAUTÉS ANTI-DÉTECTION:
  ✅ Simulation de frappe humaine caractère par caractère
  ✅ Mouvements de souris aléatoires
  ✅ Scroll progressif naturel
  ✅ Délais variables entre mots et actions
  ✅ Temps de "lecture" des résultats
  ✅ Navigation google.com → saisie → recherche
  ✅ Gestion cookies avec délais réalistes
  ✅ Mode stealth ultra-avancé

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

// Récupération des résultats Google avec simulation utilisateur complète
async function getGoogleResultsWithHumanSimulation(query, maxResults, stealthMode = true) {
  let browser = null;
  let context = null;
  let page = null;
  
  try {
    logInfo('🚀 Lancement du navigateur avec simulation utilisateur ultra-réaliste');
    
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
    await context.route('**/*.{png,jpg,jpeg,gif,svg,css,woff,woff2,ico,mp4,mp3}', route => route.abort());
    
    page = await context.newPage();
    
    // Appliquer le mode stealth avancé
    if (stealthMode) {
      await setupAdvancedStealthMode(page);
      logInfo('🥷 Mode stealth ultra-avancé activé');
    }
    
    page.setDefaultTimeout(CONFIG.page.timeout);
    page.setDefaultNavigationTimeout(CONFIG.page.navigationTimeout);
    
    // ÉTAPE 1: Navigation initiale vers Google.com (comme un utilisateur réel)
    logInfo('🌐 Navigation vers Google.com (simulation utilisateur)');
    await page.goto('https://www.google.com', { 
      waitUntil: 'domcontentloaded',
      timeout: CONFIG.page.navigationTimeout 
    });
    
    // Délai initial pour simuler le temps de chargement
    const initialDelay = randomDelay(...CONFIG.human.afterLoad);
    logInfo(`⏱️ Délai initial de lecture: ${initialDelay}ms`);
    await page.waitForTimeout(initialDelay);
    
    // Mouvements de souris pendant le chargement
    await simulateMouseMovements(page);
    
    // ÉTAPE 2: Gestion des cookies avec comportement humain
    try {
      const cookieSelectors = [
        'button:has-text("Tout accepter")',
        'button:has-text("J\'accepte")',
        '#L2AGLb',
        'button[aria-label="Tout accepter"]',
        'button:contains("Accept all")',
        'button[id="L2AGLb"]'
      ];
      
      let cookieAccepted = false;
      for (const selector of cookieSelectors) {
        try {
          await page.waitForSelector(selector, { timeout: 5000 });
          
          // Délai de "lecture" avant d'accepter les cookies
          await page.waitForTimeout(randomDelay(1500, 3500));
          
          // Mouvement de souris vers le bouton
          const buttonBox = await page.locator(selector).boundingBox();
          if (buttonBox) {
            await page.mouse.move(buttonBox.x + buttonBox.width/2, buttonBox.y + buttonBox.height/2);
            await page.waitForTimeout(randomDelay(200, 600));
          }
          
          await page.click(selector);
          await page.waitForTimeout(randomDelay(1000, 2000));
          logInfo('🍪 Cookies acceptés avec délai humain');
          cookieAccepted = true;
          break;
        } catch {
          continue;
        }
      }
      
      if (!cookieAccepted) {
        logInfo('🍪 Pas de popup de cookies détecté');
      }
    } catch {
      logInfo('🍪 Gestion des cookies échouée');
    }
    
    // ÉTAPE 3: Localiser et interagir avec la barre de recherche
    const searchDelay = randomDelay(...CONFIG.human.beforeSearch);
    logInfo(`🔍 Délai avant recherche: ${searchDelay}ms`);
    await page.waitForTimeout(searchDelay);
    
    // Trouver la barre de recherche
    const searchSelectors = [
      'input[name="q"]',
      'textarea[name="q"]',
      'input[title="Rechercher"]',
      'textarea[title="Rechercher"]',
      '[role="combobox"][name="q"]'
    ];
    
    let searchBox = null;
    for (const selector of searchSelectors) {
      try {
        await page.waitForSelector(selector, { timeout: 5000 });
        searchBox = selector;
        break;
      } catch {
        continue;
      }
    }
    
    if (!searchBox) {
      throw new Error('Impossible de trouver la barre de recherche Google');
    }
    
    logInfo('🎯 Barre de recherche trouvée, début de la saisie humaine');
    
    // Mouvement de souris vers la barre de recherche
    const searchBoxElement = await page.locator(searchBox).boundingBox();
    if (searchBoxElement) {
      await page.mouse.move(searchBoxElement.x + searchBoxElement.width/2, searchBoxElement.y + searchBoxElement.height/2);
      await page.waitForTimeout(randomDelay(300, 800));
    }
    
    // ÉTAPE 4: Saisie de la requête avec simulation humaine ultra-réaliste
    await typeHumanLike(page, searchBox, query);
    
    logInfo('⌨️ Saisie terminée, lancement de la recherche');
    
    // ÉTAPE 5: Lancer la recherche (Entrée)
    await page.keyboard.press('Enter');
    
    // Attendre la navigation
    await page.waitForNavigation({ 
      waitUntil: 'domcontentloaded',
      timeout: CONFIG.page.navigationTimeout 
    });
    
    // Délai après chargement des résultats
    const resultsDelay = randomDelay(2000, 4000);
    logInfo(`📄 Délai après chargement des résultats: ${resultsDelay}ms`);
    await page.waitForTimeout(resultsDelay);
    
    // ÉTAPE 6: Scroll naturel pour "lire" les résultats
    await simulateNaturalScroll(page);
    
    // Vérifier si reCAPTCHA ou blocage
    const pageContent = await page.content();
    if (pageContent.includes('reCAPTCHA') || pageContent.includes('robot') || pageContent.includes('captcha')) {
      logWarning('🤖 reCAPTCHA détecté - prise de screenshot');
      await page.screenshot({ path: 'recaptcha_detected.png', fullPage: false });
      throw new Error('reCAPTCHA détecté - changez d\'IP ou attendez');
    }
    
    // ÉTAPE 7: Extraction des URLs avec sélecteurs multiples
    const urls = await page.evaluate((maxResults) => {
      const selectors = [
        'div[class="MjjYud"] a[href^="http"]:not([href*="google.com"])',
        'div.g a[href^="http"]:not([href*="google.com"])',
        'div[data-hveid] a[href^="http"]:not([href*="google.com"])',
        '.rc a[href^="http"]:not([href*="google.com"])',
        'h3 a[href^="http"]:not([href*="google.com"])',
        'div[class*="yuRUbf"] a[href^="http"]:not([href*="google.com"])'
      ];
      
      let elements = [];
      for (const selector of selectors) {
        elements = Array.from(document.querySelectorAll(selector));
        if (elements.length > 0) {
          console.log(`✅ Sélecteur fonctionnel: ${selector}, ${elements.length} éléments trouvés`);
          break;
        }
      }
      
      const urls = elements
        .slice(0, maxResults * 2)
        .map(a => a.href)
        .filter(url => url && 
          url.startsWith('http') && 
          !url.includes('google.com') && 
          !url.includes('youtube.com') &&
          !url.includes('maps.google.com') &&
          !url.includes('translate.google.com')
        )
        .slice(0, maxResults);
      
      console.log('🎯 URLs extraites:', urls);
      return urls;
    }, maxResults);
    
    if (urls.length === 0) {
      logWarning('🔍 Aucune URL trouvée, capture d\'écran pour debug');
      try {
        await page.screenshot({ path: 'debug_google_results.png', fullPage: true });
        logInfo('📸 Screenshot complet sauvegardé: debug_google_results.png');
        
        const html = await page.content();
        await fs.promises.writeFile('debug_page.html', html, 'utf-8');
        logInfo('📄 HTML de debug sauvegardé: debug_page.html');
      } catch (screenshotError) {
        logWarning('📸 Impossible de faire le screenshot', { error: screenshotError.message });
      }
    }
    
    logSuccess('🎉 URLs extraites avec simulation utilisateur complète', { 
      count: urls.length, 
      urls: VERBOSE_MODE ? urls : urls.slice(0, 2) 
    });
    
    return urls;
    
  } catch (error) {
    logError(error, 'Récupération des résultats Google avec simulation utilisateur');
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
    logInfo(`🌐 Récupération du contenu avec fetch (tentative ${retryCount + 1})`, { url });
    
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
      logWarning('⚠️ Content-Type non HTML détecté', { contentType, url });
    }
    
    const html = await response.text();
    
    if (!html || html.length < 100) {
      throw new Error('Contenu HTML trop court ou vide');
    }
    
    logSuccess('✅ Contenu récupéré avec fetch', { 
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
      logInfo(`🔄 Retry fetch dans ${delay}ms`, { url, error: error.message, retryCount });
      
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
    logInfo('🔄 Fallback Playwright pour récupération de contenu', { url });
    
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
      waitUntil: 'domcontentloaded',
      timeout: CONFIG.page.navigationTimeout 
    });
    
    if (response && response.ok()) {
      await page.waitForLoadState('networkidle');
      
      const html = await page.content();
      const title = await page.title();
      
      logSuccess('✅ Playwright fallback réussi', { 
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

// Fonction principale d'extraction avec simulation utilisateur ultra-réaliste
async function extractWithHumanSimulation(query, maxResults, outputFile, stealthMode) {
  const startTime = Date.now();
  
  try {
    logInfo('🎭 Début de l\'extraction avec simulation utilisateur ultra-réaliste', { 
      query, 
      maxResults, 
      stealthMode,
      typingSpeed: CONFIG.human.typingSpeed,
      mouseMovements: CONFIG.human.mouseMovements
    });
    
    const urls = await getGoogleResultsWithHumanSimulation(query, maxResults, stealthMode);
    
    if (urls.length === 0) {
      throw new Error('Aucun résultat trouvé sur Google avec la simulation utilisateur');
    }
    
    console.log(`🔍 ${urls.length} URLs trouvées avec simulation humaine, extraction du contenu...`);
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
        const pageDelay = randomDelay(2000, 5000); // Délais plus longs
        console.log(`⏱️ Délai entre pages (simulation humaine): ${pageDelay}ms`);
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
      totalHtmlSize: results.reduce((acc, r) => acc + (r.htmlLength || 0), 0),
      humanSimulation: {
        typingSpeedRange: CONFIG.human.typingSpeed,
        mouseMovements: CONFIG.human.mouseMovements,
        scrollSimulated: true,
        naturalDelays: true
      }
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
        headless: CONFIG.browser.headless,
        humanSimulation: {
          enabled: true,
          typingSpeed: CONFIG.human.typingSpeed,
          mouseMovements: CONFIG.human.mouseMovements,
          scrollSpeed: CONFIG.human.scrollSpeed,
          naturalDelays: true
        }
      }
    };
    
    // Sauvegarde
    await fs.promises.writeFile(outputFile, JSON.stringify(serpData, null, 2), 'utf-8');
    
    logSuccess('🎉 Extraction terminée avec succès (simulation utilisateur)', stats);
    
    return serpData;
    
  } catch (error) {
    logError(error, 'Extraction avec simulation utilisateur ultra-réaliste');
    throw error;
  }
}

// Point d'entrée principal
(async () => {
  try {
    const options = parseArguments();
    VERBOSE_MODE = options.verbose;
    
    console.log(`🎭 Extracteur SERP avec Simulation Utilisateur Ultra-Réaliste`);
    console.log(`Node.js: ${process.version} | Playwright: ${require('playwright/package.json').version}`);
    console.log('=====================================================');
    console.log(`🎯 Requête: "${options.query}"`);
    console.log(`📄 Fichier de sortie: ${options.outputFile}`);
    console.log(`🔢 Nombre max de résultats: ${options.maxResults}`);
    console.log(`🔊 Mode verbeux: ${options.verbose ? 'Activé' : 'Désactivé'}`);
    console.log(`🥷 Mode stealth: ${options.stealthMode ? 'Ultra-Avancé' : 'Désactivé'}`);
    console.log(`👁️ Mode headless: ${CONFIG.browser.headless ? 'Activé' : 'Désactivé (Plus humain)'}`);
    console.log(`⌨️ Frappe humaine: ${CONFIG.human.typingSpeed[0]}-${CONFIG.human.typingSpeed[1]}ms/caractère`);
    console.log(`🖱️ Mouvements souris: ${CONFIG.human.mouseMovements ? 'Activés' : 'Désactivés'}`);
    console.log('=====================================================');
    
    const result = await extractWithHumanSimulation(options.query, options.maxResults, options.outputFile, options.stealthMode);
    
    console.log('\n🎉 EXTRACTION TERMINÉE AVEC SUCCÈS (MODE SIMULATION HUMAINE)');
    console.log('============================================================');
    console.log(`📄 Résultats sauvegardés: ${options.outputFile}`);
    console.log(`📊 Pages récupérées: ${result.stats.successful}/${result.stats.total}`);
    console.log(`⏱️  Durée totale: ${Math.round(result.stats.durationMs / 1000)}s`);
    console.log(`💾 Taille totale HTML: ${Math.round(result.stats.totalHtmlSize / 1024)}KB`);
    console.log(`🔧 Méthodes: ${result.stats.fetchMethod} fetch, ${result.stats.playwrightMethod} playwright`);
    console.log(`🎭 Simulation humaine: Frappe naturelle + Mouvements souris + Scroll progressif`);
    
    process.exit(0);
  } catch (error) {
    logError(error, 'Processus principal avec simulation utilisateur');
    console.log('\n❌ EXTRACTION ÉCHOUÉE');
    console.log('====================');
    console.log('Consultez les logs ci-dessus pour plus de détails.');
    
    // Si reCAPTCHA détecté, donner des conseils améliorés
    if (error.message.includes('reCAPTCHA') || error.message.includes('robot')) {
      console.log('\n💡 CONSEILS POUR ÉVITER LE reCAPTCHA (MODE SIMULATION HUMAINE):');
      console.log('- La simulation utilisateur est déjà activée mais peut nécessiter plus de délais');
      console.log('- Attendez 2-3 heures avant de relancer (cooldown IP)');
      console.log('- Changez votre IP (redémarrez votre routeur/VPN)');
      console.log('- Utilisez --max-results 1 pour minimiser les requêtes');
      console.log('- Le mode visible (non-headless) est déjà optimisé');
      console.log('- Vérifiez le screenshot recaptcha_detected.png pour plus d\'infos');
    }
    
    process.exit(1);
  }
})();