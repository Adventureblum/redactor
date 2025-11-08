package com.example;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Exemple d'utilisation de Logback pour le logging
 *
 * Cette classe démontre les différents niveaux de log et
 * comment utiliser SLF4J avec Logback.
 */
public class LoggingExample {

    // Créer un logger pour cette classe
    private static final Logger logger = LoggerFactory.getLogger(LoggingExample.class);

    public static void main(String[] args) {
        logger.info("=== Démarrage de l'application ===");

        // Démonstration des différents niveaux de log
        demonstrateLogLevels();

        // Démonstration du logging avec paramètres
        demonstrateParameterizedLogging();

        // Démonstration du logging d'exceptions
        demonstrateExceptionLogging();

        logger.info("=== Fin de l'application ===");
    }

    /**
     * Démontre les différents niveaux de log
     */
    private static void demonstrateLogLevels() {
        logger.trace("Ceci est un message TRACE - très détaillé");
        logger.debug("Ceci est un message DEBUG - informations de débogage");
        logger.info("Ceci est un message INFO - information générale");
        logger.warn("Ceci est un message WARN - avertissement");
        logger.error("Ceci est un message ERROR - erreur");
    }

    /**
     * Démontre le logging avec paramètres (meilleure performance)
     */
    private static void demonstrateParameterizedLogging() {
        String username = "john.doe";
        int loginAttempts = 3;

        // ❌ Mauvaise pratique - concaténation de strings
        // logger.info("L'utilisateur " + username + " a essayé de se connecter " + loginAttempts + " fois");

        // ✅ Bonne pratique - paramètres (évite la concaténation si le log n'est pas affiché)
        logger.info("L'utilisateur {} a essayé de se connecter {} fois", username, loginAttempts);

        // Multiple paramètres
        String action = "création";
        String resource = "document";
        long duration = 245;
        logger.debug("Action: {} | Resource: {} | Durée: {}ms", action, resource, duration);
    }

    /**
     * Démontre le logging d'exceptions
     */
    private static void demonstrateExceptionLogging() {
        try {
            // Simulation d'une erreur
            int result = divideByZero(10, 0);
        } catch (ArithmeticException e) {
            // ❌ Mauvaise pratique - log seulement le message
            // logger.error("Erreur: " + e.getMessage());

            // ✅ Bonne pratique - log l'exception complète avec stack trace
            logger.error("Erreur lors de la division", e);

            // Alternative avec contexte
            logger.error("Erreur lors du calcul: division impossible", e);
        }

        try {
            riskyOperation();
        } catch (Exception e) {
            // Log avec contexte additionnel
            logger.error("Échec de l'opération risquée après {} tentatives", 3, e);
        }
    }

    private static int divideByZero(int a, int b) {
        return a / b;
    }

    private static void riskyOperation() throws Exception {
        throw new Exception("Opération échouée intentionnellement");
    }
}

/**
 * Classe exemple avec un logger spécifique
 */
class UserService {
    private static final Logger logger = LoggerFactory.getLogger(UserService.class);

    public void createUser(String username, String email) {
        logger.debug("Début de la création de l'utilisateur: {}", username);

        try {
            // Logique métier...
            logger.info("Utilisateur créé avec succès: {} ({})", username, email);
        } catch (Exception e) {
            logger.error("Erreur lors de la création de l'utilisateur: {}", username, e);
            throw e;
        }
    }

    public void deleteUser(long userId) {
        logger.warn("Suppression de l'utilisateur avec ID: {}", userId);

        // Logique de suppression...

        logger.info("Utilisateur supprimé: ID={}", userId);
    }
}

/**
 * Classe pour démontrer les MDC (Mapped Diagnostic Context)
 * Utile pour tracer les requêtes dans les applications multi-thread
 */
class MDCExample {
    private static final Logger logger = LoggerFactory.getLogger(MDCExample.class);

    public void processRequest(String requestId, String userId) {
        // Ajouter des informations de contexte au MDC
        org.slf4j.MDC.put("requestId", requestId);
        org.slf4j.MDC.put("userId", userId);

        try {
            logger.info("Début du traitement de la requête");

            // Votre logique métier ici
            // Tous les logs contiendront automatiquement requestId et userId

            logger.debug("Étape 1 du traitement");
            logger.debug("Étape 2 du traitement");

            logger.info("Requête traitée avec succès");
        } finally {
            // Toujours nettoyer le MDC
            org.slf4j.MDC.clear();
        }
    }
}

/**
 * Meilleures pratiques de logging
 */
class LoggingBestPractices {
    private static final Logger logger = LoggerFactory.getLogger(LoggingBestPractices.class);

    public void goodPractices() {
        // ✅ Utiliser des paramètres plutôt que la concaténation
        String user = "alice";
        logger.info("Utilisateur connecté: {}", user);

        // ✅ Vérifier le niveau de log pour les opérations coûteuses
        if (logger.isDebugEnabled()) {
            String expensiveDebugInfo = generateExpensiveDebugInfo();
            logger.debug("Debug info: {}", expensiveDebugInfo);
        }

        // ✅ Logger les erreurs avec la stack trace
        try {
            dangerousOperation();
        } catch (Exception e) {
            logger.error("Erreur dans l'opération", e);
        }

        // ✅ Utiliser des messages clairs et informatifs
        logger.info("Transaction validée: montant={}, devise={}, compte={}",
                    100.50, "EUR", "12345");
    }

    public void badPractices() {
        String user = "bob";

        // ❌ Concaténation de strings (mauvaise performance)
        logger.info("Utilisateur connecté: " + user);

        // ❌ Opération coûteuse sans vérification du niveau
        logger.debug("Debug info: " + generateExpensiveDebugInfo());

        // ❌ Logger seulement le message d'erreur (perte de la stack trace)
        try {
            dangerousOperation();
        } catch (Exception e) {
            logger.error("Erreur: " + e.getMessage());
        }

        // ❌ Message peu informatif
        logger.info("Opération effectuée");

        // ❌ Logger des données sensibles
        String password = "secret123";
        logger.debug("Mot de passe: {}", password); // NE JAMAIS FAIRE ÇA !
    }

    private void dangerousOperation() throws Exception {
        throw new Exception("Test exception");
    }

    private String generateExpensiveDebugInfo() {
        // Simulation d'une opération coûteuse
        return "Debug information très détaillée...";
    }
}
