#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Crawler SEO Article-Centré - Analyse rapide du jus interne
Usage: python seo_crawler.py <url_article> [--competitors url1,url2,url3] [--delay 0.3] [--max-pages 15]
"""

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from dataclasses import dataclass, asdict
from typing import List, Dict, Set, Optional
import time
import logging
import argparse
import json
import sys

@dataclass
class LinkAnalysis:
    target_url: str
    internal_links_in: List[str]  # Pages qui pointent vers la target
    internal_links_out: List[str]  # Pages vers lesquelles pointe la target
    external_links_out: List[str]  # Liens externes depuis la target
    page_depth: int  # Distance depuis la homepage
    juice_score: float  # Score de jus interne estimé
    h1_tags: List[str]
    title: str
    meta_description: str
    analyzed_pages: int  # Nombre de pages analysées
    execution_time: float

class ArticleCentricCrawler:
    """Crawler ultra-léger centré sur l'analyse d'un article spécifique"""
    
    def __init__(self, delay: float = 0.3, max_pages: int = 15):
        self.session = self._create_session()
        self.delay = delay
        self.max_pages = max_pages
        self.visited_cache: Dict[str, BeautifulSoup] = {}
        self.logger = self._setup_logging()
        
    def _setup_logging(self):
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[logging.StreamHandler()]
        )
        return logging.getLogger(__name__)
    
    def _create_session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (SEO Analysis Bot/1.0)',
            'Accept': 'text/html,application/xhtml+xml',
            'Accept-Language': 'fr-FR,fr;q=0.9,en;q=0.8'
        })
        return session
    
    def _normalize_url(self, url: str) -> str:
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path.rstrip('/') or '/'}"
    
    def _get_domain(self, url: str) -> str:
        return urlparse(url).netloc
    
    def _fetch_page(self, url: str) -> Optional[BeautifulSoup]:
        """Fetch avec cache et gestion d'erreurs"""
        if url in self.visited_cache:
            return self.visited_cache[url]
        
        try:
            time.sleep(self.delay)
            self.logger.info(f"Fetching: {url}")
            response = self.session.get(url, timeout=30, allow_redirects=True)
            
            if response.status_code == 200 and 'text/html' in response.headers.get('Content-Type', ''):
                soup = BeautifulSoup(response.text, 'html.parser')
                self.visited_cache[url] = soup
                return soup
            else:
                self.logger.warning(f"Non-HTML ou erreur {response.status_code}: {url}")
                
        except Exception as e:
            self.logger.warning(f"Erreur fetch {url}: {e}")
        
        return None
    
    def _extract_links(self, soup: BeautifulSoup, base_url: str) -> tuple:
        """Extrait liens internes et externes"""
        domain = self._get_domain(base_url)
        internal_links = []
        external_links = []
        
        for link in soup.find_all('a', href=True):
            href = link['href'].strip()
            if not href or href.startswith(('#', 'javascript:', 'mailto:', 'tel:')):
                continue
            
            # Éviter les liens vers des fichiers
            if any(href.lower().endswith(ext) for ext in ['.pdf', '.jpg', '.png', '.zip', '.doc']):
                continue
            
            full_url = urljoin(base_url, href)
            normalized = self._normalize_url(full_url)
            
            if self._get_domain(normalized) == domain:
                if normalized not in internal_links:
                    internal_links.append(normalized)
            else:
                if normalized not in external_links:
                    external_links.append(normalized)
        
        return internal_links, external_links
    
    def _calculate_page_depth(self, target_url: str, homepage_url: str) -> int:
        """Calcule la profondeur d'une page depuis la homepage"""
        target_path = urlparse(target_url).path.strip('/')
        if not target_path:
            return 0  # Homepage
        
        segments = [s for s in target_path.split('/') if s]
        return len(segments)
    
    def _get_strategic_pages(self, target_url: str) -> List[str]:
        """Identifie les pages stratégiques à analyser depuis l'article cible"""
        domain = self._get_domain(target_url)
        homepage_url = f"{urlparse(target_url).scheme}://{domain}"
        strategic_pages = [homepage_url]
        
        # 1. Analyser l'article cible pour récupérer ses liens sortants
        target_soup = self._fetch_page(target_url)
        if target_soup:
            internal_links, _ = self._extract_links(target_soup, target_url)
            strategic_pages.extend(internal_links[:8])  # Limite pour focus
        
        # 2. Analyser la homepage pour récupérer navigation principale
        homepage_soup = self._fetch_page(homepage_url)
        if homepage_soup:
            # Liens du menu principal (nav, header)
            nav_links = []
            for nav in homepage_soup.find_all(['nav', 'header']):
                nav_internal, _ = self._extract_links(nav, homepage_url)
                nav_links.extend(nav_internal)
            
            # Ajouter les liens de navigation les plus importants
            strategic_pages.extend(nav_links[:6])
        
        # Supprimer doublons et limiter
        unique_pages = list(dict.fromkeys(strategic_pages))
        return unique_pages[:self.max_pages]
    
    def _find_pages_linking_to_target(self, target_url: str, search_urls: List[str]) -> List[str]:
        """Trouve les pages qui pointent vers la target"""
        linking_pages = []
        
        for url in search_urls:
            if url == target_url:
                continue
                
            soup = self._fetch_page(url)
            if not soup:
                continue
            
            internal_links, _ = self._extract_links(soup, url)
            if target_url in internal_links:
                linking_pages.append(url)
        
        return linking_pages
    
    def _estimate_juice_score(self, incoming_links: List[str], page_depth: int, homepage_url: str) -> float:
        """Calcule le score de jus interne avec pondération réaliste"""
        if not incoming_links:
            return 0.0
            
        base_score = 0.0
        
        for link in incoming_links:
            link_depth = self._calculate_page_depth(link, homepage_url)
            
            if link == homepage_url:
                base_score += 1.0  # Homepage = jus maximum
            elif link_depth == 1:
                base_score += 0.7  # Pages catégories/navigation
            elif link_depth == 2:
                base_score += 0.4  # Pages sous-catégories
            else:
                base_score += 0.2  # Pages profondes
        
        # Pénalité pour la profondeur de la page cible
        depth_penalty = max(0.1, 1 - (page_depth * 0.15))
        
        final_score = base_score * depth_penalty
        return round(final_score, 2)
    
    def analyze_article(self, target_url: str) -> LinkAnalysis:
        """Analyse complète d'un article depuis son URL"""
        start_time = time.time()
        target_url = self._normalize_url(target_url)
        domain = self._get_domain(target_url)
        homepage_url = f"{urlparse(target_url).scheme}://{domain}"
        
        self.logger.info(f"Début analyse de: {target_url}")
        
        # 1. Récupérer les pages stratégiques à analyser
        strategic_pages = self._get_strategic_pages(target_url)
        self.logger.info(f"Pages stratégiques identifiées: {len(strategic_pages)}")
        
        # 2. Analyser la page cible
        target_soup = self._fetch_page(target_url)
        if not target_soup:
            raise Exception(f"Impossible d'accéder à la page cible: {target_url}")
        
        # Extraction des données SEO de la cible
        internal_out, external_out = self._extract_links(target_soup, target_url)
        h1_tags = [h1.get_text().strip() for h1 in target_soup.find_all('h1')]
        
        title_tag = target_soup.find('title')
        title_text = title_tag.get_text().strip() if title_tag else ""
        
        meta_desc = target_soup.find('meta', attrs={'name': 'description'})
        meta_desc_text = meta_desc.get('content', '').strip() if meta_desc else ""
        
        # 3. Calculer profondeur et trouver pages linkantes
        page_depth = self._calculate_page_depth(target_url, homepage_url)
        internal_in = self._find_pages_linking_to_target(target_url, strategic_pages)
        
        # 4. Calculer score de jus
        juice_score = self._estimate_juice_score(internal_in, page_depth, homepage_url)
        
        execution_time = round(time.time() - start_time, 2)
        
        self.logger.info(f"Analyse terminée en {execution_time}s")
        self.logger.info(f"Score de jus: {juice_score} | Profondeur: {page_depth} | Liens entrants: {len(internal_in)}")
        
        return LinkAnalysis(
            target_url=target_url,
            internal_links_in=internal_in,
            internal_links_out=internal_out,
            external_links_out=external_out,
            page_depth=page_depth,
            juice_score=juice_score,
            h1_tags=h1_tags,
            title=title_text,
            meta_description=meta_desc_text,
            analyzed_pages=len(self.visited_cache),
            execution_time=execution_time
        )
    
    def compare_competitors(self, competitor_urls: List[str]) -> Dict[str, LinkAnalysis]:
        """Analyse comparative de plusieurs articles concurrents"""
        results = {}
        
        self.logger.info(f"Analyse comparative de {len(competitor_urls)} concurrents")
        
        for url in competitor_urls:
            try:
                # Reset cache entre chaque concurrent
                self.visited_cache.clear()
                analysis = self.analyze_article(url.strip())
                results[url] = analysis
                
            except Exception as e:
                self.logger.error(f"Erreur analyse {url}: {e}")
                continue
        
        return results

