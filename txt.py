#!/usr/bin/env python3
import json
import sys
from pathlib import Path

def safe_get(data, keys, default="N/A"):
    """Récupère une valeur imbriquée de manière sécurisée"""
    for key in keys:
        if isinstance(data, dict) and key in data:
            data = data[key]
        else:
            return default
    return data

def format_content(query_data):
    """Transforme le contenu généré en texte structuré"""
    output = []
    
    # Métadonnées de base
    output.append(f"=== CONTENU GÉNÉRÉ ===")
    output.append(f"ID: {safe_get(query_data, ['id'])}")
    output.append(f"Requête: {safe_get(query_data, ['text'])}")
    output.append(f"Date: {safe_get(query_data, ['created_at'])}")
    output.append(f"Score: {safe_get(query_data, ['angle_analysis', 'score_total'])}")
    output.append("")

    # Contenu généré
    generated = safe_get(query_data, ['generated_content'], {})
    if generated:
        for section, content in generated.items():
            output.append(f"──── {section.upper().replace('_', ' ')} ────")
            output.append(str(content).strip())
            output.append("")
    else:
        output.append("Aucun contenu généré trouvé dans cette requête")

    return "\n".join(output)

def main():
    try:
        # Charger le JSON
        json_path = Path('static/consigne_20250718_134201_ed3c4700.json')
        data = json.loads(json_path.read_text(encoding='utf-8'))
        
        # Traiter toutes les requêtes avec du contenu généré
        for i, query in enumerate(data.get('queries', [])):
            if 'generated_content' in query:
                txt_content = format_content(query)
                output_path = Path(f"contenu_requete_{i}.txt")
                output_path.write_text(txt_content, encoding='utf-8')
                print(f"✔ Requête {i} sauvegardée dans {output_path}")

        print("\nOpération terminée avec succès")

    except Exception as e:
        print(f"❌ Erreur: {e.__class__.__name__} - {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == '__main__':
    main()