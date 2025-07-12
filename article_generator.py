#!/usr/bin/env python3
"""
Générateur d'articles avec architecture Orchestrateur + 3 Agents spécialisés
- Agent Hook: Introduction ultra-performante avec highlight
- Agent Rédacteur: Développement (appelé X fois selon sections)
- Agent Conclusion+CTA: Synthèse + call-to-action avec faux highlight
"""

import json
import os
import sys
import glob
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, asdict
import openai
from openai import OpenAI

# Configuration OpenAI
client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

def _find_consigne_file() -> str:
    """Trouve automatiquement le fichier de consigne dans le dossier static"""
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    STATIC_DIR = os.path.join(BASE_DIR, "static")
    
    consigne_pattern = os.path.join(STATIC_DIR, "consigne*.json")
    consigne_files = glob.glob(consigne_pattern)
    
    if not consigne_files:
        raise FileNotFoundError(f"❌ Aucun fichier de consigne trouvé dans {STATIC_DIR}/ (pattern: consigne*.json)")
    
    if len(consigne_files) == 1:
        found_file = consigne_files[0]
        print(f"📁 Fichier de consigne détecté: {os.path.basename(found_file)}")
        return found_file
    
    # Si plusieurs fichiers trouvés, prendre le plus récent
    consigne_files.sort(key=os.path.getmtime, reverse=True)
    most_recent = consigne_files[0]
    print(f"📁 Plusieurs fichiers de consigne trouvés, utilisation du plus récent: {os.path.basename(most_recent)}")
    print(f"   Autres fichiers ignorés: {', '.join([os.path.basename(f) for f in consigne_files[1:]])}")
    return most_recent

@dataclass
class ContexteArticle:
    """Contexte transmis entre les agents"""
    contenu_precedent: str = ""
    mots_cles_utilises: List[str] = None
    mots_cles_restants: List[str] = None
    mots_total_rediges: int = 0
    tone_etabli: str = ""
    fil_narratif: str = ""
    progression_general_specifique: str = ""
    
    def __post_init__(self):
        if self.mots_cles_utilises is None:
            self.mots_cles_utilises = []
        if self.mots_cles_restants is None:
            self.mots_cles_restants = []

