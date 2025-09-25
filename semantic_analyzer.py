import spacy
import nltk
import numpy as np
import logging
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.cluster import KMeans
from sentence_transformers import SentenceTransformer
from collections import defaultdict
from nltk.corpus import stopwords
from typing import List, Dict

class ParallelSemanticAnalyzer:
    """Version thread-safe de l'analyseur sémantique avec modèles NLP"""

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