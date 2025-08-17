#!/usr/bin/env python3
"""
Générateur de plans d'articles SEO avec agent spécialisé - VERSION ROBUSTE
- Configuration centralisée avec validation stricte
- Logging structuré et gestion d'erreurs robuste
- Retry automatique avec backoff exponentiel
- Validation des données à tous les niveaux
- Cache intelligent et health checks
- Architecture modulaire maintenue
- ZÉRO nouvelle dépendance externe
"""

import json
import os
import sys
import glob
import time
import logging
import traceback
from typing import Dict, List, Any, Optional, Union, Tuple
from pathlib import Path
from dataclasses import dataclass, field, asdict
from enum import Enum
from datetime import datetime, timedelta
import requests
import hashlib


# ==================== CONFIGURATION CENTRALISÉE ====================

@dataclass
class APIConfig:
    """Configuration API avec validation"""
    api_key: str
    base_url: str = "https://api.deepseek.com/v1"
    timeout: int = 60
    max_retries: int = 3
    retry_delay: float = 1.0
    max_retry_delay: float = 60.0
    backoff_factor: float = 2.0
    max_tokens: int = 3000
    temperature: float = 0.7
    
    def __post_init__(self):
        """Validation post-initialisation"""
        if not self.api_key or len(self.api_key) < 10:
            raise ValueError("Clé API invalide ou trop courte")
        if self.timeout < 1 or self.timeout > 300:
            raise ValueError("Timeout doit être entre 1 et 300 secondes")
        if self.max_retries < 0 or self.max_retries > 10:
            raise ValueError("Max retries doit être entre 0 et 10")


@dataclass
class AppConfig:
    """Configuration générale de l'application"""
    prompts_dir: str = "prompts"
    static_dir: str = "static"
    cache_enabled: bool = True
    cache_ttl_hours: int = 24
    log_level: str = "INFO"
    debug_mode: bool = False
    
    def __post_init__(self):
        """Validation et normalisation"""
        self.prompts_dir = Path(self.prompts_dir).resolve()
        self.static_dir = Path(self.static_dir).resolve()
        if self.log_level not in ["DEBUG", "INFO", "WARNING", "ERROR"]:
            self.log_level = "INFO"


class RetryError(Exception):
    """Exception pour les erreurs de retry"""
    pass


class ValidationError(Exception):
    """Exception pour les erreurs de validation"""
    pass


class ConfigurationError(Exception):
    """Exception pour les erreurs de configuration"""
    pass


# ==================== LOGGING STRUCTURÉ ====================

class StructuredLogger:
    """Logger structuré avec contexte"""
    
    def __init__(self, name: str, level: str = "INFO"):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(getattr(logging, level))
        
        # Éviter les doublons de handlers
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                '%(asctime)s | %(levelname)s | %(name)s | %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
    
    def _format_message(self, message: str, **kwargs) -> str:
        """Formate le message avec contexte"""
        if kwargs:
            context = " | ".join([f"{k}={v}" for k, v in kwargs.items()])
            return f"{message} | {context}"
        return message
    
    def debug(self, message: str, **kwargs):
        self.logger.debug(self._format_message(message, **kwargs))
    
    def info(self, message: str, **kwargs):
        self.logger.info(self._format_message(message, **kwargs))
    
    def warning(self, message: str, **kwargs):
        self.logger.warning(self._format_message(message, **kwargs))
    
    def error(self, message: str, **kwargs):
        self.logger.error(self._format_message(message, **kwargs))
    
    def critical(self, message: str, **kwargs):
        self.logger.critical(self._format_message(message, **kwargs))


# ==================== CACHE INTELLIGENT ====================

@dataclass
class CacheEntry:
    """Entrée de cache avec métadonnées"""
    data: Any
    created_at: datetime
    access_count: int = 0
    last_accessed: datetime = field(default_factory=datetime.now)
    
    def is_expired(self, ttl_hours: int) -> bool:
        """Vérifie si l'entrée est expirée"""
        return datetime.now() - self.created_at > timedelta(hours=ttl_hours)
    
    def access(self):
        """Marque un accès à l'entrée"""
        self.access_count += 1
        self.last_accessed = datetime.now()


