import json
import os
from collections import defaultdict, Counter
from statistics import mean, median

class DomTrendComparator:
    """Analyse comparative complète des pratiques DOM par tranches SERP"""

    def __init__(self, rankscore_file="rankscore_dom.json"):
        self.rankscore_file = rankscore_file
        self.data = None
        self.analyses_data = []  # Stocker chaque analyse séparément
        
    def load_data(self):
        """Charge les données et prépare les analyses séparément"""
        if not os.path.exists(self.rankscore_file):
            raise FileNotFoundError(f"{self.rankscore_file} introuvable")

        with open(self.rankscore_file, 'r', encoding='utf-8') as f:
            self.data = json.load(f)

        # Préparer chaque analyse séparément
        for analysis in self.data['analyses']:
            # Adaptation pour les deux formats
            query_obj = analysis.get('query', {})
            if isinstance(query_obj, dict):
                query = query_obj.get('text', 'unknown')
            else:
                query = str(query_obj)
            analyzed_at = analysis.get('analyzed_at', analysis.get('analysis_timestamp', ''))
            total_results = analysis.get('total_results_analyzed', len(analysis.get('results', [])))
            results = analysis.get('results', [])

            # Adapter les résultats au format attendu par serprapport
            adapted_results = []
            for result in results:
                adapted_result = self._adapt_result_format(result)
                if adapted_result:
                    adapted_results.append(adapted_result)

            analysis_info = {
                'query': query,
                'analyzed_at': analyzed_at,
                'total_results_analyzed': total_results,
                'results': adapted_results,
                'positions': {}  # Structure par positions réelles uniquement
            }

            # Extraire les positions réellement présentes
            for result in adapted_results:
                pos = result['serp_position']
                pos_key = f'pos{pos}'
                if pos_key not in analysis_info['positions']:
                    analysis_info['positions'][pos_key] = {'position': pos, 'results': []}
                analysis_info['positions'][pos_key]['results'].append(result)

            self.analyses_data.append(analysis_info)

        print(f"✓ Chargé {self.data['total_analyses']} analyses")
        for i, analysis in enumerate(self.analyses_data):
            positions_list = sorted([analysis['positions'][k]['position'] for k in analysis['positions'].keys()])
            print(f"  Analyse {i+1}: '{analysis['query'][:50]}...' - Positions: {positions_list}")

        return self.data

    def _adapt_result_format(self, result):
        """Adapte un résultat du format serptestv2 vers le format serprapport"""
        try:
            # Format serptestv2 : dom_structure contient les sections
            if 'dom_structure' in result and 'sections' in result['dom_structure']:
                # Nouveau format serptestv2
                adapted_result = {
                    'serp_position': result.get('position', 1),
                    'url': result.get('url', ''),
                    'serp_title': result.get('title', ''),
                    'serp_snippet': result.get('snippet', ''),
                    'sections': self._transform_sections(result['dom_structure']['sections']),
                    'dom_structure': result.get('dom_structure', {}),
                    'seo_factors': self._extract_seo_factors(result),
                    'seo_score': result.get('page_metadata', {}).get('seo_score', 0),
                    'technical_elements': result.get('seo_analysis', {}),
                    'analyzed_at': result.get('analysis_timestamp', ''),
                    'page_type': result.get('page_type', {})
                }

                # Adapter les données structurées
                structured_data_samples = result.get('seo_analysis', {}).get('structured_data_samples', [])
                adapted_result['structured_data'] = {
                    'count': len(structured_data_samples),
                    'schema_types': self._extract_schema_types(structured_data_samples)
                }

                return adapted_result

            # Format existant serprapport - retourner tel quel
            elif 'sections' in result:
                return result

            else:
                print(f"⚠️ Format de résultat non reconnu: {list(result.keys())}")
                return None

        except Exception as e:
            print(f"❌ Erreur adaptation résultat: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _transform_sections(self, dom_sections):
        """Transforme les sections du format serptestv2 vers le format serprapport"""
        transformed_sections = []

        for section in dom_sections:
            content_elements = section.get('content_elements', {})

            # Transformer la section
            transformed_section = {
                'section_id': section.get('section_id', 1),
                'section_type': section.get('section_type', 'content'),
                'depth_level': section.get('depth_level', 0),
                'semantic_tag': section.get('semantic_tag', 'div'),
                'tag': section.get('semantic_tag', 'div'),
                'is_heading': section.get('semantic_tag', '').startswith('h'),
                'level': self._extract_heading_level(section.get('semantic_tag', '')),
                'word_count': self._count_words_in_section(content_elements),
                'text': self._extract_text_from_section(content_elements),
                'headings': content_elements.get('headings', []),
                'paragraphs': content_elements.get('paragraphs', []),
                'images': self._transform_images(content_elements.get('images', [])),
                'links': self._transform_links(content_elements.get('links', [])),
                'lists': self._transform_lists(content_elements.get('lists', [])),
                'tables': self._transform_tables(content_elements.get('tables', [])),
                'snippets': content_elements.get('code_blocks', []),
                'bold_keywords': self._extract_bold_keywords(content_elements),
                'faq': self._detect_faq_content(content_elements)
            }

            transformed_sections.append(transformed_section)

        return transformed_sections

    def _extract_heading_level(self, tag):
        """Extrait le niveau d'un heading (h1=1, h2=2, etc.)"""
        if tag and tag.startswith('h') and len(tag) == 2 and tag[1].isdigit():
            return int(tag[1])
        return 0

    def _count_words_in_section(self, content_elements):
        """Compte les mots dans une section"""
        word_count = 0

        # Compter les mots dans les paragraphes
        for para in content_elements.get('paragraphs', []):
            word_count += para.get('word_count', 0)

        # Compter les mots dans les headings
        for heading in content_elements.get('headings', []):
            text = heading.get('text', '')
            word_count += len(text.split())

        return word_count

    def _extract_text_from_section(self, content_elements):
        """Extrait le texte principal d'une section"""
        texts = []

        # Texte des headings
        for heading in content_elements.get('headings', []):
            texts.append(heading.get('text', ''))

        # Texte des paragraphes
        for para in content_elements.get('paragraphs', []):
            texts.append(para.get('text', ''))

        return ' '.join(texts)

    def _transform_images(self, images):
        """Transforme les images vers le format attendu"""
        transformed = []
        for img in images:
            transformed.append({
                'src': img.get('src', ''),
                'alt': img.get('alt', ''),
                'has_alt': bool(img.get('alt', '')),
                'loading': img.get('loading', ''),
                'element_id': img.get('element_id', '')
            })
        return transformed

    def _transform_links(self, links):
        """Transforme les liens vers le format attendu"""
        transformed = []
        for link in links:
            # Gérer le cas où link est une chaîne au lieu d'un objet
            if isinstance(link, str):
                transformed.append({
                    'href': link,
                    'text': link,
                    'type': 'internal',
                    'is_external': link.startswith('http') and not any(domain in link for domain in ['localhost', '127.0.0.1']),
                    'rel': [],
                    'title': '',
                    'aria_label': '',
                    'element_id': ''
                })
            elif isinstance(link, dict):
                transformed.append({
                    'href': link.get('href', ''),
                    'text': link.get('text', ''),
                    'type': link.get('type', 'internal'),
                    'is_external': link.get('type') == 'external',
                    'rel': link.get('rel', []),
                    'title': link.get('title', ''),
                    'aria_label': link.get('aria_label', ''),
                    'element_id': link.get('element_id', '')
                })
        return transformed

    def _transform_lists(self, lists):
        """Transforme les listes vers le format attendu"""
        transformed = []
        for lst in lists:
            transformed.append({
                'type': lst.get('type', 'ul'),
                'item_count': lst.get('item_count', 0),
                'is_nested': lst.get('is_nested', False),
                'items': lst.get('items', []),
                'element_id': lst.get('element_id', '')
            })
        return transformed

    def _transform_tables(self, tables):
        """Transforme les tableaux vers le format attendu"""
        transformed = []
        for table in tables:
            transformed.append({
                'row_count': table.get('rows', 0),
                'column_count': table.get('columns', 0),
                'has_headers': table.get('has_headers', False),
                'has_caption': table.get('has_caption', False),
                'element_id': table.get('element_id', '')
            })
        return transformed

    def _extract_bold_keywords(self, content_elements):
        """Extrait les mots en gras d'une section"""
        bold_keywords = []

        # Chercher dans les paragraphes
        for para in content_elements.get('paragraphs', []):
            if para.get('has_bold', False):
                # Simulation de l'extraction - à adapter selon la structure réelle
                text = para.get('text', '')
                # Ici on pourrait parser le HTML pour extraire les vrais mots en gras
                bold_keywords.extend(['mot_gras_exemple'])  # Placeholder

        return bold_keywords

    def _detect_faq_content(self, content_elements):
        """Détecte si la section contient du contenu FAQ"""
        # Chercher des patterns FAQ dans les accordéons ou listes
        accordions = content_elements.get('accordions', [])

        if accordions:
            return {
                'is_faq': True,
                'qa_count': len(accordions)
            }

        return {
            'is_faq': False,
            'qa_count': 0
        }

    def _extract_seo_factors(self, result):
        """Extrait les facteurs SEO depuis le format serptestv2"""
        seo_factors = {}

        # H1 count depuis metrics
        metrics = result.get('metrics', {})
        seo_factors['h1_count'] = metrics.get('h1_count', 0)

        # Breadcrumbs et TOC depuis seo_analysis
        seo_analysis = result.get('seo_analysis', {})
        seo_factors['has_breadcrumb'] = 'breadcrumb' in str(seo_analysis.get('structured_data_samples', [])).lower()
        seo_factors['has_toc'] = seo_analysis.get('additional_factors', {}).get('has_table_of_contents', False)

        return seo_factors

    def _extract_schema_types(self, structured_data_samples):
        """Extrait les types de schéma depuis les échantillons"""
        schema_types = []

        for sample in structured_data_samples:
            try:
                if '"@type"' in sample:
                    import re
                    types = re.findall(r'"@type":\s*"([^"]+)"', sample)
                    schema_types.extend(types)
            except:
                continue

        return list(set(schema_types))  # Dédupliquer

    def analyze_single_analysis(self, analysis_index):
        """Analyse une seule analyse par ses positions réelles"""
        if analysis_index >= len(self.analyses_data):
            raise IndexError(f"Analyse {analysis_index} n'existe pas")

        analysis = self.analyses_data[analysis_index]
        positions = analysis['positions']

        print(f"\n📊 Analyse {analysis_index + 1}: '{analysis['query']}'")
        print(f"📊 Répartition par position:")
        for pos_key in sorted(positions.keys(), key=lambda x: int(x[3:])):
            pos_num = positions[pos_key]['position']
            count = len(positions[pos_key]['results'])
            print(f"  Position {pos_num}: {count} pages")

        return analysis
    
    def analyze_position_for_analysis(self, analysis_positions, position_key):
        """Analyse complète d'une position pour une analyse donnée"""
        if position_key not in analysis_positions:
            return None

        results = analysis_positions[position_key]['results']

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
        pages_avec_listes = 0
        
        for result in results:
            page_has_list = False
            
            # Parcourir les sections (nouveau format)
            for section in result['sections']:
                lists = section.get('lists', [])
                if lists:
                    page_has_list = True
                    total_listes += len(lists)
                    
                    for lst in lists:
                        types.append(lst['type'])
                        items_counts.append(lst['item_count'])
                        
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
            'moyenne_items': mean(items_counts) if items_counts else 0
        }
    
    def _analyze_tableaux(self, results):
        """Analyse des tableaux"""
        total_tableaux = 0
        positions = []
        rows = []
        cols = []
        pages_avec = 0
        
        for result in results:
            page_has_table = False
            
            for section in result['sections']:
                tables = section.get('tables', [])
                if tables:
                    page_has_table = True
                    total_tableaux += len(tables)
                    
                    for table in tables:
                        rows.append(table['row_count'])
                        cols.append(table['column_count'])
                        
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
            'moyenne_cols': mean(cols) if cols else 0
        }
    
    def _analyze_images(self, results):
        """Analyse des images"""
        total_images = 0
        positions = []
        alt_count = 0
        lazy_count = 0
        pages_avec = 0
        
        for result in results:
            page_has_img = False
            
            for section in result['sections']:
                images = section.get('images', [])
                if images:
                    page_has_img = True
                    total_images += len(images)
                    
                    for img in images:
                        if img.get('alt', ''):
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
            'alt_pct': (alt_count / total_images * 100) if total_images else 0,
            'lazy_pct': (lazy_count / total_images * 100) if total_images else 0
        }
    
    def _analyze_liens(self, results):
        """Analyse des liens"""
        total_liens = 0
        total_internal = 0
        total_external = 0
        positions = []
        
        for result in results:
            for section in result['sections']:
                links = section.get('links', [])
                if links:
                    total_liens += len(links)
                    
                    for link in links:
                        if link['is_external']:
                            total_external += 1
                        else:
                            total_internal += 1
                    
                    section_id = section['section_id']
                    if section_id <= 3:
                        positions.append('haut')
                    elif section_id <= 7:
                        positions.append('milieu')
                    else:
                        positions.append('bas')
        
        return {
            'total': total_liens,
            'moyenne_par_page': total_liens / len(results) if results else 0,
            'internal': total_internal,
            'external': total_external,
            'internal_pct': (total_internal / total_liens * 100) if total_liens else 0,
            'external_pct': (total_external / total_liens * 100) if total_liens else 0,
            'positions': dict(Counter(positions))
        }
    
    def _analyze_faq(self, results):
        """Analyse des FAQ"""
        pages_avec_faq = 0
        total_questions = 0
        positions = []
        
        for result in results:
            has_faq = False
            
            for section in result['sections']:
                faq = section.get('faq', {})
                if faq.get('is_faq', False):
                    has_faq = True
                    qa_count = faq.get('qa_count', 0)
                    total_questions += qa_count
                    
                    section_id = section['section_id']
                    if section_id <= 3:
                        positions.append('haut')
                    elif section_id <= 7:
                        positions.append('milieu')
                    else:
                        positions.append('bas')
            
            if has_faq:
                pages_avec_faq += 1
        
        return {
            'pages_avec': pages_avec_faq,
            'pct_pages_avec': (pages_avec_faq / len(results) * 100) if results else 0,
            'moyenne_questions': total_questions / pages_avec_faq if pages_avec_faq else 0,
            'positions': dict(Counter(positions))
        }
    
    def _analyze_seo(self, results):
        """Analyse SEO générale"""
        scores = []
        word_counts = []

        for r in results:
            # Adapter selon le format du score SEO
            if isinstance(r.get('seo_score'), dict):
                # Format avec 'score' dans un dict
                score = r['seo_score'].get('score', 0)
            else:
                # Score direct (nouveau format serptestv2)
                score = r.get('seo_score', 0)
            scores.append(score)

            # Récupérer le nombre de mots - essayer plusieurs sources
            word_count = 0

            # D'abord essayer dom_structure
            if 'dom_structure' in r:
                word_count = r['dom_structure'].get('total_words', 0)

            # Sinon essayer de compter depuis les sections
            if word_count == 0 and 'sections' in r:
                word_count = sum(section.get('word_count', 0) for section in r['sections'])

            word_counts.append(word_count)

        return {
            'score_moyen': mean(scores) if scores else 0,
            'word_count_moyen': mean(word_counts) if word_counts else 0
        }
    
    def _analyze_structure(self, results):
        """Analyse de la structure"""
        total_sections = []
        h1_counts = []
        avg_para_lengths = []

        for result in results:
            # Total sections - adapter selon le format
            dom_struct = result.get('dom_structure', {})
            if 'total_sections' in dom_struct:
                total_sections.append(dom_struct['total_sections'])
            else:
                # Compter depuis les sections directement pour le nouveau format
                sections_count = len(result.get('sections', []))
                total_sections.append(sections_count)

            # H1 count
            h1_count = result.get('seo_factors', {}).get('h1_count', 0)
            h1_counts.append(h1_count)

            # Average paragraph length
            avg_para_length = dom_struct.get('average_paragraph_length', 0)
            if avg_para_length == 0:
                # Calculer depuis les sections pour le nouveau format
                p_sections = [s for s in result.get('sections', []) if s.get('tag') == 'p']
                if p_sections:
                    total_words = sum(s.get('word_count', 0) for s in p_sections)
                    avg_para_length = total_words / len(p_sections)
            avg_para_lengths.append(avg_para_length)

        return {
            'moyenne_sections': mean(total_sections) if total_sections else 0,
            'h1_moyen': mean(h1_counts) if h1_counts else 0,
            'avg_paragraph_length': mean(avg_para_lengths) if avg_para_lengths else 0
        }
    
    def _analyze_page_types(self, results):
        """Analyse des types de pages"""
        types = []
        confidences = []

        for result in results:
            page_type = result.get('page_type', {})
            if page_type:
                # Nouveau format serptestv2: le type est directement dans 'type'
                page_type_value = page_type.get('type', page_type.get('page_type', 'unknown'))
                types.append(page_type_value)
                confidences.append(page_type.get('confidence', 0))

        type_distribution = Counter(types)

        return {
            'distribution': dict(type_distribution),
            'dominant': type_distribution.most_common(1)[0][0] if type_distribution else 'unknown',
            'confidence_moyenne': mean(confidences) if confidences else 0
        }
    
    def _analyze_semantic(self, results):
        """Analyse des tags sémantiques (heading levels)"""
        heading_levels = []

        for result in results:
            for section in result['sections']:
                # Adapter selon le format
                level = section.get('level', 0)
                if level == 0 and section.get('is_heading', False):
                    # Extraire le niveau depuis le tag pour le nouveau format
                    tag = section.get('tag', '')
                    if tag.startswith('h') and tag[1:].isdigit():
                        level = int(tag[1:])

                if level > 0:  # C'est un heading
                    heading_levels.append(f"h{level}")

        level_counts = Counter(heading_levels)
        total = sum(level_counts.values())

        return {
            'distribution': dict(level_counts),
            'h1_pct': (level_counts.get('h1', 0) / total * 100) if total else 0,
            'h2_pct': (level_counts.get('h2', 0) / total * 100) if total else 0,
            'h3_pct': (level_counts.get('h3', 0) / total * 100) if total else 0
        }
    
    def _analyze_profondeur(self, results):
        """Analyse de la profondeur de contenu"""
        max_levels = []

        for result in results:
            levels = []
            for s in result['sections']:
                # Adapter selon le format
                level = s.get('level', 0)
                if level == 0 and s.get('is_heading', False):
                    # Extraire le niveau depuis le tag pour le nouveau format
                    tag = s.get('tag', '')
                    if tag.startswith('h') and tag[1:].isdigit():
                        level = int(tag[1:])
                if level > 0:
                    levels.append(level)

            if levels:
                max_levels.append(max(levels))

        return {
            'max_moyen': mean(max_levels) if max_levels else 0,
            'max_absolu': max(max_levels) if max_levels else 0
        }
    
    def _analyze_mots_gras(self, results):
        """Analyse des mots en gras"""
        total_bold = 0
        pages_avec_bold = 0
        
        for result in results:
            page_has_bold = False
            
            for section in result['sections']:
                bold_keywords = section.get('bold_keywords', [])
                if bold_keywords:
                    total_bold += len(bold_keywords)
                    page_has_bold = True
            
            if page_has_bold:
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
            structured_data = result.get('structured_data', {})
            if structured_data.get('count', 0) > 0:
                pages_avec_sd += 1
                schema_types.extend(structured_data.get('schema_types', []))
        
        return {
            'pages_avec': pages_avec_sd,
            'pct_pages_avec': (pages_avec_sd / len(results) * 100) if results else 0,
            'types': dict(Counter(schema_types).most_common(5))
        }
    
    def _analyze_performance(self, results):
        """Analyse des facteurs de performance (basique car pas de données détaillées)"""
        lazy_loading = 0
        
        for result in results:
            for section in result['sections']:
                images = section.get('images', [])
                for img in images:
                    if img.get('loading', '') == 'lazy':
                        lazy_loading += 1
                        break  # Une seule fois par page
        
        return {
            'lazy_loading_pct': (lazy_loading / len(results) * 100) if results else 0
        }
    
    def _analyze_navigation(self, results):
        """Analyse des éléments de navigation"""
        pages_avec_breadcrumb = 0
        pages_avec_toc = 0
        
        for result in results:
            has_breadcrumb = result['seo_factors'].get('has_breadcrumb', False)
            has_toc = result['seo_factors'].get('has_toc', False)
            
            if has_breadcrumb:
                pages_avec_breadcrumb += 1
            if has_toc:
                pages_avec_toc += 1
        
        return {
            'breadcrumb_pct': (pages_avec_breadcrumb / len(results) * 100) if results else 0,
            'toc_pct': (pages_avec_toc / len(results) * 100) if results else 0
        }
    
    def _analyze_meta_social(self, results):
        """Analyse des métadonnées sociales (non disponible dans le nouveau format)"""
        return {
            'og_present': 0,
            'twitter_present': 0,
            'note': 'Données non disponibles dans le nouveau format'
        }
    
    def _analyze_quotes(self, results):
        """Analyse des citations (non disponible dans le nouveau format)"""
        return {
            'total': 0,
            'pages_avec': 0,
            'note': 'Données non disponibles dans le nouveau format'
        }
    
    def _analyze_code(self, results):
        """Analyse des snippets de code"""
        total_snippets = 0
        pages_avec_code = 0
        
        for result in results:
            page_has_code = False
            
            for section in result['sections']:
                snippets = section.get('snippets', [])
                if snippets:
                    total_snippets += len(snippets)
                    page_has_code = True
            
            if page_has_code:
                pages_avec_code += 1
        
        return {
            'total': total_snippets,
            'pages_avec': pages_avec_code,
            'pct_pages_avec': (pages_avec_code / len(results) * 100) if results else 0,
            'moyenne_par_page': total_snippets / len(results) if results else 0
        }
    
    def _analyze_liens_qualite(self, results):
        """Analyse de la qualité des liens"""
        total_avec_title = 0
        total_avec_aria = 0
        total_nofollow = 0
        total_liens = 0
        
        for result in results:
            for section in result['sections']:
                links = section.get('links', [])
                for link in links:
                    total_liens += 1
                    if link.get('title', ''):
                        total_avec_title += 1
                    if link.get('aria_label', ''):
                        total_avec_aria += 1
                    if 'nofollow' in link.get('rel', []):
                        total_nofollow += 1
        
        return {
            'title_pct': (total_avec_title / total_liens * 100) if total_liens else 0,
            'aria_pct': (total_avec_aria / total_liens * 100) if total_liens else 0,
            'nofollow_pct': (total_nofollow / total_liens * 100) if total_liens else 0
        }
    
    def generate_comparative_report_for_analysis(self, analysis_index):
        """Génère le rapport comparatif pour UNE SEULE analyse avec ses positions réelles"""
        if analysis_index >= len(self.analyses_data):
            raise IndexError(f"Analyse {analysis_index} n'existe pas")

        analysis = self.analyses_data[analysis_index]
        query_text = analysis['query']
        positions = analysis['positions']

        # Obtenir les positions réelles triées
        real_positions = sorted(positions.keys(), key=lambda x: int(x[3:]))
        positions_numbers = [int(pos[3:]) for pos in real_positions]

        report = []
        report.append("\n" + "="*200)
        report.append(f"📊 ANALYSE COMPARATIVE - REQUÊTE: '{query_text}'")
        report.append(f"📊 POSITIONS ANALYSÉES: {positions_numbers}")
        report.append("="*200)

        # Analyse de chaque position réelle uniquement
        analyses = {}
        for pos_key in real_positions:
            analyses[pos_key] = self.analyze_position_for_analysis(positions, pos_key)
        
        # ===========================
        # SECTION 1: ÉLÉMENTS DE CONTENU
        # ===========================

        # === LISTES ===
        report.append("\n" + "━"*200)
        report.append("📝 LISTES (UL/OL)")
        report.append("━"*200)

        # En-tête du tableau avec les positions réelles uniquement
        header = f"{'Métrique':<35}"
        for pos_key in real_positions:
            pos_num = int(pos_key[3:])
            header += f" {'P' + str(pos_num):<15}"
        report.append(header)
        report.append("-"*200)

        # Métriques des listes
        for metric, label in [
            ('nb_pages', '📄 Nb pages'),
            ('listes.pages_avec', '✓ Pages avec listes'),
            ('listes.pct_pages_avec', '📊 % pages/listes'),
            ('listes.moyenne_par_page', '📈 Listes/page'),
            ('listes.moyenne_items', '🔢 Items/liste'),
        ]:
            values = self._extract_metric_values_horizontal_real(analyses, metric, real_positions)
            report.append(f"{label:<35} {values}")

        # Position et type dominants pour les listes
        report.append("-"*200)
        report.append(self._format_position_line_horizontal_real('listes', analyses, '📍 Position préférée', real_positions))
        report.append(self._format_type_line_horizontal_real('listes', analyses, '🔸 Type dominant', real_positions))
        
        # === TABLEAUX ===
        report.append("\n" + "━"*200)
        report.append("📋 TABLEAUX")
        report.append("━"*200)

        header = f"{'Métrique':<35}"
        for pos_key in real_positions:
            pos_num = int(pos_key[3:])
            header += f" {'P' + str(pos_num):<15}"
        report.append(header)
        report.append("-"*200)

        for metric, label in [
            ('tableaux.pages_avec', '✓ Pages/tableaux'),
            ('tableaux.pct_pages_avec', '📊 % pages/tableaux'),
            ('tableaux.moyenne_par_page', '📈 Tableaux/page'),
            ('tableaux.moyenne_rows', '↕️ Lignes moy'),
            ('tableaux.moyenne_cols', '↔️ Colonnes moy'),
        ]:
            values = self._extract_metric_values_horizontal_real(analyses, metric, real_positions)
            report.append(f"{label:<35} {values}")

        report.append("-"*200)
        report.append(self._format_position_line_horizontal_real('tableaux', analyses, '📍 Position préférée', real_positions))
        
        # === IMAGES ===
        report.append("\n" + "━"*200)
        report.append("🖼️ IMAGES")
        report.append("━"*200)

        header = f"{'Métrique':<35}"
        for pos_key in real_positions:
            pos_num = int(pos_key[3:])
            header += f" {'P' + str(pos_num):<15}"
        report.append(header)
        report.append("-"*200)

        for metric, label in [
            ('images.pages_avec', '✓ Pages/images'),
            ('images.pct_pages_avec', '📊 % pages/images'),
            ('images.moyenne_par_page', '📈 Images/page'),
            ('images.alt_pct', '🏷️ % avec ALT'),
            ('images.lazy_pct', '⚡ % lazy loading')
        ]:
            values = self._extract_metric_values_horizontal_real(analyses, metric, real_positions)
            report.append(f"{label:<35} {values}")

        report.append("-"*200)
        report.append(self._format_position_line_horizontal_real('images', analyses, '📍 Position préférée', real_positions))

        
        # === SEO & STRUCTURE ===
        report.append("\n" + "━"*200)
        report.append("🎯 SEO & STRUCTURE")
        report.append("━"*200)

        header = f"{'Métrique':<35}"
        for pos_key in real_positions:
            pos_num = int(pos_key[3:])
            header += f" {'P' + str(pos_num):<15}"
        report.append(header)
        report.append("-"*200)

        for metric, label in [
            ('seo.score_moyen', '⭐ Score SEO'),
            ('seo.word_count_moyen', '📝 Mots/page'),
            ('structure.moyenne_sections', '📑 Sections/page'),
            ('structure.h1_moyen', '📌 H1/page'),
            ('structure.avg_paragraph_length', '📄 Long. paragraphe')
        ]:
            values = self._extract_metric_values_horizontal_real(analyses, metric, real_positions)
            report.append(f"{label:<35} {values}")

        # === LIENS ===
        report.append("\n" + "━"*200)
        report.append("🔗 LIENS")
        report.append("━"*200)

        header = f"{'Métrique':<35}"
        for pos_key in real_positions:
            pos_num = int(pos_key[3:])
            header += f" {'P' + str(pos_num):<15}"
        report.append(header)
        report.append("-"*200)

        for metric, label in [
            ('liens.moyenne_par_page', '📈 Liens/page'),
            ('liens.internal_pct', '📊 % internes'),
            ('liens.external_pct', '📊 % externes')
        ]:
            values = self._extract_metric_values_horizontal_real(analyses, metric, real_positions)
            report.append(f"{label:<35} {values}")

        # === FAQ ===
        report.append("\n" + "━"*200)
        report.append("❓ FAQ / ACCORDÉONS")
        report.append("━"*200)

        header = f"{'Métrique':<35}"
        for pos_key in real_positions:
            pos_num = int(pos_key[3:])
            header += f" {'P' + str(pos_num):<15}"
        report.append(header)
        report.append("-"*200)

        for metric, label in [
            ('faq.pages_avec', '✓ Pages/FAQ'),
            ('faq.pct_pages_avec', '📊 % pages/FAQ'),
            ('faq.moyenne_questions', '🔢 Questions/FAQ')
        ]:
            values = self._extract_metric_values_horizontal_real(analyses, metric, real_positions)
            report.append(f"{label:<35} {values}")

        # === DONNÉES STRUCTURÉES ===
        report.append("\n" + "━"*200)
        report.append("📦 DONNÉES STRUCTURÉES (JSON-LD)")
        report.append("━"*200)

        header = f"{'Métrique':<35}"
        for pos_key in real_positions:
            pos_num = int(pos_key[3:])
            header += f" {'P' + str(pos_num):<15}"
        report.append(header)
        report.append("-"*200)

        for metric, label in [
            ('structured_data.pages_avec', '✓ Pages/JSON-LD'),
            ('structured_data.pct_pages_avec', '📊 % pages/JSON-LD')
        ]:
            values = self._extract_metric_values_horizontal_real(analyses, metric, real_positions)
            report.append(f"{label:<35} {values}")

        # === PERFORMANCE ===
        report.append("\n" + "━"*200)
        report.append("⚡ PERFORMANCE TECHNIQUE")
        report.append("━"*200)

        header = f"{'Métrique':<35}"
        for pos_key in real_positions:
            pos_num = int(pos_key[3:])
            header += f" {'P' + str(pos_num):<15}"
        report.append(header)
        report.append("-"*200)

        for metric, label in [
            ('performance.lazy_loading_pct', '⚡ % lazy loading')
        ]:
            values = self._extract_metric_values_horizontal_real(analyses, metric, real_positions)
            report.append(f"{label:<35} {values}")

        # === NAVIGATION ===
        report.append("\n" + "━"*200)
        report.append("🧭 NAVIGATION & UX")
        report.append("━"*200)

        header = f"{'Métrique':<35}"
        for pos_key in real_positions:
            pos_num = int(pos_key[3:])
            header += f" {'P' + str(pos_num):<15}"
        report.append(header)
        report.append("-"*200)

        for metric, label in [
            ('navigation.breadcrumb_pct', '🍞 % breadcrumbs'),
            ('navigation.toc_pct', '📑 % table matières')
        ]:
            values = self._extract_metric_values_horizontal_real(analyses, metric, real_positions)
            report.append(f"{label:<35} {values}")

        # === SYNTHÈSE MACRO ===
        report.append("\n" + "="*200)
        report.append("📊 SYNTHÈSE MACRO - TENDANCES GRANULAIRES")
        report.append("="*200)

        # Identification des positions dominantes pour chaque métrique (positions réelles)
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
            best_pos = self._find_best_position_real(analyses, metric, real_positions)
            if best_pos:
                report.append(f"  • {label:<20}: Position {best_pos['position']} ({best_pos['value']:.1f})")
        
            # === SYNTHÈSE MACRO - RECOMMANDATIONS INTELLIGENTES ===
            report.append("\n" + "="*200)
            report.append("🎯 RECOMMANDATIONS STRATÉGIQUES - ANALYSE APPROFONDIE")
            report.append("="*200)
            
            # Identifier les pages "à structure significative" (exclure les outliers)
            meaningful_positions = self._identify_meaningful_positions(analyses, real_positions)
            
            # Déterminer les meilleures positions à analyser
            if len(meaningful_positions) >= 2:
                best_positions = [int(pos[3:]) for pos in meaningful_positions[:3]]  # Top 3 des positions significatives
                analysis_positions = meaningful_positions
                report.append(f"\n🏆 PAGES À STRUCTURE SIGNIFICATIVE ANALYSÉES: {best_positions}")
            else:
                best_positions = positions_numbers[:3] if len(positions_numbers) >= 3 else [min(positions_numbers)]
                analysis_positions = real_positions
                report.append(f"\n⚠️  ANALYSE SUR TOUTES LES POSITIONS (données structurelles limitées): {best_positions}")
            
            # Analyser chaque métrique pour identifier les patterns gagnants
            winning_patterns = []
            
            # 1. Analyse du contenu textuel
            word_counts = {}
            for pos_key in analysis_positions:
                if analyses.get(pos_key) and analyses[pos_key]['seo']['word_count_moyen']:
                    word_counts[pos_key] = analyses[pos_key]['seo']['word_count_moyen']
            
            if word_counts:
                best_word_count_pos = max(word_counts.items(), key=lambda x: x[1])
                if int(best_word_count_pos[0][3:]) in best_positions:
                    winning_patterns.append(f"  • 📝 Volume de contenu élevé: {best_word_count_pos[1]:.0f} mots en moyenne")
            
            # 2. Analyse des images
            image_density = {}
            for pos_key in analysis_positions:
                if analyses.get(pos_key) and analyses[pos_key]['images']['moyenne_par_page']:
                    image_density[pos_key] = analyses[pos_key]['images']['moyenne_par_page']
            
            if image_density:
                best_image_pos = max(image_density.items(), key=lambda x: x[1])
                if int(best_image_pos[0][3:]) in best_positions:
                    winning_patterns.append(f"  • 🖼️ Densité d'images optimale: {best_image_pos[1]:.1f} images/page")
            
            # 3. Analyse des listes
            list_density = {}
            for pos_key in analysis_positions:
                if analyses.get(pos_key) and analyses[pos_key]['listes']['moyenne_par_page']:
                    list_density[pos_key] = analyses[pos_key]['listes']['moyenne_par_page']
            
            if list_density:
                best_list_pos = max(list_density.items(), key=lambda x: x[1])
                if int(best_list_pos[0][3:]) in best_positions:
                    winning_patterns.append(f"  • 📋 Structuration par listes: {best_list_pos[1]:.1f} listes/page")
            
            # 4. Analyse des tableaux
            table_presence = {}
            for pos_key in analysis_positions:
                if analyses.get(pos_key) and analyses[pos_key]['tableaux']['pct_pages_avec']:
                    table_presence[pos_key] = analyses[pos_key]['tableaux']['pct_pages_avec']
            
            if table_presence:
                best_table_pos = max(table_presence.items(), key=lambda x: x[1])
                if int(best_table_pos[0][3:]) in best_positions and best_table_pos[1] > 30:
                    winning_patterns.append(f"  • 📊 Utilisation de tableaux: {best_table_pos[1]:.1f}% des pages")
            
            # 5. Analyse FAQ
            faq_presence = {}
            for pos_key in analysis_positions:
                if analyses.get(pos_key) and analyses[pos_key]['faq']['pct_pages_avec']:
                    faq_presence[pos_key] = analyses[pos_key]['faq']['pct_pages_avec']
            
            if faq_presence:
                best_faq_pos = max(faq_presence.items(), key=lambda x: x[1])
                if int(best_faq_pos[0][3:]) in best_positions and best_faq_pos[1] > 20:
                    winning_patterns.append(f"  • ❓ Sections FAQ: {best_faq_pos[1]:.1f}% des pages")
            
            # 6. Structure H1
            h1_counts = {}
            for pos_key in analysis_positions:
                if analyses.get(pos_key) and analyses[pos_key]['structure']['h1_moyen']:
                    h1_counts[pos_key] = analyses[pos_key]['structure']['h1_moyen']
            
            if h1_counts:
                best_h1_pos = max(h1_counts.items(), key=lambda x: x[1])
                if int(best_h1_pos[0][3:]) in best_positions and best_h1_pos[1] >= 1:
                    winning_patterns.append(f"  • 📌 Présence systématique de H1: {best_h1_pos[1]:.1f} H1/page")
            
            # 7. Analyse des liens
            link_density = {}
            for pos_key in analysis_positions:
                if analyses.get(pos_key) and analyses[pos_key]['liens']['moyenne_par_page']:
                    link_density[pos_key] = analyses[pos_key]['liens']['moyenne_par_page']
            
            if link_density:
                best_link_pos = max(link_density.items(), key=lambda x: x[1])
                if int(best_link_pos[0][3:]) in best_positions:
                    winning_patterns.append(f"  • 🔗 Densité de liens: {best_link_pos[1]:.1f} liens/page")
            
            # Afficher les patterns gagnants
            if winning_patterns:
                report.append("\n📊 CARACTÉRISTIQUES DISTINCTIVES DES MEILLEURES POSITIONS:")
                for pattern in winning_patterns:
                    report.append(pattern)
            else:
                report.append("\n🔍 Aucun pattern distinctif clair identifié")
                if len(meaningful_positions) < 2:
                    report.append("   ⚠️  Les performances sont probablement liées à l'autorité ou au netlinking")
            
            # RECOMMANDATIONS ACTIONNABLES
            report.append(f"\n🚀 ACTIONS PRIORITAIRES:")
            
            actions = []
            
            # Recommandation volume de contenu (seulement si écart significatif)
            if word_counts and len(word_counts) > 1:
                best_wc = max(word_counts.values())
                worst_wc = min(word_counts.values())
                if best_wc / worst_wc > 1.5:  # Écart significatif
                    actions.append(f"  • 📝 Augmenter le volume de contenu: cible {best_wc:.0f} mots minimum")
            
            # Recommandation images
            if image_density and len(image_density) > 1:
                best_img = max(image_density.values())
                worst_img = min(image_density.values())
                if best_img > worst_img * 1.3:
                    actions.append(f"  • 🖼️ Optimiser la densité d'images: viser {best_img:.1f} images/page")
            
            # Recommandation structure listes
            if list_density and len(list_density) > 1:
                best_list = max(list_density.values())
                worst_list = min(list_density.values())
                if best_list > worst_list * 1.5:
                    actions.append(f"  • 📋 Structurer avec des listes: {best_list:.1f} listes/page recommandé")
            
            # Recommandation tableaux
            if table_presence and len(table_presence) > 1:
                best_table = max(table_presence.values())
                if best_table > 40:  # Seuil significatif
                    actions.append(f"  • 📊 Intégrer des tableaux: présent sur {best_table:.1f}% des pages top")
            
            # Recommandation FAQ
            if faq_presence and len(faq_presence) > 1:
                best_faq = max(faq_presence.values())
                if best_faq > 25:  # Seuil significatif
                    actions.append(f"  • ❓ Ajouter une section FAQ: présent sur {best_faq:.1f}% des pages top")
            
            # Recommandation technique
            lazy_loading = {}
            for pos_key in analysis_positions:
                if analyses.get(pos_key) and analyses[pos_key]['images']['lazy_pct']:
                    lazy_loading[pos_key] = analyses[pos_key]['images']['lazy_pct']
            
            if lazy_loading:
                best_lazy = max(lazy_loading.values())
                if best_lazy < 80:  # Marge d'amélioration
                    actions.append(f"  • ⚡ Implémenter le lazy loading: cible >80% (actuel max: {best_lazy:.1f}%)")
            
            # Afficher les actions
            if actions:
                for action in actions[:6]:  # Limiter à 6 actions prioritaires
                    report.append(action)
            else:
                report.append("  • ✅ Les positions analysées présentent des caractéristiques structurelles similaires")
                report.append("  • 🔍 Se concentrer sur l'autorité de domaine et le netlinking")
            
            # SYNTHÈSE FINALE
            report.append(f"\n📈 STRATÉGIE GLOBALE:")
            report.append(f"  • 🎯 Focus sur les positions {best_positions} comme référence structurelle")
            if len(meaningful_positions) >= 2:
                report.append(f"  • 📊 Basé sur l'analyse de {len(meaningful_positions)} positions à structure cohérente")
            else:
                report.append(f"  • ⚠️  Analyse limitée - seulement {len(meaningful_positions)} position(s) à structure indicative")
            report.append(f"  • 🔄 Écart analysé: position {min(positions_numbers)} vs position {max(positions_numbers)}")
            report.append(f"  • 🚀 {len(actions)} actions prioritaires identifiées sur {len(winning_patterns)} patterns")

            report.append("\n" + "="*200)
            report.append(f"📅 Rapport généré le: {self._get_timestamp()}")
            report.append("="*200)
        
        return "\n".join(report)

    def _identify_meaningful_positions(self, analyses, real_positions):
        """Identifie les positions avec une structure cohérente (exclut les outliers)"""
        meaningful = []
        word_counts = []
        
        # Collecter les données de volume de contenu
        for pos_key in real_positions:
            if analyses.get(pos_key) and analyses[pos_key]['seo']['word_count_moyen']:
                word_counts.append(analyses[pos_key]['seo']['word_count_moyen'])
        
        if not word_counts:
            return real_positions  # Fallback si pas de données
        
        # Calculer les quartiles pour identifier les outliers
        sorted_counts = sorted(word_counts)
        q1 = sorted_counts[len(sorted_counts) // 4]
        q3 = sorted_counts[3 * len(sorted_counts) // 4]
        iqr = q3 - q1
        
        # Seuils pour outliers
        lower_bound = q1 - 1.5 * iqr
        upper_bound = q3 + 1.5 * iqr
        
        # Garder seulement les positions dans la plage normale
        for pos_key in real_positions:
            if analyses.get(pos_key) and analyses[pos_key]['seo']['word_count_moyen']:
                wc = analyses[pos_key]['seo']['word_count_moyen']
                if lower_bound <= wc <= upper_bound:
                    meaningful.append(pos_key)
        
        return meaningful if meaningful else real_positions  # Fallback si tout est outlier

    def _is_metric_significant(self, metric_dict):
        """Vérifie si les différences entre les valeurs sont significatives"""
        if len(metric_dict) < 2:
            return False
        
        values = list(metric_dict.values())
        avg = sum(values) / len(values)
        
        # Écart-type pour mesurer la dispersion
        variance = sum((x - avg) ** 2 for x in values) / len(values)
        std_dev = variance ** 0.5
        
        # Coefficient de variation > 15% considéré comme significatif
        return (std_dev / avg) > 0.15 if avg > 0 else False
    
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

    def _extract_metric_values_horizontal_real(self, analyses, metric, real_positions):
        """Extrait les valeurs d'une métrique pour les positions réelles uniquement"""
        values = []
        for pos_key in real_positions:
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

    def _format_position_line_horizontal_real(self, element_key, analyses, label, real_positions):
        """Formate une ligne de position préférée pour les positions réelles"""
        line = f"{label:<35}"
        for pos_key in real_positions:
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

    def _format_type_line_horizontal_real(self, element_key, analyses, label, real_positions):
        """Formate une ligne de type dominant pour les positions réelles"""
        line = f"{label:<35}"
        for pos_key in real_positions:
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
    
    def _find_best_position_real(self, analyses, metric, real_positions):
        """Trouve la position avec la meilleure valeur pour une métrique donnée (positions réelles)"""
        best_value = -1
        best_position = None

        for pos_key in real_positions:
            if analyses.get(pos_key):
                keys = metric.split('.')
                val = analyses[pos_key]
                for k in keys:
                    val = val.get(k, 0) if isinstance(val, dict) else val

                if isinstance(val, (int, float)) and val > best_value:
                    best_value = val
                    best_position = int(pos_key[3:])

        if best_position:
            return {'position': best_position, 'value': best_value}
        return None

    def _get_timestamp(self):
        """Retourne le timestamp actuel"""
        from datetime import datetime
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    def save_report_for_analysis(self, analysis_index, filename=None):
        """Sauvegarde le rapport pour une analyse donnée"""
        if filename is None:
            analysis = self.analyses_data[analysis_index]
            query_clean = analysis['query'].replace(' ', '_').replace('/', '_')[:50]
            filename = f"dom_rapport_analyse_{analysis_index}_{query_clean}.txt"

        report = self.generate_comparative_report_for_analysis(analysis_index)

        with open(filename, 'w', encoding='utf-8') as f:
            f.write(report)

        print(f"\n✓ Rapport pour analyse {analysis_index + 1} sauvegardé: {filename}")
        return filename

    def save_all_reports(self):
        """Sauvegarde un rapport pour chaque analyse"""
        filenames = []
        for i in range(len(self.analyses_data)):
            filename = self.save_report_for_analysis(i)
            filenames.append(filename)
        return filenames


def main():
    print("="*80)
    print("📊 SERPRAPPORT - Analyseur de tendances DOM SERP")
    print("✓ Compatible avec les formats: serprapport + serptestv2")
    print("="*80)

    comparator = DomTrendComparator("rankscore_dom.json")

    try:
        # Chargement
        print("\n🔄 Chargement des données...")
        comparator.load_data()

        # Génération d'un rapport pour chaque analyse
        print("\n🔄 Génération des rapports par analyse...")
        filenames = comparator.save_all_reports()

        print("\n✅ Analyse terminée avec succès!")
        print(f"📄 {len(filenames)} rapports générés:")
        for filename in filenames:
            print(f"   - {filename}")

        print(f"\n🎯 Utilisez les rapports pour analyser les tendances SEO/DOM par position SERP")

    except FileNotFoundError as e:
        print(f"❌ Erreur: {e}")
        print("💡 Assurez-vous d'avoir exécuté serptestv2.py pour générer rankscore_dom.json")
    except Exception as e:
        print(f"❌ Erreur inattendue: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()