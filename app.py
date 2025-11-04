from flask import Flask,render_template,request,redirect,url_for
from flask_socketio import SocketIO,emit
import json
import subprocess
import os
import time
import random
import hashlib
import glob
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import threading
import asyncio
from multiprocessing import Pool, cpu_count
app=Flask(__name__)
socketio=SocketIO(app,cors_allowed_origins="*")
executor=ThreadPoolExecutor(max_workers=min(6, cpu_count()))

OUTPUT_DIR="results"
PROCESSED_FILE="processed_queries.json"
PYTHON_SCRIPT="serp.py"

def find_consigne_file():
 consigne_pattern="static/consignesrun/*.json"
 consigne_files=glob.glob(consigne_pattern)
 if not consigne_files:
  # Fallback sur l'ancien dossier
  consigne_pattern="static/consigne*.json"
  consigne_files=glob.glob(consigne_pattern)
 if not consigne_files:raise FileNotFoundError(f"Aucun fichier de consigne trouvé dans le dossier static/ ou static/consignesrun/")
 if len(consigne_files)==1:return consigne_files[0]
 consigne_files.sort(key=os.path.getmtime,reverse=True)
 return consigne_files[0]

def load_consigne():
 consigne_file=find_consigne_file()
 if not os.path.exists(consigne_file):raise FileNotFoundError(f"Fichier consigne introuvable: {consigne_file}")
 with open(consigne_file,'r',encoding='utf-8') as f:return json.load(f)

def load_processed_queries():
 if os.path.exists(PROCESSED_FILE):
  try:
   with open(PROCESSED_FILE,'r',encoding='utf-8') as f:
    data=json.load(f)
    return set(data.get('processed_queries',[]))
  except:return set()
 return set()

def generate_query_hash(query_text):return hashlib.md5(query_text.lower().strip().encode('utf-8')).hexdigest()

def generate_output_filename(query_id,query_text):
 clean_text="".join(c for c in query_text if c.isalnum() or c in(' ','-','_')).strip()
 clean_text=clean_text.replace(' ','_')[:40]
 return f"serp_{query_id:03d}_{clean_text}.json"

def save_processed_query(query_hash,query_id,query_text):
 processed_queries=load_processed_queries()
 processed_queries.add(query_hash)
 details={}
 if os.path.exists(PROCESSED_FILE):
  try:
   with open(PROCESSED_FILE,'r',encoding='utf-8') as f:
    data=json.load(f)
    details=data.get('query_details',{})
  except:pass
 details[query_hash]={'id':query_id,'text':query_text,'processed_at':time.strftime('%Y-%m-%d %H:%M:%S')}
 data={'processed_queries':list(processed_queries),'query_details':details,'last_updated':time.strftime('%Y-%m-%d %H:%M:%S'),'total_processed':len(processed_queries)}
 with open(PROCESSED_FILE,'w',encoding='utf-8') as f:json.dump(data,f,indent=2,ensure_ascii=False)

def execute_python_script_batch(queries,max_results=10,verbose=False,no_delay=False):
 Path(OUTPUT_DIR).mkdir(exist_ok=True)
 max_workers = min(len(queries), cpu_count(), 4)
 socketio.emit('batch_log',{'message':f'🚀 Traitement parallèle avec {max_workers} workers pour {len(queries)} requêtes'})
 
 with ThreadPoolExecutor(max_workers=max_workers) as batch_executor:
  futures = []
  for query in queries:
   future = batch_executor.submit(process_single_query, query, max_results, verbose, no_delay)
   futures.append((future, query['id']))
  
  completed = 0
  total = len(futures)
  for future, query_id in futures:
   try:
    future.result(timeout=400)
    completed += 1
    socketio.emit('batch_progress',{
     'completed': completed,
     'total': total,
     'percentage': int((completed/total)*100),
     'query_id': query_id
    })
   except Exception as e:
    socketio.emit('job_error',{'query_id': query_id, 'error': f'Future execution error: {str(e)}'})
    completed += 1
  
  socketio.emit('batch_complete',{'message': f'✓ Traitement parallèle terminé: {completed}/{total} requêtes'})

def process_single_query(query,max_results,verbose,no_delay):
 query_id,query_text=query['id'],query['text']
 query_hash=generate_query_hash(query_text)
 output_filename=generate_output_filename(query_id,query_text)
 output_path=Path(OUTPUT_DIR)/output_filename
 
 cmd=['./venv/bin/python',PYTHON_SCRIPT,'--query',query_text,'--output',str(output_path),'--max-results',str(max_results),'--ws','http://127.0.0.1:5000']
 if verbose:cmd.append('--verbose')
 
 env=os.environ.copy()
 env['PYTHONUNBUFFERED'] = '1'
 
 if not no_delay:
  delay=random.randint(2,8)
  socketio.emit('batch_log',{'message':f'⏱️ Délai optimisé: {delay}s pour requête #{query_id}','query_id':query_id})
  time.sleep(delay)
 
 try:
  start_time = time.time()
  socketio.emit('job_start',{'query':query_text,'query_id':query_id,'timestamp':start_time})
  
  result=subprocess.run(
   cmd,
   capture_output=True,
   text=True,
   timeout=400,
   encoding='utf-8',
   env=env,
   cwd=os.getcwd()
  )
  
  processing_time = time.time() - start_time
  
  if result.returncode==0:
   save_processed_query(query_hash,query_id,query_text)
   socketio.emit('job_complete',{
    'query_id':query_id,
    'success':True,
    'output_file':output_filename,
    'processing_time': f'{processing_time:.2f}s',
    'timestamp': time.time()
   })
  else:
   error_msg = result.stderr or result.stdout or 'Unknown error'
   socketio.emit('job_error',{
    'query_id':query_id,
    'error': error_msg,
    'processing_time': f'{processing_time:.2f}s'
   })
   
 except subprocess.TimeoutExpired:
  socketio.emit('job_error',{
   'query_id':query_id,
   'error':'Timeout (6 minutes - optimisé pour parallélisme)',
   'timeout': True
  })
 except Exception as e:
  socketio.emit('job_error',{
   'query_id':query_id,
   'error':f'Erreur inattendue: {str(e)}',
   'exception_type': type(e).__name__
  })

@app.route('/')
def index():
 try:
  data=load_consigne()
  processed=load_processed_queries()
  consigne_file=find_consigne_file()
  return render_template('index.html',queries=data['queries'],processed_ids=processed,main_query=data.get("main_query","—"),filename=os.path.basename(consigne_file),consigne_id=data.get("id"))
 except Exception as e:return f"Erreur lors du chargement: {e}",500

@app.route('/process',methods=['POST'])
def process_queries():
 selected_ids=request.form.getlist('selected_queries')
 print(f"DEBUG: Form data received: {dict(request.form)}")
 print(f"DEBUG: Selected IDs: {selected_ids}")
 if not selected_ids:
  print("DEBUG: No selected_ids, redirecting to index")
  return redirect(url_for('index'))
 try:
  consigne=load_consigne()
  processed=load_processed_queries()
  queries_to_process=[q for q in consigne['queries'] if str(q['id']) in selected_ids and generate_query_hash(q['text']) not in processed]
  socketio.emit('batch_start',{'total':len(queries_to_process)})
  executor.submit(execute_python_script_batch,queries_to_process,10,True,False)
  return redirect(url_for('index'))
 except Exception as e:return f"Erreur: {e}",500
@socketio.on('log')
def handle_log(data):emit('live_log',data,broadcast=True)

if __name__=='__main__':socketio.run(app,host='0.0.0.0',port=5000,debug=True)