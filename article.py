import json
import os
import re
from pathlib import Path
from typing import List, Dict, Any

class ArticleHTMLConverter:
    def __init__(self, json_file_path: str):
        """
        Initialise le convertisseur avec le chemin vers le fichier JSON de consigne
        """
        self.json_file_path = json_file_path
        self.data = self.load_json_data()
        
    def load_json_data(self) -> Dict[str, Any]:
        """Charge les données JSON depuis le fichier"""
        try:
            with open(self.json_file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            print(f"Erreur: Le fichier {self.json_file_path} n'a pas été trouvé.")
            return {}
        except json.JSONDecodeError:
            print(f"Erreur: Le fichier {self.json_file_path} n'est pas un JSON valide.")
            return {}
    
    def get_ready_queries(self) -> List[int]:
        """Trouve automatiquement toutes les requêtes prêtes à être traitées"""
        if 'queries' not in self.data:
            return []
        
        queries = self.data['queries']
        ready_ids = []
        
        for q in queries:
            # Vérifie que la requête a des angles et une analyse (generated_content)
            has_angles = 'differentiating_angles' in q and q['differentiating_angles']
            has_content = 'generated_content' in q and q['generated_content']
            
            if has_angles and has_content:
                ready_ids.append(q['id'])
                
        return ready_ids
    
    def format_markdown_text(self, text: str) -> str:
        """
        Convertit le texte markdown en HTML
        - **texte** devient <strong>texte</strong>
        - [lien](url) devient <a href="url">lien</a>
        - - item devient <li>item</li> (dans des <ul>)
        """
        if not text:
            return ""
        
        # Conversion des mots en gras
        text = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', text)
        
        # Conversion des liens markdown
        text = re.sub(r'\[([^\]]+)\]\(([^\)]+)\)', r'<a href="\2">\1</a>', text)
        
        # Traitement des listes à puces
        lines = text.split('\n')
        result_lines = []
        in_list = False
        
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            
            # Vérifier si c'est une liste à puces
            if line.startswith('- '):
                if not in_list:
                    result_lines.append('<ul>')
                    in_list = True
                
                # Extraire le texte de l'item et appliquer le formatage
                item_text = line[2:].strip()
                item_text = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', item_text)
                result_lines.append(f'<li>{item_text}</li>')
                
            elif line == '' and in_list:
                # Ligne vide dans une liste - la conserver
                pass
                
            else:
                # Fermer la liste si on était dedans
                if in_list:
                    result_lines.append('</ul>')
                    in_list = False
                
                # Ajouter la ligne normale si elle n'est pas vide
                if line:
                    result_lines.append(line)
            
            i += 1
        
        # Fermer la liste si elle était encore ouverte
        if in_list:
            result_lines.append('</ul>')
        
        return '\n'.join(result_lines)
    
    def create_html_content(self, generated_content: Dict[str, Any]) -> str:
        """
        Crée le contenu HTML à partir du generated_content
        """
        html_parts = []
        
        # Titre principal (H1)
        if 'title' in generated_content:
            title = self.format_markdown_text(generated_content['title'])
            html_parts.append(f'<h1>{title}</h1>')
        
        # Introduction
        if 'introduction' in generated_content:
            intro = self.format_markdown_text(generated_content['introduction'])
            html_parts.append(f'<p>{intro}</p>')
        
        # Traitement des sections dynamiquement
        section_num = 1
        while True:
            section_title_key = f'section_{section_num}_title'
            section_content_key = f'section_{section_num}'
            
            # Si ni le titre ni le contenu n'existent, on arrête
            if section_title_key not in generated_content and section_content_key not in generated_content:
                break
            
            # Titre de section (H2)
            if section_title_key in generated_content:
                section_title = self.format_markdown_text(generated_content[section_title_key])
                html_parts.append(f'<h2>{section_title}</h2>')
            
            # Contenu de section
            if section_content_key in generated_content:
                section_content = self.format_markdown_text(generated_content[section_content_key])
                html_parts.append(f'<p>{section_content}</p>')
            
            # Traitement des sous-sections
            subsection_num = 1
            while True:
                subsection_title_key = f'section_{section_num}_subsection_{subsection_num}_title'
                subsection_content_key = f'section_{section_num}_subsection_{subsection_num}'
                
                # Si ni le titre ni le contenu n'existent, on arrête cette boucle
                if (subsection_title_key not in generated_content and 
                    subsection_content_key not in generated_content):
                    break
                
                # Titre de sous-section (H3)
                if subsection_title_key in generated_content:
                    subsection_title = self.format_markdown_text(generated_content[subsection_title_key])
                    html_parts.append(f'<h3>{subsection_title}</h3>')
                
                # Contenu de sous-section
                if subsection_content_key in generated_content:
                    subsection_content = self.format_markdown_text(generated_content[subsection_content_key])
                    html_parts.append(f'<p>{subsection_content}</p>')
                
                subsection_num += 1
            
            section_num += 1
        
        # Conclusion
        if 'conclusion' in generated_content:
            conclusion = self.format_markdown_text(generated_content['conclusion'])
            html_parts.append(f'<p>{conclusion}</p>')
        
        return '\n\n'.join(html_parts)
    
    def create_full_html(self, title: str, content: str) -> str:
        """
        Crée un document HTML complet optimisé pour les Core Web Vitals
        """
        # CSS critique inline minifié
        critical_css = """body{font-family:system-ui,-apple-system,sans-serif;max-width:800px;margin:0 auto;padding:1.25rem;line-height:1.6;color:#333;font-display:swap}h1{color:#2c3e50;border-bottom:3px solid #3b82f6;padding-bottom:.625rem;font-size:clamp(1.5rem,4vw,2.5rem)}h2{color:#34495e;border-left:4px solid #1d4ed8;padding-left:.9375rem;margin-top:1.875rem;font-size:clamp(1.25rem,3.5vw,2rem)}h3{color:#5a67d8;margin-top:1.5625rem;font-size:clamp(1.125rem,3vw,1.5rem)}p{margin-bottom:.9375rem}strong{color:#1d4ed8}a{color:#3b82f6;text-decoration:none}a:hover{text-decoration:underline}ul{margin:.9375rem 0}li{margin-bottom:.3125rem}"""
        
        return f"""<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <meta name="description" content="{title[:155]}...">
    <style>{critical_css}</style>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="dns-prefetch" href="//fonts.googleapis.com">
</head>
<body>
<main>
{content}
</main>
</body>
</html>"""
    
    def sanitize_filename(self, filename: str) -> str:
        """
        Nettoie le nom de fichier pour qu'il soit valide sur tous les OS
        """
        # Supprime les caractères non autorisés
        filename = re.sub(r'[<>:"/\\|?*]', '', filename)
        # Remplace les espaces par des underscores
        filename = filename.replace(' ', '_')
        # Limite la longueur
        if len(filename) > 100:
            filename = filename[:100]
        return filename
    
    def process_articles(self):
        """
        Traite tous les articles prêts et les sauvegarde en HTML
        """
        ready_ids = self.get_ready_queries()
        
        if not ready_ids:
            print("Aucune requête prête à traiter trouvée.")
            return
        
        # Créer le dossier articles basé sur le nom du fichier de consigne
        consigne_name = Path(self.json_file_path).stem
        articles_dir = Path(f"articles_{consigne_name}")
        articles_dir.mkdir(exist_ok=True)
        
        print(f"Traitement de {len(ready_ids)} articles...")
        print(f"Dossier de sortie: {articles_dir}")
        
        for query_id in ready_ids:
            # Trouver la requête correspondante
            query = None
            for q in self.data['queries']:
                if q['id'] == query_id:
                    query = q
                    break
            
            if not query or 'generated_content' not in query:
                print(f"Erreur: Contenu non trouvé pour la requête {query_id}")
                continue
            
            generated_content = query['generated_content']
            
            # Extraire le titre pour le nom de fichier
            title = generated_content.get('title', f'Article_{query_id}')
            filename = self.sanitize_filename(title) + '.html'
            
            # Créer le contenu HTML
            html_content = self.create_html_content(generated_content)
            full_html = self.create_full_html(title, html_content)
            
            # Sauvegarder le fichier
            output_path = articles_dir / filename
            try:
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(full_html)
                print(f"✓ Article sauvegardé: {output_path}")
            except Exception as e:
                print(f"✗ Erreur lors de la sauvegarde de {filename}: {e}")
        
        print(f"\nTraitement terminé. {len(ready_ids)} articles traités dans {articles_dir}/")

def find_consigne_files():
    """
    Trouve tous les fichiers de consigne dans le dossier static/
    """
    static_dir = Path("static")
    if not static_dir.exists():
        print("Erreur: Le dossier 'static' n'existe pas.")
        return []
    
    # Recherche des fichiers JSON qui contiennent "consigne" dans le nom
    consigne_files = list(static_dir.glob("*consigne*.json"))
    return consigne_files

def main():
    """
    Fonction principale pour exécuter le script
    """
    # Chercher les fichiers de consigne dans le dossier static
    consigne_files = find_consigne_files()
    
    if not consigne_files:
        print("Aucun fichier de consigne trouvé dans le dossier 'static/'.")
        print("Les fichiers doivent contenir 'consigne' dans leur nom et avoir l'extension .json")
        return
    
    print(f"Fichiers de consigne trouvés dans static/:")
    for i, file_path in enumerate(consigne_files, 1):
        print(f"{i}. {file_path.name}")
    
    # Si un seul fichier, le traiter automatiquement
    if len(consigne_files) == 1:
        selected_file = consigne_files[0]
        print(f"\nTraitement automatique de: {selected_file.name}")
    else:
        # Demander à l'utilisateur de choisir
        while True:
            try:
                choice = input(f"\nChoisissez un fichier (1-{len(consigne_files)}) ou 'all' pour tous: ").strip().lower()
                
                if choice == 'all':
                    # Traiter tous les fichiers
                    for file_path in consigne_files:
                        print(f"\n{'='*50}")
                        print(f"Traitement de: {file_path.name}")
                        print(f"{'='*50}")
                        converter = ArticleHTMLConverter(str(file_path))
                        converter.process_articles()
                    return
                
                choice_num = int(choice)
                if 1 <= choice_num <= len(consigne_files):
                    selected_file = consigne_files[choice_num - 1]
                    break
                else:
                    print(f"Veuillez choisir un nombre entre 1 et {len(consigne_files)}")
            except ValueError:
                print("Veuillez entrer un nombre valide ou 'all'")
    
    # Créer le convertisseur et traiter les articles
    print(f"\nTraitement de: {selected_file.name}")
    converter = ArticleHTMLConverter(str(selected_file))
    converter.process_articles()

if __name__ == "__main__":
    main()