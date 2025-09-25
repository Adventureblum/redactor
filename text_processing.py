import re
import unicodedata
from bs4 import BeautifulSoup, Comment
from typing import Optional, Set

def normalize_text_for_filename(text: str) -> str:
    """Normalise un texte pour correspondre au format filename"""
    # Remplacer les espaces par des underscores et nettoyer
    normalized = re.sub(r'[^\w\s]', '', text.lower())
    normalized = re.sub(r'\s+', '_', normalized.strip())
    return normalized

class ThreadSafeTextCleaner:
    """Nettoie le contenu HTML et texte de manière thread-safe"""

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
            import logging
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