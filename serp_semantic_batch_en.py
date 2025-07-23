import os
import re
import json
import logging
import asyncio
import aiofiles
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
from typing import List, Dict, Tuple, Optional, Set
from collections import defaultdict
import glob
from pathlib import Path
import aiofiles
import numpy as np
import spacy
import nltk
from nltk.corpus import stopwords
from bs4 import BeautifulSoup, Comment
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.cluster import KMeans
from sentence_transformers import SentenceTransformer
from openai import AsyncOpenAI
import unicodedata

# === Initial Configuration ===
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

try:
    stopwords.words('english')
except LookupError:
    nltk.download('stopwords')

# === OpenAI API Configuration ===
api_key = os.getenv('OPENAI_API_KEY')
if not api_key:
    logging.warning("No OpenAI API key found in environment variables")
    async_client = None
else:
    async_client = AsyncOpenAI(api_key=api_key)
    logging.info("OpenAI API key loaded for async processing")

# === Files and Directories ===
BASE_DIR = os.path.dirname(__file__)
RESULTS_DIR = os.path.join(BASE_DIR, "results")

def _find_consigne_file() -> str:
    """Automatically finds the instruction file in the static folder"""
    consigne_pattern = os.path.join(BASE_DIR, "static", "consigne*.json")
    consigne_files = glob.glob(consigne_pattern)
    
    if not consigne_files:
        raise FileNotFoundError(f"❌ No instruction file found in {os.path.join(BASE_DIR, 'static')}/ (pattern: consigne*.json)")
    
    if len(consigne_files) == 1:
        found_file = consigne_files[0]
        logging.info(f"📁 Instruction file detected: {os.path.basename(found_file)}")
        return found_file
    
    # If multiple files found, take the most recent
    consigne_files.sort(key=os.path.getmtime, reverse=True)
    most_recent = consigne_files[0]
    logging.info(f"📁 Multiple instruction files found, using most recent: {os.path.basename(most_recent)}")
    logging.info(f"   Other files ignored: {', '.join([os.path.basename(f) for f in consigne_files[1:]])}")
    return most_recent

CONSIGNE_FILE = _find_consigne_file()

# === Parallelization Configuration ===
MAX_WORKERS_IO = 4  # For I/O operations
MAX_WORKERS_CPU = 2  # For BERT/spaCy models
MAX_CONCURRENT_API = 3  # For concurrent OpenAI calls

# === Section calculation function (unchanged) ===
def calculate_sections(word_count):
    """Calculates the plan structure based on word count"""
    intro_concl = 225
    available_words = word_count - (intro_concl * 2)
    num_sections = round(available_words / 325) if available_words > 0 else 0
    words_per_section = available_words / num_sections if num_sections > 0 else 0
    return {
        'introduction': {'length': intro_concl},
        'development': {'number_sections': num_sections, 'words_per_section': round(words_per_section, 1)},
        'conclusion': {'length': intro_concl}
    }

# === Matching Utilities ===
def normalize_text_for_filename(text: str) -> str:
    """Normalizes text to match filename format"""
    # Replace spaces with underscores and clean
    normalized = re.sub(r'[^\w\s]', '', text.lower())
    normalized = re.sub(r'\s+', '_', normalized.strip())
    return normalized

def find_matching_files(consigne_data: Dict) -> List[Tuple[str, Dict]]:
    """Finds SERP files matching queries from consigne.json"""
    if not os.path.exists(RESULTS_DIR):
        logging.error(f"Directory {RESULTS_DIR} does not exist")
        return []
    
    pattern = os.path.join(RESULTS_DIR, "serp_*.json")
    serp_files = glob.glob(pattern)
    logging.info(f"Found {len(serp_files)} SERP files in {RESULTS_DIR}")
    
    matches = []
    queries = consigne_data.get('queries', [])
    
    for filepath in serp_files:
        filename = os.path.basename(filepath)
        
        # Extract ID from filename (serp_XXX_...)
        id_match = re.match(r'serp_(\d{3})_(.+)\.json', filename)
        if not id_match:
            logging.warning(f"Unrecognized file format: {filename}")
            continue
        
        file_id = int(id_match.group(1))
        file_text_part = id_match.group(2)
        
        # Search for corresponding query - improved logic
        matching_query = None
        for query in queries:
            if query.get('id') == file_id:
                # ID match is sufficient - no need to check exact text
                # as filenames may be truncated
                matching_query = query
                break
        
        if matching_query:
            matches.append((filepath, matching_query))
            logging.info(f"✓ Match found: {filename} -> query ID {file_id} (\"{matching_query.get('text', '')[:50]}...\")")
        else:
            logging.warning(f"✗ No match for: {filename} (ID {file_id} not found in consigne.json)")
    
    return matches