class OrchestrateurArticle:
    def __init__(self, consigne_path: str):
        self.consigne_path = consigne_path
        self.consigne_data = self.load_consigne()
        
    def load_consigne(self) -> Dict:
        """Charge le fichier consigne.json"""
        try:
            with open(self.consigne_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            print(f"❌ Fichier {self.consigne_path} non trouvé.")
            sys.exit(1)
        except json.JSONDecodeError as e:
            print(f"❌ Erreur JSON dans {self.consigne_path}: {e}")
            sys.exit(1)
    
    def save_consigne(self):
        """Sauvegarde le fichier consigne.json"""
        with open(self.consigne_path, 'w', encoding='utf-8') as f:
            json.dump(self.consigne_data, f, ensure_ascii=False, indent=4)
    
    def prepare_keywords_list(self, top_keywords: str) -> List[str]:
        """Prépare la liste des mots-clés depuis la chaîne top_keywords"""
        return [kw.strip() for kw in top_keywords.split(',') if kw.strip()]
    
    def calculate_keyword_budget(self, total_words: int) -> int:
        """Calcule le nombre de mots-clés à intégrer (1 top_keyword / 4-5 mots)"""
        return total_words // 5  # On prend la moyenne (1/5)
    
    def distribute_keywords(self, keywords: List[str], sections_count: int) -> Dict[str, List[str]]:
        """Distribue les mots-clés entre introduction, sections et conclusion"""
        total_kw = len(keywords)
        
        # Répartition: 30% intro, 60% sections (équitable), 10% conclusion
        intro_kw = max(1, int(total_kw * 0.3))
        conclusion_kw = max(1, int(total_kw * 0.1))
        sections_kw = total_kw - intro_kw - conclusion_kw
        
        kw_per_section = sections_kw // sections_count if sections_count > 0 else 0
        
        distribution = {
            'introduction': keywords[:intro_kw],
            'sections': [],
            'conclusion': keywords[-conclusion_kw:] if conclusion_kw > 0 else []
        }
        
        # Distribution par section
        start_idx = intro_kw
        for i in range(sections_count):
            end_idx = start_idx + kw_per_section
            distribution['sections'].append(keywords[start_idx:end_idx])
            start_idx = end_idx
        
        return distribution
    
    def agent_hook(self, query_data: Dict, contexte: ContexteArticle, keywords_assignes: List[str]) -> str:
        """Agent Hook - Introduction ultra-performante avec highlight"""
        plan = query_data.get('generated_article_plan', {})
        intro_notes = plan.get('introduction_notes', {})
        nb_mots = query_data['plan']['introduction']['longueur']
        
        prompt = f"""Tu es l'Agent Hook, spécialiste des introductions ultra-performantes.

MISSION: Rédiger une introduction captivante de {nb_mots} mots EXACTEMENT.

DONNÉES CONTEXTUELLES:
- Requête: "{query_data['text']}"
- Titre SEO: {plan.get('SEO Title', '')}
- Angle différenciant: {query_data.get('selected_differentiating_angle', '')}

PROGRESSION GÉNÉRALE → SPÉCIFIQUE:
Tu ouvres l'article avec une vue d'ensemble/problématique générale avant de cibler.

MOTS-CLÉS ASSIGNÉS À TOI (intégrer naturellement):
{', '.join(keywords_assignes)}

HIGHLIGHT OBLIGATOIRE À INTÉGRER:
- URL: {self.consigne_data.get('highlight', '')}
- Contexte suggéré: {intro_notes.get('highlight_integration', '')}
- Ancrage suggéré: {intro_notes.get('suggested_anchor_text', '')}

SECTIONS À ANNONCER:
{chr(10).join([f"- {section['section_title']}" for section in plan.get('sections', [])])}

CONTRAINTES STRICTES:
1. EXACTEMENT {nb_mots} mots
2. Hook ultra-engageant (question, statistique, fait surprenant)
3. Intégrer le lien highlight NATURELLEMENT 
4. Annoncer le plan avec les sections exactes
5. Ton professionnel mais accessible
6. Score Flesch 60-70 (accessible)

STRUCTURE OPTIMALE:
- Hook puissant (problématique/questionnement)
- Contextualisation générale
- Intégration naturelle du highlight
- Annonce du plan détaillé
- Transition vers le développement

Rédige cette introduction ultra-performante."""

        try:
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=800
            )
            
            introduction = response.choices[0].message.content.strip()
            
            # Mise à jour du contexte
            contexte.contenu_precedent = introduction
            contexte.mots_total_rediges += len(introduction.split())
            contexte.tone_etabli = "professionnel accessible"
            contexte.fil_narratif = "Introduction hook établie - Vue d'ensemble donnée"
            contexte.progression_general_specifique = "Phase 1: Général (problématique globale établie)"
            
            return introduction
            
        except Exception as e:
            print(f"❌ Erreur Agent Hook: {e}")
            return ""
    
    def agent_redacteur(self, query_data: Dict, contexte: ContexteArticle, 
                       section_data: Dict, section_index: int, keywords_assignes: List[str]) -> str:
        """Agent Rédacteur - Développement d'une section spécifique"""
        
        # Calcul des mots par section
        word_count_total = query_data.get('word_count', 1121)
        intro_words = query_data['plan']['introduction']['longueur']
        conclusion_words = query_data['plan']['conclusion']['longueur']
        development_words = word_count_total - intro_words - conclusion_words  
        
        plan = query_data.get('generated_article_plan', {})
        sections_count = len(plan.get('sections', []))
        mots_par_section = development_words // sections_count if sections_count > 0 else 300
        
        # Progression général → spécifique
        if section_index == 0:
            niveau_specifique = "Niveau 2: Plus ciblé que l'introduction"
        elif section_index == 1:
            niveau_specifique = "Niveau 3: Encore plus spécifique et détaillé"
        else:
            niveau_specifique = f"Niveau {section_index + 2}: Très détaillé et pratique"
        
        prompt = f"""Tu es l'Agent Rédacteur, spécialiste du développement structuré.

MISSION: Rédiger la section "{section_data['section_title']}" de {int(mots_par_section)} mots EXACTEMENT.

CONTEXTE PRÉCÉDENT:
{contexte.contenu_precedent[-1000:]}  # Garder les 1000 derniers caractères

PROGRESSION GÉNÉRAL → SPÉCIFIQUE:
{niveau_specifique}
Fils narratif actuel: {contexte.fil_narratif}

PLAN DÉTAILLÉ DE CETTE SECTION:
- Titre: {section_data['section_title']}
- Type de snippet: {section_data.get('snippet_type', 'None')}
- Placement: {section_data.get('placement', 'middle')}
- Sous-sections OBLIGATOIRES:
{chr(10).join([f"  • {sub['subsection_title']}" for sub in section_data.get('subsections', [])])}

MOTS-CLÉS ASSIGNÉS À CETTE SECTION:
{', '.join(keywords_assignes)}

CONTRAINTES STRICTES:
1. EXACTEMENT {int(mots_par_section)} mots
2. Traiter TOUTES les sous-sections listées
3. Transition fluide depuis le contenu précédent
4. Ton cohérent: {contexte.tone_etabli}  
5. Structure H2 + H3 pour sous-sections
6. Score Flesch 60-70
7. Éviter la sur-optimisation des mots-clés déjà utilisés: {', '.join(contexte.mots_cles_utilises[-10:])}

FORMAT ATTENDU:
## {section_data['section_title']}

### {section_data.get('subsections', [{}])[0].get('subsection_title', 'Première sous-section')}
[Contenu détaillé...]

### [Autres sous-sections...]
[Contenu...]

Rédige cette section en respectant la progression du général au spécifique."""

        try:
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=1500
            )
            
            section_content = response.choices[0].message.content.strip()
            
            # Mise à jour du contexte
            contexte.contenu_precedent += f"\n\n{section_content}"
            contexte.mots_total_rediges += len(section_content.split())
            contexte.fil_narratif = f"Section '{section_data['section_title']}' complétée - {niveau_specifique}"
            contexte.progression_general_specifique = niveau_specifique
            
            return section_content
            
        except Exception as e:
            print(f"❌ Erreur Agent Rédacteur section {section_index + 1}: {e}")
            return ""
    
    def agent_conclusion_cta(self, query_data: Dict, contexte: ContexteArticle, keywords_assignes: List[str]) -> str:
        """Agent Conclusion+CTA - Synthèse + call-to-action ultra pertinent"""
        plan = query_data.get('generated_article_plan', {})
        nb_mots = query_data['plan']['conclusion']['longueur']
        
        # Génération d'un faux highlight contextuel
        sujet_principal = query_data['text'].replace('qu est ce que', '').replace('comment', '').strip()
        faux_highlight = f"https://formation-{sujet_principal.replace(' ', '-').replace('d-', '').replace('intérieur', 'interieur')}.fr"
        
        prompt = f"""Tu es l'Agent Conclusion+CTA, spécialiste des finales ultra-persuasives.

MISSION: Rédiger une conclusion de {nb_mots} mots EXACTEMENT avec CTA intégré.

ARTICLE COMPLET PRÉCÉDENT:
{contexte.contenu_precedent[-2000:]}  # Garder les 2000 derniers caractères

DONNÉES CONTEXTUELLES:
- Requête initiale: "{query_data['text']}"
- Titre: {plan.get('SEO Title', '')}
- Progression atteinte: {contexte.progression_general_specifique}

MOTS-CLÉS ASSIGNÉS (éviter sur-optimisation):
{', '.join(keywords_assignes)}

FAUX HIGHLIGHT À INTÉGRER:
{faux_highlight}

CONTRAINTES STRICTES:
1. EXACTEMENT {nb_mots} mots
2. Synthèse claire des points clés abordés
3. Réponse définitive à la question initiale
4. CTA ultra-pertinent avec le faux highlight
5. Ton conclusif et actionnable
6. Score Flesch 60-70
7. Éviter répétition des mots-clés sur-utilisés: {', '.join(contexte.mots_cles_utilises[-15:])}

STRUCTURE OPTIMALE:
- Récapitulatif des points essentiels (synthèse)
- Réponse claire et définitive à la question
- Conseil pratique ou perspective d'avenir
- CTA naturel avec le faux highlight
- Fermeture inspirante

PROGRESSION GÉNÉRAL → SPÉCIFIQUE:
Tu conclus en transformant toute l'information en ACTION CONCRÈTE pour le lecteur.

Rédige cette conclusion ultra-persuasive avec CTA intégré."""

        try:
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=800
            )
            
            conclusion = response.choices[0].message.content.strip()
            return conclusion
            
        except Exception as e:
            print(f"❌ Erreur Agent Conclusion+CTA: {e}")
            return ""
    
    def orchestrer_article(self, query_id: int) -> Dict:
        """Orchestrateur principal - Coordonne les 3 agents"""
        query_data = self.get_query_data(query_id)
        if not query_data or 'generated_article_plan' not in query_data:
            return {}
        
        print(f"\n🎼 ORCHESTRATION pour ID {query_id}: '{query_data['text']}'")
        
        # Préparation
        keywords = self.prepare_keywords_list(query_data.get('top_keywords', ''))
        plan = query_data.get('generated_article_plan', {})
        sections = plan.get('sections', [])
        
        # Distribution des mots-clés
        kw_distribution = self.distribute_keywords(keywords, len(sections))
        
        contexte = ContexteArticle()
        contexte.mots_cles_restants = keywords.copy()
        
        print(f"   📊 Mots-clés distribués: Intro({len(kw_distribution['introduction'])}), Sections({len(kw_distribution['sections'])}), Conclusion({len(kw_distribution['conclusion'])})")
        
        # 1. Agent Hook - Introduction
        print("   🎯 Agent Hook: Génération introduction...")
        introduction = self.agent_hook(query_data, contexte, kw_distribution['introduction'])
        
        # 2. Agent Rédacteur - Sections (appelé X fois)
        sections_content = []
        for i, section in enumerate(sections):
            section_keywords = kw_distribution['sections'][i] if i < len(kw_distribution['sections']) else []
            print(f"   ✍️  Agent Rédacteur: Section {i+1}/{len(sections)} - '{section['section_title']}'...")
            section_content = self.agent_redacteur(query_data, contexte, section, i, section_keywords)
            sections_content.append(section_content)
        
        # 3. Agent Conclusion+CTA
        print("   🎯 Agent Conclusion+CTA: Génération finale...")
        conclusion = self.agent_conclusion_cta(query_data, contexte, kw_distribution['conclusion'])
        
        # Assemblage final
        article_complet = {
            'title': plan.get('SEO Title', f"Article sur {query_data['text']}"),
            'introduction': introduction,
            'sections': sections_content,
            'conclusion': conclusion,
            'word_count': len(f"{introduction} {' '.join(sections_content)} {conclusion}".split()),
            'generated_date': "2025-06-30",
            'generation_method': 'orchestrateur_3_agents',
            'keyword_distribution': kw_distribution
        }
        
        return article_complet
    
    def get_query_data(self, query_id: int) -> Optional[Dict]:
        """Récupère les données d'une requête par son ID"""
        for query in self.consigne_data.get('queries', []):
            if query['id'] == query_id:
                return query
        return None
    
    def list_available_queries(self) -> List[Dict]:
        """Liste toutes les requêtes disponibles avec leur statut"""
        queries = []
        for query in self.consigne_data.get('queries', []):
            has_plan = 'generated_article_plan' in query
            has_article = 'generated_article' in query
            status = "🟢 Complet" if has_article else "🟡 Plan prêt" if has_plan else "🔴 Non traité"
            queries.append({
                'id': query['id'],
                'text': query['text'],
                'status': status,
                'has_plan': has_plan,
                'has_article': has_article
            })
        return queries
    
    def select_queries_to_process(self) -> List[int]:
        """Interface utilisateur pour sélectionner les requêtes à traiter"""
        queries = self.list_available_queries()
        
        print("\n📋 REQUÊTES DISPONIBLES:")
        print("=" * 80)
        for q in queries:
            print(f"ID {q['id']:2d} | {q['status']} | {q['text']}")
        
        print("\n💡 Instructions:")
        print("- Tapez un ID pour traiter une seule requête: 5")
        print("- Tapez plusieurs IDs séparés par des virgules: 1,3,5")
        print("- Tapez une plage d'IDs: 1-5")
        print("- Tapez 'all' pour traiter toutes les requêtes avec plan")
        print("- Tapez 'q' pour quitter")
        
        while True:
            user_input = input("\n🎯 Votre sélection: ").strip().lower()
            
            if user_input == 'q':
                print("👋 Au revoir!")
                sys.exit(0)
            
            if user_input == 'all':
                return [q['id'] for q in queries if q['has_plan'] and not q['has_article']]
            
            try:
                selected_ids = []
                
                # Gestion des plages (1-5)
                if '-' in user_input and user_input.count('-') == 1:
                    start, end = map(int, user_input.split('-'))
                    selected_ids = list(range(start, end + 1))
                
                # Gestion des listes (1,3,5)
                elif ',' in user_input:
                    selected_ids = [int(x.strip()) for x in user_input.split(',')]
                
                # ID unique
                else:
                    selected_ids = [int(user_input)]
                
                # Validation
                valid_ids = [q['id'] for q in queries]
                invalid_ids = [id for id in selected_ids if id not in valid_ids]
                
                if invalid_ids:
                    print(f"❌ IDs invalides: {invalid_ids}")
                    continue
                
                # Vérification des plans
                no_plan_ids = [id for id in selected_ids 
                              if not any(q['id'] == id and q['has_plan'] for q in queries)]
                
                if no_plan_ids:
                    print(f"⚠️  Les IDs suivants n'ont pas de plan généré: {no_plan_ids}")
                    continue_anyway = input("Continuer quand même? (y/N): ").lower() == 'y'
                    if not continue_anyway:
                        continue
                
                return selected_ids
                
            except ValueError:
                print("❌ Format invalide. Utilisez des nombres, des virgules ou des tirets.")
    
    def process_queries(self, query_ids: List[int]):
        """Traite une liste de requêtes avec l'orchestrateur"""
        print(f"\n🎼 ORCHESTRATION DE {len(query_ids)} REQUÊTE(S): {query_ids}")
        
        for query_id in query_ids:
            try:
                article = self.orchestrer_article(query_id)
                
                if article:
                    # Intégration dans consigne.json
                    for query in self.consigne_data['queries']:
                        if query['id'] == query_id:
                            query['generated_article'] = article
                            break
                    
                    print(f"   ✅ Article orchestré pour ID {query_id} ({article['word_count']} mots)")
                else:
                    print(f"   ❌ Échec orchestration pour ID {query_id}")
                    
            except Exception as e:
                print(f"   ❌ Erreur lors de l'orchestration ID {query_id}: {e}")
        
        # Sauvegarde
        try:
            self.save_consigne()
            print(f"\n💾 Fichier {self.consigne_path} mis à jour avec succès!")
        except Exception as e:
            print(f"❌ Erreur lors de la sauvegarde: {e}")

