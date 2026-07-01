"""Package `app` : bibliothèque partagée du dashboard (connexion DuckDB, requêtes SQL).

Ce fichier est indispensable : à la racine coexistent `app.py` (script Streamlit)
et le dossier `app/`. Sans __init__.py, l'import `from app.lib import db` résout
`app` vers le fichier app.py ("'app' is not a package"). Avec lui, le package
prend la priorité sur le module et l'import fonctionne partout (local + Docker).
"""