class SimpleCache:
    """Cache simple en mémoire avec TTL"""
    
    def __init__(self, ttl_hours: int = 24, max_size: int = 1000):
        self.cache: Dict[str, CacheEntry] = {}
        self.ttl_hours = ttl_hours
        self.max_size = max_size
        self.logger = StructuredLogger("SimpleCache")
    
    def _generate_key(self, *args, **kwargs) -> str:
        """Génère une clé de cache"""
        key_data = str(args) + str(sorted(kwargs.items()))
        return hashlib.md5(key_data.encode()).hexdigest()
    
    def get(self, key: str) -> Optional[Any]:
        """Récupère une valeur du cache"""
        if key not in self.cache:
            return None
        
        entry = self.cache[key]
        if entry.is_expired(self.ttl_hours):
            del self.cache[key]
            self.logger.debug("Cache entry expired", key=key)
            return None
        
        entry.access()
        self.logger.debug("Cache hit", key=key, access_count=entry.access_count)
        return entry.data
    
    def set(self, key: str, value: Any):
        """Stocke une valeur dans le cache"""
        # Nettoyage si taille max atteinte
        if len(self.cache) >= self.max_size:
            self._cleanup()
        
        self.cache[key] = CacheEntry(data=value, created_at=datetime.now())
        self.logger.debug("Cache set", key=key, cache_size=len(self.cache))
    
    def _cleanup(self):
        """Nettoie les entrées expirées et anciennes"""
        now = datetime.now()
        expired_keys = [
            key for key, entry in self.cache.items()
            if entry.is_expired(self.ttl_hours)
        ]
        
        for key in expired_keys:
            del self.cache[key]
        
        # Si toujours trop plein, supprimer les moins utilisées
        if len(self.cache) >= self.max_size:
            sorted_entries = sorted(
                self.cache.items(),
                key=lambda x: (x[1].access_count, x[1].last_accessed)
            )
            keys_to_remove = [key for key, _ in sorted_entries[:self.max_size // 4]]
            for key in keys_to_remove:
                del self.cache[key]
        
        self.logger.info("Cache cleanup completed", 
                        expired=len(expired_keys), 
                        current_size=len(self.cache))


# ==================== RETRY AVEC BACKOFF ====================

class RetryManager:
    """Gestionnaire de retry avec backoff exponentiel"""
    
    def __init__(self, max_retries: int = 3, initial_delay: float = 1.0, 
                 backoff_factor: float = 2.0, max_delay: float = 60.0):
        self.max_retries = max_retries
        self.initial_delay = initial_delay
        self.backoff_factor = backoff_factor
        self.max_delay = max_delay
        self.logger = StructuredLogger("RetryManager")
    
    def execute_with_retry(self, func, *args, **kwargs):
        """Exécute une fonction avec retry automatique"""
        last_exception = None
        
        for attempt in range(self.max_retries + 1):
            try:
                self.logger.debug("Executing function", 
                                attempt=attempt + 1, 
                                max_retries=self.max_retries + 1,
                                function=func.__name__)
                return func(*args, **kwargs)
                
            except Exception as e:
                last_exception = e
                
                if attempt == self.max_retries:
                    self.logger.error("All retry attempts failed", 
                                    attempts=attempt + 1,
                                    function=func.__name__,
                                    error=str(e))
                    break
                
                delay = min(
                    self.initial_delay * (self.backoff_factor ** attempt),
                    self.max_delay
                )
                
                self.logger.warning("Function failed, retrying", 
                                  attempt=attempt + 1,
                                  function=func.__name__,
                                  error=str(e),
                                  retry_delay=delay)
                
                time.sleep(delay)
        
        raise RetryError(f"Failed after {self.max_retries + 1} attempts: {last_exception}")


# ==================== VALIDATION DES DONNÉES ====================

class DataValidator:
    """Validateur de données avec règles strictes"""
    
    @staticmethod
    def validate_query_data(data: Dict) -> Dict[str, List[str]]:
        """Valide les données d'une requête"""
        errors = {}
        
        # Validation des champs obligatoires
        required_fields = ['id', 'text']
        for field in required_fields:
            if field not in data:
                errors.setdefault('missing_fields', []).append(field)
            # ✅ CORRECTIF : Vérification explicite pour chaque type
            elif field == 'id' and data[field] is None:
                errors.setdefault('empty_fields', []).append(field)
            elif field == 'text' and (not data[field] or data[field].strip() == ""):
                errors.setdefault('empty_fields', []).append(field)
        
        # Validation des types
        if 'id' in data and not isinstance(data['id'], int):
            errors.setdefault('type_errors', []).append(f"id must be int, got {type(data['id'])}")
        
        if 'text' in data and not isinstance(data['text'], str):
            errors.setdefault('type_errors', []).append(f"text must be str, got {type(data['text'])}")
        
        if 'word_count' in data and not isinstance(data['word_count'], int):
            errors.setdefault('type_errors', []).append(f"word_count must be int, got {type(data['word_count'])}")
        
        # Validation des valeurs
        if 'word_count' in data and data['word_count'] < 100:
            errors.setdefault('value_errors', []).append("word_count must be >= 100")
        
        return errors
        
    @staticmethod
    def validate_agent_response(data: Dict) -> Dict[str, List[str]]:
        """Valide les données agent_response"""
        errors = {}
        
        expected_fields = [
            'shock_statistics', 'expert_insights', 'benchmark_data',
            'market_trends', 'competitive_landscape', 'credibility_boosters',
            'content_marketing_angles'
        ]
        
        for field in expected_fields:
            if field in data and not isinstance(data[field], list):
                errors.setdefault('type_errors', []).append(
                    f"{field} must be list, got {type(data[field])}"
                )
        
        return errors
    
    @staticmethod
    def validate_json_structure(data: Any) -> Dict[str, List[str]]:
        """Valide la structure JSON"""
        errors = {}
        
        if not isinstance(data, dict):
            errors.setdefault('structure_errors', []).append(
                f"Root must be dict, got {type(data)}"
            )
            return errors
        
        # Validation de la structure attendue
        if 'queries' in data:
            if not isinstance(data['queries'], list):
                errors.setdefault('structure_errors', []).append(
                    "queries must be list"
                )
            else:
                for i, query in enumerate(data['queries']):
                    query_errors = DataValidator.validate_query_data(query)
                    if query_errors:
                        errors[f'query_{i}'] = query_errors
        
        return errors


# ==================== CLIENT API ROBUSTE ====================

class RobustDeepSeekClient:
    """Client DeepSeek robuste avec retry et validation"""
    
    def __init__(self, config: APIConfig, cache: Optional[SimpleCache] = None):
        self.config = config
        self.retry_manager = RetryManager(
            max_retries=config.max_retries,
            initial_delay=config.retry_delay,
            max_delay=config.max_retry_delay,
            backoff_factor=config.backoff_factor
        )
        self.cache = cache
        self.logger = StructuredLogger("RobustDeepSeekClient")
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "SEO-Generator-Robust/1.0"
        })
        
        # Health check au démarrage
        self._health_check()
    
    def _health_check(self):
        """Vérifie la connectivité API"""
        try:
            # Test simple de connectivité
            response = self.session.get(
                f"{self.config.base_url.rstrip('/')}/models",
                timeout=10
            )
            if response.status_code == 200:
                self.logger.info("API health check passed")
            else:
                self.logger.warning("API health check failed", 
                                  status_code=response.status_code)
        except Exception as e:
            self.logger.error("API health check error", error=str(e))
    
    def _generate_cache_key(self, model: str, messages: List[Dict], 
                          temperature: float, max_tokens: int) -> str:
        """Génère une clé de cache pour la requête"""
        key_data = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens
        }
        return hashlib.md5(json.dumps(key_data, sort_keys=True).encode()).hexdigest()
    
    def _make_api_call(self, model: str, messages: List[Dict], 
                      temperature: float, max_tokens: int) -> Dict:
        """Effectue l'appel API brut"""
        url = f"{self.config.base_url}/chat/completions"
        data = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False
        }
        
        self.logger.debug("Making API call", 
                         model=model, 
                         messages_count=len(messages),
                         temperature=temperature,
                         max_tokens=max_tokens)
        
        response = self.session.post(url, json=data, timeout=self.config.timeout)
        response.raise_for_status()
        
        result = response.json()
        
        # Validation de la réponse
        if 'choices' not in result or not result['choices']:
            raise ValueError("Invalid API response: missing choices")
        
        if 'message' not in result['choices'][0]:
            raise ValueError("Invalid API response: missing message")
        
        self.logger.info("API call successful", 
                        tokens_used=result.get('usage', {}).get('total_tokens', 'unknown'))
        
        return result
    
    def chat_completions_create(self, model: str, messages: List[Dict], 
                              temperature: float = 0.7, max_tokens: int = 3000) -> Dict:
        """Interface publique avec cache et retry"""
        # Validation des entrées
        if not model or not isinstance(model, str):
            raise ValueError("Model must be a non-empty string")
        
        if not messages or not isinstance(messages, list):
            raise ValueError("Messages must be a non-empty list")
        
        for msg in messages:
            if not isinstance(msg, dict) or 'role' not in msg or 'content' not in msg:
                raise ValueError("Each message must have 'role' and 'content'")
        
        # Vérification du cache
        cache_key = None
        if self.cache:
            cache_key = self._generate_cache_key(model, messages, temperature, max_tokens)
            cached_result = self.cache.get(cache_key)
            if cached_result:
                self.logger.info("Cache hit for API call", cache_key=cache_key)
                return cached_result
        
        # Appel avec retry
        try:
            result = self.retry_manager.execute_with_retry(
                self._make_api_call, model, messages, temperature, max_tokens
            )
            
            # Mise en cache
            if self.cache and cache_key:
                self.cache.set(cache_key, result)
            
            return result
            
        except Exception as e:
            self.logger.error("API call failed", error=str(e))
            raise