def print_analysis_report(analysis: LinkAnalysis):
    """Affiche un rapport détaillé de l'analyse"""
    print(f"\n{'='*60}")
    print(f"ANALYSE SEO - {analysis.target_url}")
    print(f"{'='*60}")
    
    print(f"\n📊 MÉTRIQUES PRINCIPALES:")
    print(f"   Score de jus interne: {analysis.juice_score}/10")
    print(f"   Profondeur dans l'arborescence: {analysis.page_depth}")
    print(f"   Pages analysées: {analysis.analyzed_pages}")
    print(f"   Temps d'exécution: {analysis.execution_time}s")
    
    print(f"\n🔗 ANALYSE DES LIENS:")
    print(f"   Liens entrants (jus reçu): {len(analysis.internal_links_in)}")
    for link in analysis.internal_links_in[:5]:
        print(f"     ← {link}")
    
    print(f"   Liens sortants (jus donné): {len(analysis.internal_links_out)}")
    for link in analysis.internal_links_out[:5]:
        print(f"     → {link}")
    
    print(f"   Liens externes: {len(analysis.external_links_out)}")
    
    print(f"\n📝 DONNÉES SEO:")
    print(f"   Titre: {analysis.title}")
    print(f"   Meta description: {analysis.meta_description[:100]}...")
    print(f"   H1 tags ({len(analysis.h1_tags)}): {', '.join(analysis.h1_tags)}")
    
    # Recommandations basiques
    print(f"\n💡 RECOMMANDATIONS:")
    if analysis.juice_score < 2:
        print("   ⚠️ Score de jus faible - Renforcer le maillage interne")
    if analysis.page_depth > 3:
        print("   ⚠️ Page trop profonde - Créer des liens depuis pages plus hautes")
    if not analysis.internal_links_in:
        print("   🚨 Page orpheline - Aucun lien interne détecté")
    if analysis.juice_score >= 5:
        print("   ✅ Bon potentiel de jus interne")

