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

# === Configuration initiale ===
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

try:
    stopwords.words('french')
except LookupError:
    nltk.download('stopwords')

# === Configuration API OpenAI ===
api_key = os.getenv('OPENAI_API_KEY')
if not api_key:
    logging.warning("Aucune clé API OpenAI trouvée dans les variables d'environnement")
    async_client = None
else:
    async_client = AsyncOpenAI(api_key=api_key)
    logging.info("Clé API OpenAI chargée pour traitement async")

# === Fichiers et dossiers ===
BASE_DIR = os.path.dirname(__file__)
RESULTS_DIR = os.path.join(BASE_DIR, "results")

def _find_consigne_file() -> str:
    """Trouve automatiquement le fichier de consigne dans le dossier static"""
    consigne_pattern = os.path.join(BASE_DIR, "static", "consigne*.json")
    consigne_files = glob.glob(consigne_pattern)
    
    if not consigne_files:
        raise FileNotFoundError(f"❌ Aucun fichier de consigne trouvé dans {os.path.join(BASE_DIR, 'static')}/ (pattern: consigne*.json)")
    
    if len(consigne_files) == 1:
        found_file = consigne_files[0]
        logging.info(f"📁 Fichier de consigne détecté: {os.path.basename(found_file)}")
        return found_file
    
    # Si plusieurs fichiers trouvés, prendre le plus récent
    consigne_files.sort(key=os.path.getmtime, reverse=True)
    most_recent = consigne_files[0]
    logging.info(f"📁 Plusieurs fichiers de consigne trouvés, utilisation du plus récent: {os.path.basename(most_recent)}")
    logging.info(f"   Autres fichiers ignorés: {', '.join([os.path.basename(f) for f in consigne_files[1:]])}")
    return most_recent

CONSIGNE_FILE = _find_consigne_file()

# === Configuration parallélisation ===
MAX_WORKERS_IO = 4  # Pour les opérations I/O
MAX_WORKERS_CPU = 2  # Pour les modèles BERT/spaCy
MAX_CONCURRENT_API = 3  # Pour les appels OpenAI simultanés

# === Fonction de calcul du plan (inchangée) ===
def calculate_sections(word_count):
    """Calcule la structure du plan en fonction du nombre de mots"""
    intro_concl = 225
    available_words = word_count - (intro_concl * 2)
    num_sections = round(available_words / 325) if available_words > 0 else 0
    words_per_section = available_words / num_sections if num_sections > 0 else 0
    return {
        'introduction': {'longueur': intro_concl},
        'developpement': {'nombre_sections': num_sections, 'mots_par_section': round(words_per_section, 1)},
        'conclusion': {'longueur': intro_concl}
    }

# === Utilitaires de correspondance ===
def normalize_text_for_filename(text: str) -> str:
    """Normalise un texte pour correspondre au format filename"""
    # Remplacer les espaces par des underscores et nettoyer
    normalized = re.sub(r'[^\w\s]', '', text.lower())
    normalized = re.sub(r'\s+', '_', normalized.strip())
    return normalized

def find_matching_files(consigne_data: Dict) -> List[Tuple[str, Dict]]:
    """Trouve les fichiers SERP correspondant aux requêtes de consigne.json"""
    if not os.path.exists(RESULTS_DIR):
        logging.error(f"Le dossier {RESULTS_DIR} n'existe pas")
        return []
    
    pattern = os.path.join(RESULTS_DIR, "serp_*.json")
    serp_files = glob.glob(pattern)
    logging.info(f"Trouvé {len(serp_files)} fichiers SERP dans {RESULTS_DIR}")
    
    matches = []
    queries = consigne_data.get('queries', [])
    
    for filepath in serp_files:
        filename = os.path.basename(filepath)
        
        # Extraction de l'ID depuis le nom de fichier (serp_XXX_...)
        id_match = re.match(r'serp_(\d{3})_(.+)\.json', filename)
        if not id_match:
            logging.warning(f"Format de fichier non reconnu: {filename}")
            continue
        
        file_id = int(id_match.group(1))
        file_text_part = id_match.group(2)
        
        # Recherche de la requête correspondante - logique améliorée
        matching_query = None
        for query in queries:
            if query.get('id') == file_id:
                # Correspondance par ID suffit - pas besoin de vérifier le texte exact
                # car les noms de fichiers peuvent être tronqués
                matching_query = query
                break
        
        if matching_query:
            matches.append((filepath, matching_query))
            logging.info(f"✓ Correspondance trouvée: {filename} -> requête ID {file_id} (\"{matching_query.get('text', '')[:50]}...\")")
        else:
            logging.warning(f"✗ Aucune correspondance pour: {filename} (ID {file_id} non trouvé dans consigne.json)")
    
    return matches

