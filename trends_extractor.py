#!/usr/bin/env python3
"""
Script d'extraction Google Trends avec pytrends
Inclut gestion d'erreurs, rate limiting et sauvegarde des données
"""

import pandas as pd
import time
import json
from datetime import datetime
from pytrends.request import TrendReq
import random

class TrendsExtractor:
    def __init__(self, language='fr', timezone=60):
        """
        Initialise l'extracteur de tendances
        
        Args:
            language (str): Code langue (fr, en, etc.)
            timezone (int): Timezone offset
        """
        self.pytrends = TrendReq(hl=language, tz=timezone)
        self.results = {}
        
    def extract_keyword_data(self, keyword, timeframe='today 12-m', geo='FR'):
        """
        Extrait toutes les données disponibles pour un mot-clé
        
        Args:
            keyword (str): Mot-clé à analyser
            timeframe (str): Période d'analyse
            geo (str): Zone géographique
        """
        print(f"🔍 Extraction des données pour: '{keyword}'")
        
        try:
            # Construction de la requête
            self.pytrends.build_payload([keyword], timeframe=timeframe, geo=geo)
            
            # 1. Évolution dans le temps
            print("  📊 Récupération de l'évolution temporelle...")
            interest_time = self.pytrends.interest_over_time()
            
            # 2. Intérêt par région
            print("  🗺️  Récupération des données géographiques...")
            try:
                interest_region = self.pytrends.interest_by_region(resolution='CITY')
            except Exception as e:
                print(f"    ⚠️  Données régionales non disponibles: {str(e)}")
                interest_region = pd.DataFrame()
            
            # 3. Requêtes liées
            print("  🔗 Récupération des requêtes liées...")
            try:
                related_queries = self.pytrends.related_queries()
            except Exception as e:
                print(f"    ⚠️  Requêtes liées non disponibles: {str(e)}")
                related_queries = {}
            
            # 4. Sujets liés
            print("  📚 Récupération des sujets liés...")
            try:
                related_topics = self.pytrends.related_topics()
            except Exception as e:
                print(f"    ⚠️  Sujets liés non disponibles: {str(e)}")
                related_topics = {}
            
            # 5. Suggestions (avec gestion d'erreur)
            print("  💡 Récupération des suggestions...")
            try:
                suggestions = self.pytrends.suggestions(keyword=keyword)
            except Exception as e:
                print(f"    ⚠️  Suggestions non disponibles: {str(e)}")
                suggestions = []
            
            # Stockage des résultats
            self.results[keyword] = {
                'timestamp': datetime.now().isoformat(),
                'interest_over_time': interest_time,
                'interest_by_region': interest_region,
                'related_queries': related_queries,
                'related_topics': related_topics,
                'suggestions': suggestions,
                'metadata': {
                    'timeframe': timeframe,
                    'geo': geo,
                    'keyword': keyword
                }
            }
            
            print(f"  ✅ Extraction terminée pour '{keyword}'")
            return True
            
        except Exception as e:
            print(f"  ❌ Erreur lors de l'extraction de '{keyword}': {str(e)}")
            return False
    
    def extract_multiple_keywords(self, keywords, delay_range=(2, 5)):
        """
        Extrait les données pour plusieurs mots-clés avec délais
        
        Args:
            keywords (list): Liste des mots-clés
            delay_range (tuple): Range de délai entre requêtes (min, max)
        """
        print(f"🚀 Début de l'extraction pour {len(keywords)} mots-clés")
        
        successful = 0
        for i, keyword in enumerate(keywords, 1):
            print(f"\n[{i}/{len(keywords)}]", end=" ")
            
            if self.extract_keyword_data(keyword):
                successful += 1
            
            # Délai aléatoire pour éviter le rate limiting
            if i < len(keywords):
                delay = random.uniform(*delay_range)
                print(f"  ⏳ Pause de {delay:.1f}s avant la prochaine requête...")
                time.sleep(delay)
        
        print(f"\n✨ Extraction terminée: {successful}/{len(keywords)} réussies")
    
    def display_summary(self, keyword):
        """Affiche un résumé des données extraites"""
        if keyword not in self.results:
            print(f"❌ Aucune donnée trouvée pour '{keyword}'")
            return
        
        data = self.results[keyword]
        print(f"\n📋 RÉSUMÉ POUR '{keyword.upper()}'")
        print("=" * 50)
        
        # Évolution temporelle
        interest_time = data['interest_over_time']
        if not interest_time.empty:
            avg_interest = interest_time[keyword].mean()
            max_interest = interest_time[keyword].max()
            print(f"📊 Intérêt moyen: {avg_interest:.1f}/100")
            print(f"📈 Pic d'intérêt: {max_interest}/100")
        
        # Top régions
        interest_region = data['interest_by_region']
        if not interest_region.empty:
            top_regions = interest_region.nlargest(5, keyword)
            print(f"\n🏆 TOP 5 RÉGIONS:")
            for region, score in top_regions.iterrows():
                print(f"   • {region}: {score[keyword]}/100")
        
        # Requêtes liées
        related_queries = data['related_queries']
        if related_queries and keyword in related_queries:
            if 'top' in related_queries[keyword] and related_queries[keyword]['top'] is not None:
                print(f"\n🔗 TOP REQUÊTES LIÉES:")
                top_queries = related_queries[keyword]['top'].head(5)
                for idx, row in top_queries.iterrows():
                    print(f"   • {row['query']}: {row['value']}/100")
            
            if 'rising' in related_queries[keyword] and related_queries[keyword]['rising'] is not None:
                print(f"\n🚀 REQUÊTES EN CROISSANCE:")
                rising_queries = related_queries[keyword]['rising'].head(5)
                for idx, row in rising_queries.iterrows():
                    growth = row['value'] if row['value'] != 'Breakout' else '+1000%'
                    print(f"   • {row['query']}: {growth}")
    
    def save_to_files(self, keyword, output_dir='./trends_data'):
        """Sauvegarde les données dans des fichiers"""
        import os
        
        if keyword not in self.results:
            print(f"❌ Aucune donnée à sauvegarder pour '{keyword}'")
            return
        
        # Créer le dossier de sortie
        os.makedirs(output_dir, exist_ok=True)
        
        data = self.results[keyword]
        safe_keyword = keyword.replace(' ', '_').replace('/', '_')
        
        # Sauvegarder chaque type de données
        if not data['interest_over_time'].empty:
            data['interest_over_time'].to_csv(f"{output_dir}/{safe_keyword}_evolution.csv")
        
        if not data['interest_by_region'].empty:
            data['interest_by_region'].to_csv(f"{output_dir}/{safe_keyword}_regions.csv")
        
        # Sauvegarder les métadonnées et requêtes liées en JSON
        json_data = {
            'metadata': data['metadata'],
            'related_queries': self._serialize_related_data(data['related_queries']),
            'related_topics': self._serialize_related_data(data['related_topics']),
            'suggestions': data['suggestions']
        }
        
        with open(f"{output_dir}/{safe_keyword}_metadata.json", 'w', encoding='utf-8') as f:
            json.dump(json_data, f, indent=2, ensure_ascii=False)
        
        print(f"💾 Données sauvegardées dans {output_dir}/")
    
    def _serialize_related_data(self, data):
        """Convertit les DataFrames en dictionnaires pour la sérialisation JSON"""
        if not data:
            return None
        
        result = {}
        for keyword, related_data in data.items():
            result[keyword] = {}
            for category, df in related_data.items():
                if df is not None and not df.empty:
                    result[keyword][category] = df.to_dict('records')
                else:
                    result[keyword][category] = None
        return result


def main():
    """Fonction principale - exemple d'utilisation"""
    
    # Initialisation
    extractor = TrendsExtractor(language='fr', timezone=60)
    
    # Mots-clés à analyser (commencez petit pour tester)
    keywords_test = [
        'formation python',
        'apprendre javascript',
        'cours html css'
    ]
    
    # Extraction des données
    print("🎯 EXTRACTION GOOGLE TRENDS")
    print("=" * 40)
    
    extractor.extract_multiple_keywords(keywords_test)
    
    # Affichage des résultats
    for keyword in keywords_test:
        extractor.display_summary(keyword)
        extractor.save_to_files(keyword)
        print("\n" + "-" * 60)


if __name__ == "__main__":
    main()