# ==================== GESTIONNAIRES ROBUSTES ====================

class RobustPromptManager:
    """Gestionnaire de prompts avec validation stricte"""
    
    def __init__(self, prompts_dir: Path):
        self.prompts_dir = prompts_dir
        self.logger = StructuredLogger("RobustPromptManager")
        self._prompt_cache = {}
        self._ensure_directory()
        self._find_plan_prompt()
    
    def _ensure_directory(self):
        """Assure l'existence du répertoire prompts"""
        try:
            self.prompts_dir.mkdir(parents=True, exist_ok=True)
            self.logger.info("Prompts directory ready", path=str(self.prompts_dir))
        except Exception as e:
            raise ConfigurationError(f"Cannot create prompts directory: {e}")
    
    def _find_plan_prompt(self):
        """Trouve et valide le prompt de plan"""
        candidates = [
            self.prompts_dir / "plan_generator.yaml",
            self.prompts_dir / "plan_generator.txt"
        ]
        
        for candidate in candidates:
            if candidate.exists():
                self.plan_prompt_file = candidate.name
                self.logger.info("Plan prompt found", file=candidate.name)
                # Test de chargement
                try:
                    self.load_prompt(candidate.name)
                    return
                except Exception as e:
                    self.logger.error("Failed to load prompt", file=candidate.name, error=str(e))
                    continue
        
        raise ConfigurationError(
            f"No valid plan prompt found. Create one of: {[c.name for c in candidates]}"
        )
    
    def load_prompt(self, filename: str) -> str:
        """Charge un prompt avec cache et validation"""
        if filename in self._prompt_cache:
            return self._prompt_cache[filename]
        
        prompt_path = self.prompts_dir / filename
        if not prompt_path.exists():
            raise FileNotFoundError(f"Prompt file not found: {prompt_path}")
        
        try:
            content = prompt_path.read_text(encoding='utf-8')
            if not content.strip():
                raise ValueError(f"Prompt file is empty: {prompt_path}")
            
            self._prompt_cache[filename] = content
            self.logger.debug("Prompt loaded", file=filename, size=len(content))
            return content
            
        except Exception as e:
            raise ConfigurationError(f"Cannot load prompt {filename}: {e}")
    

    def format_prompt(self, template_vars: Dict[str, Any]) -> str:
        """Formate le prompt avec string.Template pour éviter les conflits JSON"""
        from string import Template
        
        template_content = self.load_prompt(self.plan_prompt_file)
        
        try:
            # SOLUTION 2: Utiliser string.Template avec $ au lieu de {}
            # Convertir le template de {} vers $
            converted_template = self._convert_to_template_format(template_content, template_vars)
            
            # Utiliser Template pour le remplacement
            template = Template(converted_template)
            formatted_template = template.safe_substitute(**template_vars)
            
            self.logger.debug("Prompt formatted with Template", 
                            variables_used=len(template_vars),
                            template_length=len(formatted_template))
            
            return formatted_template
            
        except Exception as e:
            self.logger.error("Template formatting failed", error=str(e))
            return template_content
    
    def _convert_to_template_format(self, text: str, template_vars: Dict[str, Any]) -> str:
        """Convertit les placeholders {var} en $var pour Template"""
        converted_text = text
        
        # Remplacer seulement les variables connues
        for var_name in template_vars.keys():
            old_placeholder = "{" + var_name + "}"
            new_placeholder = "${" + var_name + "}"
            converted_text = converted_text.replace(old_placeholder, new_placeholder)
            self.logger.debug("Converted placeholder", 
                            old=old_placeholder, 
                            new=new_placeholder)
        
        return converted_text
    
    def _extract_remaining_placeholders(self, text: str) -> List[str]:
        """Extrait les placeholders non remplacés dans le texte"""
        import re
        pattern = r'\{([^}]+)\}'
        return list(set(re.findall(pattern, text)))


class RobustFileManager:
    """Gestionnaire de fichiers avec validation"""
    
    def __init__(self, static_dir: Path):
        self.static_dir = static_dir
        self.logger = StructuredLogger("RobustFileManager")
    
    def find_consigne_file(self) -> Path:
        """Trouve le fichier de consigne avec validation"""
        if not self.static_dir.exists():
            raise FileNotFoundError(f"Static directory not found: {self.static_dir}")
        
        pattern = "consigne*.json"
        consigne_files = list(self.static_dir.glob(pattern))
        
        if not consigne_files:
            raise FileNotFoundError(
                f"No consigne file found in {self.static_dir} (pattern: {pattern})"
            )
        
        if len(consigne_files) == 1:
            found_file = consigne_files[0]
            self.logger.info("Consigne file found", file=found_file.name)
        else:
            # Prendre le plus récent
            consigne_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
            found_file = consigne_files[0]
            self.logger.info("Multiple consigne files found, using most recent", 
                           file=found_file.name,
                           total_found=len(consigne_files))
        
        # Validation du fichier
        self._validate_consigne_file(found_file)
        return found_file
    
    def _validate_consigne_file(self, file_path: Path):
        """Valide le fichier de consigne"""
        try:
            data = self.load_json_file(file_path)
            errors = DataValidator.validate_json_structure(data)
            if errors:
                self.logger.warning("Consigne file has validation errors", 
                                  file=file_path.name,
                                  errors=errors)
        except Exception as e:
            raise ValidationError(f"Invalid consigne file {file_path.name}: {e}")
    
    def load_json_file(self, file_path: Path) -> Dict:
        """Charge un fichier JSON avec validation"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            self.logger.debug("JSON file loaded", 
                            file=file_path.name,
                            size=file_path.stat().st_size)
            return data
            
        except json.JSONDecodeError as e:
            raise ValidationError(f"Invalid JSON in {file_path.name}: {e}")
        except Exception as e:
            raise ConfigurationError(f"Cannot load {file_path.name}: {e}")
    
    def save_json_file(self, file_path: Path, data: Dict):
        """Sauvegarde un fichier JSON avec backup"""
        # Backup de l'ancien fichier
        if file_path.exists():
            backup_path = file_path.with_suffix(f'.bak.{int(time.time())}')
            try:
                file_path.rename(backup_path)
                self.logger.debug("Backup created", backup=backup_path.name)
            except Exception as e:
                self.logger.warning("Backup creation failed", error=str(e))
        
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            
            self.logger.info("JSON file saved", 
                           file=file_path.name,
                           size=file_path.stat().st_size)
            
        except Exception as e:
            self.logger.error("Failed to save JSON file", 
                            file=file_path.name,
                            error=str(e))
            raise


# ==================== ANALYSEURS ROBUSTES ====================

class RobustDataAnalyzer:
    """Analyseur de données avec validation stricte"""
    
    def __init__(self):
        self.logger = StructuredLogger("RobustDataAnalyzer")
    
    def analyze_data_richness(self, agent_response: Dict) -> Dict[str, int]:
        """Analyse la richesse des données avec validation"""
        if not isinstance(agent_response, dict):
            self.logger.warning("Invalid agent_response type", 
                              expected="dict", 
                              got=type(agent_response).__name__)
            return self._empty_richness()
        
        # Validation des données
        errors = DataValidator.validate_agent_response(agent_response)
        if errors:
            self.logger.warning("Agent response validation errors", errors=errors)
        
        try:
            richness = {
                'shock_statistics': len(agent_response.get('shock_statistics', [])),
                'expert_insights': len(agent_response.get('expert_insights', [])),
                'benchmark_data': len(agent_response.get('benchmark_data', [])),
                'market_trends': len(agent_response.get('market_trends', [])),
                'competitive_landscape': len(agent_response.get('competitive_landscape', [])),
                'hook_potential': 1 if agent_response.get('hook_potential') else 0,
                'credibility_boosters': len(agent_response.get('credibility_boosters', [])),
                'content_marketing_angles': len(agent_response.get('content_marketing_angles', []))
            }
            
            total_richness = sum(richness.values())
            self.logger.debug("Data richness analyzed", 
                            total_points=total_richness,
                            breakdown=richness)
            
            return richness
            
        except Exception as e:
            self.logger.error("Failed to analyze data richness", error=str(e))
            return self._empty_richness()
    
    def _empty_richness(self) -> Dict[str, int]:
        """Retourne une analyse vide en cas d'erreur"""
        return {
            'shock_statistics': 0,
            'expert_insights': 0,
            'benchmark_data': 0,
            'market_trends': 0,
            'competitive_landscape': 0,
            'hook_potential': 0,
            'credibility_boosters': 0,
            'content_marketing_angles': 0
        }