# === Analyseur sémantique optimisé pour parallélisation ===
class ParallelSemanticAnalyzer:
    """Version thread-safe de l'analyseur sémantique"""
    
    def __init__(self):
        self.stop_words = set(stopwords.words('french'))
        additional_stops = {
            'les', 'plus', 'cette', 'fait', 'être', 'deux',
            'comme', 'tout', 'mais', 'aussi', 'avoir', 'faire',
            'autre', 'ceci', 'cela', 'dont', 'sans', 'sous', 'entre'
        }
        self.stop_words.update(additional_stops)
    
    def _init_models(self):
        """Initialise les modèles dans le thread worker avec fallback"""
        try:
            # Essayer d'abord le modèle large, puis les alternatives
            models_to_try = ['fr_core_news_lg']
            
            self.nlp = None
            for model_name in models_to_try:
                try:
                    self.nlp = spacy.load(model_name)
                    logging.info(f"✓ Modèle spaCy chargé: {model_name}")
                    break
                except Exception as e:
                    logging.warning(f"Modèle {model_name} non disponible: {e}")
                    continue
            
            if self.nlp is None:
                logging.error("Aucun modèle spaCy français disponible")
                return False
            
            # Charger le modèle SentenceTransformer
            try:
                self.sentence_model = SentenceTransformer('distiluse-base-multilingual-cased', device='cpu')
                logging.info("✓ Modèle SentenceTransformer chargé")
            except Exception as e:
                logging.error(f"Erreur lors du chargement de SentenceTransformer: {e}")
                return False
            
            # Ajouter les stop words spaCy
            self.stop_words.update(self.nlp.Defaults.stop_words)
            return True
            
        except Exception as e:
            logging.error(f"Erreur lors du chargement des modèles : {str(e)}")
            return False
    
    def extract_entities(self, text: str) -> List[Dict]:
        """Extraction des entités nommées avec spaCy"""
        if not hasattr(self, 'nlp'):
            if not self._init_models():
                return []
        
        doc = self.nlp(text)
        entities = []
        for ent in doc.ents:
            if ent.label_ in ["PERSON", "ORG", "PRODUCT", "LOC", "MISC"]:
                entities.append({
                    "text": ent.text,
                    "label": ent.label_,
                    "start": ent.start_char,
                    "end": ent.end_char
                })
        return entities
    
    def extract_key_phrases(self, text: str, max_phrases: int = 20) -> List[str]:
        """Extraction des expressions clés importantes"""
        if not hasattr(self, 'nlp'):
            if not self._init_models():
                return []
        
        doc = self.nlp(text)
        phrases = []
        
        # Extraction des chunks nominaux
        for chunk in doc.noun_chunks:
            if len(chunk.text.split()) <= 3 and len(chunk.text) > 3:
                phrases.append(chunk.text.lower().strip())
        
        # Extraction des patterns syntaxiques intéressants
        for token in doc:
            if token.pos_ in ["NOUN", "ADJ"] and token.dep_ in ["nsubj", "dobj", "amod"]:
                if token.head.pos_ == "NOUN":
                    phrase = f"{token.text} {token.head.text}".lower()
                    phrases.append(phrase)
        
        # Déduplication et filtrage
        unique_phrases = list(set(phrases))
        return unique_phrases[:max_phrases]
    
    def cluster_keywords_semantic(self, keywords: List[str], n_clusters: int = 5) -> Dict[str, List[str]]:
        """Clustering sémantique des mots-clés avec BERT"""
        if len(keywords) < n_clusters:
            return {"cluster_0": keywords}
        
        try:
            if not hasattr(self, 'sentence_model'):
                if not self._init_models():
                    return {"cluster_0": keywords}
            
            # Génération des embeddings avec SentenceTransformer
            embeddings = self.sentence_model.encode(keywords)
            
            # Clustering K-means
            kmeans = KMeans(n_clusters=n_clusters, random_state=42)
            cluster_labels = kmeans.fit_predict(embeddings)
            
            # Organisation par clusters
            clusters = defaultdict(list)
            for keyword, label in zip(keywords, cluster_labels):
                clusters[f"cluster_{label}"].append(keyword)
            
            return dict(clusters)
            
        except Exception as e:
            logging.warning(f"Erreur lors du clustering : {str(e)}")
            return {"cluster_0": keywords}
    
    def analyze_semantic_relations(self, text: str) -> List[Dict]:
        """Analyse des relations sémantiques dans le texte"""
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

# === Nettoyeur de contenu HTML (thread-safe) ===
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
        """Nettoie le contenu HTML pour extraire le texte"""
        if not html_content:
            return ""
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Suppression des commentaires
            for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
                comment.extract()
            
            # Suppression des tags indésirables
            for tag in self.remove_tags:
                for element in soup.find_all(tag):
                    element.decompose()
            
            # Conservation seulement des tags utiles
            if self.keep_tags:
                for tag in soup.find_all():
                    if tag.name not in self.keep_tags:
                        tag.unwrap()
            
            return soup.get_text(separator=' ', strip=True)
        except Exception as e:
            logging.warning(f"Erreur lors du nettoyage HTML: {e}")
            return ""

    def remove_unwanted_content(self, text: str) -> str:
        """Supprime les URLs, emails et caractères spéciaux"""
        text = self.url_pattern.sub(' ', text)
        text = self.email_pattern.sub(' ', text)
        text = self.special_chars_pattern.sub(' ', text)
        return text

    def clean_words(self, text: str) -> str:
        """Filtre les mots selon leur longueur"""
        return ' '.join(
            word.lower() for word in text.split()
            if self.min_word_length <= len(word) <= self.max_word_length
        )

    def clean_text(self, html_content: Optional[str], normalize: bool = False) -> str:
        """Pipeline complet de nettoyage de texte"""
        text = self.clean_html(html_content)
        if not text:
            return ""
        
        if normalize:
            text = unicodedata.normalize('NFKD', text)
            text = text.encode('ASCII', 'ignore').decode('ASCII')
        
        text = self.remove_unwanted_content(text)
        text = self.clean_words(text)
        return self.whitespace_pattern.sub(' ', text).strip()