def print_competitive_report(results: Dict[str, LinkAnalysis]):
    """Affiche un rapport comparatif des concurrents"""
    if not results:
        return
        
    print(f"\n{'='*60}")
    print(f"ANALYSE COMPARATIVE - {len(results)} CONCURRENTS")
    print(f"{'='*60}")
    
    # Tri par score de jus décroissant
    sorted_results = sorted(results.items(), key=lambda x: x[1].juice_score, reverse=True)
    
    print(f"\n📊 CLASSEMENT PAR SCORE DE JUS:")
    for i, (url, analysis) in enumerate(sorted_results, 1):
        domain = urlparse(url).netloc
        print(f"   {i}. {domain} - Score: {analysis.juice_score} | Profondeur: {analysis.page_depth} | Liens_in: {len(analysis.internal_links_in)}")
    
    # Statistiques
    scores = [a.juice_score for a in results.values()]
    avg_score = sum(scores) / len(scores)
    
    print(f"\n📈 STATISTIQUES:")
    print(f"   Score moyen: {avg_score:.2f}")
    print(f"   Meilleur score: {max(scores)}")
    print(f"   Score le plus faible: {min(scores)}")

def main():
    parser = argparse.ArgumentParser(
        description="Analyseur SEO centré sur l'article - Calcul du jus interne",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemples d'utilisation:
  python seo_crawler.py https://example.com/mon-article
  python seo_crawler.py https://example.com/article --competitors https://concurrent1.com/page,https://concurrent2.com/article
  python seo_crawler.py https://example.com/article --delay 0.5 --max-pages 20 --output analysis.json
        """
    )
    
    parser.add_argument('target_url', help='URL de l\'article à analyser')
    parser.add_argument('--competitors', '-c', help='URLs des concurrents séparées par des virgules')
    parser.add_argument('--delay', '-d', type=float, default=0.3, help='Délai entre requêtes en secondes (défaut: 0.3)')
    parser.add_argument('--max-pages', '-m', type=int, default=15, help='Nombre max de pages à analyser (défaut: 15)')
    parser.add_argument('--output', '-o', help='Fichier JSON de sortie (optionnel)')
    parser.add_argument('--verbose', '-v', action='store_true', help='Mode verbose')
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    try:
        # Initialisation du crawler
        crawler = ArticleCentricCrawler(delay=args.delay, max_pages=args.max_pages)
        
        # Analyse de l'article principal
        print(f"🚀 Analyse de l'article cible...")
        main_analysis = crawler.analyze_article(args.target_url)
        print_analysis_report(main_analysis)
        
        results = {'target': main_analysis}
        
        # Analyse des concurrents si spécifiés
        if args.competitors:
            competitor_urls = [url.strip() for url in args.competitors.split(',')]
            print(f"\n🔍 Analyse des concurrents ({len(competitor_urls)})...")
            
            competitor_results = crawler.compare_competitors(competitor_urls)
            results['competitors'] = competitor_results
            
            print_competitive_report(competitor_results)
        
        # Sauvegarde JSON si demandée
        if args.output:
            # Conversion en dict sérialisable
            json_data = {}
            for key, value in results.items():
                if isinstance(value, LinkAnalysis):
                    json_data[key] = asdict(value)
                elif isinstance(value, dict):
                    json_data[key] = {url: asdict(analysis) for url, analysis in value.items()}
            
            with open(args.output, 'w', encoding='utf-8') as f:
                json.dump(json_data, f, indent=2, ensure_ascii=False)
            
            print(f"\n💾 Données sauvegardées: {args.output}")
        
        print(f"\n✅ Analyse terminée avec succès!")
        
    except KeyboardInterrupt:
        print(f"\n❌ Analyse interrompue par l'utilisateur")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Erreur: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()