# ==================== GÉNÉRATEUR PRINCIPAL ROBUSTE ====================

class RobustGenerateurPlanArticle:
    """Générateur principal robuste avec toutes les améliorations"""
    
    def __init__(self, config: AppConfig, api_config: APIConfig):
        self.config = config
        self.logger = StructuredLogger("RobustGenerateurPlanArticle", config.log_level)
        
        # Initialisation du cache
        self.cache = SimpleCache(ttl_hours=config.cache_ttl_hours) if config.cache_enabled else None
        
        # Initialisation des composants
        self.api_client = RobustDeepSeekClient(api_config, self.cache)
        self.prompt_manager = RobustPromptManager(config.prompts_dir)
        self.file_manager = RobustFileManager(config.static_dir)
        self.data_analyzer = RobustDataAnalyzer()
        
        # Chargement des données
        self.consigne_path = self.file_manager.find_consigne_file()
        self.consigne_data = self.file_manager.load_json_file(self.consigne_path)
        
        self.logger.info("Generator initialized successfully", 
                        cache_enabled=config.cache_enabled,
                        prompts_dir=str(config.prompts_dir),
                        consigne_file=self.consigne_path.name)
    
    def get_query_data(self, query_id: int) -> Optional[Dict]:
        """Récupère les données d'une requête avec validation"""
        if not isinstance(query_id, int):
            self.logger.error("Invalid query_id type", 
                            expected="int", 
                            got=type(query_id).__name__)
            return None
        
        queries = self.consigne_data.get('queries', [])
        for query in queries:
            if query.get('id') == query_id:
                # Validation des données de la requête
                errors = DataValidator.validate_query_data(query)
                if errors:
                    self.logger.warning("Query data validation errors", 
                                      query_id=query_id,
                                      errors=errors)
                return query
        
        self.logger.warning("Query not found", query_id=query_id)
        return None
    
    def generer_plan_article_optimise(self, query_data: Dict) -> Optional[Dict]:
        """Génère un plan avec toutes les validations et retry"""
        query_id = query_data.get('id', 'unknown')
        
        try:
            # Validation des données d'entrée
            errors = DataValidator.validate_query_data(query_data)
            if errors:
                self.logger.error("Invalid query data", 
                                query_id=query_id,
                                errors=errors)
                return None
            
            # Extraction des paramètres avec valeurs par défaut
            requete = query_data.get('text', '')
            word_count = query_data.get('word_count', 1000)
            top_keywords = query_data.get('top_keywords', '')
            plan_config = query_data.get('plan', {})
            agent_response = query_data.get('agent_response', {})
            angle_recommande = query_data.get('angle_analysis', {}).get('angle_recommande', '')
            
            # Analyse de la richesse des données
            data_richness = self.data_analyzer.analyze_data_richness(agent_response)
            
            # Configuration des sections
            dev_config = plan_config.get('developpement', {})
            base_sections = dev_config.get('nombre_sections', 3)
            
            # Génération des sections optimales
            optimal_sections = self._suggest_optimal_sections(
                agent_response, base_sections, angle_recommande
            )
            
            # Assignation des données aux sections
            sections_with_data = [
                self._assign_data_to_section(section, agent_response) 
                for section in optimal_sections
            ]
            
            # Construction du contexte enrichi
            enhanced_context = self._create_enhanced_context(sections_with_data)
            sections_json_str = self._build_sections_json(sections_with_data)
            
            # Construction du hook
            hook_suggestion = self._build_hook_suggestion(agent_response)
            
            # Préparation des variables pour le prompt
            template_vars = {
                'requete': requete,
                'word_count': word_count,
                'top_keywords': top_keywords,
                'nb_sections': len(sections_with_data),
                'enhanced_context': enhanced_context,
                'hook_suggestion': hook_suggestion,
                'sections_json_str': sections_json_str,
                'angle_recommande': angle_recommande
            }
            
            # Formatage et appel API
            formatted_prompt = self.prompt_manager.format_prompt(template_vars)
            
            # Log du prompt envoyé (en mode debug)
            if self.config.debug_mode:
                print("="*100)
                print("PROMPT COMPLET ENVOYÉ À L'API:")
                print("="*100)
                print(formatted_prompt)
                print("="*100)
                print("FIN DU PROMPT")
                print("="*100)
            else:
                self.logger.info("Prompt prepared for API", 
                            prompt_length=len(formatted_prompt),
                            variables_count=len(template_vars))
            
            response = self.api_client.chat_completions_create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": formatted_prompt}],
                temperature=0.7,
                max_tokens=3000
            )
            
            # Extraction et nettoyage du contenu
            plan_content = response['choices'][0]['message']['content'].strip()
            plan_content = self._clean_json_content(plan_content)
            
            # Parsing JSON avec validation
            plan_json = self._parse_and_validate_plan(plan_content)
            
            if plan_json:
                self.logger.info("Plan generated successfully", 
                               query_id=query_id,
                               sections_count=len(sections_with_data),
                               data_points=sum(data_richness.values()))
                return plan_json
            else:
                self.logger.error("Failed to generate valid plan", query_id=query_id)
                return None
                
        except Exception as e:
            self.logger.error("Plan generation failed", 
                            query_id=query_id,
                            error=str(e),
                            traceback=traceback.format_exc())
            return None
    
    def _suggest_optimal_sections(self, agent_response: Dict, base_sections: int, 
                                 angle_recommande: str) -> List[Dict]:
        """Suggère des sections optimales (logique préservée)"""
        try:
            richness = self.data_analyzer.analyze_data_richness(agent_response)
            sections = []
            
            # Détection du type d'angle
            angle_type = self._detect_angle_type(angle_recommande)
            
            # Section 1: Introduction/bases
            sections.append({
                'type': 'éducatif',
                'focus': 'bases_concepts',
                'data_sources': ['shock_statistics', 'expert_insights'],
                'title_hint': 'Comprendre les bases/fondamentaux',
                'angle_adaptation': f"Adapter selon l'angle: {angle_recommande}",
                'angle_type': angle_type
            })
            
            # Sections adaptatives
            if richness['benchmark_data'] >= 2:
                sections.append({
                    'type': 'informatif',
                    'focus': 'donnees_performance',
                    'data_sources': ['benchmark_data', 'shock_statistics'],
                    'title_hint': 'Données de performance et statistiques clés',
                    'specific_data': agent_response.get('benchmark_data', []),
                    'angle_adaptation': f"Interpréter les données selon: {angle_recommande}",
                    'angle_type': angle_type
                })
            
            if richness['market_trends'] >= 1:
                sections.append({
                    'type': 'informatif',
                    'focus': 'tendances_marche',
                    'data_sources': ['market_trends', 'competitive_landscape'],
                    'title_hint': 'Évolutions du marché et tendances',
                    'specific_data': agent_response.get('market_trends', []),
                    'angle_adaptation': f"Contextualiser selon: {angle_recommande}",
                    'angle_type': angle_type
                })
            
            if richness['competitive_landscape'] >= 1:
                sections.append({
                    'type': 'informatif',
                    'focus': 'comparatifs',
                    'data_sources': ['competitive_landscape', 'benchmark_data'],
                    'title_hint': 'Comparaisons et alternatives',
                    'specific_data': agent_response.get('competitive_landscape', []),
                    'angle_adaptation': f"Comparer dans l'optique: {angle_recommande}",
                    'angle_type': angle_type
                })
            
            if richness['expert_insights'] >= 2:
                sections.append({
                    'type': 'informatif',
                    'focus': 'avis_experts',
                    'data_sources': ['expert_insights', 'credibility_boosters'],
                    'title_hint': 'Recommandations d\'experts',
                    'specific_data': agent_response.get('expert_insights', []),
                    'angle_adaptation': f"Sélectionner experts pertinents pour: {angle_recommande}",
                    'angle_type': angle_type
                })
            
            # Sections commerciales
            if len(sections) < base_sections - 1:
                sections.append({
                    'type': 'commercial léger',
                    'focus': 'solutions_pratiques',
                    'data_sources': ['content_marketing_angles', 'benchmark_data'],
                    'title_hint': 'Solutions pratiques et conseils',
                    'angle_adaptation': f"Proposer solutions alignées avec: {angle_recommande}",
                    'angle_type': angle_type
                })
            
            sections.append({
                'type': 'commercial subtil',
                'focus': 'optimisation_resultats',
                'data_sources': ['content_marketing_angles', 'market_trends'],
                'title_hint': 'Optimiser ses résultats/choix',
                'angle_adaptation': f"Conclure en cohérence avec: {angle_recommande}",
                'angle_type': angle_type
            })
            
            final_sections = sections[:base_sections] if len(sections) > base_sections else sections
            self.logger.debug("Sections generated", 
                            count=len(final_sections),
                            angle_type=angle_type)
            return final_sections
            
        except Exception as e:
            self.logger.error("Failed to suggest sections", error=str(e))
            # Retour fallback
            return [{
                'type': 'éducatif',
                'focus': 'bases_concepts',
                'title_hint': 'Section par défaut',
                'angle_type': 'généraliste'
            }]
    
    def _detect_angle_type(self, angle_recommande: str) -> str:
        """Détecte le type d'angle (logique préservée)"""
        if not isinstance(angle_recommande, str):
            return 'généraliste'
            
        angle_lower = angle_recommande.lower()
        
        angle_keywords = {
            'psychologique': ['psycholog', 'émot', 'humain', 'stress', 'mental'],
            'géographique': ['géograph', 'local', 'région', 'ville'],
            'financier': ['budget', 'financ', 'économ', 'gestion'],
            'technique': ['technique', 'expert', 'professionnel', 'spécialisé'],
            'comparatif': ['comparai', 'versus', 'alternative', 'choix'],
            'prospectif': ['tendance', 'évolution', 'futur', 'innovation']
        }
        
        for angle_type, keywords in angle_keywords.items():
            if any(word in angle_lower for word in keywords):
                return angle_type
        
        return 'généraliste'

    def _attempt_json_repair(self, content: str) -> Optional[Dict]:
        """Tentative de réparation automatique du JSON malformé"""
        try:
            self.logger.info("Attempting JSON repair")
            
            # Réparations courantes
            repaired_content = content
            
            # 1. Supprimer les virgules en trop
            repaired_content = re.sub(r',(\s*[}\]])', r'\1', repaired_content)
            
            # 2. Ajouter des guillemets manquants autour des clés
            repaired_content = re.sub(r'(\w+)(\s*:)', r'"\1"\2', repaired_content)
            
            # 3. Corriger les guillemets simples en doubles
            repaired_content = repaired_content.replace("'", '"')
            
            # 4. S'assurer que le JSON se termine correctement
            if not repaired_content.rstrip().endswith('}'):
                repaired_content = repaired_content.rstrip() + '}'
            
            # Tentative de parsing du JSON réparé
            plan_json = json.loads(repaired_content)
            
            self.logger.info("JSON repair successful")
            return plan_json
            
        except Exception as e:
            self.logger.error("JSON repair failed", error=str(e))
            return None
    
    def _assign_data_to_section(self, section: Dict, agent_response: Dict) -> Dict:
        """Assigne des données spécifiques à une section (logique préservée)"""
        try:
            section_copy = section.copy()
            assigned_data = {}
            
            focus = section.get('focus', '')
            angle_type = section.get('angle_type', 'généraliste')
            angle_adaptation = section.get('angle_adaptation', '')
            
            # Assignation par focus
            if focus == 'bases_concepts':
                stats = agent_response.get('shock_statistics', [])
                if stats:
                    assigned_data['primary_statistic'] = stats[0]
                    assigned_data['supporting_insights'] = agent_response.get('expert_insights', [])[:1]
            
            elif focus == 'donnees_performance':
                assigned_data['benchmark_metrics'] = agent_response.get('benchmark_data', [])
                shock_stats = agent_response.get('shock_statistics', [])
                assigned_data['supporting_statistics'] = shock_stats[1:] if len(shock_stats) > 1 else []
            
            elif focus == 'tendances_marche':
                assigned_data['market_trends'] = agent_response.get('market_trends', [])
                assigned_data['competitive_data'] = agent_response.get('competitive_landscape', [])
            
            elif focus == 'comparatifs':
                assigned_data['comparisons'] = agent_response.get('competitive_landscape', [])
                benchmark_data = agent_response.get('benchmark_data', [])
                assigned_data['quantified_benefits'] = [
                    b for b in benchmark_data 
                    if 'économis' in b.get('metric', '').lower()
                ]
            
            elif focus == 'avis_experts':
                assigned_data['expert_opinions'] = agent_response.get('expert_insights', [])
                assigned_data['authority_sources'] = agent_response.get('credibility_boosters', [])
            
            elif focus in ['solutions_pratiques', 'optimisation_resultats']:
                assigned_data['marketing_angles'] = agent_response.get('content_marketing_angles', [])
                assigned_data['hook_elements'] = agent_response.get('hook_potential', {})
            
            # Enrichissement avec l'angle
            assigned_data['angle_context'] = {
                'angle_type': angle_type,
                'angle_instruction': angle_adaptation,
                'prioritized_approach': self._get_approach_by_angle(angle_type)
            }
            
            section_copy['assigned_data'] = assigned_data
            return section_copy
            
        except Exception as e:
            self.logger.error("Failed to assign data to section", 
                            focus=section.get('focus', 'unknown'),
                            error=str(e))
            section['assigned_data'] = {}
            return section
    
    def _get_approach_by_angle(self, angle_type: str) -> str:
        """Retourne l'approche par type d'angle (logique préservée)"""
        approaches = {
            'psychologique': 'Privilégier l\'impact émotionnel et humain des données',
            'géographique': 'Contextualiser selon les spécificités locales/régionales',
            'financier': 'Mettre l\'accent sur l\'aspect économique et budgétaire',
            'technique': 'Approfondir les aspects techniques et expertises',
            'comparatif': 'Structurer en comparaisons et alternatives',
            'prospectif': 'Orienter vers les évolutions et tendances futures',
            'généraliste': 'Équilibrer tous les aspects selon les données disponibles'
        }
        return approaches.get(angle_type, approaches['généraliste'])
    
    def _create_enhanced_context(self, sections_with_data: List[Dict]) -> str:
        """Crée le contexte enrichi (logique préservée)"""
        try:
            context_parts = []
            
            for i, section in enumerate(sections_with_data, 1):
                section_context = [
                    f"**SECTION {i} - {section.get('title_hint', 'Section')} ({section.get('type', 'informatif')})**"
                ]
                
                assigned_data = section.get('assigned_data', {})
                
                # Contexte d'angle
                angle_context = assigned_data.get('angle_context', {})
                if angle_context:
                    section_context.extend([
                        f"🎯 ANGLE D'APPROCHE: {angle_context.get('angle_type', 'généraliste').upper()}",
                        f"📋 INSTRUCTION: {angle_context.get('angle_instruction', 'Traitement standard')}",
                        f"🎨 APPROCHE PRIORITAIRE: {angle_context.get('prioritized_approach', 'Équilibrer tous les aspects')}",
                        ""
                    ])
                
                # Données spécifiques
                for data_type, data_content in assigned_data.items():
                    if not data_content or data_type == 'angle_context':
                        continue
                    
                    if data_type == 'primary_statistic' and isinstance(data_content, dict):
                        section_context.append(f"📊 STATISTIQUE PRINCIPALE: {data_content.get('statistic', 'N/A')}")
                        if 'usage_potential' in data_content:
                            section_context.append(f"   → Usage suggéré: {data_content['usage_potential']}")
                    
                    elif data_type == 'benchmark_metrics' and isinstance(data_content, list):
                        section_context.append(f"📈 MÉTRIQUES DE PERFORMANCE ({len(data_content)} éléments):")
                        for metric in data_content:
                            section_context.append(f"   • {metric.get('metric', 'N/A')} | {metric.get('sample_size', 'N/A')}")
                    
                    elif data_type == 'market_trends' and isinstance(data_content, list):
                        section_context.append(f"📈 TENDANCES MARCHÉ ({len(data_content)} éléments):")
                        for trend in data_content:
                            section_context.append(f"   • {trend.get('trend', 'N/A')}")
                            if 'commercial_opportunity' in trend:
                                section_context.append(f"     💡 Opportunité: {trend['commercial_opportunity']}")
                    
                    elif data_type == 'expert_opinions' and isinstance(data_content, list):
                        section_context.append(f"👨‍💼 AVIS D'EXPERTS ({len(data_content)} éléments):")
                        for insight in data_content:
                            section_context.append(f"   • {insight.get('insight', 'N/A')}")
                            if 'authority_source' in insight:
                                section_context.append(f"     🏛️ Source: {insight['authority_source']}")
                    
                    elif data_type == 'comparisons' and isinstance(data_content, list):
                        section_context.append(f"⚖️ ÉLÉMENTS COMPARATIFS ({len(data_content)} éléments):")
                        for comp in data_content:
                            section_context.append(f"   • {comp.get('comparison_point', 'N/A')}: {comp.get('quantified_difference', 'N/A')}")
                    
                    elif data_type == 'marketing_angles' and isinstance(data_content, list):
                        section_context.append(f"🎯 ANGLES MARKETING: {' | '.join(data_content)}")
                    
                    elif data_type == 'hook_elements' and isinstance(data_content, dict):
                        if 'intro_hooks' in data_content:
                            section_context.append(f"🪝 ÉLÉMENTS D'ACCROCHE: {' | '.join(data_content['intro_hooks'])}")
                
                if len(section_context) > 1:
                    context_parts.append('\n'.join(section_context))
            
            return '\n\n'.join(context_parts)
            
        except Exception as e:
            self.logger.error("Failed to create enhanced context", error=str(e))
            return "Contexte non disponible"
    
    def _build_sections_json(self, sections_with_data: List[Dict]) -> str:
        """Construit le JSON des sections avec échappement correct"""
        try:
            sections_json = []
            
            for i, section in enumerate(sections_with_data, 1):
                section_template = f'''    "section_{i}": {{
      "title": "Titre optimisé pour: {section.get('title_hint', 'Section')}",
      "angle": "{section.get('type', 'informatif')}",
      "focus_theme": "{section.get('focus', 'general')}",
      "objectives": [
        "Objectif principal basé sur le focus {section.get('focus', 'general')}",
        "Objectif secondaire exploitant les données assignées"
      ],
      "key_points": [
        "Point clé exploitant les données spécifiques assignées",
        "Point clé créant de la valeur avec les insights disponibles"
      ],
      "data_to_include": [
        "Données spécifiques assignées à cette section",
        "Éléments de preuve pertinents du contexte enrichi"
      ]'''
                
                # Ajout des données spécifiques - SIMPLIFIÉ pour éviter les accolades imbriquées
                assigned_data = section.get('assigned_data', {})
                if assigned_data:
                    data_types = [data_type for data_type, data_content in assigned_data.items() if data_content]
                    if data_types:
                        section_template += f''',
      "assigned_data_types": {str(data_types)}'''
                
                # CTA pour sections commerciales
                if "commercial" in section.get('type', ''):
                    section_template += f''',
      "cta_hint": "Call-to-action adapté au niveau {section.get('type', '')}"'''
                
                section_template += "\n    }"
                sections_json.append(section_template)
            
            return ",\n".join(sections_json)
            
        except Exception as e:
            self.logger.error("Failed to build sections JSON", error=str(e))
            return '"section_1": {"title": "Section par défaut", "angle": "informatif"}'
    
    def _build_hook_suggestion(self, agent_response: Dict) -> str:
        """Construit la suggestion de hook"""
        try:
            shock_stats = agent_response.get('shock_statistics', [])
            if shock_stats and isinstance(shock_stats, list) and len(shock_stats) > 0:
                first_stat = shock_stats[0]
                if isinstance(first_stat, dict):
                    stat_text = first_stat.get('statistic', 'Stat non trouvée')
                    return f"ACCROCHE RECOMMANDÉE: {stat_text}"
            
            return "Statistique générale ou fait marquant"
            
        except Exception as e:
            self.logger.error("Failed to build hook suggestion", error=str(e))
            return "Fait marquant à déterminer"
    
    def _clean_json_content(self, content: str) -> str:
        """Nettoie et extrait le contenu JSON de la réponse API"""
        try:
            content = content.strip()
            
            # Log du contenu brut pour debug
            self.logger.debug("Raw API response preview", 
                            content_start=content[:200],
                            content_length=len(content))
            
            # Méthode 1: Chercher le JSON entre ```json et ```
            import re
            json_pattern = r'```json\s*(.*?)\s*```'
            json_match = re.search(json_pattern, content, re.DOTALL)
            
            if json_match:
                extracted_json = json_match.group(1).strip()
                self.logger.debug("JSON extracted from markdown block", 
                                json_length=len(extracted_json))
                return extracted_json
            
            # Méthode 2: Chercher le JSON entre ``` et ``` (sans "json")
            generic_pattern = r'```\s*(.*?)\s*```'
            generic_match = re.search(generic_pattern, content, re.DOTALL)
            
            if generic_match:
                extracted_json = generic_match.group(1).strip()
                self.logger.debug("JSON extracted from generic markdown block", 
                                json_length=len(extracted_json))
                return extracted_json
            
            # Méthode 3: Chercher le premier { jusqu'au dernier }
            first_brace = content.find('{')
            last_brace = content.rfind('}')
            
            if first_brace != -1 and last_brace != -1 and first_brace < last_brace:
                extracted_json = content[first_brace:last_brace + 1]
                self.logger.debug("JSON extracted by brace detection", 
                                json_start=first_brace,
                                json_end=last_brace,
                                json_length=len(extracted_json))
                return extracted_json
            
            # Méthode 4: Si rien ne fonctionne, essayer de nettoyer ligne par ligne
            lines = content.split('\n')
            json_lines = []
            in_json = False
            
            for line in lines:
                line = line.strip()
                if line.startswith('{') or in_json:
                    in_json = True
                    json_lines.append(line)
                    if line.endswith('}') and line.count('}') >= line.count('{'):
                        break
            
            if json_lines:
                extracted_json = '\n'.join(json_lines)
                self.logger.debug("JSON extracted line by line", 
                                lines_count=len(json_lines),
                                json_length=len(extracted_json))
                return extracted_json
            
            # Si aucune méthode ne fonctionne, retourner le contenu original
            self.logger.warning("No JSON extraction method worked, returning original content")
            return content
            
        except Exception as e:
            self.logger.error("Failed to clean JSON content", error=str(e))
            return content

    def _parse_and_validate_plan(self, content: str) -> Optional[Dict]:
        """Parse et valide le plan JSON avec debug amélioré"""
        try:
            # Nettoyer le contenu d'abord
            cleaned_content = self._clean_json_content(content)
            
            # Log du contenu nettoyé
            self.logger.debug("Attempting to parse cleaned JSON", 
                            cleaned_length=len(cleaned_content),
                            cleaned_preview=cleaned_content[:300] + "..." if len(cleaned_content) > 300 else cleaned_content)
            
            # Tentative de parsing
            plan_json = json.loads(cleaned_content)
            
            # Validation basique de la structure
            if not isinstance(plan_json, dict):
                self.logger.error("Plan is not a dictionary", 
                                actual_type=type(plan_json).__name__)
                return None
            
            # Validation des champs attendus (flexible)
            expected_fields = ['structure', 'meta', 'article_metadata']
            found_fields = [field for field in expected_fields if field in plan_json]
            
            if not found_fields:
                self.logger.warning("Plan missing expected fields", 
                                expected=expected_fields,
                                found=list(plan_json.keys()))
            else:
                self.logger.info("Plan parsed successfully", 
                            found_fields=found_fields,
                            total_fields=len(plan_json))
            
            return plan_json
            
        except json.JSONDecodeError as e:
            self.logger.error("JSON parsing failed", 
                            error=str(e),
                            error_line=getattr(e, 'lineno', 'unknown'),
                            error_column=getattr(e, 'colno', 'unknown'),
                            content_preview=cleaned_content[:500] + "..." if len(cleaned_content) > 500 else cleaned_content)
            
            # Tentative de récupération : essayer de réparer le JSON
            return self._attempt_json_repair(cleaned_content)
            
        except Exception as e:
            self.logger.error("Plan validation failed", error=str(e))
            return None

    
    def process_queries(self, query_ids: List[int]):
        """Traite une liste de requêtes avec robustesse complète"""
        if not query_ids:
            self.logger.warning("No query IDs provided")
            return
        
        self.logger.info("Starting robust plan generation", 
                        query_count=len(query_ids),
                        cache_enabled=self.cache is not None)
        
        successful_generations = 0
        failed_generations = 0
        
        for query_id in query_ids:
            try:
                self.logger.info("Processing query", query_id=query_id)
                
                # Récupération des données de la requête
                query_data = self.get_query_data(query_id)
                if not query_data:
                    self.logger.error("Query data not found", query_id=query_id)
                    failed_generations += 1
                    continue
                
                # Analyse de la richesse des données
                agent_response = query_data.get('agent_response', {})
                data_richness = self.data_analyzer.analyze_data_richness(agent_response)
                total_data_points = sum(data_richness.values())
                
                self.logger.info("Query data analyzed", 
                               query_id=query_id,
                               text_preview=query_data.get('text', 'N/A')[:50] + "...",
                               data_points=total_data_points)
                
                # Génération du plan
                start_time = time.time()
                plan = self.generer_plan_article_optimise(query_data)
                generation_time = time.time() - start_time
                
                if plan:
                    # Intégration dans les données de consigne
                    for query in self.consigne_data['queries']:
                        if query['id'] == query_id:
                            query['generated_plan'] = plan
                            break
                    
                    sections_count = len(plan.get('structure', {})) - 2  # -2 pour intro/conclusion
                    successful_generations += 1
                    
                    self.logger.info("Plan generated successfully", 
                                   query_id=query_id,
                                   sections_count=sections_count,
                                   generation_time_seconds=round(generation_time, 2),
                                   data_exploitation=plan.get('data_exploitation_summary', 'N/A'))
                else:
                    failed_generations += 1
                    self.logger.error("Plan generation failed", query_id=query_id)
                    
            except Exception as e:
                failed_generations += 1
                self.logger.error("Unexpected error processing query", 
                                query_id=query_id,
                                error=str(e),
                                traceback=traceback.format_exc())
        
        # Sauvegarde des résultats
        try:
            self.file_manager.save_json_file(self.consigne_path, self.consigne_data)
            self.logger.info("Results saved successfully", 
                           file=self.consigne_path.name,
                           successful=successful_generations,
                           failed=failed_generations)
        except Exception as e:
            self.logger.critical("Failed to save results", 
                               file=self.consigne_path.name,
                               error=str(e))
            raise
        
        # Résumé final
        self.logger.info("Processing completed", 
                        total_queries=len(query_ids),
                        successful=successful_generations,
                        failed=failed_generations,
                        success_rate=f"{(successful_generations/len(query_ids)*100):.1f}%")


