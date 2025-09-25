#!/usr/bin/env node

const { chromium } = require('playwright');

(async () => {
  const args = process.argv.slice(2);
  if (args.length < 1) {
    console.error('Usage: node serp.js "requête de recherche"');
    process.exit(1);
  }
  const query = args[0];

  const browser = await chromium.launch({
    headless: true,
    args: ['--no-sandbox', '--disable-dev-shm-usage']
  });

  const context = await browser.newContext({
    viewport: { width: 1280, height: 800 },
    userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    locale: 'fr-FR',
    timezoneId: 'Europe/Paris',
    extraHTTPHeaders: {
      'Accept-Language': 'fr-FR,fr;q=0.9,en;q=0.8'
    }
  });

  // Petit "stealth"
  await context.addInitScript(() => {
    Object.defineProperty(navigator, 'webdriver', { get: () => false });
  });

  const page = await context.newPage();
  const searchUrl = `https://www.google.com/search?q=${encodeURIComponent(query)}&hl=fr&gl=fr`;
  await page.goto(searchUrl, { waitUntil: 'domcontentloaded' });

  // Gestion consentement (page)
  try {
    const consentBtn = await page.$('button:has-text("Tout accepter"), #L2AGLb, [aria-label*="Accepter"], [aria-label*="Accept"]');
    if (consentBtn) {
      await consentBtn.click({ timeout: 3000 }).catch(() => {});
      await page.waitForLoadState('networkidle', { timeout: 5000 }).catch(() => {});
    }
  } catch {}

  // Gestion consentement (iframe)
  try {
    const consentFrame = page.frames().find(f => /consent|consent\.google\.com/.test(f.url()));
    if (consentFrame) {
      const btn = await consentFrame.$('button:has-text("Tout accepter"), #L2AGLb, [aria-label*="Accepter"], [aria-label*="Accept"]');
      if (btn) {
        await btn.click({ timeout: 3000 }).catch(() => {});
        await page.waitForLoadState('networkidle', { timeout: 5000 }).catch(() => {});
      }
    }
  } catch {}

  // Attendre que la SERP apparaisse
  await page.waitForSelector('#rso h3', { timeout: 10000 }).catch(() => {});

  const results = await page.evaluate(() => {
    // Sélection large et filtrage
    const cards = Array.from(document.querySelectorAll('#rso .g, #rso .MjjYud'));
    const out = [];
    let pos = 1;

    for (const el of cards) {
      const h3 = el.querySelector('h3');
      let a = null;

      // Lien le plus proche autour du h3
      if (h3) {
        a = h3.closest('a') || el.querySelector('a[href]');
      } else {
        a = el.querySelector('a[href] h3')?.closest('a');
      }

      const title = h3?.textContent?.trim();
      const url = a?.href;

      if (!title || !url) continue;
      // éliminer les liens internes Google
      if (url.includes('google.com/search') || url.startsWith('/search')) continue;

      out.push({ position: pos++, title, url });
      if (out.length >= 10) break;
    }
    return out;
  });

  console.log(JSON.stringify(results, null, 2));

  await browser.close();
})();
