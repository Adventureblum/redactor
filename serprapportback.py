import json
import os
from collections import defaultdict, Counter
from statistics import mean, median

class DomTrendComparator:
    """Analyse comparative complète des pratiques DOM par tranches SERP"""
    
    def __init__(self, rankscore_file="rankscore_dom.json"):
        self.rankscore_file = rankscore_file
        self.data = None

        # Structure par positions individuelles (1 à 10)
        self.positions = {}
        for i in range(1, 11):
            self.positions[f'pos{i}'] = {'position': i, 'results': []}
        
    def load_data(self):
        """Charge les données"""
        if not os.path.exists(self.rankscore_file):
            raise FileNotFoundError(f"{self.rankscore_file} introuvable")
        
        with open(self.rankscore_file, 'r', encoding='utf-8') as f:
            self.data = json.load(f)
        
        print(f"✓ Chargé {self.data['total_analyses']} analyses")
        return self.data
    
    def categorize_by_positions(self):
        """Répartit les résultats par positions individuelles"""
        for analysis in self.data['analyses']:
            for result in analysis['results']:
                pos = result['position']

                if 1 <= pos <= 10:
                    position_key = f'pos{pos}'
                    self.positions[position_key]['results'].append(result)

        print(f"\n📊 Répartition par position:")
        for pos_key, data in self.positions.items():
            pos_num = data['position']
            count = len(data['results'])
            print(f"  Position {pos_num}: {count} pages")
    
    def analyze_position(self, position_key):
        """Analyse complète d'une position"""
        results = self.positions[position_key]['results']
        
        if not results:
            return None
        
        stats = {
            'nb_pages': len(results),
            'listes': self._analyze_listes(results),
            'tableaux': self._analyze_tableaux(results),
            'images': self._analyze_images(results),
            'liens': self._analyze_liens(results),
            'faq': self._analyze_faq(results),
            'seo': self._analyze_seo(results),
            'structure': self._analyze_structure(results),
            'page_types': self._analyze_page_types(results),
            'semantic': self._analyze_semantic(results),
            'profondeur': self._analyze_profondeur(results),
            'mots_gras': self._analyze_mots_gras(results),
            'structured_data': self._analyze_structured_data(results),
            'performance': self._analyze_performance(results),
            'navigation': self._analyze_navigation(results),
            'meta_social': self._analyze_meta_social(results),
            'quotes': self._analyze_quotes(results),
            'code': self._analyze_code(results),
            'liens_qualite': self._analyze_liens_qualite(results)
        }
        
        return stats
    
    def _analyze_listes(self, results):
        """Analyse des listes"""
        total_listes = 0
        types = []
        positions = []
        items_counts = []
        nested = 0
        pages_avec_listes = 0
        
        for result in results:
            page_has_list = False
            for section in result['dom_structure']['sections']:
                lists = section['content_elements']['lists']
                if lists:
                    page_has_list = True
                    total_listes += len(lists)
                    
                    for lst in lists:
                        types.append(lst['type'])
                        items_counts.append(lst['item_count'])
                        if lst.get('has_nested', False):
                            nested += 1
                        
                        # Position dans l'article
                        section_id = section['section_id']
                        if section_id <= 3:
                            positions.append('haut')
                        elif section_id <= 7:
                            positions.append('milieu')
                        else:
                            positions.append('bas')
            
            if page_has_list:
                pages_avec_listes += 1
        
        return {
            'total': total_listes,
            'pages_avec': pages_avec_listes,
            'pct_pages_avec': (pages_avec_listes / len(results) * 100) if results else 0,
            'moyenne_par_page': total_listes / len(results) if results else 0,
            'types': dict(Counter(types)),
            'positions': dict(Counter(positions)),
            'moyenne_items': mean(items_counts) if items_counts else 0,
            'nested_pct': (nested / total_listes * 100) if total_listes else 0
        }
    
    def _analyze_tableaux(self, results):
        """Analyse des tableaux"""
        total_tableaux = 0
        positions = []
        rows = []
        cols = []
        complex_count = 0
        pages_avec = 0
        
        for result in results:
            page_has_table = False
            for section in result['dom_structure']['sections']:
                tables = section['content_elements']['tables']
                if tables:
                    page_has_table = True
                    total_tableaux += len(tables)
                    
                    for table in tables:
                        rows.append(table['rows'])
                        cols.append(table['columns'])
                        if table.get('is_complex', False):
                            complex_count += 1
                        
                        section_id = section['section_id']
                        if section_id <= 3:
                            positions.append('haut')
                        elif section_id <= 7:
                            positions.append('milieu')
                        else:
                            positions.append('bas')
            
            if page_has_table:
                pages_avec += 1
        
        return {
            'total': total_tableaux,
            'pages_avec': pages_avec,
            'pct_pages_avec': (pages_avec / len(results) * 100) if results else 0,
            'moyenne_par_page': total_tableaux / len(results) if results else 0,
            'positions': dict(Counter(positions)),
            'moyenne_rows': mean(rows) if rows else 0,
            'moyenne_cols': mean(cols) if cols else 0,
            'complex_pct': (complex_count / total_tableaux * 100) if total_tableaux else 0
        }
    
    def _analyze_images(self, results):
        """Analyse des images"""
        total_images = 0
        positions = []
        formats = []
        alt_count = 0
        lazy_count = 0
        pages_avec = 0
        
        for result in results:
            page_has_img = False
            for section in result['dom_structure']['sections']:
                images = section['content_elements']['images']
                if images:
                    page_has_img = True
                    total_images += len(images)
                    
                    for img in images:
                        formats.append(img.get('format', 'unknown'))
                        if img.get('has_alt', False):
                            alt_count += 1
                        if img.get('loading', '') == 'lazy':
                            lazy_count += 1
                        
                        section_id = section['section_id']
                        if section_id <= 3:
                            positions.append('haut')
                        elif section_id <= 7:
                            positions.append('milieu')
                        else:
                            positions.append('bas')
            
            if page_has_img:
                pages_avec += 1
        
        return {
            'total': total_images,
            'pages_avec': pages_avec,
            'pct_pages_avec': (pages_avec / len(results) * 100) if results else 0,
            'moyenne_par_page': total_images / len(results) if results else 0,
            'positions': dict(Counter(positions)),
            'formats': dict(Counter(formats).most_common(5)),
            'alt_pct': (alt_count / total_images * 100) if total_images else 0,
            'lazy_pct': (lazy_count / total_images * 100) if total_images else 0
        }
    
    def _analyze_liens(self, results):
        """Analyse des liens"""
        total_liens = 0
        total_internal = 0
        total_external = 0
        positions = []
        sections_avec_liens = 0
        
        for result in results:
            for section in result['dom_structure']['sections']:
                links = section['content_elements']['links']
                if links.get('total', 0) > 0:
                    sections_avec_liens += 1
                    total_liens += links['total']
                    total_internal += links['internal']
                    total_external += links['external']
                    
                    section_id = section['section_id']
                    if section_id <= 3:
                        positions.append('haut')
                    elif section_id <= 7:
                        positions.append('milieu')
                    else:
                        positions.append('bas')
        
        # Liens totaux depuis metrics (plus fiable)
        total_liens_page = sum(r['metrics']['total_links'] for r in results)
        total_internal_page = sum(r['metrics']['internal_links'] for r in results)
        total_external_page = sum(r['metrics']['external_links'] for r in results)
        
        return {
            'total': total_liens_page,
            'moyenne_par_page': total_liens_page / len(results) if results else 0,
            'internal': total_internal_page,
            'external': total_external_page,
            'internal_pct': (total_internal_page / total_liens_page * 100) if total_liens_page else 0,
            'external_pct': (total_external_page / total_liens_page * 100) if total_liens_page else 0,
            'positions': dict(Counter(positions))
        }
    
    def _analyze_faq(self, results):
        """Analyse des FAQ"""
        pages_avec_faq = 0
        total_questions = 0
        positions = []
        
        for result in results:
            has_faq = result['seo_analysis'].get('has_faq_content', False)
            if has_faq:
                pages_avec_faq += 1
                
                for section in result['dom_structure']['sections']:
                    interactive = section['content_elements']['interactive']
                    if interactive:
                        total_questions += len(interactive)
                        
                        section_id = section['section_id']
                        if section_id <= 3:
                            positions.append('haut')
                        elif section_id <= 7:
                            positions.append('milieu')
                        else:
                            positions.append('bas')
        
        return {
            'pages_avec': pages_avec_faq,
            'pct_pages_avec': (pages_avec_faq / len(results) * 100) if results else 0,
            'moyenne_questions': total_questions / pages_avec_faq if pages_avec_faq else 0,
            'positions': dict(Counter(positions))
        }
    
    def _analyze_seo(self, results):
        """Analyse SEO générale"""
        scores = [r['page_metadata']['seo_score'] for r in results]
        word_counts = [r['page_metadata']['total_word_count'] for r in results]
        mobile = sum(1 for r in results if r['page_metadata']['mobile_optimized'])
        
        return {
            'score_moyen': mean(scores) if scores else 0,
            'word_count_moyen': mean(word_counts) if word_counts else 0,
            'mobile_pct': (mobile / len(results) * 100) if results else 0
        }
    
    def _analyze_structure(self, results):
        """Analyse de la structure"""
        total_sections = []
        h1_counts = []
        paras_per_section = []
        
        for result in results:
            total_sections.append(result['dom_structure']['total_sections'])
            h1_counts.append(result['metrics']['h1_count'])
            
            # Calcul paragraphes/section
            total_paras = sum(
                len(s['content_elements']['paragraphs']) 
                for s in result['dom_structure']['sections']
            )
            nb_sections = result['dom_structure']['total_sections']
            if nb_sections > 0:
                paras_per_section.append(total_paras / nb_sections)
        
        return {
            'moyenne_sections': mean(total_sections) if total_sections else 0,
            'h1_moyen': mean(h1_counts) if h1_counts else 0,
            'paras_per_section': mean(paras_per_section) if paras_per_section else 0
        }
    
    def _analyze_page_types(self, results):
        """Analyse des types de pages"""
        types = []
        confidences = []
        smoothed_count = 0
        
        for result in results:
            page_type = result.get('page_type', {})
            if page_type:
                types.append(page_type.get('type', 'unknown'))
                confidences.append(page_type.get('confidence', 0))
                if page_type.get('smoothed', False):
                    smoothed_count += 1
        
        type_distribution = Counter(types)
        
        return {
            'distribution': dict(type_distribution),
            'dominant': type_distribution.most_common(1)[0][0] if type_distribution else 'unknown',
            'confidence_moyenne': mean(confidences) if confidences else 0,
            'smoothed_count': smoothed_count,
            'smoothed_pct': (smoothed_count / len(results) * 100) if results else 0
        }
    
    def _analyze_semantic(self, results):
        """Analyse des tags sémantiques"""
        semantic_tags = []
        
        for result in results:
            for section in result['dom_structure']['sections']:
                semantic_tag = section.get('semantic_tag', 'div')
                semantic_tags.append(semantic_tag)
        
        tag_counts = Counter(semantic_tags)
        total = sum(tag_counts.values())
        
        return {
            'distribution': dict(tag_counts),
            'article_pct': (tag_counts.get('article', 0) / total * 100) if total else 0,
            'section_pct': (tag_counts.get('section', 0) / total * 100) if total else 0,
            'div_pct': (tag_counts.get('div', 0) / total * 100) if total else 0
        }
    
    def _analyze_profondeur(self, results):
        """Analyse de la profondeur de contenu"""
        depth_levels = []
        
        for result in results:
            for section in result['dom_structure']['sections']:
                depth_levels.append(section.get('depth_level', 0))
        
        depth_distribution = Counter(depth_levels)
        
        return {
            'distribution': dict(depth_distribution),
            'max': max(depth_levels) if depth_levels else 0,
            'moyenne': mean(depth_levels) if depth_levels else 0
        }
    
    def _analyze_mots_gras(self, results):
        """Analyse des mots en gras"""
        total_bold = 0
        pages_avec_bold = 0
        
        for result in results:
            bold_keywords = result['seo_analysis'].get('bolded_keywords', [])
            if bold_keywords:
                total_bold += len(bold_keywords)
                pages_avec_bold += 1
        
        return {
            'total': total_bold,
            'pages_avec': pages_avec_bold,
            'pct_pages_avec': (pages_avec_bold / len(results) * 100) if results else 0,
            'moyenne_par_page': total_bold / len(results) if results else 0
        }
    
    def _analyze_structured_data(self, results):
        """Analyse des données structurées"""
        pages_avec_sd = 0
        schema_types = []
        
        for result in results:
            if result['metrics'].get('structured_data_found', False):
                pages_avec_sd += 1
                
                # Extraire les types de schemas depuis les samples
                samples = result['seo_analysis'].get('structured_data_samples', [])
                for sample in samples:
                    try:
                        data = json.loads(sample)
                        if isinstance(data, dict):
                            if '@type' in data:
                                # Gérer le cas où @type peut être une liste ou une chaîne
                                type_value = data['@type']
                                if isinstance(type_value, list):
                                    # Si c'est une liste, ajouter chaque élément
                                    for t in type_value:
                                        if isinstance(t, str):
                                            schema_types.append(t)
                                elif isinstance(type_value, str):
                                    # Si c'est une chaîne, l'ajouter directement
                                    schema_types.append(type_value)
                            elif '@graph' in data:
                                for item in data['@graph']:
                                    if isinstance(item, dict) and '@type' in item:
                                        # Même logique pour les éléments du graphe
                                        type_value = item['@type']
                                        if isinstance(type_value, list):
                                            for t in type_value:
                                                if isinstance(t, str):
                                                    schema_types.append(t)
                                        elif isinstance(type_value, str):
                                            schema_types.append(type_value)
                    except:
                        continue
        
        return {
            'pages_avec': pages_avec_sd,
            'pct_pages_avec': (pages_avec_sd / len(results) * 100) if results else 0,
            'types': dict(Counter(schema_types).most_common(5))
        }
    
    def _analyze_performance(self, results):
        """Analyse des facteurs de performance"""
        css_external = []
        js_external = []
        css_minified = 0
        js_minified = 0
        preconnect = 0
        lazy_loading = 0
        
        for result in results:
            speed = result['seo_analysis'].get('page_speed_factors', {})
            css_external.append(speed.get('external_css_count', 0))
            js_external.append(speed.get('external_js_count', 0))
            
            if speed.get('has_minified_css', False):
                css_minified += 1
            if speed.get('has_minified_js', False):
                js_minified += 1
            
            cwv = result['seo_analysis'].get('core_web_vitals', {})
            if cwv.get('uses_preconnect', False):
                preconnect += 1
            if cwv.get('lazy_loading_used', False):
                lazy_loading += 1
        
        return {
            'css_external_moyen': mean(css_external) if css_external else 0,
            'js_external_moyen': mean(js_external) if js_external else 0,
            'css_minified_pct': (css_minified / len(results) * 100) if results else 0,
            'js_minified_pct': (js_minified / len(results) * 100) if results else 0,
            'preconnect_pct': (preconnect / len(results) * 100) if results else 0,
            'lazy_loading_pct': (lazy_loading / len(results) * 100) if results else 0
        }
    
    def _analyze_navigation(self, results):
        """Analyse des éléments de navigation"""
        breadcrumbs = 0
        toc = 0
        
        for result in results:
            if result['seo_analysis'].get('has_breadcrumbs', False):
                breadcrumbs += 1
            if result['seo_analysis'].get('has_table_of_contents', False):
                toc += 1
        
        return {
            'breadcrumbs_pct': (breadcrumbs / len(results) * 100) if results else 0,
            'toc_pct': (toc / len(results) * 100) if results else 0
        }
    
    def _analyze_meta_social(self, results):
        """Analyse des meta tags sociaux"""
        og_tags = []
        twitter_tags = []
        
        for result in results:
            meta_social = result['seo_analysis'].get('meta_social', {})
            og_tags.append(meta_social.get('og_tags', 0))
            twitter_tags.append(meta_social.get('twitter_tags', 0))
        
        return {
            'og_moyen': mean(og_tags) if og_tags else 0,
            'twitter_moyen': mean(twitter_tags) if twitter_tags else 0
        }
    
    def _analyze_quotes(self, results):
        """Analyse des citations"""
        total_quotes = 0
        positions = []
        with_author = 0
        
        for result in results:
            for section in result['dom_structure']['sections']:
                quotes = section['content_elements']['quotes']
                if quotes:
                    total_quotes += len(quotes)
                    
                    for quote in quotes:
                        if quote.get('has_author', False):
                            with_author += 1
                        
                        section_id = section['section_id']
                        if section_id <= 3:
                            positions.append('haut')
                        elif section_id <= 7:
                            positions.append('milieu')
                        else:
                            positions.append('bas')
        
        return {
            'total': total_quotes,
            'moyenne_par_page': total_quotes / len(results) if results else 0,
            'with_author_pct': (with_author / total_quotes * 100) if total_quotes else 0,
            'positions': dict(Counter(positions))
        }
    
    def _analyze_code(self, results):
        """Analyse des blocs de code"""
        total_code = 0
        with_syntax = 0
        positions = []
        
        for result in results:
            for section in result['dom_structure']['sections']:
                code_blocks = section['content_elements']['code_blocks']
                if code_blocks:
                    total_code += len(code_blocks)
                    
                    for code in code_blocks:
                        if code.get('has_syntax_highlight', False):
                            with_syntax += 1
                        
                        section_id = section['section_id']
                        if section_id <= 3:
                            positions.append('haut')
                        elif section_id <= 7:
                            positions.append('milieu')
                        else:
                            positions.append('bas')
        
        return {
            'total': total_code,
            'moyenne_par_page': total_code / len(results) if results else 0,
            'with_syntax_pct': (with_syntax / total_code * 100) if total_code else 0,
            'positions': dict(Counter(positions))
        }
    
    def _analyze_liens_qualite(self, results):
        """Analyse de la qualité des liens"""
        dofollow = 0
        nofollow = 0
        sponsored = 0
        ugc = 0
        
        for result in results:
            dofollow += result['seo_analysis'].get('dofollow', 0)
            nofollow += result['seo_analysis'].get('nofollow', 0)
            sponsored += result['seo_analysis'].get('sponsored', 0)
            ugc += result['seo_analysis'].get('ugc', 0)
        
        total = dofollow + nofollow + sponsored + ugc
        
        return {
            'dofollow_pct': (dofollow / total * 100) if total else 0,
            'nofollow_pct': (nofollow / total * 100) if total else 0,
            'sponsored_pct': (sponsored / total * 100) if total else 0,
            'ugc_pct': (ugc / total * 100) if total else 0
        }
    
    def generate_comparative_report(self):
        """Génère le rapport comparatif par POSITIONS INDIVIDUELLES"""
        report = []
        report.append("\n" + "="*200)
        report.append("📊 ANALYSE COMPARATIVE PAR POSITIONS SERP INDIVIDUELLES (1-10)")
        report.append("="*200)

        # Analyse de chaque position
        analyses = {}
        for pos_key in self.positions.keys():
            analyses[pos_key] = self.analyze_position(pos_key)
        
        # ===========================
        # SECTION 1: ÉLÉMENTS DE CONTENU
        # ===========================

        # === LISTES ===
        report.append("\n" + "━"*200)
        report.append("📝 LISTES (UL/OL)")
        report.append("━"*200)

        # En-tête du tableau avec les 10 positions
        header = f"{'Métrique':<35}"
        for i in range(1, 11):
            header += f" {'P' + str(i):<15}"
        report.append(header)
        report.append("-"*200)

        # Métriques des listes
        for metric, label in [
            ('nb_pages', '📄 Nb pages'),
            ('listes.pages_avec', '✓ Pages avec listes'),
            ('listes.pct_pages_avec', '📊 % pages/listes'),
            ('listes.moyenne_par_page', '📈 Listes/page'),
            ('listes.moyenne_items', '🔢 Items/liste'),
            ('listes.nested_pct', '🔗 % imbriquées')
        ]:
            values = self._extract_metric_values_horizontal(analyses, metric)
            report.append(f"{label:<35} {values}")

        # Position et type dominants pour les listes
        report.append("-"*200)
        report.append(self._format_position_line_horizontal('listes', analyses, '📍 Position préférée'))
        report.append(self._format_type_line_horizontal('listes', analyses, '🔸 Type dominant'))
        
        # === TABLEAUX ===
        report.append("\n" + "━"*200)
        report.append("📋 TABLEAUX")
        report.append("━"*200)

        header = f"{'Métrique':<35}"
        for i in range(1, 11):
            header += f" {'P' + str(i):<15}"
        report.append(header)
        report.append("-"*200)

        for metric, label in [
            ('tableaux.pages_avec', '✓ Pages/tableaux'),
            ('tableaux.pct_pages_avec', '📊 % pages/tableaux'),
            ('tableaux.moyenne_par_page', '📈 Tableaux/page'),
            ('tableaux.moyenne_rows', '↕️ Lignes moy'),
            ('tableaux.moyenne_cols', '↔️ Colonnes moy'),
            ('tableaux.complex_pct', '🔬 % complexes')
        ]:
            values = self._extract_metric_values_horizontal(analyses, metric)
            report.append(f"{label:<35} {values}")

        report.append("-"*200)
        report.append(self._format_position_line_horizontal('tableaux', analyses, '📍 Position préférée'))
        
        # === IMAGES ===
        report.append("\n" + "━"*200)
        report.append("🖼️ IMAGES")
        report.append("━"*200)

        header = f"{'Métrique':<35}"
        for i in range(1, 11):
            header += f" {'P' + str(i):<15}"
        report.append(header)
        report.append("-"*200)

        for metric, label in [
            ('images.pages_avec', '✓ Pages/images'),
            ('images.pct_pages_avec', '📊 % pages/images'),
            ('images.moyenne_par_page', '📈 Images/page'),
            ('images.alt_pct', '🏷️ % avec ALT'),
            ('images.lazy_pct', '⚡ % lazy loading')
        ]:
            values = self._extract_metric_values_horizontal(analyses, metric)
            report.append(f"{label:<35} {values}")

        report.append("-"*200)
        report.append(self._format_position_line_horizontal('images', analyses, '📍 Position préférée'))

        # Formats d'images par position
        report.append("🎨 Format dominant:")
        line = f"{'Format dominant':<35}"
        for i in range(1, 11):
            pos_key = f'pos{i}'
            if analyses.get(pos_key) and analyses[pos_key]['images']['formats']:
                formats = analyses[pos_key]['images']['formats']
                if formats:
                    dominant = max(formats.items(), key=lambda x: x[1])
                    line += f"{dominant[0]:<15}"
                else:
                    line += f"{'N/A':<15}"
            else:
                line += f"{'N/A':<15}"
        report.append(line)
        
        # === SEO & STRUCTURE ===
        report.append("\n" + "━"*200)
        report.append("🎯 SEO & STRUCTURE")
        report.append("━"*200)

        header = f"{'Métrique':<35}"
        for i in range(1, 11):
            header += f" {'P' + str(i):<15}"
        report.append(header)
        report.append("-"*200)

        for metric, label in [
            ('seo.score_moyen', '⭐ Score SEO'),
            ('seo.word_count_moyen', '📝 Mots/page'),
            ('seo.mobile_pct', '📱 % mobile'),
            ('structure.moyenne_sections', '📑 Sections/page'),
            ('structure.h1_moyen', '📌 H1/page'),
            ('structure.paras_per_section', '📄 Para/section')
        ]:
            values = self._extract_metric_values_horizontal(analyses, metric)
            report.append(f"{label:<35} {values}")

        # === LIENS ===
        report.append("\n" + "━"*200)
        report.append("🔗 LIENS")
        report.append("━"*200)

        header = f"{'Métrique':<35}"
        for i in range(1, 11):
            header += f" {'P' + str(i):<15}"
        report.append(header)
        report.append("-"*200)

        for metric, label in [
            ('liens.moyenne_par_page', '📈 Liens/page'),
            ('liens.internal_pct', '📊 % internes'),
            ('liens.external_pct', '📊 % externes')
        ]:
            values = self._extract_metric_values_horizontal(analyses, metric)
            report.append(f"{label:<35} {values}")

        # === FAQ ===
        report.append("\n" + "━"*200)
        report.append("❓ FAQ / ACCORDÉONS")
        report.append("━"*200)

        header = f"{'Métrique':<35}"
        for i in range(1, 11):
            header += f" {'P' + str(i):<15}"
        report.append(header)
        report.append("-"*200)

        for metric, label in [
            ('faq.pages_avec', '✓ Pages/FAQ'),
            ('faq.pct_pages_avec', '📊 % pages/FAQ'),
            ('faq.moyenne_questions', '🔢 Questions/FAQ')
        ]:
            values = self._extract_metric_values_horizontal(analyses, metric)
            report.append(f"{label:<35} {values}")

        # === DONNÉES STRUCTURÉES ===
        report.append("\n" + "━"*200)
        report.append("📦 DONNÉES STRUCTURÉES (JSON-LD)")
        report.append("━"*200)

        header = f"{'Métrique':<35}"
        for i in range(1, 11):
            header += f" {'P' + str(i):<15}"
        report.append(header)
        report.append("-"*200)

        for metric, label in [
            ('structured_data.pages_avec', '✓ Pages/JSON-LD'),
            ('structured_data.pct_pages_avec', '📊 % pages/JSON-LD')
        ]:
            values = self._extract_metric_values_horizontal(analyses, metric)
            report.append(f"{label:<35} {values}")

        # === PERFORMANCE ===
        report.append("\n" + "━"*200)
        report.append("⚡ PERFORMANCE TECHNIQUE")
        report.append("━"*200)

        header = f"{'Métrique':<35}"
        for i in range(1, 11):
            header += f" {'P' + str(i):<15}"
        report.append(header)
        report.append("-"*200)

        for metric, label in [
            ('performance.css_minified_pct', '✅ % CSS minifiés'),
            ('performance.js_minified_pct', '✅ % JS minifiés'),
            ('performance.lazy_loading_pct', '⚡ % lazy loading')
        ]:
            values = self._extract_metric_values_horizontal(analyses, metric)
            report.append(f"{label:<35} {values}")

        # === NAVIGATION ===
        report.append("\n" + "━"*200)
        report.append("🧭 NAVIGATION & UX")
        report.append("━"*200)

        header = f"{'Métrique':<35}"
        for i in range(1, 11):
            header += f" {'P' + str(i):<15}"
        report.append(header)
        report.append("-"*200)

        for metric, label in [
            ('navigation.breadcrumbs_pct', '🍞 % breadcrumbs'),
            ('navigation.toc_pct', '📑 % table matières')
        ]:
            values = self._extract_metric_values_horizontal(analyses, metric)
            report.append(f"{label:<35} {values}")

        # === SYNTHÈSE MACRO ===
        report.append("\n" + "="*200)
        report.append("📊 SYNTHÈSE MACRO - TENDANCES GRANULAIRES")
        report.append("="*200)

        # Identification des positions dominantes pour chaque métrique
        report.append("\n🏆 POSITIONS DOMINANTES PAR MÉTRIQUE:")
        key_metrics = [
            ('seo.score_moyen', 'Score SEO'),
            ('images.moyenne_par_page', 'Densité images'),
            ('listes.moyenne_par_page', 'Densité listes'),
            ('tableaux.pct_pages_avec', 'Présence tableaux'),
            ('faq.pct_pages_avec', 'Présence FAQ'),
            ('liens.moyenne_par_page', 'Densité liens'),
            ('performance.lazy_loading_pct', 'Lazy loading')
        ]

        for metric, label in key_metrics:
            best_pos = self._find_best_position(analyses, metric)
            if best_pos:
                report.append(f"  • {label:<20}: Position {best_pos['position']} ({best_pos['value']:.1f})")

        report.append("\n🎯 RECOMMANDATIONS POSITION-SPECIFIC:")
        report.append("  • Analyser spécifiquement les pratiques des positions 1-3")
        report.append("  • Identifier les écarts par rapport aux positions 4-10")
        report.append("  • Optimiser selon les patterns dominants observés")

        report.append("\n" + "="*200)
        report.append(f"📅 Rapport généré le: {self._get_timestamp()}")
        report.append("="*200)
        
        return "\n".join(report)
    
    def _extract_metric_values(self, analyses, metric):
        """Extrait les valeurs d'une métrique pour les 3 tranches (ancien système)"""
        values = []
        for tranche in ['top1-3', 'top3-5', 'top5-10']:
            if analyses[tranche]:
                keys = metric.split('.')
                val = analyses[tranche]
                for k in keys:
                    val = val.get(k, 0) if isinstance(val, dict) else val

                # Formatage selon le type
                if isinstance(val, str):
                    values.append(f"{val}")
                elif 'pct' in metric or 'confidence' in metric:
                    values.append(f"{val:.1f}%")
                elif 'moyenne' in metric or 'moyen' in metric or 'per' in metric:
                    values.append(f"{val:.1f}")
                elif isinstance(val, float):
                    values.append(f"{val:.2f}")
                else:
                    values.append(f"{val}")
            else:
                values.append("N/A")

        # Ajuster la longueur pour alignement
        return [f"{v:<23}" for v in values]

    def _extract_metric_values_horizontal(self, analyses, metric):
        """Extrait les valeurs d'une métrique pour les 10 positions"""
        values = []
        for i in range(1, 11):
            pos_key = f'pos{i}'
            if analyses.get(pos_key):
                keys = metric.split('.')
                val = analyses[pos_key]
                for k in keys:
                    val = val.get(k, 0) if isinstance(val, dict) else val

                # Formatage selon le type
                if isinstance(val, str):
                    formatted = f"{val}"
                elif 'pct' in metric or 'confidence' in metric:
                    formatted = f"{val:.1f}%"
                elif 'moyenne' in metric or 'moyen' in metric or 'per' in metric:
                    formatted = f"{val:.1f}"
                elif isinstance(val, float):
                    formatted = f"{val:.1f}"
                else:
                    formatted = f"{val}"

                values.append(f"{formatted:<15}")
            else:
                values.append(f"{'N/A':<15}")

        return "".join(values)
    
    def _format_position_line(self, element_key, analyses, label):
        """Formate une ligne de position préférée (ancien système)"""
        line = f"{label:<50}"
        for tranche in ['top1-3', 'top3-5', 'top5-10']:
            if analyses[tranche] and analyses[tranche][element_key].get('positions'):
                positions = analyses[tranche][element_key]['positions']
                if positions:
                    pos = max(positions.items(), key=lambda x: x[1])
                    total = sum(positions.values())
                    pct = (pos[1] / total * 100) if total > 0 else 0
                    line += f"{pos[0]} ({pct:.0f}%)"
                    line += " "*(23 - len(f"{pos[0]} ({pct:.0f}%)"))
                else:
                    line += f"{'N/A':<23}"
            else:
                line += f"{'N/A':<23}"
        return line

    def _format_position_line_horizontal(self, element_key, analyses, label):
        """Formate une ligne de position préférée pour les 10 positions"""
        line = f"{label:<35}"
        for i in range(1, 11):
            pos_key = f'pos{i}'
            if analyses.get(pos_key) and analyses[pos_key][element_key].get('positions'):
                positions = analyses[pos_key][element_key]['positions']
                if positions:
                    pos = max(positions.items(), key=lambda x: x[1])
                    total = sum(positions.values())
                    pct = (pos[1] / total * 100) if total > 0 else 0
                    formatted = f"{pos[0]}({pct:.0f}%)"
                    line += f"{formatted:<15}"
                else:
                    line += f"{'N/A':<15}"
            else:
                line += f"{'N/A':<15}"
        return line

    def _format_type_line(self, element_key, analyses, label):
        """Formate une ligne de type dominant (ancien système)"""
        line = f"{label:<50}"
        for tranche in ['top1-3', 'top3-5', 'top5-10']:
            if analyses[tranche] and analyses[tranche][element_key].get('types'):
                types = analyses[tranche][element_key]['types']
                if types:
                    typ = max(types.items(), key=lambda x: x[1])
                    line += f"{typ[0]} ({typ[1]})"
                    line += " "*(23 - len(f"{typ[0]} ({typ[1]})"))
                else:
                    line += f"{'N/A':<23}"
            else:
                line += f"{'N/A':<23}"
        return line

    def _format_type_line_horizontal(self, element_key, analyses, label):
        """Formate une ligne de type dominant pour les 10 positions"""
        line = f"{label:<35}"
        for i in range(1, 11):
            pos_key = f'pos{i}'
            if analyses.get(pos_key) and analyses[pos_key][element_key].get('types'):
                types = analyses[pos_key][element_key]['types']
                if types:
                    typ = max(types.items(), key=lambda x: x[1])
                    formatted = f"{typ[0]}({typ[1]})"
                    line += f"{formatted:<15}"
                else:
                    line += f"{'N/A':<15}"
            else:
                line += f"{'N/A':<15}"
        return line
    
    def _generate_differences(self, analyses):
        """Génère automatiquement la liste des différences notables"""
        diffs = []
        threshold_pct = 15  # Différence de 15% = notable
        threshold_abs = 10  # Différence absolue de 10 unités = notable
        
        comparisons = [
            ('listes.nested_pct', 'Listes imbriquées', threshold_pct, '%'),
            ('images.moyenne_par_page', 'Images/page', 5, 'unités'),
            ('liens.moyenne_par_page', 'Liens/page', 30, 'unités'),
            ('seo.word_count_moyen', 'Mots/page', 200, 'mots'),
            ('tableaux.pct_pages_avec', 'Pages avec tableaux', threshold_pct, '%'),
            ('performance.lazy_loading_pct', 'Lazy loading', threshold_pct, '%'),
            ('navigation.breadcrumbs_pct', 'Breadcrumbs', threshold_pct, '%'),
            ('mots_gras.moyenne_par_page', 'Mots en gras/page', 5, 'unités'),
            ('structure.moyenne_sections', 'Sections/page', 5, 'sections')
        ]
        
        for metric, label, threshold, unit in comparisons:
            keys = metric.split('.')
            val_1_3 = analyses['top1-3']
            val_5_10 = analyses['top5-10']
            
            for k in keys:
                val_1_3 = val_1_3.get(k, 0) if isinstance(val_1_3, dict) else val_1_3
                val_5_10 = val_5_10.get(k, 0) if isinstance(val_5_10, dict) else val_5_10
            
            if abs(val_1_3 - val_5_10) >= threshold:
                if unit == '%':
                    diffs.append(f"  • {label}: {val_1_3:.1f}% (top1-3) vs {val_5_10:.1f}% (top5-10)")
                elif unit == 'mots':
                    diffs.append(f"  • {label}: {val_1_3:.0f} (top1-3) vs {val_5_10:.0f} (top5-10)")
                else:
                    diffs.append(f"  • {label}: {val_1_3:.1f} (top1-3) vs {val_5_10:.1f} (top5-10)")
        
        return diffs
    
    def _find_best_position(self, analyses, metric):
        """Trouve la position avec la meilleure valeur pour une métrique donnée"""
        best_value = -1
        best_position = None

        for i in range(1, 11):
            pos_key = f'pos{i}'
            if analyses.get(pos_key):
                keys = metric.split('.')
                val = analyses[pos_key]
                for k in keys:
                    val = val.get(k, 0) if isinstance(val, dict) else val

                if isinstance(val, (int, float)) and val > best_value:
                    best_value = val
                    best_position = i

        if best_position:
            return {'position': best_position, 'value': best_value}
        return None

    def _get_timestamp(self):
        """Retourne le timestamp actuel"""
        from datetime import datetime
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    def save_report(self, filename="dom_comparative_report_complet.txt"):
        """Sauvegarde le rapport"""
        report = self.generate_comparative_report()
        
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(report)
        
        print(f"\n✓ Rapport comparatif complet sauvegardé: {filename}")
        return filename


def main():
    comparator = DomTrendComparator("rankscore_dom.json")

    try:
        # Chargement
        comparator.load_data()

        # Catégorisation par positions individuelles
        comparator.categorize_by_positions()

        # Génération rapport
        print("\n🔄 Génération du rapport par positions individuelles en cours...")
        report = comparator.generate_comparative_report()
        print(report)

        # Sauvegarde
        comparator.save_report("dom_comparative_report_positions.txt")

        print("\n✅ Analyse terminée avec succès!")
        print("📄 Le rapport détaillé a été sauvegardé dans: dom_comparative_report_positions.txt")

    except FileNotFoundError as e:
        print(f"❌ Erreur: {e}")
    except Exception as e:
        print(f"❌ Erreur inattendue: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()