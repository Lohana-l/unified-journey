"""Helpers partagés pour le dashboard de monitoring CDP Streamlit.

- ``db``      : connexion DuckDB en lecture seule + sonde de statut du warehouse.
- ``queries`` : fonctions SQL, une par domaine du dashboard.

Le point d'entrée est ``app.py`` à la racine du dépôt (``streamlit run app.py``).
"""
