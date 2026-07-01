"""Stub d'extracteur Email (type Mailchimp).

Le mode API réelle est laissé pour plus tard : la plupart des comptes Mailchimp
gratuits ont très peu de données à extraire, ce qui fait du chemin synthétique
le défaut réaliste. Ce stub documente la forme de la vraie intégration et
sera remplacé par un appel à l'API Mailchimp quand les credentials seront
disponibles.
"""

from __future__ import annotations


def run() -> None:
    raise RuntimeError(
        "Real-API Mailchimp extraction is not wired yet. The synthetic path "
        "is the default for Email events. Run `python -m ingestion.main --all` "
        "to trigger the synthetic generator. Real integration points are "
        "documented in docs/data_sources.md §4."
    )
