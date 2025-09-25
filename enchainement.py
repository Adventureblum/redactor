def execute_workflow(steps_config, stop_on_error=True):
    """
    Exécute une séquence de commandes de manière générique
    
    Args:
        steps_config (list): Liste de dictionnaires avec la config de chaque étape
        stop_on_error (bool): Arrêter le workflow en cas d'erreur
        
    Format des étapes:
    {
        'name': 'nom_etape',
        'command': ['python', 'script.py'],
        'message': 'Message de succès',
        'output_file': 'fichier_sortie.json',  # optionnel
        'required_files': ['fichier1.json'],   # optionnel
    }
    
    Returns:
        tuple: (success: bool, results: list)
    """
    results = []
    
    for i, step in enumerate(steps_config):
        step_name = step.get('name', f'step_{i+1}')
        command = step['command']
        success_msg = step['message']
        output_file = step.get('output_file')
        required_files = step.get('required_files', [])
        
        # Vérifier les fichiers requis
        missing_files = [f for f in required_files if not os.path.exists(f)]
        if missing_files:
            result = {
                'step': step_name,
                'command': ' '.join(command),
                'success': False,
                'message': f'Fichiers manquants: {", ".join(missing_files)}'
            }
            results.append(result)
            if stop_on_error:
                return False, results
            continue
        
        # Exécuter la commande
        success, output = execute_command(command, success_msg, output_file)
        
        result = {
            'step': step_name,
            'command': ' '.join(command),
            'success': success,
            'message': success_msg if success else output
        }
        results.append(result)
        
        # Arrêter si erreur et mode strict
        if not success and stop_on_error:
            return False, results
    
    # Succès global si toutes les étapes ont réussi
    all_success = all(r['success'] for r in results)
    return all_success, results


    def handle_write_flow():
    """Exécute le flux 'write'"""
    steps = [
        (["python", "jason_producer.py"], "Jason Producer terminé.", "received_data.json"),
        (["node", "extractor.js"], "Extraction Google SERP terminée.", None),
        (["python", "serp_semantic.py"], "Analyse sémantique SERP terminée.", None),
        (["python", "plan_redactor.py"], "Plan de rédaction généré.", "received_data.json"),
        (["python", "redactor_article.py"], "Article rédigé.", os.path.join("articles", "article.json")),
        (["python", "Faq_responder.py"], "FAQ générée.", "faq_output.json"),
        (["python", "convert_html_xml.py"], "Conversion HTML/XML terminée.", "articles.xml")
    ]
    
    results = []
    for command, success_msg, output_file in steps:
        success, output = execute_command(command, success_msg, output_file)
        results.append({
            'command': ' '.join(command),
            'success': success,
            'message': success_msg if success else output
        })
        if not success:
            return False, results
    
    return True, results
