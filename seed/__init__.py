"""Générateur de données synthétiques.

Produit les 5 tables sources (événements GA4, événements Meta Pixel, clients Shopify,
commandes Shopify, événements Email) avec des identités délibérément chevauchantes
pour que le graphe d'identité en aval ait de vrais signaux de matching à découvrir.

C'est le fallback hors-ligne quand les APIs réelles ne sont pas configurées. Sa sortie
est fidèle au schéma des vraies APIs vendor. Un revieweur DE peut differ la forme
contre la documentation Google / Meta / Shopify / Mailchimp.
"""
