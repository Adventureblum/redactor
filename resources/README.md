# Configuration Logback

Ce dossier contient la configuration Logback pour la gestion des logs des applications Java.

## 📁 Structure

```
resources/
└── logback.xml          # Configuration Logback principale
```

## 🔧 Configuration

### Caractéristiques principales

#### 1. **Rotation des logs par taille et date**
- **Taille maximale par fichier** : 100 MB
- **Pattern de fichier** : `application-%d{yyyy-MM-dd}.%i.log.gz`
- **Compression automatique** : Les fichiers archivés sont compressés en `.gz`

#### 2. **Politique de rétention**
- **Historique des logs** : 30 jours
- **Taille totale maximale** : 3 GB
- **Nettoyage au démarrage** : Activé

#### 3. **Appenders configurés**

##### CONSOLE
- Niveau minimal : `INFO`
- Sortie : Console standard
- Encodage : UTF-8

##### ROLLING_FILE
- Fichier actuel : `logging/application.log`
- Archives : `logging/archive/application-YYYY-MM-DD.INDEX.log.gz`
- Niveau minimal : `DEBUG`
- Rotation : Par taille (100MB) et par jour

##### ERROR_FILE
- Fichier actuel : `logging/application-error.log`
- Archives : `logging/archive/application-error-YYYY-MM-DD.INDEX.log.gz`
- Niveau minimal : `WARN`
- Rétention : 90 jours
- Taille totale : 1 GB

##### ASYNC_FILE et ASYNC_ERROR
- Appenders asynchrones pour améliorer les performances
- Taille de queue : 512 pour les logs généraux, 256 pour les erreurs

## 📊 Format des logs

```
yyyy-MM-dd HH:mm:ss.SSS [thread] LEVEL logger.name - message
```

**Exemple :**
```
2025-11-08 22:24:15.123 [main] INFO  com.example.MyClass - Application démarrée
```

## 🚀 Utilisation

### Avec Maven

Placez le fichier dans `src/main/resources/logback.xml`. Logback le détectera automatiquement.

### Avec Gradle

Placez le fichier dans `src/main/resources/logback.xml`.

### Dépendances requises

```xml
<dependency>
    <groupId>ch.qos.logback</groupId>
    <artifactId>logback-classic</artifactId>
    <version>1.4.14</version>
</dependency>
```

## 🔄 Fonctionnement de la rotation

### Scénario 1 : Rotation par taille
Quand `application.log` atteint 100 MB :
```
application.log                          (actif)
application-2025-11-08.0.log.gz         (archivé)
```

### Scénario 2 : Multiple rotations le même jour
```
application.log                          (actif)
application-2025-11-08.0.log.gz
application-2025-11-08.1.log.gz
application-2025-11-08.2.log.gz
```

### Scénario 3 : Rotation par date
À minuit, un nouveau fichier est créé :
```
application.log                          (actif - nouveau jour)
application-2025-11-08.0.log.gz         (jour précédent)
application-2025-11-09.0.log.gz         (jour précédent)
```

## ⚙️ Personnalisation

### Modifier la taille maximale des fichiers

```xml
<property name="MAX_FILE_SIZE" value="100MB"/>
```

Valeurs possibles : `10MB`, `50MB`, `100MB`, `500MB`, `1GB`, etc.

### Modifier la durée de rétention

```xml
<property name="MAX_HISTORY" value="30"/>
```

Nombre de jours à conserver.

### Modifier le répertoire des logs

```xml
<property name="LOG_DIR" value="logging"/>
```

### Modifier le pattern de log

```xml
<property name="LOG_PATTERN" value="%d{yyyy-MM-dd HH:mm:ss.SSS} [%thread] %-5level %logger{36} - %msg%n"/>
```

## 🎯 Loggers spécifiques

### Logger pour votre application

```xml
<logger name="com.votreentreprise" level="DEBUG" additivity="false">
    <appender-ref ref="ASYNC_FILE"/>
    <appender-ref ref="ASYNC_ERROR"/>
    <appender-ref ref="CONSOLE"/>
</logger>
```

**Remplacez** `com.votreentreprise` par le package de votre application.

### Logger pour Hibernate/JPA

```xml
<logger name="org.hibernate.SQL" level="DEBUG"/>
```

### Logger pour Spring Framework

```xml
<logger name="org.springframework" level="INFO"/>
```

## 📝 Niveaux de log

Par ordre de sévérité :

1. `TRACE` - Très détaillé (rarement utilisé)
2. `DEBUG` - Informations de débogage
3. `INFO` - Informations générales
4. `WARN` - Avertissements
5. `ERROR` - Erreurs

## 🔍 Monitoring des logs

### Visualiser les logs en temps réel

```bash
tail -f logging/application.log
```

### Rechercher des erreurs

```bash
grep "ERROR" logging/application.log
```

### Compter les erreurs du jour

```bash
grep "ERROR" logging/application.log | wc -l
```

### Décompresser un log archivé

```bash
gunzip -c logging/archive/application-2025-11-08.0.log.gz | less
```

## 🛡️ Bonnes pratiques

1. **Ne jamais logger de données sensibles** (mots de passe, tokens, etc.)
2. **Utiliser des niveaux appropriés** :
   - `DEBUG` pour le développement
   - `INFO` pour les opérations normales
   - `WARN` pour les situations anormales non critiques
   - `ERROR` pour les erreurs nécessitant une attention
3. **Activer les appenders asynchrones** en production pour ne pas ralentir l'application
4. **Monitorer l'espace disque** utilisé par les logs
5. **Configurer des alertes** sur les logs ERROR en production

## 🐛 Dépannage

### Les logs ne sont pas créés

Vérifiez que :
- Le dossier `logging/` existe et est accessible en écriture
- Les dépendances Logback sont présentes
- Le fichier `logback.xml` est dans le classpath

### Les logs ne tournent pas

Vérifiez :
- La configuration `maxFileSize`
- Les permissions d'écriture sur le dossier
- L'espace disque disponible

### Problème de performance

- Utilisez les appenders asynchrones (`ASYNC_FILE`, `ASYNC_ERROR`)
- Augmentez la taille de la queue : `<queueSize>1024</queueSize>`
- Réduisez le niveau de log en production (`INFO` au lieu de `DEBUG`)

## 📚 Ressources

- [Documentation Logback officielle](https://logback.qos.ch/manual/index.html)
- [Configuration avancée](https://logback.qos.ch/manual/configuration.html)
- [Rolling Policies](https://logback.qos.ch/manual/appenders.html#RollingFileAppender)
