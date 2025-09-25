import os
import logging
from pathlib import Path
import nltk

# Configuration logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Vérification et téléchargement des ressources NLTK
try:
    nltk.data.find('corpora/stopwords')
except LookupError:
    nltk.download('stopwords')

# Chemins et constantes
BASE_DIR = os.path.dirname(__file__)
RESULTS_DIR = os.path.join(BASE_DIR, "results")

# Configuration parallélisation
MAX_WORKERS_IO = 4
MAX_WORKERS_CPU = 2
MAX_CONCURRENT_API = 3

# Configuration API
API_KEY = os.getenv('OPENAI_API_KEY')