# === Semantic Analyzer optimized for parallelization ===
class ParallelSemanticAnalyzer:
    """Thread-safe version of semantic analyzer"""
    
    def __init__(self):
        self.stop_words = set(stopwords.words('english'))
        additional_stops = {
            'the', 'more', 'this', 'that', 'these', 'those',
            'such', 'very', 'much', 'many', 'most', 'some',
            'other', 'another', 'each', 'every', 'either', 'neither',
            'both', 'all', 'any', 'few', 'several', 'enough'
        }
        self.stop_words.update(additional_stops)
    
    def _init_models(self):
        """Initialize models in worker thread with fallback"""
        try:
            # Try large model first, then alternatives
            models_to_try = ['en_core_web_lg', 'en_core_web_md', 'en_core_web_sm']
            
            self.nlp = None
            for model_name in models_to_try:
                try:
                    self.nlp = spacy.load(model_name)
                    logging.info(f"✓ spaCy model loaded: {model_name}")
                    break
                except Exception as e:
                    logging.warning(f"Model {model_name} not available: {e}")
                    continue
            
            if self.nlp is None:
                logging.error("No English spaCy model available")
                return False
            
            # Load SentenceTransformer model
            try:
                self.sentence_model = SentenceTransformer('all-MiniLM-L6-v2', device='cpu')
                logging.info("✓ SentenceTransformer model loaded")
            except Exception as e:
                logging.error(f"Error loading SentenceTransformer: {e}")
                return False
            
            # Add spaCy stop words
            self.stop_words.update(self.nlp.Defaults.stop_words)
            return True
            
        except Exception as e:
            logging.error(f"Error loading models: {str(e)}")
            return False
    
    def extract_entities(self, text: str) -> List[Dict]:
        """Named entity extraction with spaCy"""
        if not hasattr(self, 'nlp'):
            if not self._init_models():
                return []
        
        doc = self.nlp(text)
        entities = []
        for ent in doc.ents:
            if ent.label_ in ["PERSON", "ORG", "PRODUCT", "GPE", "WORK_OF_ART", "FAC", "EVENT"]:
                entities.append({
                    "text": ent.text,
                    "label": ent.label_,
                    "start": ent.start_char,
                    "end": ent.end_char
                })
        return entities
    
    def extract_key_phrases(self, text: str, max_phrases: int = 20) -> List[str]:
        """Extract important key phrases"""
        if not hasattr(self, 'nlp'):
            if not self._init_models():
                return []
        
        doc = self.nlp(text)
        phrases = []
        
        # Extract noun chunks
        for chunk in doc.noun_chunks:
            if len(chunk.text.split()) <= 3 and len(chunk.text) > 3:
                phrases.append(chunk.text.lower().strip())
        
        # Extract interesting syntactic patterns
        for token in doc:
            if token.pos_ in ["NOUN", "ADJ"] and token.dep_ in ["nsubj", "dobj", "amod"]:
                if token.head.pos_ == "NOUN":
                    phrase = f"{token.text} {token.head.text}".lower()
                    phrases.append(phrase)
        
        # Deduplication and filtering
        unique_phrases = list(set(phrases))
        return unique_phrases[:max_phrases]
    
    def cluster_keywords_semantic(self, keywords: List[str], n_clusters: int = 5) -> Dict[str, List[str]]:
        """Semantic clustering of keywords with BERT"""
        if len(keywords) < n_clusters:
            return {"cluster_0": keywords}
        
        try:
            if not hasattr(self, 'sentence_model'):
                if not self._init_models():
                    return {"cluster_0": keywords}
            
            # Generate embeddings with SentenceTransformer
            embeddings = self.sentence_model.encode(keywords)
            
            # K-means clustering
            kmeans = KMeans(n_clusters=n_clusters, random_state=42)
            cluster_labels = kmeans.fit_predict(embeddings)
            
            # Organize by clusters
            clusters = defaultdict(list)
            for keyword, label in zip(keywords, cluster_labels):
                clusters[f"cluster_{label}"].append(keyword)
            
            return dict(clusters)
            
        except Exception as e:
            logging.warning(f"Error during clustering: {str(e)}")
            return {"cluster_0": keywords}
    
    def analyze_semantic_relations(self, text: str) -> List[Dict]:
        """Analyze semantic relations in text"""
        if not hasattr(self, 'nlp'):
            if not self._init_models():
                return []
        
        doc = self.nlp(text)
        relations = []
        
        for token in doc:
            if token.pos_ in ["NOUN", "VERB"] and token.dep_ in ["nsubj", "dobj", "prep"]:
                if token.head.pos_ in ["NOUN", "VERB"]:
                    relations.append({
                        "head": token.head.text,
                        "relation": token.dep_,
                        "dependent": token.text,
                        "context": token.sent.text[:100] + "..." if len(token.sent.text) > 100 else token.sent.text
                    })
        
        return relations[:10]

