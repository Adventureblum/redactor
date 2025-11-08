#!/bin/bash

# Script de validation de la configuration Logback
# Vérifie que la configuration XML est valide et bien formée

set -e

echo "=========================================="
echo "Validation de la configuration Logback"
echo "=========================================="
echo ""

# Couleurs pour la sortie
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Fichiers à vérifier
LOGBACK_FILES=(
    "logback.xml"
    "../src/main/resources/logback.xml"
)

# Fonction pour vérifier si un fichier existe
check_file_exists() {
    local file=$1
    if [ -f "$file" ]; then
        echo -e "${GREEN}✓${NC} Fichier trouvé: $file"
        return 0
    else
        echo -e "${RED}✗${NC} Fichier non trouvé: $file"
        return 1
    fi
}

# Fonction pour valider la syntaxe XML
validate_xml_syntax() {
    local file=$1
    echo -n "  Validation syntaxe XML... "

    if command -v xmllint &> /dev/null; then
        if xmllint --noout "$file" 2>/dev/null; then
            echo -e "${GREEN}✓ Valide${NC}"
            return 0
        else
            echo -e "${RED}✗ Invalide${NC}"
            xmllint --noout "$file"
            return 1
        fi
    else
        echo -e "${YELLOW}⚠ xmllint non disponible, validation ignorée${NC}"
        return 0
    fi
}

# Fonction pour vérifier les propriétés importantes
check_properties() {
    local file=$1
    echo "  Vérification des propriétés:"

    # Vérifier MAX_FILE_SIZE
    if grep -q "MAX_FILE_SIZE" "$file"; then
        local max_size=$(grep "MAX_FILE_SIZE" "$file" | grep -oP 'value="\K[^"]+')
        echo -e "    ${GREEN}✓${NC} MAX_FILE_SIZE = $max_size"
    else
        echo -e "    ${YELLOW}⚠${NC} MAX_FILE_SIZE non défini"
    fi

    # Vérifier MAX_HISTORY
    if grep -q "MAX_HISTORY" "$file"; then
        local max_history=$(grep "MAX_HISTORY" "$file" | grep -oP 'value="\K[^"]+')
        echo -e "    ${GREEN}✓${NC} MAX_HISTORY = $max_history jours"
    else
        echo -e "    ${YELLOW}⚠${NC} MAX_HISTORY non défini"
    fi

    # Vérifier TOTAL_SIZE_CAP
    if grep -q "TOTAL_SIZE_CAP" "$file"; then
        local total_cap=$(grep "TOTAL_SIZE_CAP" "$file" | grep -oP 'value="\K[^"]+')
        echo -e "    ${GREEN}✓${NC} TOTAL_SIZE_CAP = $total_cap"
    else
        echo -e "    ${YELLOW}⚠${NC} TOTAL_SIZE_CAP non défini"
    fi
}

# Fonction pour vérifier les appenders
check_appenders() {
    local file=$1
    echo "  Vérification des appenders:"

    local appenders=("CONSOLE" "ROLLING_FILE" "ERROR_FILE" "ASYNC_FILE" "ASYNC_ERROR")

    for appender in "${appenders[@]}"; do
        if grep -q "name=\"$appender\"" "$file"; then
            echo -e "    ${GREEN}✓${NC} $appender configuré"
        else
            echo -e "    ${YELLOW}⚠${NC} $appender non trouvé"
        fi
    done
}

# Fonction pour vérifier la politique de rotation
check_rolling_policy() {
    local file=$1
    echo "  Vérification de la politique de rotation:"

    if grep -q "SizeAndTimeBasedRollingPolicy" "$file"; then
        echo -e "    ${GREEN}✓${NC} SizeAndTimeBasedRollingPolicy configurée"
    else
        echo -e "    ${RED}✗${NC} SizeAndTimeBasedRollingPolicy manquante"
    fi

    if grep -q "maxFileSize" "$file"; then
        echo -e "    ${GREEN}✓${NC} maxFileSize défini"
    else
        echo -e "    ${RED}✗${NC} maxFileSize manquant"
    fi

    if grep -q "fileNamePattern" "$file"; then
        local pattern=$(grep "fileNamePattern" "$file" | head -1 | grep -oP '>\K[^<]+')
        echo -e "    ${GREEN}✓${NC} fileNamePattern = $pattern"
    else
        echo -e "    ${RED}✗${NC} fileNamePattern manquant"
    fi
}

# Fonction pour vérifier l'encodage
check_encoding() {
    local file=$1
    echo "  Vérification de l'encodage:"

    if grep -q "UTF-8" "$file"; then
        echo -e "    ${GREEN}✓${NC} Encodage UTF-8 configuré"
    else
        echo -e "    ${YELLOW}⚠${NC} Encodage UTF-8 non spécifié"
    fi
}

# Fonction principale de validation
validate_logback_file() {
    local file=$1

    echo ""
    echo "----------------------------------------"
    echo "Validation: $file"
    echo "----------------------------------------"

    if ! check_file_exists "$file"; then
        return 1
    fi

    validate_xml_syntax "$file" || return 1
    check_properties "$file"
    check_appenders "$file"
    check_rolling_policy "$file"
    check_encoding "$file"

    echo ""
    echo -e "${GREEN}✓ Validation complétée pour $file${NC}"
    return 0
}

# Vérification de la disponibilité des outils
echo "Vérification des outils disponibles:"
if command -v xmllint &> /dev/null; then
    echo -e "${GREEN}✓${NC} xmllint disponible"
else
    echo -e "${YELLOW}⚠${NC} xmllint non disponible (installer libxml2-utils pour une validation complète)"
fi

# Validation de tous les fichiers
all_valid=true
for file in "${LOGBACK_FILES[@]}"; do
    if [ -f "$file" ]; then
        if ! validate_logback_file "$file"; then
            all_valid=false
        fi
    fi
done

echo ""
echo "=========================================="
if [ "$all_valid" = true ]; then
    echo -e "${GREEN}✓ Toutes les validations ont réussi${NC}"
    echo "=========================================="
    exit 0
else
    echo -e "${RED}✗ Certaines validations ont échoué${NC}"
    echo "=========================================="
    exit 1
fi
