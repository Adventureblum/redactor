# 🚀 Guide de démarrage rapide - Logback

## Pour utilisateurs Java

### 1️⃣ Ajouter les dépendances

**Maven** (`pom.xml`):
```xml
<dependency>
    <groupId>ch.qos.logback</groupId>
    <artifactId>logback-classic</artifactId>
    <version>1.4.14</version>
</dependency>
```

**Gradle** (`build.gradle`):
```gradle
implementation 'ch.qos.logback:logback-classic:1.4.14'
```

### 2️⃣ Copier la configuration

```bash
# Pour Maven/Gradle
cp resources/logback.xml src/main/resources/

# Ou utilisez directement celle dans src/main/resources/
```

### 3️⃣ Utiliser dans votre code

```java
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public class MyApp {
    private static final Logger logger = LoggerFactory.getLogger(MyApp.class);
    
    public static void main(String[] args) {
        logger.info("Application démarrée");
        logger.debug("Message de debug");
        logger.error("Une erreur s'est produite", new Exception());
    }
}
```

### 4️⃣ Exécuter et vérifier

```bash
# Compiler et exécuter
mvn clean install
java -jar target/votre-app.jar

# Vérifier les logs
ls -lh logging/
tail -f logging/application.log
```

---

## Pour utilisateurs Python (ce projet)

Ce projet utilise déjà le module `logging` de Python (voir `serpanalyzer.py`).

La configuration Logback est fournie pour d'éventuels composants Java futurs.

### Configuration Python actuelle

```python
# Logs complets
logging/serpanalyzer.log    # DEBUG + détails

# Logs minifiés  
logging/__main__.log        # WARNING + uniquement
```

---

## 📂 Structure des logs générés

```
logging/
├── application.log                          # Log actif
├── application-error.log                    # Erreurs actives
└── archive/
    ├── application-2025-11-08.0.log.gz     # Archivé (jour 1, fichier 0)
    ├── application-2025-11-08.1.log.gz     # Archivé (jour 1, fichier 1)
    └── application-error-2025-11-08.0.log.gz
```

---

## 🔧 Personnalisation rapide

### Changer la taille maximale

**Dans `logback.xml`:**
```xml
<property name="MAX_FILE_SIZE" value="50MB"/>  <!-- Au lieu de 100MB -->
```

### Changer la rétention

```xml
<property name="MAX_HISTORY" value="60"/>  <!-- 60 jours au lieu de 30 -->
```

### Changer le niveau de log

```xml
<root level="DEBUG">  <!-- Au lieu de INFO -->
```

---

## ✅ Validation

```bash
cd resources
./validate-logback.sh
```

---

## 📚 Documentation complète

Voir `resources/README.md` pour la documentation détaillée.

---

## 🆘 Problèmes courants

### Les logs ne sont pas créés
- Vérifier que `logging/` existe et est accessible en écriture
- Vérifier les dépendances Logback

### Les fichiers ne tournent pas
- Vérifier `maxFileSize` dans la config
- Vérifier l'espace disque disponible

### Performance lente
- Utiliser les appenders asynchrones (déjà configurés)
- Réduire le niveau de log en production (INFO au lieu de DEBUG)

---

**Besoin d'aide ?** Consultez `resources/README.md` ou `resources/LoggingExample.java`