# === HTML Content Cleaner (thread-safe) ===
class ThreadSafeTextCleaner:
    def __init__(self,
                 remove_tags: Set[str] = {'script', 'style', 'meta', 'nav', 'footer', 'header'},
                 keep_tags: Set[str] = {'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'article', 'section', 'main', 'div'},
                 min_word_length: int = 1,
                 max_word_length: int = 45):
        self.remove_tags = remove_tags
        self.keep_tags = keep_tags
        self.min_word_length = min_word_length
        self.max_word_length = max_word_length
        self.whitespace_pattern = re.compile(r'\s+')
        self.special_chars_pattern = re.compile(r'[^\w\s-]')
        self.url_pattern = re.compile(
            r'http[s]?://(?:[a-zA-Z0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'
        )
        self.email_pattern = re.compile(r'[\w\.-]+@[\w\.-]+\.\w+')

    def clean_html(self, html_content: Optional[str]) -> str:
        """Clean HTML content to extract text"""
        if not html_content:
            return ""
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Remove comments
            for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
                comment.extract()
            
            # Remove unwanted tags
            for tag in self.remove_tags:
                for element in soup.find_all(tag):
                    element.decompose()
            
            # Keep only useful tags
            if self.keep_tags:
                for tag in soup.find_all():
                    if tag.name not in self.keep_tags:
                        tag.unwrap()
            
            return soup.get_text(separator=' ', strip=True)
        except Exception as e:
            logging.warning(f"Error cleaning HTML: {e}")
            return ""

    def remove_unwanted_content(self, text: str) -> str:
        """Remove URLs, emails and special characters"""
        text = self.url_pattern.sub(' ', text)
        text = self.email_pattern.sub(' ', text)
        text = self.special_chars_pattern.sub(' ', text)
        return text

    def clean_words(self, text: str) -> str:
        """Filter words by length"""
        return ' '.join(
            word.lower() for word in text.split()
            if self.min_word_length <= len(word) <= self.max_word_length
        )

    def clean_text(self, html_content: Optional[str], normalize: bool = False) -> str:
        """Complete text cleaning pipeline"""
        text = self.clean_html(html_content)
        if not text:
            return ""
        
        if normalize:
            text = unicodedata.normalize('NFKD', text)
            text = text.encode('ASCII', 'ignore').decode('ASCII')
        
        text = self.remove_unwanted_content(text)
        text = self.clean_words(text)
        return self.whitespace_pattern.sub(' ', text).strip()

# === Individual SERP File Processor ===
class SerpFileProcessor:
    def __init__(self):
        self.semantic_analyzer = ParallelSemanticAnalyzer()
        self.text_cleaner = ThreadSafeTextCleaner()
    
    def preprocess_text(self, text: str) -> List[str]:
        """Preprocess text for TF-IDF analysis"""
        try:
            if not hasattr(self.semantic_analyzer, 'nlp'):
                if not self.semantic_analyzer._init_models():
                    return []
            
            doc = self.semantic_analyzer.nlp(text)
            return [token.lemma_.lower() for token in doc 
                    if token.is_alpha and len(token.text) > 2 and token.lemma_.lower() not in self.semantic_analyzer.stop_words]
        except Exception as e:
            logging.warning(f"Error normalizing text: {str(e)}")
            return []
    
    def calculate_serp_weight(self, position: int) -> float:
        """Calculate SERP result weight based on position"""
        return 1 / np.log2(position + 2)
    
    def calculate_weighted_tfidf(self, documents: List[Dict]) -> Tuple[Dict[str, float], List[str]]:
        """Calculate TF-IDF weighted by SERP position"""
        try:
            if not documents:
                return {}, []
            
            corpus = []
            weights = []
            for doc in documents:
                tokens = self.preprocess_text(doc['text'])
                corpus.append(' '.join(tokens))
                weights.append(self.calculate_serp_weight(doc['position']))
            
            if not any(corpus):
                return {}, []
            
            vectorizer = TfidfVectorizer(ngram_range=(1, 2), min_df=1)
            tfidf_matrix = vectorizer.fit_transform(corpus)
            weighted_tfidf = tfidf_matrix.multiply(np.array(weights)[:, np.newaxis])
            scores = np.array(weighted_tfidf.sum(axis=0)).flatten()
            return dict(zip(vectorizer.get_feature_names_out(), scores)), vectorizer.get_feature_names_out()
        except Exception as e:
            logging.error(f"Error calculating TF-IDF: {str(e)}")
            return {}, []
    
    def extract_text_from_html(self, html_content: str) -> str:
        """Extract clean text from HTML content"""
        return self.text_cleaner.clean_text(html_content, normalize=False)
    
    def _suggest_entity_angle(self, entity_text: str, entity_type: str) -> str:
        """Suggest a potential angle based on an entity"""
        angle_suggestions = {
            "PERSON": f"Expert perspective from {entity_text}",
            "ORG": f"Comparative analysis with {entity_text}",
            "PRODUCT": f"Case study featuring {entity_text}",
            "GPE": f"Geographic context of {entity_text}",
            "WORK_OF_ART": f"Cultural impact of {entity_text}",
            "FAC": f"Infrastructure focus on {entity_text}",
            "EVENT": f"Lessons learned from {entity_text}"
        }
        return angle_suggestions.get(entity_type, f"Unique angle through {entity_text}")

    def _suggest_relation_angle(self, relation: Dict) -> str:
        """Suggest an angle based on a semantic relation"""
        relation_type = relation.get('relation', '')
        head = relation.get('head', '')
        dependent = relation.get('dependent', '')
        
        if relation_type == 'nsubj':
            return f"Focus on {dependent}'s impact on {head}"
        elif relation_type == 'dobj':
            return f"Analysis of {head}-{dependent} interaction"
        elif relation_type == 'prep':
            return f"Relational context of {head} and {dependent}"
        else:
            return f"{head}-{dependent} connection to explore"

    def _identify_cluster_theme(self, keywords: List[str]) -> str:
        """Identify the main theme of a cluster"""
        if not keywords:
            return "Undetermined theme"
        
        # Basic lexical pattern analysis
        technical_words = sum(1 for kw in keywords if any(tech in kw.lower() for tech in ['technical', 'technology', 'digital', 'software', 'hardware']))
        business_words = sum(1 for kw in keywords if any(biz in kw.lower() for biz in ['business', 'enterprise', 'market', 'sales', 'revenue']))
        user_words = sum(1 for kw in keywords if any(user in kw.lower() for user in ['user', 'customer', 'client', 'people', 'human']))
        
        if technical_words > business_words and technical_words > user_words:
            return "Technical aspects"
        elif business_words > user_words:
            return "Business implications"
        elif user_words > 0:
            return "Human dimension"
        else:
            return "General theme"

    def _suggest_cluster_angles(self, keywords: List[str], cluster_name: str) -> List[str]:
        """Suggest differentiating angles for a cluster"""
        theme = self._identify_cluster_theme(keywords)
        base_angles = []
        
        if "technical" in theme.lower():
            base_angles = [
                f"Innovative technical approach through {', '.join(keywords[:3])}",
                f"Technical challenges around {keywords[0] if keywords else 'this domain'}"
            ]
        elif "business" in theme.lower():
            base_angles = [
                f"ROI and business impacts of {', '.join(keywords[:3])}",
                f"Competitive strategies around {keywords[0] if keywords else 'this sector'}"
            ]
        elif "human" in theme.lower():
            base_angles = [
                f"User experience centered on {', '.join(keywords[:3])}",
                f"Human impact of {keywords[0] if keywords else 'this dimension'}"
            ]
        else:
            base_angles = [
                f"Unique perspective on {', '.join(keywords[:3])}",
                f"Novel angle through {keywords[0] if keywords else 'this cluster'}"
            ]
        
        return base_angles

    def _calculate_thematic_diversity(self, clusters: Dict) -> float:
        """Calculate thematic diversity score"""
        if not clusters:
            return 0.0
        
        cluster_sizes = [len(keywords) for keywords in clusters.values()]
        if not cluster_sizes:
            return 0.0
        
        # Measure based on cluster size distribution
        avg_size = np.mean(cluster_sizes)
        size_variance = np.var(cluster_sizes)
        
        # Normalized score (more balanced = more diverse)
        diversity_score = min(1.0, avg_size / (1 + size_variance)) * len(clusters) / 5
        return round(diversity_score, 2)

    def _calculate_semantic_complexity(self, relations: List[Dict], entities: List[Dict]) -> float:
        """Calculate semantic complexity score"""
        if not relations and not entities:
            return 0.0
        
        # Score based on number and diversity of relations and entities
        relation_diversity = len(set(rel.get('relation', '') for rel in relations))
        entity_diversity = len(set(ent.get('label', '') for ent in entities))
        
        complexity_score = (len(relations) * 0.6 + len(entities) * 0.4) * (relation_diversity + entity_diversity) / 20
        return round(min(1.0, complexity_score), 2)

    def _generate_local_angles(self, context: Dict) -> List[str]:
        """Generate basic angles when GPT is not available"""
        angles = []
        
        # Angles based on clusters
        for cluster_name, cluster_data in context.get("thematic_clusters", {}).items():
            theme = cluster_data.get("main_theme", "")
            if theme and cluster_data.get("keywords"):
                angles.extend(cluster_data.get("differentiating_angles", []))
        
        # Angles based on entities
        for entity in context.get("important_entities", [])[:3]:
            angles.append(entity.get("potential_angle", ""))
        
        # Angles based on relations
        for relation in context.get("semantic_relations", [])[:2]:
            angles.append(relation.get("potential_angle", ""))
        
        # Clean and limit
        clean_angles = [angle for angle in angles if angle and len(angle) > 10]
        return clean_angles[:10]

    def _parse_angles_from_gpt(self, gpt_response: str) -> List[str]:
        """Parse GPT response to extract angles"""
        angles = []
        lines = gpt_response.split('\n')
        
        current_angle = ""
        for line in lines:
            line = line.strip()
            if re.match(r'^\d+\.', line):  # Line starting with number
                if current_angle:
                    angles.append(current_angle.strip())
                current_angle = re.sub(r'^\d+\.\s*', '', line)
            elif line and current_angle:
                current_angle += " " + line
        
        # Add last angle
        if current_angle:
            angles.append(current_angle.strip())
        
        return angles[:10]
    
    async def process_file(self, filepath: str, query_data: Dict) -> Optional[Dict]:
        """Process individual SERP file asynchronously"""
        try:
            logging.info(f"Starting processing of {os.path.basename(filepath)}")
            
            # Load SERP file
            async with aiofiles.open(filepath, 'r', encoding='utf-8') as f:
                content = await f.read()
                serp_data = json.loads(content)
            
            if not serp_data.get('success') or not serp_data.get('organicResults'):
                logging.warning(f"Invalid SERP data in {filepath}")
                return None
            
            main_keyword = query_data.get('text', '')
            logging.info(f"Semantic analysis for: {main_keyword}")
            
            # === 1. Document extraction and preparation ===
            documents = []
            full_corpus_text = ""
            max_word_count = 0
            
            for position, result in enumerate(serp_data.get('organicResults', [])):
                if result.get('html'):
                    text = self.extract_text_from_html(result['html'])
                    if text:
                        word_count = len(text.split())
                        max_word_count = max(max_word_count, word_count)
                        documents.append({'position': position, 'text': text, 'url': result.get('url', '')})
                        full_corpus_text += " " + text
            
            if not documents:
                logging.warning(f"No valid documents found in {filepath}")
                return None

            # === 2. Advanced semantic analysis (in thread pool) ===
            loop = asyncio.get_event_loop()
            with ThreadPoolExecutor(max_workers=1) as executor:
                # Execute CPU-intensive tasks in thread
                entities_task = loop.run_in_executor(executor, self.semantic_analyzer.extract_entities, full_corpus_text)
                key_phrases_task = loop.run_in_executor(executor, self.semantic_analyzer.extract_key_phrases, full_corpus_text)
                relations_task = loop.run_in_executor(executor, self.semantic_analyzer.analyze_semantic_relations, full_corpus_text)
                tfidf_task = loop.run_in_executor(executor, self.calculate_weighted_tfidf, documents)
                
                # Wait for all results
                entities, key_phrases, relations, (weighted_scores, _) = await asyncio.gather(
                    entities_task, key_phrases_task, relations_task, tfidf_task
                )
            
            if not weighted_scores:
                logging.warning(f"Failed to calculate TF-IDF scores for {filepath}")
                return None

            # === 3. Keyword selection and clustering ===
            threshold = np.percentile(list(weighted_scores.values()), 75)
            important_terms = {
                term: score for term, score in weighted_scores.items()
                if score <= 5000 and score > threshold
            }
            
            # Add important key phrases
            for phrase in key_phrases:
                if phrase not in important_terms:
                    important_terms[phrase] = np.mean(list(important_terms.values())) if important_terms else 1.0
            
            # Semantic clustering (in thread pool)
            keywords_list = list(important_terms.keys())
            with ThreadPoolExecutor(max_workers=1) as executor:
                clusters = await loop.run_in_executor(
                    executor, 
                    self.semantic_analyzer.cluster_keywords_semantic, 
                    keywords_list
                )
            
            # === 4. Create enriched context ===
            enriched_context = {
                "main_subject": main_keyword,
                "important_entities": [
                    {
                        "name": ent["text"],
                        "type": ent["label"],
                        "potential_angle": self._suggest_entity_angle(ent["text"], ent["label"])
                    }
                    for ent in entities[:10]
                ],
                "thematic_clusters": {},
                "semantic_relations": [
                    {
                        "relation": f"{rel['head']} -> {rel['relation']} -> {rel['dependent']}",
                        "context": rel['context'][:80] + "..." if len(rel['context']) > 80 else rel['context'],
                        "potential_angle": self._suggest_relation_angle(rel)
                    }
                    for rel in relations[:8]
                ],
                "semantic_statistics": {
                    "number_clusters": len(clusters),
                    "number_relations": len(relations),
                    "number_entities": len(entities),
                    "thematic_diversity": self._calculate_thematic_diversity(clusters),
                    "semantic_complexity": self._calculate_semantic_complexity(relations, entities)
                }
            }
            
            # Organize clusters with differentiating angles
            for cluster_name, cluster_keywords in clusters.items():
                cluster_scores = {kw: important_terms.get(kw, 0) for kw in cluster_keywords}
                top_cluster_keywords = sorted(cluster_scores.items(), key=lambda x: x[1], reverse=True)[:8]
                
                enriched_context["thematic_clusters"][cluster_name] = {
                    "keywords": [kw for kw, _ in top_cluster_keywords],
                    "scores": {kw: score for kw, score in top_cluster_keywords},
                    "main_theme": self._identify_cluster_theme(cluster_keywords),
                    "differentiating_angles": self._suggest_cluster_angles(cluster_keywords, cluster_name)
                }

            # === 5. GPT call with concurrency management ===
            refined_keywords = ""
            differentiating_angles = []
            
            try:
                if not enriched_context["thematic_clusters"]:
                    logging.warning(f"No thematic clusters for {filepath}, using fallback")
                    refined_keywords = ", ".join(keywords_list[:60])
                elif async_client is None:
                    logging.warning(f"OpenAI API key missing for {filepath}, using local clustering")
                    all_clustered_keywords = []
                    for cluster_data in enriched_context["thematic_clusters"].values():
                        all_clustered_keywords.extend(cluster_data["keywords"])
                    refined_keywords = ", ".join(all_clustered_keywords[:60])
                    differentiating_angles = self._generate_local_angles(enriched_context)
                else:
                    # Parallel OpenAI API calls
                    context_str = json.dumps(enriched_context, ensure_ascii=False, indent=2)
                    
                    # Create two API tasks
                    keywords_task = async_client.chat.completions.create(
                        model="gpt-4o",
                        messages=[
                            {
                                "role": "system",
                                "content": (
                                    "You are an expert in SEO and semantic analysis. Analyze this SERP corpus "
                                    "and return 60 strategic keywords that cover all important aspects "
                                    "of the topic. Organize them logically and return only the comma-separated list."
                                )
                            },
                            {
                                "role": "user",
                                "content": f"Semantic analysis of topic '{main_keyword}':\n{context_str}"
                            }
                        ],
                        temperature=0.7,
                        max_tokens=1024,
                        timeout=30
                    )
                    
                    angles_task = async_client.chat.completions.create(
                        model="gpt-4o",
                        messages=[
                            {
                                "role": "system",
                                "content": (
                                    "You are a content strategy expert. "
                                    "From this detailed semantic analysis (clusters, entities, relations), "
                                    "identify 10 differentiating and original angles to address this topic. "
                                    "Each angle should leverage semantic insights to stand out from competition. "
                                    "Format: numbered list with title and brief explanation (2-3 lines max per angle)."
                                )
                            },
                            {
                                "role": "user",
                                "content": (
                                    f"TARGET QUERY (MANDATORY): '{main_keyword}'\n"
                                    f"⚠️ IMPORTANT: All angles MUST directly address this exact query. This is what users type in Google.\n\n"
                                    f"Semantic context:\n{context_str}\n\n"
                                    "Find unique angles that:\n"
                                    f"1. DIRECTLY ANSWER the query '{main_keyword}'\n"
                                    f"2. Match the search intent of this specific query\n"
                                    "3. Exploit unexpected semantic relationships\n" 
                                    "4. Use connections between clusters\n"
                                    "5. Highlight underutilized entities\n"
                                    "6. Cover underrepresented aspects in the SERP\n\n"
                                    f"Each angle must explain how it specifically addresses '{main_keyword}'."
                                )
                            }
                        ],
                        temperature=0.8,
                        max_tokens=1500,
                        timeout=45
                    )
    
                    
                    # Wait for both responses in parallel
                    keywords_response, angles_response = await asyncio.gather(
                        keywords_task, angles_task, return_exceptions=True
                    )
                    
                    # Process responses
                    if isinstance(keywords_response, Exception):
                        logging.error(f"Error during keywords API call: {keywords_response}")
                        all_clustered_keywords = []
                        for cluster_data in enriched_context["thematic_clusters"].values():
                            all_clustered_keywords.extend(cluster_data["keywords"])
                        refined_keywords = ", ".join(all_clustered_keywords[:60])
                    else:
                        refined_keywords = keywords_response.choices[0].message.content.strip()
                    
                    if isinstance(angles_response, Exception):
                        logging.error(f"Error during angles API call: {angles_response}")
                        differentiating_angles = self._generate_local_angles(enriched_context)
                    else:
                        differentiating_angles_text = angles_response.choices[0].message.content.strip()
                        differentiating_angles = self._parse_angles_from_gpt(differentiating_angles_text)
                    
                    logging.info(f"Advanced semantic analysis generated with GPT for {os.path.basename(filepath)}")
                        
            except Exception as e:
                logging.error(f"Error calling OpenAI API for {filepath}: {str(e)}")
                # Intelligent fallback
                all_clustered_keywords = []
                for cluster_data in enriched_context["thematic_clusters"].values():
                    all_clustered_keywords.extend(cluster_data["keywords"])
                refined_keywords = ", ".join(all_clustered_keywords[:60])
                differentiating_angles = self._generate_local_angles(enriched_context)
                logging.info(f"Using semantic clustering as fallback for {os.path.basename(filepath)}")

            # === 6. Build final result ===
            result = {
                'main_keyword': main_keyword,
                'top_keywords': refined_keywords,
                'word_count': max_word_count,
                'plan': calculate_sections(max_word_count),
                'semantic_analysis': {
                    'entities': [ent["name"] for ent in enriched_context["important_entities"][:5]],
                    'clusters_count': enriched_context["semantic_statistics"]["number_clusters"],
                    'relations_found': enriched_context["semantic_statistics"]["number_relations"],
                    'thematic_diversity': enriched_context["semantic_statistics"]["thematic_diversity"],
                    'semantic_complexity': enriched_context["semantic_statistics"]["semantic_complexity"]
                },
                'differentiating_angles': differentiating_angles
            }
            
            logging.info(f"✓ Processing completed successfully for {os.path.basename(filepath)}")
            return result
            
        except Exception as e:
            logging.error(f"Error processing {filepath}: {str(e)}")
            return None

# === Batch Processing Manager ===
class BatchSerpProcessor:
    def __init__(self):
        self.semaphore = asyncio.Semaphore(MAX_CONCURRENT_API)
    
    async def process_files_batch(self, file_matches: List[Tuple[str, Dict]]) -> Dict[int, Dict]:
        """Process all SERP files in parallel with concurrency limiting"""
        
        async def process_with_semaphore(filepath: str, query_data: Dict) -> Tuple[int, Optional[Dict]]:
            async with self.semaphore:  # Limit API call concurrency
                processor = SerpFileProcessor()
                result = await processor.process_file(filepath, query_data)
                return query_data['id'], result
        
        # Create all tasks
        tasks = [
            process_with_semaphore(filepath, query_data) 
            for filepath, query_data in file_matches
        ]
        
        # Execute all tasks with concurrency limiting
        logging.info(f"Starting parallel processing of {len(tasks)} files...")
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process results
        processed_results = {}
        successful_files = []
        
        for i, (filepath, query_data) in enumerate(file_matches):
            result = results[i]
            
            if isinstance(result, Exception):
                logging.error(f"Error processing {filepath}: {result}")
                continue
            
            query_id, processed_data = result
            if processed_data is not None:
                processed_results[query_id] = processed_data
                successful_files.append(filepath)
                logging.info(f"✓ Success for query ID {query_id}")
            else:
                logging.warning(f"✗ Failed for query ID {query_id}")
        
        return processed_results, successful_files

# === File Manager and consigne.json Update ===
async def load_consigne_data() -> Optional[Dict]:
    """Load instruction data from consigne.json asynchronously"""
    try:
        if not os.path.exists(CONSIGNE_FILE):
            logging.error(f"File {CONSIGNE_FILE} does not exist")
            return None
        
        async with aiofiles.open(CONSIGNE_FILE, 'r', encoding='utf-8') as f:
            content = await f.read()
            return json.loads(content)
    except Exception as e:
        logging.error(f"Error loading {CONSIGNE_FILE}: {e}")
        return None

async def update_consigne_data(consigne_data: Dict, processed_results: Dict[int, Dict]) -> bool:
    """Update consigne.json with processed results"""
    try:
        # Update queries with results
        for query in consigne_data.get('queries', []):
            query_id = query.get('id')
            if query_id in processed_results:
                result_data = processed_results[query_id]
                # Overwrite existing data with new
                query.update({
                    'top_keywords': result_data.get('top_keywords', ''),
                    'word_count': result_data.get('word_count', 0),
                    'plan': result_data.get('plan', {}),
                    'semantic_analysis': result_data.get('semantic_analysis', {}),
                    'differentiating_angles': result_data.get('differentiating_angles', [])
                })
                logging.info(f"✓ Query ID {query_id} updated in consigne.json")
        
        # Save updated file
        async with aiofiles.open(CONSIGNE_FILE, 'w', encoding='utf-8') as f:
            content = json.dumps(consigne_data, indent=4, ensure_ascii=False)
            await f.write(content)
        
        logging.info(f"✓ File {CONSIGNE_FILE} updated with {len(processed_results)} results")
        return True
        
    except Exception as e:
        logging.error(f"Error updating {CONSIGNE_FILE}: {e}")
        return False

async def update_processed_queries(processed_results: Dict[int, Dict], consigne_data: Dict) -> bool:
    """Update processed_queries.json file with semantic information"""
    try:
        processed_file = os.path.join(BASE_DIR, "processed_queries.json")
        
        # Load existing data
        processed_data = {}
        if os.path.exists(processed_file):
            try:
                async with aiofiles.open(processed_file, 'r', encoding='utf-8') as f:
                    content = await f.read()
                    processed_data = json.loads(content)
            except Exception as e:
                logging.warning(f"Error loading {processed_file}: {e}")
                processed_data = {"processed_queries": [], "query_details": {}}
        else:
            processed_data = {"processed_queries": [], "query_details": {}}
        
        # Function to generate query hash
        import hashlib
        def generate_query_hash(query_text: str) -> str:
            return hashlib.md5(query_text.lower().strip().encode('utf-8')).hexdigest()
        
        # Update details for each processed query
        for query_id, result in processed_results.items():
            # Find corresponding query in consigne_data
            query_info = None
            for query in consigne_data.get('queries', []):
                if query.get('id') == query_id:
                    query_info = query
                    break
            
            if query_info:
                query_text = query_info.get('text', '')
                query_hash = generate_query_hash(query_text)
                
                # Add hash to processed queries list if not there
                if query_hash not in processed_data.get("processed_queries", []):
                    processed_data.setdefault("processed_queries", []).append(query_hash)
                
                # Update or create query details
                if "query_details" not in processed_data:
                    processed_data["query_details"] = {}
                
                if query_hash not in processed_data["query_details"]:
                    processed_data["query_details"][query_hash] = {
                        'id': query_id,
                        'text': query_text,
                        'processed_at': None
                    }
                
                # Add semantic information
                processed_data["query_details"][query_hash].update({
                    'semantic': 1,  # 1 = semantic processing success
                    'semantic_processed_at': __import__('time').strftime('%Y-%m-%d %H:%M:%S'),
                    'semantic_analysis': {
                        'clusters_count': result.get('semantic_analysis', {}).get('clusters_count', 0),
                        'relations_found': result.get('semantic_analysis', {}).get('relations_found', 0),
                        'entities_count': len(result.get('semantic_analysis', {}).get('entities', [])),
                        'angles_generated': len(result.get('differentiating_angles', [])),
                        'thematic_diversity': result.get('semantic_analysis', {}).get('thematic_diversity', 0),
                        'semantic_complexity': result.get('semantic_analysis', {}).get('semantic_complexity', 0)
                    }
                })
                logging.info(f"✓ Semantic details added for query ID {query_id} (hash: {query_hash[:8]})")
        
        # Mark failed queries (semantic = 0)
        for query in consigne_data.get('queries', []):
            query_id = query.get('id')
            if query_id not in processed_results:
                query_text = query.get('text', '')
                query_hash = generate_query_hash(query_text)
                
                if query_hash in processed_data.get("query_details", {}):
                    # Query was already in processed_queries but semantic processing failed
                    processed_data["query_details"][query_hash]['semantic'] = 0
                    processed_data["query_details"][query_hash]['semantic_processed_at'] = __import__('time').strftime('%Y-%m-%d %H:%M:%S')
                    logging.info(f"✗ Semantic processing failed for query ID {query_id} (hash: {query_hash[:8]})")
        
        # Update metadata
        processed_data.update({
            'last_updated': __import__('time').strftime('%Y-%m-%d %H:%M:%S'),
            'total_processed': len(processed_data.get("processed_queries", [])),
            'semantic_processed': len([q for q in processed_data.get("query_details", {}).values() if q.get('semantic') == 1])
        })
        
        # Save updated file
        async with aiofiles.open(processed_file, 'w', encoding='utf-8') as f:
            content = json.dumps(processed_data, indent=2, ensure_ascii=False)
            await f.write(content)
        
        semantic_count = processed_data.get('semantic_processed', 0)
        logging.info(f"✓ File {os.path.basename(processed_file)} updated with {semantic_count} semantic processings")
        return True
        
    except Exception as e:
        logging.error(f"Error updating processed_queries.json: {e}")
        return False

async def cleanup_processed_files(successful_files: List[str]) -> None:
    """Delete successfully processed SERP files"""
    try:
        for filepath in successful_files:
            if os.path.exists(filepath):
                os.remove(filepath)
                logging.info(f"✓ File deleted: {os.path.basename(filepath)}")
        
        logging.info(f"✓ Cleanup completed: {len(successful_files)} files deleted")
        
    except Exception as e:
        logging.error(f"Error during file cleanup: {e}")

# === Statistics Display Function ===
def display_batch_summary(processed_results: Dict[int, Dict], total_files: int) -> None:
    """Display detailed batch processing summary"""
    print("\n" + "="*80)
    print("                    BATCH PROCESSING SUMMARY")
    print("="*80)
    
    # General statistics
    success_count = len(processed_results)
    success_rate = (success_count / total_files * 100) if total_files > 0 else 0
    
    print(f"📊 GENERAL STATISTICS:")
    print(f"   • Successfully processed files: {success_count}/{total_files} ({success_rate:.1f}%)")
    print(f"   • Failed files: {total_files - success_count}")
    
    if processed_results:
        # Aggregated metrics
        total_keywords = sum(len(result.get('top_keywords', '').split(',')) for result in processed_results.values())
        total_angles = sum(len(result.get('differentiating_angles', [])) for result in processed_results.values())
        avg_clusters = np.mean([result.get('semantic_analysis', {}).get('clusters_count', 0) for result in processed_results.values()])
        avg_complexity = np.mean([result.get('semantic_analysis', {}).get('semantic_complexity', 0) for result in processed_results.values()])
        
        print(f"\n🔍 AGGREGATED SEMANTIC METRICS:")
        print(f"   • Total keywords generated: {total_keywords}")
        print(f"   • Total differentiating angles: {total_angles}")
        print(f"   • Average clusters per query: {avg_clusters:.1f}")
        print(f"   • Average semantic complexity: {avg_complexity:.2f}/1.0")
        
        # Top 3 queries by complexity
        sorted_by_complexity = sorted(
            processed_results.items(), 
            key=lambda x: x[1].get('semantic_analysis', {}).get('semantic_complexity', 0),
            reverse=True
        )
        
        print(f"\n🎯 TOP 3 MOST COMPLEX QUERIES:")
        for i, (query_id, result) in enumerate(sorted_by_complexity[:3], 1):
            complexity = result.get('semantic_analysis', {}).get('semantic_complexity', 0)
            main_kw = result.get('main_keyword', 'N/A')[:50]
            print(f"   {i}. ID {query_id}: {main_kw} (complexity: {complexity:.2f})")
        
        # Preview of generated angles
        sample_angles = []
        for result in list(processed_results.values())[:3]:
            angles = result.get('differentiating_angles', [])
            if angles:
                sample_angles.append(angles[0][:80] + "..." if len(angles[0]) > 80 else angles[0])
        
        if sample_angles:
            print(f"\n💡 SAMPLE DIFFERENTIATING ANGLES GENERATED:")
            for i, angle in enumerate(sample_angles, 1):
                print(f"   {i}. {angle}")
    
    print(f"\n📁 FILES:")
    print(f"   • consigne.json updated with {success_count} enriched queries")
    print(f"   • {success_count} SERP files deleted after processing")
    
    print("\n" + "="*80)
    print("Batch processing completed successfully!")
    print("="*80 + "\n")

# === Main Async Function ===
async def main():
    """Main function for batch processing SERP files"""
    try:
        logging.info("=== STARTING SERP BATCH PROCESSING ===")
        
        # Configuration check
        if not async_client:
            logging.warning("Degraded mode enabled (no OpenAI API key)")
        else:
            logging.info("Full mode enabled (with OpenAI API)")
        
        # Load instruction data
        logging.info("Loading consigne.json...")
        consigne_data = await load_consigne_data()
        if not consigne_data:
            logging.error("Unable to load consigne.json. Stopping program.")
            return False
        
        # Search for matching SERP files
        logging.info("Searching for matching SERP files...")
        file_matches = find_matching_files(consigne_data)
        
        if not file_matches:
            logging.warning("No matching SERP files found.")
            return True
        
        total_files = len(file_matches)
        logging.info(f"Found {total_files} SERP files to process")
        
        # Parallel file processing
        logging.info("Starting parallel processing...")
        processor = BatchSerpProcessor()
        processed_results, successful_files = await processor.process_files_batch(file_matches)
        
        if not processed_results:
            logging.warning("No files processed successfully.")
            return False
        
        # Update consigne.json
        logging.info("Updating consigne.json...")
        update_success = await update_consigne_data(consigne_data, processed_results)
        
        if not update_success:
            logging.error("Error updating consigne.json")
            return False
        
        # Update processed_queries.json with semantic information
        logging.info("Updating processed_queries.json...")
        processed_queries_success = await update_processed_queries(processed_results, consigne_data)
        
        if not processed_queries_success:
            logging.error("Error updating processed_queries.json")
            return False
        
        # Clean up processed files
        logging.info("Cleaning up processed files...")
        await cleanup_processed_files(successful_files)
        
        # Display summary
        display_batch_summary(processed_results, total_files)
        
        logging.info("=== BATCH PROCESSING COMPLETED SUCCESSFULLY ===")
        return True
        
    except KeyboardInterrupt:
        logging.info("Processing interrupted by user")
        return False
    except Exception as e:
        logging.error(f"Critical error in main program: {str(e)}")
        return False

# === Script Entry Point ===
if __name__ == "__main__":
    # Windows configuration
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    
    success = asyncio.run(main())
    exit_code = 0 if success else 1
    exit(exit_code)