def main():
    """Fonction principale"""
    print("🎼 GÉNÉRATEUR D'ARTICLES - ORCHESTRATEUR + 3 AGENTS")
    print("=" * 60)
    print("🎯 Agent Hook | ✍️  Agent Rédacteur | 🎯 Agent Conclusion+CTA")
    
    # Vérification de la clé API OpenAI
    if not os.getenv('OPENAI_API_KEY'):
        print("❌ Variable d'environnement OPENAI_API_KEY manquante.")
        print("Ajoutez votre clé API OpenAI:")
        print("export OPENAI_API_KEY='your-api-key-here'")
        sys.exit(1)
    
    # Auto-détection du fichier consigne avec identifiants uniques
    try:
        consigne_path = _find_consigne_file()
    except FileNotFoundError as e:
        print(str(e))
        print("💡 Assurez-vous qu'un fichier consigne*.json existe dans le dossier static/")
        sys.exit(1)
    
    # Initialisation de l'orchestrateur
    orchestrateur = OrchestrateurArticle(consigne_path)
    
    # Sélection et traitement
    try:
        selected_ids = orchestrateur.select_queries_to_process()
        if selected_ids:
            orchestrateur.process_queries(selected_ids)
        else:
            print("ℹ️  Aucune requête sélectionnée.")
    
    except KeyboardInterrupt:
        print("\n\n⏹️  Arrêt demandé par l'utilisateur.")
    except Exception as e:
        print(f"\n❌ Erreur inattendue: {e}")

if __name__ == "__main__":
    main()