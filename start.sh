#!/bin/bash
echo "=================================="
echo "  TikTok Scheduler - Démarrage"
echo "=================================="
echo ""

# Vérifier Python
if ! command -v python3 &> /dev/null && ! command -v python &> /dev/null; then
    echo "❌ Python n'est pas installé. Installe Python 3.8+ sur python.org"
    exit 1
fi

PYTHON=python3
command -v python3 &> /dev/null || PYTHON=python

echo "✓ Python détecté"

# Installer Flask si besoin
$PYTHON -c "import flask" 2>/dev/null || {
    echo "📦 Installation de Flask..."
    $PYTHON -m pip install flask werkzeug -q
}

echo "✓ Flask prêt"
echo ""
echo "🚀 Démarrage de l'application..."
echo "👉 Ouvre ton navigateur sur : http://localhost:5000"
echo ""
echo "   Appuie sur CTRL+C pour arrêter"
echo ""

$PYTHON app.py