# === Processeur de fichier SERP individuel ===
class SerpFileProcessor:
    def __init__(self):
        self.semantic_analyzer = ParallelSemanticAnalyzer()
        self.text_cleaner = ThreadSafeTextCleaner()
    
    def preprocess_text(self, text: str) -> List[str]:
        """Prétraite le texte pour l'analyse TF-IDF"""
        try:
            if not hasattr(self.semantic_analyzer, 'nlp'):
                if not self.semantic_analyzer._init_models():
                    return []
            
            doc = self.semantic_analyzer.nlp(text)
            return [token.lemma_.lower() for token in doc 
                    if token.is_alpha and len(token.text) > 2 and token.lemma_.lower() not in self.semantic_analyzer.stop_words]
        except Exception as e:
            logging.warning(f"Erreur lors de la normalisation du texte : {str(e)}")
            return []
    
    def calculate_serp_weight(self, position: int) -> float:
        """Calcule le poids d'un résultat SERP selon sa position"""
        return 1 / np.log2(position + 2)
    
    def calculate_weighted_tfidf(self, documents: List[Dict]) -> Tuple[Dict[str, float], List[str]]:
        """Calcule le TF-IDF pondéré par la position SERP"""
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
            logging.error(f"Erreur lors du calcul du TF-IDF : {str(e)}")
            return {}, []
    
    def extract_text_from_html(self, html_content: str) -> str:
        """Extrait le texte propre depuis le contenu HTML"""
        return self.text_cleaner.clean_text(html_content, normalize=False)
    
    def _suggest_entity_angle(self, entity_text: str, entity_type: str) -> str:
        """Suggère un angle potentiel basé sur une entité"""
        angle_suggestions = {
            "PERSON": f"Perspective/témoignage de {entity_text}",
            "ORG": f"Analyse comparative avec {entity_text}",
            "PRODUCT": f"Étude de cas avec {entity_text}",
            "LOC": f"Contexte géographique de {entity_text}",
            "MISC": f"Aspect spécialisé via {entity_text}"
        }
        return angle_suggestions.get(entity_type, f"Angle unique via {entity_text}")

    def _suggest_relation_angle(self, relation: Dict) -> str:
        """Suggère un angle basé sur une relation sémantique"""
        relation_type = relation.get('relation', '')
        head = relation.get('head', '')
        dependent = relation.get('dependent', '')
        
        if relation_type == 'nsubj':
            return f"Focus sur l'impact de {dependent} sur {head}"
        elif relation_type == 'dobj':
            return f"Analyse de l'interaction {head}-{dependent}"
        elif relation_type == 'prep':
            return f"Contexte relationnel {head}-{dependent}"
        else:
            return f"Connexion {head}-{dependent} à explorer"

    def _identify_cluster_theme(self, keywords: List[str]) -> str:
        """Identifie le thème principal d'un cluster"""
        if not keywords:
            return "Thème indéterminé"
        
        # Analyse basique des patterns lexicaux
        technical_words = sum(1 for kw in keywords if any(tech in kw.lower() for tech in ['technique', 'technologie', 'digital', 'numérique']))
        business_words = sum(1 for kw in keywords if any(biz in kw.lower() for biz in ['business', 'entreprise', 'marché', 'vente']))
        user_words = sum(1 for kw in keywords if any(user in kw.lower() for user in ['utilisateur', 'client', 'personne', 'humain']))
        
        if technical_words > business_words and technical_words > user_words:
            return "Aspects techniques"
        elif business_words > user_words:
            return "Enjeux business"
        elif user_words > 0:
            return "Dimension humaine"
        else:
            return "Thème général"

    def _suggest_cluster_angles(self, keywords: List[str], cluster_name: str) -> List[str]:
        """Suggère des angles différenciants pour un cluster"""
        theme = self._identify_cluster_theme(keywords)
        base_angles = []
        
        if "technique" in theme.lower():
            base_angles = [
                f"Approche technique innovante via {', '.join(keywords[:3])}",
                f"Défis techniques autour de {keywords[0] if keywords else 'ce domaine'}"
            ]
        elif "business" in theme.lower():
            base_angles = [
                f"ROI et impacts business de {', '.join(keywords[:3])}",
                f"Stratégies concurrentielles autour de {keywords[0] if keywords else 'ce secteur'}"
            ]
        elif "humain" in theme.lower():
            base_angles = [
                f"Expérience utilisateur centrée sur {', '.join(keywords[:3])}",
                f"Impact humain de {keywords[0] if keywords else 'cette dimension'}"
            ]
        else:
            base_angles = [
                f"Perspective unique sur {', '.join(keywords[:3])}",
                f"Angle novateur via {keywords[0] if keywords else 'ce cluster'}"
            ]
        
        return base_angles

    def _calculate_thematic_diversity(self, clusters: Dict) -> float:
        """Calcule un score de diversité thématique"""
        if not clusters:
            return 0.0
        
        cluster_sizes = [len(keywords) for keywords in clusters.values()]
        if not cluster_sizes:
            return 0.0
        
        # Mesure basée sur la distribution des tailles de clusters
        avg_size = np.mean(cluster_sizes)
        size_variance = np.var(cluster_sizes)
        
        # Score normalisé (plus c'est équilibré, plus c'est diversifié)
        diversity_score = min(1.0, avg_size / (1 + size_variance)) * len(clusters) / 5
        return round(diversity_score, 2)

    def _calculate_semantic_complexity(self, relations: List[Dict], entities: List[Dict]) -> float:
        """Calcule un score de complexité sémantique"""
        if not relations and not entities:
            return 0.0
        
        # Score basé sur le nombre et la diversité des relations et entités
        relation_diversity = len(set(rel.get('relation', '') for rel in relations))
        entity_diversity = len(set(ent.get('label', '') for ent in entities))
        
        complexity_score = (len(relations) * 0.6 + len(entities) * 0.4) * (relation_diversity + entity_diversity) / 20
        return round(min(1.0, complexity_score), 2)

    def _generate_local_angles(self, context: Dict) -> List[str]:
        """Génère des angles basiques quand GPT n'est pas disponible"""
        angles = []
        
        # Angles basés sur les clusters
        for cluster_name, cluster_data in context.get("clusters_thematiques", {}).items():
            theme = cluster_data.get("theme_principal", "")
            if theme and cluster_data.get("mots_cles"):
                angles.extend(cluster_data.get("angles_differenciants", []))
        
        # Angles basés sur les entités
        for entity in context.get("entites_importantes", [])[:3]:
            angles.append(entity.get("potentiel_angle", ""))
        
        # Angles basés sur les relations
        for relation in context.get("relations_semantiques", [])[:2]:
            angles.append(relation.get("angle_potentiel", ""))
        
        # Nettoyage et limitation
        clean_angles = [angle for angle in angles if angle and len(angle) > 10]
        return clean_angles[:10]

    def _parse_angles_from_gpt(self, gpt_response: str) -> List[str]:
        """Parse la réponse GPT pour extraire les angles"""
        angles = []
        lines = gpt_response.split('\n')
        
        current_angle = ""
        for line in lines:
            line = line.strip()
            if re.match(r'^\d+\.', line):  # Ligne commençant par un numéro
                if current_angle:
                    angles.append(current_angle.strip())
                current_angle = re.sub(r'^\d+\.\s*', '', line)
            elif line and current_angle:
                current_angle += " " + line
        
        # Ajouter le dernier angle
        if current_angle:
            angles.append(current_angle.strip())
        
        return angles[:10]
    
    async def process_file(self, filepath: str, query_data: Dict) -> Optional[Dict]:
        """Traite un fichier SERP individuel de manière asynchrone"""
        try:
            logging.info(f"Début du traitement de {os.path.basename(filepath)}")
            
            # Chargement du fichier SERP
            async with aiofiles.open(filepath, 'r', encoding='utf-8') as f:
                content = await f.read()
                serp_data = json.loads(content)
            
            if not serp_data.get('success') or not serp_data.get('organicResults'):
                logging.warning(f"Données SERP invalides dans {filepath}")
                return None
            
            main_keyword = query_data.get('text', '')
            logging.info(f"Analyse sémantique pour : {main_keyword}")
            
            # === 1. Extraction et préparation des documents ===
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
                logging.warning(f"Aucun document valide trouvé dans {filepath}")
                return None

            # === 2. Analyse sémantique avancée (en thread pool) ===
            loop = asyncio.get_event_loop()
            with ThreadPoolExecutor(max_workers=1) as executor:
                # Exécution des tâches CPU-intensives dans un thread
                entities_task = loop.run_in_executor(executor, self.semantic_analyzer.extract_entities, full_corpus_text)
                key_phrases_task = loop.run_in_executor(executor, self.semantic_analyzer.extract_key_phrases, full_corpus_text)
                relations_task = loop.run_in_executor(executor, self.semantic_analyzer.analyze_semantic_relations, full_corpus_text)
                tfidf_task = loop.run_in_executor(executor, self.calculate_weighted_tfidf, documents)
                
                # Attendre tous les résultats
                entities, key_phrases, relations, (weighted_scores, _) = await asyncio.gather(
                    entities_task, key_phrases_task, relations_task, tfidf_task
                )
            
            if not weighted_scores:
                logging.warning(f"Échec du calcul des scores TF-IDF pour {filepath}")
                return None

            # === 3. Sélection et clustering des mots-clés ===
            threshold = np.percentile(list(weighted_scores.values()), 75)
            important_terms = {
                term: score for term, score in weighted_scores.items()
                if score <= 5000 and score > threshold
            }
            
            # Ajout des expressions clés importantes
            for phrase in key_phrases:
                if phrase not in important_terms:
                    important_terms[phrase] = np.mean(list(important_terms.values())) if important_terms else 1.0
            
            # Clustering sémantique (en thread pool)
            keywords_list = list(important_terms.keys())
            with ThreadPoolExecutor(max_workers=1) as executor:
                clusters = await loop.run_in_executor(
                    executor, 
                    self.semantic_analyzer.cluster_keywords_semantic, 
                    keywords_list
                )
            
            # === 4. Création du contexte enrichi ===
            enriched_context = {
                "sujet_principal": main_keyword,
                "entites_importantes": [
                    {
                        "nom": ent["text"],
                        "type": ent["label"],
                        "potentiel_angle": self._suggest_entity_angle(ent["text"], ent["label"])
                    }
                    for ent in entities[:10]
                ],
                "clusters_thematiques": {},
                "relations_semantiques": [
                    {
                        "relation": f"{rel['head']} -> {rel['relation']} -> {rel['dependent']}",
                        "contexte": rel['context'][:80] + "..." if len(rel['context']) > 80 else rel['context'],
                        "angle_potentiel": self._suggest_relation_angle(rel)
                    }
                    for rel in relations[:8]
                ],
                "statistiques_semantiques": {
                    "nombre_clusters": len(clusters),
                    "nombre_relations": len(relations),
                    "nombre_entites": len(entities),
                    "diversite_thematique": self._calculate_thematic_diversity(clusters),
                    "complexite_semantique": self._calculate_semantic_complexity(relations, entities)
                }
            }
            
            # Organisation des clusters avec angles différenciants
            for cluster_name, cluster_keywords in clusters.items():
                cluster_scores = {kw: important_terms.get(kw, 0) for kw in cluster_keywords}
                top_cluster_keywords = sorted(cluster_scores.items(), key=lambda x: x[1], reverse=True)[:8]
                
                enriched_context["clusters_thematiques"][cluster_name] = {
                    "mots_cles": [kw for kw, _ in top_cluster_keywords],
                    "scores": {kw: score for kw, score in top_cluster_keywords},
                    "theme_principal": self._identify_cluster_theme(cluster_keywords),
                    "angles_differenciants": self._suggest_cluster_angles(cluster_keywords, cluster_name)
                }

            # === 5. Appel à GPT avec gestion des limites de concurrence ===
            refined_keywords = ""
            differentiating_angles = []
            
            try:
                if not enriched_context["clusters_thematiques"]:
                    logging.warning(f"Aucun cluster thématique pour {filepath}, utilisation du fallback")
                    refined_keywords = ", ".join(keywords_list[:60])
                elif async_client is None:
                    logging.warning(f"Clé API OpenAI manquante pour {filepath}, utilisation du clustering local")
                    all_clustered_keywords = []
                    for cluster_data in enriched_context["clusters_thematiques"].values():
                        all_clustered_keywords.extend(cluster_data["mots_cles"])
                    refined_keywords = ", ".join(all_clustered_keywords[:60])
                    differentiating_angles = self._generate_local_angles(enriched_context)
                else:
                    # Appels API OpenAI en parallèle
                    context_str = json.dumps(enriched_context, ensure_ascii=False, indent=2)
                    
                    # Créer les deux tâches API
                    keywords_task = async_client.chat.completions.create(
                        model="gpt-4o",
                        messages=[
                            {
                                "role": "system",
                                "content": (
                                    "Tu es un expert en SEO et en analyse sémantique. Analyse ce corpus SERP "
                                    "et retourne 60 mots-clés stratégiques qui couvrent tous les aspects importants "
                                    "du sujet. Organise-les logiquement et retourne uniquement la liste séparée par des virgules."
                                )
                            },
                            {
                                "role": "user",
                                "content": f"Analyse sémantique du sujet '{main_keyword}':\n{context_str}"
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
                                    "Tu es un expert en stratégie de contenu. "
                                    "À partir de cette analyse sémantique détaillée (clusters, entités, relations), "
                                    "identifie 10 angles différenciants et originaux pour traiter ce sujet. "
                                    "Chaque angle doit exploiter les insights sémantiques pour se démarquer de la concurrence. "
                                    "Format : liste numérotée avec titre et brève explication (2-3 lignes max par angle)."
                                )
                            },
                            {
                                "role": "user",
                                "content": (
                                    f"REQUÊTE CIBLE (OBLIGATOIRE) : '{main_keyword}'\n"
                                    f"⚠️ IMPORTANT : Tous les angles DOIVENT répondre directement à cette requête exacte. C'est ce que les utilisateurs tapent dans Google.\n\n"
                                    f"Contexte sémantique :\n{context_str}\n\n"
                                    "Trouve des angles uniques qui :\n"
                                    f"1. RÉPONDENT DIRECTEMENT à la requête '{main_keyword}'\n"
                                    f"2. Correspondent à l'intention de recherche de cette requête spécifique\n"
                                    "3. Exploitent les relations sémantiques inattendues\n" 
                                    "4. Utilisent les connexions entre clusters\n"
                                    "5. Mettent en avant les entités peu exploitées\n"
                                    "6. Couvrent les aspects sous-représentés dans la SERP\n\n"
                                    f"Chaque angle doit expliquer comment il répond spécifiquement à '{main_keyword}'."
                                )
                            }
                        ],
                        temperature=0.8,
                        max_tokens=1500,
                        timeout=45
                    )
    
                    
                    # Attendre les deux réponses en parallèle
                    keywords_response, angles_response = await asyncio.gather(
                        keywords_task, angles_task, return_exceptions=True
                    )
                    
                    # Traitement des réponses
                    if isinstance(keywords_response, Exception):
                        logging.error(f"Erreur lors de l'appel keywords API : {keywords_response}")
                        all_clustered_keywords = []
                        for cluster_data in enriched_context["clusters_thematiques"].values():
                            all_clustered_keywords.extend(cluster_data["mots_cles"])
                        refined_keywords = ", ".join(all_clustered_keywords[:60])
                    else:
                        refined_keywords = keywords_response.choices[0].message.content.strip()
                    
                    if isinstance(angles_response, Exception):
                        logging.error(f"Erreur lors de l'appel angles API : {angles_response}")
                        differentiating_angles = self._generate_local_angles(enriched_context)
                    else:
                        differentiating_angles_text = angles_response.choices[0].message.content.strip()
                        differentiating_angles = self._parse_angles_from_gpt(differentiating_angles_text)
                    
                    logging.info(f"Analyse sémantique avancée générée avec GPT pour {os.path.basename(filepath)}")
                        
            except Exception as e:
                logging.error(f"Erreur lors de l'appel à l'API OpenAI pour {filepath} : {str(e)}")
                # Fallback intelligent
                all_clustered_keywords = []
                for cluster_data in enriched_context["clusters_thematiques"].values():
                    all_clustered_keywords.extend(cluster_data["mots_cles"])
                refined_keywords = ", ".join(all_clustered_keywords[:60])
                differentiating_angles = self._generate_local_angles(enriched_context)
                logging.info(f"Utilisation du clustering sémantique comme fallback pour {os.path.basename(filepath)}")

            # === 6. Construction du résultat final ===
            result = {
                'main_keyword': main_keyword,
                'top_keywords': refined_keywords,
                'word_count': max_word_count,
                'plan': calculate_sections(max_word_count),
                'semantic_analysis': {
                    'entities': [ent["nom"] for ent in enriched_context["entites_importantes"][:5]],
                    'clusters_count': enriched_context["statistiques_semantiques"]["nombre_clusters"],
                    'relations_found': enriched_context["statistiques_semantiques"]["nombre_relations"],
                    'thematic_diversity': enriched_context["statistiques_semantiques"]["diversite_thematique"],
                    'semantic_complexity': enriched_context["statistiques_semantiques"]["complexite_semantique"]
                },
                'differentiating_angles': differentiating_angles
            }
            
            logging.info(f"✓ Traitement terminé avec succès pour {os.path.basename(filepath)}")
            return result
            
        except Exception as e:
            logging.error(f"Erreur lors du traitement de {filepath} : {str(e)}")
            return None