# ==================== INITIALISATION ET CONFIGURATION ====================

def load_configuration() -> Tuple[AppConfig, APIConfig]:
    """Charge la configuration depuis les variables d'environnement"""
    logger = StructuredLogger("ConfigLoader")
    
    # Configuration API
    deepseek_key = os.getenv('DEEPSEEK_KEY')
    if not deepseek_key:
        logger.critical("DEEPSEEK_KEY environment variable missing")
        print("❌ Variable d'environnement DEEPSEEK_KEY manquante.")
        print("💡 Pour définir la variable:")
        print("   Linux/Mac: export DEEPSEEK_KEY='votre_clé_ici'")
        print("   Windows:   set DEEPSEEK_KEY=votre_clé_ici")
        sys.exit(1)
    
    try:
        # Timeout configurable par variable d'environnement
        api_timeout = int(os.getenv('API_TIMEOUT', '120'))  # 2 minutes par défaut
        api_config = APIConfig(
            api_key=deepseek_key,
            timeout=api_timeout
        )
        logger.info("API configuration loaded", 
                   key_length=len(deepseek_key),
                   timeout_seconds=api_timeout)
    except ValueError as e:
        logger.critical("Invalid API configuration", error=str(e))
        sys.exit(1)
    
    # Configuration application
    try:
        app_config = AppConfig(
            prompts_dir=os.getenv('PROMPTS_DIR', 'prompts'),
            static_dir=os.getenv('STATIC_DIR', 'static'),
            cache_enabled=os.getenv('CACHE_ENABLED', 'true').lower() == 'true',
            cache_ttl_hours=int(os.getenv('CACHE_TTL_HOURS', '24')),
            log_level=os.getenv('LOG_LEVEL', 'INFO'),
            debug_mode=os.getenv('DEBUG_MODE', 'false').lower() == 'true'
        )
        logger.info("Application configuration loaded", config=asdict(app_config))
    except Exception as e:
        logger.critical("Invalid application configuration", error=str(e))
        sys.exit(1)
    
    return app_config, api_config


