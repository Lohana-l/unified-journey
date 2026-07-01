#!/usr/bin/env python3
"""
Capture des visuels du dashboard Tessera pour le README (docs/img/).

PRÉREQUIS (à lancer une fois, sur ta machine) :
    make nuke && make up && make pipeline && make quality   # stack propre + données peuplées
    .venv/bin/pip install playwright pillow
    .venv/bin/playwright install chromium

LANCER :
    .venv/bin/python scripts/capture_assets.py

Produit dans docs/img/ : identity-graph.png, attribution.png, gdpr-score.png,
pipeline-timeline.png, minio-console.png, tessera-demo.gif
Rendu 1600 px de large, facteur d'échelle 2 (rétina, net).
"""

from __future__ import annotations

import contextlib
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

IMG_DIR = Path(__file__).resolve().parents[1] / "docs" / "img"
APP_URL = "http://localhost:8501"  # Streamlit
MINIO_URL = "http://localhost:9001"  # Console MinIO (minioadmin / minioadmin)
VIEWPORT = {"width": 1600, "height": 1200}
SCALE = 2  # device_scale_factor : rendu net "rétina"


def _settle(page, seconds: float = 2.5) -> None:
    """Laisse Streamlit finir de peindre. Pas de 'networkidle' : le websocket
    Streamlit reste ouvert, donc 'networkidle' n'arrive jamais (et bloque)."""
    page.wait_for_timeout(int(seconds * 1000))


def _open_tab(page, label: str) -> None:
    """Clique un onglet Streamlit par son libellé, puis laisse le contenu se peindre."""
    try:
        page.get_by_role("tab", name=label).click(timeout=6000)
    except Exception:  # noqa: BLE001
        print(f"  ! onglet « {label} » non cliquable")
    page.wait_for_timeout(1800)


def _shot(page, filename: str, *, card: str | None = None, near: str | None = None) -> None:
    """Capture, dans l'ordre de préférence :
    1. une carte .panel-card contenant le texte `card` (cadrage net de la section) ;
    2. sinon le bloc Streamlit autour d'un titre `near` ;
    3. sinon la page entière (fallback)."""
    out = IMG_DIR / filename
    if card:
        try:
            el = page.locator(".panel-card", has_text=card).first
            el.scroll_into_view_if_needed(timeout=4000)
            page.wait_for_timeout(600)
            el.screenshot(path=str(out), timeout=6000)
            print(f"  ✓ {filename}  (carte « {card} »)")
            return
        except Exception:  # noqa: BLE001
            print(f"  ! {filename} : carte « {card} » introuvable, essai suivant.")
    if near:
        try:
            block = page.locator(
                f"xpath=//*[@data-testid='stVerticalBlock'][.//*[contains(text(), {near!r})]]"
            ).last
            block.scroll_into_view_if_needed(timeout=4000)
            page.wait_for_timeout(500)
            block.screenshot(path=str(out), timeout=5000)
            print(f"  ✓ {filename}  (bloc « {near} »)")
            return
        except Exception:  # noqa: BLE001
            print(f"  ! {filename} : bloc « {near} » introuvable, capture pleine page.")
    page.screenshot(path=str(out), full_page=True)
    print(f"  ✓ {filename}  (pleine page)")


def _make_gif(page) -> None:
    """GIF de démo qui simule l'usage : haut de la Vue d'ensemble (logo + KPIs),
    un cran plus bas (charts), puis passage par les onglets RGPD et Logs.
    Largeur 1600 px + Lanczos + palette adaptative (net)."""
    frames_dir = IMG_DIR / "_frames"
    frames_dir.mkdir(exist_ok=True)
    shots: list[Path] = []

    def grab(n: int = 1) -> None:
        for _ in range(n):
            p = frames_dir / f"f{len(shots):03d}.png"
            page.screenshot(path=str(p))
            shots.append(p)
            page.wait_for_timeout(180)

    def tab(label: str, hold: int = 3) -> None:
        t = page.get_by_role("tab", name=label)
        with contextlib.suppress(Exception):
            t.scroll_into_view_if_needed(timeout=4000)
            t.click()
        page.wait_for_timeout(800)
        grab(hold)

    def view(locator, hold: int = 2) -> None:
        with contextlib.suppress(Exception):
            locator.scroll_into_view_if_needed(timeout=4000)
        page.wait_for_timeout(700)
        grab(hold)

    _open_tab(page, "Vue d'ensemble")
    page.evaluate(
        "() => (document.querySelector('section[data-testid=\"stMain\"]') "
        "|| document.scrollingElement).scrollTo(0, 0)"
    )
    page.wait_for_timeout(500)
    grab(2)
    view(page.get_by_text("Indicateurs clés").first, 2)
    view(page.locator(".panel-card", has_text="Identity Graph").first, 2)
    tab("RGPD & Confidentialité", 2)
    tab("Logs Pipeline", 2)
    tab("Vue d'ensemble", 2)

    imgs = []
    for p in shots:
        im = Image.open(p).convert("RGB")
        if im.width != 1600:
            im = im.resize((1600, int(im.height * 1600 / im.width)), Image.LANCZOS)
        imgs.append(im.convert("P", palette=Image.ADAPTIVE))
    imgs[0].save(
        IMG_DIR / "tessera-demo.gif",
        save_all=True,
        append_images=imgs[1:],
        duration=850,
        loop=0,
        optimize=True,
    )
    for p in shots:
        p.unlink(missing_ok=True)
    frames_dir.rmdir()
    print("  ✓ tessera-demo.gif (parcours des onglets)")


def main() -> None:
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport=VIEWPORT, device_scale_factor=SCALE)
        page.set_default_timeout(6000)  # plus jamais d'attente > 6 s

        # ---- Dashboard Streamlit ------------------------------------------
        print("Dashboard Streamlit :")
        page.goto(APP_URL, wait_until="domcontentloaded")
        _settle(page, 4.0)

        _open_tab(page, "Vue d'ensemble")
        _shot(page, "identity-graph.png", card="Identity Graph")
        _shot(page, "attribution.png", card="Attribution Multi-Touch")

        _open_tab(page, "RGPD & Confidentialité")
        _shot(page, "gdpr-score.png", near="Consentement")

        _open_tab(page, "Logs Pipeline")
        _shot(page, "pipeline-timeline.png", near="pipeline")

        _make_gif(page)

        # ---- Console MinIO -------------------------------------------------
        print("Console MinIO :")
        page.goto(MINIO_URL, wait_until="domcontentloaded")
        _settle(page, 2.0)
        try:
            page.get_by_placeholder("Username").fill("minioadmin")
            page.get_by_placeholder("Password").fill("minioadmin")
            page.get_by_role("button", name="Login").click()
            _settle(page, 2.5)
        except Exception:  # noqa: BLE001
            print("  ! login MinIO auto échoué — connecte-toi à la main puis relance ce bloc.")
        page.goto(MINIO_URL + "/browser", wait_until="domcontentloaded")
        _settle(page, 2.5)
        _shot(page, "minio-console.png")

        browser.close()
    print(
        "\nTerminé. Vérifie les images dans docs/img/ (je peux les relire et recadrer si besoin)."
    )


if __name__ == "__main__":
    main()
