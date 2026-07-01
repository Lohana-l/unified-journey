"""Package d'ingestion Tessera CDP.

Quatre extracteurs (GA4, Meta, Shopify, Email) plus le droit à l'oubli RGPD.
Chaque extracteur appelle l'API source réelle (si les credentials sont fournis)
ou bascule sur le générateur synthétique dans `seed/`. Toutes les écritures
vont dans la couche bronze MinIO en Parquet partitionné.
"""