# === Gestionnaire de traitement en lots ===
class BatchSerpProcessor:
    def __init__(self):
        self.semaphore = asyncio.Semaphore(MAX_CONCURRENT_API)
    
    async def process_files_batch(self, file_matches: List[Tuple[str, Dict]]) -> Dict[int, Dict]:
        """Traite tous les fichiers SERP en parallèle avec limitation de concurrence"""
        
        async def process_with_semaphore(filepath: str, query_data: Dict) -> Tuple[int, Optional[Dict]]:
            async with self.semaphore:  # Limite la concurrence des appels API
                processor = SerpFileProcessor()
                result = await processor.process_file(filepath, query_data)
                return query_data['id'], result
        
        # Créer toutes les tâches
        tasks = [
            process_with_semaphore(filepath, query_data) 
            for filepath, query_data in file_matches
        ]
        
        # Exécuter toutes les tâches avec limitation de concurrence
        logging.info(f"Début du traitement en parallèle de {len(tasks)} fichiers...")
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Traitement des résultats
        processed_results = {}
        successful_files = []
        
        for i, (filepath, query_data) in enumerate(file_matches):
            result = results[i]
            
            if isinstance(result, Exception):
                logging.error(f"Erreur lors du traitement de {filepath}: {result}")
                continue
            
            query_id, processed_data = result
            if processed_data is not None:
                processed_results[query_id] = processed_data
                successful_files.append(filepath)
                logging.info(f"✓ Succès pour requête ID {query_id}")
            else:
                logging.warning(f"✗ Échec pour requête ID {query_id}")
        
        return processed_results, successful_files

