import re
from typing import Dict, List

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

def detect_search_intention(query: str) -> str:
    """Détecte l'intention de recherche basée sur la requête"""
    query_lower = query.lower().strip()

    # Test How-To (priorité haute - patterns spécifiques)
    howto_patterns = [
        r'^comment\s+',
        r'^guide\s+',
        r'^étapes?\s+',
        r'^tutorial\s+',
        r'^procédure\s+',
        r'^méthode\s+',
        r'^installer\s+',
        r'^configurer\s+',
        r'^créer\s+',
        r'^faire\s+'
    ]

    if any(re.search(pattern, query_lower) for pattern in howto_patterns):
        return "HOW-TO"

    # Test Comparative
    comparative_keywords = [
        'vs', 'versus', 'ou', 'meilleur', 'meilleure', 'comparaison',
        'différence', 'choisir', 'alternative', 'entre', 'comparatif'
    ]

    if any(keyword in query_lower for keyword in comparative_keywords):
        return "COMPARATIVE"

    # Test Transactionnelle
    transactional_keywords = [
        'prix', 'coût', 'tarif', 'acheter', 'achat', 'vendre', 'vente',
        'devis', 'gratuit', 'payant', 'abonnement', 'offre', 'promotion',
        'discount', 'soldes', 'pas cher', 'économique'
    ]

    if any(keyword in query_lower for keyword in transactional_keywords):
        return "TRANSACTIONNELLE"

    # Test Informationnelle (par défaut)
    informational_patterns = [
        r'^qu\'est-ce\s+',
        r'^quelle?\s+est\s+',
        r'^définition\s+',
        r'^signification\s+',
        r'^explication\s+',
        r'^pourquoi\s+',
        r'^histoire\s+',
        r'^origine\s+'
    ]

    if any(re.search(pattern, query_lower) for pattern in informational_patterns):
        return "INFORMATIONNELLE"

    # Fallback intelligent basé sur la structure
    if '?' in query:
        return "INFORMATIONNELLE"

    # Par défaut
    return "INFORMATIONNELLE"

def calculate_topic_complexity(tfidf_scores: Dict, entities: List[Dict],
                              relations: List[Dict], query: str) -> str:
    """Calcule la complexité du sujet basée sur les métriques sémantiques"""

    # Critère 1: Diversité terminologique (TF-IDF)
    if not tfidf_scores:
        technical_score = 0
    else:
        # Mots techniques détectés
        technical_terms = [
            'api', 'algorithme', 'architecture', 'backend', 'frontend', 'database',
            'framework', 'javascript', 'python', 'sql', 'css', 'html', 'json',
            'server', 'cloud', 'saas', 'paas', 'devops', 'cicd', 'kubernetes',
            'docker', 'microservices', 'oauth', 'jwt', 'rest', 'graphql'
        ]

        technical_count = sum(1 for term in tfidf_scores.keys()
                            if any(tech in term.lower() for tech in technical_terms))
        technical_score = min(technical_count / 5, 1.0) * 5  # Normalisé sur 5 points

    # Critère 2: Nombre d'entités spécialisées
    entity_score = 0
    if entities:
        specialized_entities = [ent for ent in entities
                              if ent.get('label') in ['ORG', 'PRODUCT', 'PERSON']]
        entity_score = min(len(specialized_entities) / 3, 1.0) * 3  # Normalisé sur 3 points

    # Critère 3: Complexité relationnelle
    relation_score = min(len(relations) / 5, 1.0) * 3  # Normalisé sur 3 points

    # Critère 4: Longueur et structure de la requête
    query_words = len(query.split())
    query_score = 0
    if query_words >= 6:
        query_score = 2
    elif query_words >= 4:
        query_score = 1

    # Critère 5: Diversité du vocabulaire TF-IDF
    vocab_score = 0
    if tfidf_scores:
        unique_terms = len([term for term, score in tfidf_scores.items() if score > 0.1])
        vocab_score = min(unique_terms / 30, 1.0) * 2  # Normalisé sur 2 points

    # Score total sur 15 points
    total_score = technical_score + entity_score + relation_score + query_score + vocab_score

    # Classification
    if total_score >= 10:
        return "complexe"
    elif total_score >= 6:
        return "moyen"
    else:
        return "simple"

def select_sections_by_matrix(intention: str, complexity: str) -> Dict[str, List[str]]:
    """Sélectionne les sections selon la matrice intention × complexité"""

    # Matrice de sélection des sections
    section_matrix = {
        "INFORMATIONNELLE": {
            "simple": {
                "titulaires": ["introduction", "definition", "fonctionnement", "orientation"],
                "remplacants": []
            },
            "moyen": {
                "titulaires": ["introduction", "definition", "fonctionnement", "orientation"],
                "remplacants": ["contexte", "meilleures_pratiques"]
            },
            "complexe": {
                "titulaires": ["introduction", "definition", "fonctionnement", "contexte", "orientation"],
                "remplacants": ["typologie", "meilleures_pratiques", "exemples"]
            }
        },
        "COMPARATIVE": {
            "simple": {
                "titulaires": ["introduction", "criteres", "analyse_options", "tableau_comparatif", "recommandations"],
                "remplacants": []
            },
            "moyen": {
                "titulaires": ["introduction", "criteres", "analyse_options", "tableau_comparatif", "recommandations"],
                "remplacants": ["avantages_inconvenients"]
            },
            "complexe": {
                "titulaires": ["introduction", "criteres", "analyse_options", "tableau_comparatif", "face_a_face", "recommandations"],
                "remplacants": ["definition", "faq"]
            }
        },
        "TRANSACTIONNELLE": {
            "simple": {
                "titulaires": ["introduction", "pricing", "garanties", "cta"],
                "remplacants": []
            },
            "moyen": {
                "titulaires": ["introduction", "pricing", "garanties", "cta"],
                "remplacants": ["processus", "roi"]
            },
            "complexe": {
                "titulaires": ["introduction", "pricing", "garanties", "processus", "roi", "cta"],
                "remplacants": ["tableau_comparatif", "faq"]
            }
        },
        "HOW-TO": {
            "simple": {
                "titulaires": ["introduction", "etapes", "validation"],
                "remplacants": ["diagnostic"]
            },
            "moyen": {
                "titulaires": ["introduction", "diagnostic", "etapes", "validation"],
                "remplacants": ["outils", "orientation"]
            },
            "complexe": {
                "titulaires": ["introduction", "diagnostic", "outils", "etapes", "validation", "orientation"],
                "remplacants": ["meilleures_pratiques", "erreurs_communes"]
            }
        }
    }

    # Récupération des sections pour cette combinaison
    sections_config = section_matrix.get(intention, {}).get(complexity, {
        "titulaires": ["introduction", "conclusion"],
        "remplacants": []
    })

    return sections_config