def main():
    """Fonction principale robuste"""
    print("📝 GÉNÉRATEUR DE PLANS D'ARTICLES SEO - VERSION ROBUSTE")
    print("=" * 70)
    print("🛡️  Configuration centralisée + Logging structuré + Retry automatique")
    print("🔍 Validation stricte + Cache intelligent + Health checks")
    print("⚡ Zero nouvelle dépendance - Fonctionnalité strictement identique")
    print()
    
    # Chargement de la configuration
    try:
        app_config, api_config = load_configuration()
    except SystemExit:
        return
    
    # Initialisation du générateur
    try:
        generateur = RobustGenerateurPlanArticle(app_config, api_config)
        print(f"✅ Générateur initialisé avec succès")
        print(f"📁 Prompts: {generateur.prompt_manager.prompts_dir}")
        print(f"📄 Consigne: {generateur.consigne_path.name}")
        print(f"🗄️  Cache: {'Activé' if app_config.cache_enabled else 'Désactivé'}")
        
    except (ConfigurationError, ValidationError, FileNotFoundError) as e:
        print(f"❌ Erreur de configuration: {e}")
        print("\n📋 GUIDE DE DÉMARRAGE:")
        print("1. Créez le dossier 'prompts/' dans votre projet")
        print("2. Créez le fichier 'prompts/plan_generator.txt' avec votre prompt")
        print("3. Assurez-vous qu'un fichier consigne*.json existe dans static/")
        print("4. Vérifiez la variable DEEPSEEK_KEY")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Erreur inattendue lors de l'initialisation: {e}")
        if app_config.debug_mode:
            traceback.print_exc()
        sys.exit(1)
    
    # Interface utilisateur
    print(f"\n💡 Tapez l'ID de la requête à traiter:")
    try:
        user_input = input("ID: ").strip()
        query_id = int(user_input)
        
        print(f"\n🚀 Démarrage du traitement robuste pour la requête {query_id}")
        generateur.process_queries([query_id])
        
        print("\n✅ Traitement terminé avec succès!")
        
    except ValueError:
        print("❌ ID invalide. Veuillez entrer un nombre entier.")
    except KeyboardInterrupt:
        print("\n⏹️  Arrêt demandé par l'utilisateur.")
    except Exception as e:
        print(f"❌ Erreur inattendue: {e}")
        if app_config.debug_mode:
            traceback.print_exc()


if __name__ == "__main__":
    main()