# === Gestionnaire de fichiers et mise à jour consigne.json ===
async def load_consigne_data() -> Optional[Dict]:
    """Charge les données de consigne.json de manière asynchrone"""
    try:
        if not os.path.exists(CONSIGNE_FILE):
            logging.error(f"Le fichier {CONSIGNE_FILE} n'existe pas")
            return None
        
        async with aiofiles.open(CONSIGNE_FILE, 'r', encoding='utf-8') as f:
            content = await f.read()
            return json.loads(content)
    except Exception as e:
        logging.error(f"Erreur lors du chargement de {CONSIGNE_FILE}: {e}")
        return None

async def update_consigne_data(consigne_data: Dict, processed_results: Dict[int, Dict]) -> bool:
    """Met à jour consigne.json avec les résultats traités"""
    try:
        # Mise à jour des requêtes avec les résultats
        for query in consigne_data.get('queries', []):
            query_id = query.get('id')
            if query_id in processed_results:
                result_data = processed_results[query_id]
                # Écraser les données existantes avec les nouvelles
                query.update({
                    'top_keywords': result_data.get('top_keywords', ''),
                    'word_count': result_data.get('word_count', 0),
                    'plan': result_data.get('plan', {}),
                    'semantic_analysis': result_data.get('semantic_analysis', {}),
                    'differentiating_angles': result_data.get('differentiating_angles', [])
                })
                logging.info(f"✓ Requête ID {query_id} mise à jour dans consigne.json")
        
        # Sauvegarde du fichier mis à jour
        async with aiofiles.open(CONSIGNE_FILE, 'w', encoding='utf-8') as f:
            content = json.dumps(consigne_data, indent=4, ensure_ascii=False)
            await f.write(content)
        
        logging.info(f"✓ Fichier {CONSIGNE_FILE} mis à jour avec {len(processed_results)} résultats")
        return True
        
    except Exception as e:
        logging.error(f"Erreur lors de la mise à jour de {CONSIGNE_FILE}: {e}")
        return False