def calculate_word_distribution(sections: Dict[str, List[str]], target_word_count: int) -> Dict[str, int]:
    """Calcule la distribution des mots par section"""

    # Définition des poids par type de section
    section_weights = {
        "introduction": 0.10,  # 10% du total
        "definition": 0.12,
        "fonctionnement": 0.15,
        "contexte": 0.10,
        "criteres": 0.12,
        "analyse_options": 0.20,  # Section principale pour comparatif
        "tableau_comparatif": 0.08,
        "face_a_face": 0.15,
        "recommandations": 0.12,
        "pricing": 0.18,  # Section importante pour transactionnel
        "garanties": 0.15,
        "processus": 0.15,
        "roi": 0.12,
        "cta": 0.08,
        "diagnostic": 0.12,
        "outils": 0.10,
        "etapes": 0.25,  # Section principale pour how-to
        "validation": 0.10,
        "meilleures_pratiques": 0.12,
        "erreurs_communes": 0.10,
        "typologie": 0.12,
        "exemples": 0.12,
        "avantages_inconvenients": 0.10,
        "faq": 0.08,
        "orientation": 0.10,
        "conclusion": 0.10
    }

    # Calcul des mots réservés pour intro/conclusion
    reserved_words = int(target_word_count * 0.20)  # 20% pour intro/conclusion
    available_words = target_word_count - reserved_words

    # Liste de toutes les sections sélectionnées
    all_sections = sections.get("titulaires", []) + sections.get("remplacants", [])
    content_sections = [s for s in all_sections if s not in ["introduction", "conclusion"]]

    # Distribution proportionnelle
    word_distribution = {}
    total_weight = sum(section_weights.get(section, 0.10) for section in content_sections)

    for section in content_sections:
        weight = section_weights.get(section, 0.10)
        words = int((weight / total_weight) * available_words)
        word_distribution[section] = max(words, 50)  # Minimum 50 mots par section

    # Ajout intro/conclusion
    if "introduction" in all_sections:
        word_distribution["introduction"] = reserved_words // 2
    if "conclusion" in all_sections:
        word_distribution["conclusion"] = reserved_words // 2

    return word_distribution

def generate_section_metadata(intention: str, sections_config: Dict,
                            word_distribution: Dict[str, int]) -> Dict[str, Dict]:
    """Génère les métadonnées détaillées pour chaque section"""

    # Templates de métadonnées par type de section
    section_templates = {
        "introduction": {
            "objectif": "Capter l'attention et présenter le sujet",
            "elements_cles": ["hook", "problème identifié", "promesse de valeur", "plan annoncé"]
        },
        "definition": {
            "objectif": "Clarifier le concept principal",
            "elements_cles": ["définition claire", "contexte d'usage", "différenciation"]
        },
        "fonctionnement": {
            "objectif": "Expliquer les mécanismes",
            "elements_cles": ["processus détaillé", "exemples concrets", "schémas explicatifs"]
        },
        "criteres": {
            "objectif": "Établir les bases de comparaison",
            "elements_cles": ["critères objectifs", "pondération", "méthode d'évaluation"]
        },
        "analyse_options": {
            "objectif": "Analyser chaque alternative",
            "elements_cles": ["forces/faiblesses", "cas d'usage", "positionnement"]
        },
        "etapes": {
            "objectif": "Guider l'action étape par étape",
            "elements_cles": ["actions concrètes", "validation par étape", "troubleshooting"]
        },
        "pricing": {
            "objectif": "Lever le frein prix",
            "elements_cles": ["transparence tarifaire", "justification valeur", "comparatif marché"]
        }
    }

    # Génération des métadonnées
    section_metadata = {}
    all_sections = sections_config.get("titulaires", []) + sections_config.get("remplacants", [])

    for section in all_sections:
        template = section_templates.get(section, {
            "objectif": f"Développer l'aspect {section}",
            "elements_cles": ["contenu pertinent", "exemples", "synthèse"]
        })

        section_metadata[section] = {
            "type": "titulaire" if section in sections_config.get("titulaires", []) else "remplacant",
            "word_count": word_distribution.get(section, 150),
            "objectif": template["objectif"],
            "elements_cles": template["elements_cles"],
            "priorite": 1 if section in sections_config.get("titulaires", []) else 2
        }

    return section_metadata