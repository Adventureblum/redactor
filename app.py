from flask import Flask, render_template, request, redirect, url_for
import json
import subprocess
import os
from serp_processor import SerpSingleProcessor

app = Flask(__name__)

@app.route('/')
def index():
    processor = SerpSingleProcessor()
    data = processor.load_consigne()
    processed = processor._load_processed_queries()
    
    return render_template('index.html', 
                           queries=data['queries'],
                           processed_ids=processed,
                           main_query=data.get("main_query", "—"),
                           filename=os.path.basename(processor.consigne_file),
                           consigne_id=data.get("id"))

@app.route('/process', methods=['POST'])
def process_queries():
    selected_ids = request.form.getlist('selected_queries')
    
    if not selected_ids:
        return redirect(url_for('index'))
    
    processor = SerpSingleProcessor()
    consigne = processor.load_consigne()
    processed = processor._load_processed_queries()
    
    queries_to_process = [q for q in consigne['queries'] if str(q['id']) in selected_ids and processor._generate_query_hash(q['text']) not in processed]
    
    for query in queries_to_process:
        processor.process_single_query(verbose=True, no_delay=True)
    
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True)