async def update_processed_queries(processed_results: Dict[int, Dict], consigne_data: Dict) -> bool:
    """Met à jour le fichier processed_queries.json avec les informations sémantiques"""
    try:
        processed_file = os.path.join(BASE_DIR, "processed_queries.json")
        
        # Charger les données existantes
        processed_data = {}
        if os.path.exists(processed_file):
            try:
                async with aiofiles.open(processed_file, 'r', encoding='utf-8') as f:
                    content = await f.read()
                    processed_data = json.loads(content)
            except Exception as e:
                logging.warning(f"Erreur lors du chargement de {processed_file}: {e}")
                processed_data = {"processed_queries": [], "query_details": {}}
        else:
            processed_data = {"processed_queries": [], "query_details": {}}
        
        # Fonction pour générer le hash d'une requête
        import hashlib
        def generate_query_hash(query_text: str) -> str:
            return hashlib.md5(query_text.lower().strip().encode('utf-8')).hexdigest()
        
        # Mettre à jour les détails pour chaque requête traitée
        for query_id, result in processed_results.items():
            # Trouver la requête correspondante dans consigne_data
            query_info = None
            for query in consigne_data.get('queries', []):
                if query.get('id') == query_id:
                    query_info = query
                    break
            
            if query_info:
                query_text = query_info.get('text', '')
                query_hash = generate_query_hash(query_text)
                
                # Ajouter le hash à la liste des requêtes traitées s'il n'y est pas
                if query_hash not in processed_data.get("processed_queries", []):
                    processed_data.setdefault("processed_queries", []).append(query_hash)
                
                # Mettre à jour ou créer les détails de la requête
                if "query_details" not in processed_data:
                    processed_data["query_details"] = {}
                
                if query_hash not in processed_data["query_details"]:
                    processed_data["query_details"][query_hash] = {
                        'id': query_id,
                        'text': query_text,
                        'processed_at': None
                    }
                
                # Ajouter les informations sémantiques
                processed_data["query_details"][query_hash].update({
                    'semantic': 1,  # 1 = succès du traitement sémantique
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
                logging.info(f"✓ Détails sémantiques ajoutés pour la requête ID {query_id} (hash: {query_hash[:8]})")
        
        # Marquer les requêtes qui ont échoué (semantic = 0)
        for query in consigne_data.get('queries', []):
            query_id = query.get('id')
            if query_id not in processed_results:
                query_text = query.get('text', '')
                query_hash = generate_query_hash(query_text)
                
                if query_hash in processed_data.get("query_details", {}):
                    # La requête était déjà dans processed_queries mais le traitement sémantique a échoué
                    processed_data["query_details"][query_hash]['semantic'] = 0
                    processed_data["query_details"][query_hash]['semantic_processed_at'] = __import__('time').strftime('%Y-%m-%d %H:%M:%S')
                    logging.info(f"✗ Traitement sémantique échoué pour la requête ID {query_id} (hash: {query_hash[:8]})")
        
        # Mettre à jour les métadonnées
        processed_data.update({
            'last_updated': __import__('time').strftime('%Y-%m-%d %H:%M:%S'),
            'total_processed': len(processed_data.get("processed_queries", [])),
            'semantic_processed': len([q for q in processed_data.get("query_details", {}).values() if q.get('semantic') == 1])
        })
        
        # Sauvegarder le fichier mis à jour
        async with aiofiles.open(processed_file, 'w', encoding='utf-8') as f:
            content = json.dumps(processed_data, indent=2, ensure_ascii=False)
            await f.write(content)
        
        semantic_count = processed_data.get('semantic_processed', 0)
        logging.info(f"✓ Fichier {os.path.basename(processed_file)} mis à jour avec {semantic_count} traitements sémantiques")
        return True
        
    except Exception as e:
        logging.error(f"Erreur lors de la mise à jour de processed_queries.json: {e}")
        return False

async def cleanup_processed_files(successful_files: List[str]) -> None:
    """Supprime les fichiers SERP traités avec succès"""
    try:
        for filepath in successful_files:
            if os.path.exists(filepath):
                os.remove(filepath)
                logging.info(f"✓ Fichier supprimé: {os.path.basename(filepath)}")
        
        logging.info(f"✓ Nettoyage terminé: {len(successful_files)} fichiers supprimés")
        
    except Exception as e:
        logging.error(f"Erreur lors du nettoyage des fichiers: {e}")

# === Fonction d'affichage des statistiques ===
def display_batch_summary(processed_results: Dict[int, Dict], total_files: int) -> None:
    """Affiche un résumé détaillé du traitement en lot"""
    print("\n" + "="*80)
    print("                    RÉSUMÉ DU TRAITEMENT EN LOT")
    print("="*80)
    
    # Statistiques générales
    success_count = len(processed_results)
    success_rate = (success_count / total_files * 100) if total_files > 0 else 0
    
    print(f"📊 STATISTIQUES GÉNÉRALES:")
    print(f"   • Fichiers traités avec succès: {success_count}/{total_files} ({success_rate:.1f}%)")
    print(f"   • Fichiers en échec: {total_files - success_count}")
    
    if processed_results:
        # Métriques agrégées
        total_keywords = sum(len(result.get('top_keywords', '').split(',')) for result in processed_results.values())
        total_angles = sum(len(result.get('differentiating_angles', [])) for result in processed_results.values())
        avg_clusters = np.mean([result.get('semantic_analysis', {}).get('clusters_count', 0) for result in processed_results.values()])
        avg_complexity = np.mean([result.get('semantic_analysis', {}).get('semantic_complexity', 0) for result in processed_results.values()])
        
        print(f"\n🔍 MÉTRIQUES SÉMANTIQUES AGRÉGÉES:")
        print(f"   • Total mots-clés générés: {total_keywords}")
        print(f"   • Total angles différenciants: {total_angles}")
        print(f"   • Moyenne clusters par requête: {avg_clusters:.1f}")
        print(f"   • Complexité sémantique moyenne: {avg_complexity:.2f}/1.0")
        
        # Top 3 des requêtes par complexité
        sorted_by_complexity = sorted(
            processed_results.items(), 
            key=lambda x: x[1].get('semantic_analysis', {}).get('semantic_complexity', 0),
            reverse=True
        )
        
        print(f"\n🎯 TOP 3 DES REQUÊTES LES PLUS COMPLEXES:")
        for i, (query_id, result) in enumerate(sorted_by_complexity[:3], 1):
            complexity = result.get('semantic_analysis', {}).get('semantic_complexity', 0)
            main_kw = result.get('main_keyword', 'N/A')[:50]
            print(f"   {i}. ID {query_id}: {main_kw} (complexité: {complexity:.2f})")
        
        # Aperçu des angles générés
        sample_angles = []
        for result in list(processed_results.values())[:3]:
            angles = result.get('differentiating_angles', [])
            if angles:
                sample_angles.append(angles[0][:80] + "..." if len(angles[0]) > 80 else angles[0])
        
        if sample_angles:
            print(f"\n💡 EXEMPLES D'ANGLES DIFFÉRENCIANTS GÉNÉRÉS:")
            for i, angle in enumerate(sample_angles, 1):
                print(f"   {i}. {angle}")
    
    print(f"\n📁 FICHIERS:")
    print(f"   • consigne.json mis à jour avec {success_count} requêtes enrichies")
    print(f"   • {success_count} fichiers SERP supprimés après traitement")
    
    print("\n" + "="*80)
    print("Traitement en lot terminé avec succès!")
    print("="*80 + "\n")

# === Fonction principale asynchrone ===
async def main():
    """Fonction principale pour le traitement en lot des fichiers SERP"""
    try:
        logging.info("=== DÉMARRAGE DU TRAITEMENT EN LOT SERP ===")
        
        # Vérification de la configuration
        if not async_client:
            logging.warning("Mode dégradé activé (pas de clé API OpenAI)")
        else:
            logging.info("Mode complet activé (avec API OpenAI)")
        
        # Chargement des données de consigne
        logging.info("Chargement de consigne.json...")
        consigne_data = await load_consigne_data()
        if not consigne_data:
            logging.error("Impossible de charger consigne.json. Arrêt du programme.")
            return False
        
        # Recherche des fichiers SERP correspondants
        logging.info("Recherche des fichiers SERP correspondants...")
        file_matches = find_matching_files(consigne_data)
        
        if not file_matches:
            logging.warning("Aucun fichier SERP correspondant trouvé.")
            return True
        
        total_files = len(file_matches)
        logging.info(f"Trouvé {total_files} fichiers SERP à traiter")
        
        # Traitement en parallèle des fichiers
        logging.info("Début du traitement en parallèle...")
        processor = BatchSerpProcessor()
        processed_results, successful_files = await processor.process_files_batch(file_matches)
        
        if not processed_results:
            logging.warning("Aucun fichier traité avec succès.")
            return False
        
        # Mise à jour de consigne.json
        logging.info("Mise à jour de consigne.json...")
        update_success = await update_consigne_data(consigne_data, processed_results)
        
        if not update_success:
            logging.error("Erreur lors de la mise à jour de consigne.json")
            return False
        
        # Mise à jour de processed_queries.json avec les informations sémantiques
        logging.info("Mise à jour de processed_queries.json...")
        processed_queries_success = await update_processed_queries(processed_results, consigne_data)
        
        if not processed_queries_success:
            logging.error("Erreur lors de la mise à jour de processed_queries.json")
            return False
        
        # Nettoyage des fichiers traités
        logging.info("Nettoyage des fichiers traités...")
        await cleanup_processed_files(successful_files)
        
        # Affichage du résumé
        display_batch_summary(processed_results, total_files)
        
        logging.info("=== TRAITEMENT EN LOT TERMINÉ AVEC SUCCÈS ===")
        return True
        
    except KeyboardInterrupt:
        logging.info("Traitement interrompu par l'utilisateur")
        return False
    except Exception as e:
        logging.error(f"Erreur critique dans le programme principal: {str(e)}")
        return False

# === Point d'entrée du script ===
if __name__ == "__main__":
    # Configuration pour Windows
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    
    success = asyncio.run(main())
    exit_code = 0 if success else 1
    exit(exit_code)