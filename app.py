from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import pandas as pd
import streamlit as st

from app.lib import db as uj_db
from app.lib import queries as uj_q

# ── configuration ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Tessera | CDP Monitoring",
    page_icon=":material/hub:",
    layout="wide",
    initial_sidebar_state="expanded",
)

DATA_SOURCES = ["GA4", "Meta Ads", "Shopify", "Mailchimp"]
PRIVACY_STATUSES = ["Pseudonymisé", "Anonymisé", "Consentement OK", "À anonymiser"]
PIPELINE_STAGES = ["Bronze", "Silver", "Gold"]

MOIS_FR = ["Jan", "Fév", "Mar", "Avr", "Mai", "Jun", "Jul", "Aoû", "Sep", "Oct", "Nov", "Déc"]
# Seuil d'alerte fraîcheur aligné sur la cadence réelle du pipeline (batch
# quotidien) : on tolère 26 h entre deux ingestions avant de lever un warning.
FRESHNESS_THRESHOLD_MIN = 26 * 60
PRESET_DAYS = {"7j": 7, "30j": 30, "90j": 90, "6m": 180, "1an": 365}


# ── utilitaires ───────────────────────────────────────────────────────────────
def format_nombre_fr(valeur: int | float, prefix: str = "", suffix: str = "") -> str:
    if valeur >= 1_000_000:
        return f"{prefix}{valeur / 1_000_000:.2f}M{suffix}"
    if valeur >= 1_000:
        return f"{prefix}{valeur / 1_000:.0f}K{suffix}"
    return f"{prefix}{int(valeur)}{suffix}"


def format_date_fr(d: date) -> str:
    return f"{d.day:02d} {MOIS_FR[d.month - 1]} {d.year}"


def _section_header(icon: str, label: str) -> str:
    return (
        f'<div class="sidebar-section-header">'
        f'<span class="material-symbols-outlined" style="font-size:0.85rem;vertical-align:middle;">'
        f"{icon}</span>{label}</div>"
    )


# ── CSS global ────────────────────────────────────────────────────────────────
def inject_css() -> None:
    st.markdown(
        """<style>
[data-testid="stSidebar"]::before{content:'';position:fixed;top:0;left:0;width:260px;height:300px;background:radial-gradient(ellipse at 20% 10%,rgba(194,80,58,0.07) 0%,transparent 70%);pointer-events:none;z-index:0}
[data-testid="stSidebar"]::after{content:'';position:fixed;bottom:0;left:0;width:260px;height:200px;background:radial-gradient(ellipse at 30% 90%,rgba(217,119,6,0.06) 0%,transparent 70%);pointer-events:none;z-index:0}
.sidebar-section-header,[data-testid="stSidebar"] .sidebar-section-header{font-size:0.82rem!important;letter-spacing:0.08em!important;font-weight:700!important}
[data-testid="stSidebar"] div[style*="0.68rem"],[data-testid="stSidebar"] div[style*="0.67rem"]{display:inline-flex!important;align-items:center!important;gap:5px!important;background:rgba(51,39,30,0.05)!important;border:1px solid rgba(51,39,30,0.12)!important;border-radius:6px!important;padding:3px 10px 3px 8px!important;margin-bottom:8px!important;width:auto!important}
[data-testid="stSidebar"] .st-key-src_pills [data-testid="stBaseButton-pills"]{border:1.5px solid rgba(51,39,30,0.18)!important;border-radius:8px!important;color:#8a7a66!important;background:#ffffff!important;box-shadow:none!important}
[data-testid="stSidebar"] .st-key-src_pills [data-testid="stBaseButton-pillsActive"]{border:1.5px solid rgba(180,85,45,0.55)!important;border-radius:8px!important;color:#b4552d!important;background:rgba(180,85,45,0.07)!important;box-shadow:none!important}
[data-testid="stSidebar"] .st-key-preset_pills [data-testid="stBaseButton-pills"]{border-radius:6px!important;background:rgba(51,39,30,0.04)!important;border:1px solid rgba(51,39,30,0.12)!important;color:rgb(111,96,82)!important}
[data-testid="stSidebar"] .st-key-preset_pills [data-testid="stBaseButton-pillsActive"]{border-radius:6px!important;color:#b4552d!important;background:rgba(180,85,45,0.08)!important;border:1px solid rgba(180,85,45,0.5)!important;box-shadow:none!important}
[data-testid="stSidebar"] .status-row{padding:10px 12px!important;min-height:44px!important;box-sizing:border-box!important;margin:3px 0!important;display:flex!important;align-items:center!important;justify-content:space-between!important;flex-wrap:nowrap!important;gap:10px!important}
[data-testid="stSidebar"] .status-row:not(.status-row-alert){background:linear-gradient(135deg,rgba(22,163,74,0.06),rgba(255,255,255,0.85))!important;border:1px solid rgba(22,163,74,0.2)!important;border-radius:7px!important;box-shadow:none!important}
[data-testid="stSidebar"] .status-row:not(.status-row-alert):hover{background:linear-gradient(135deg,rgba(22,163,74,0.1),rgba(255,255,255,0.9))!important;border-color:rgba(22,163,74,0.35)!important;box-shadow:none!important}
[data-testid="stSidebar"] .status-row-alert{background:linear-gradient(135deg,rgba(217,119,6,0.08),rgba(255,255,255,0.85))!important;border:1px solid rgba(217,119,6,0.25)!important;border-radius:7px!important;box-shadow:none!important}
[data-testid="stSidebar"] [data-testid="stElementContainer"]:has(.status-row){padding:0!important;background:transparent!important;border:none!important;box-shadow:none!important}
[data-testid="stSidebar"] [data-testid="stElementContainer"]:has(.status-row) [data-testid="stMarkdown"],[data-testid="stSidebar"] [data-testid="stElementContainer"]:has(.status-row) [data-testid="stMarkdownContainer"],[data-testid="stSidebar"] [data-testid="stElementContainer"]:has(.status-row) [class*="mdg660"]{width:100%!important}
[data-testid="stSidebar"] .status-row>div:first-child{display:flex!important;align-items:center!important;gap:8px!important;flex:1 1 auto!important;min-width:0!important;overflow:hidden!important}
[data-testid="stSidebar"] .status-row>span:last-child{flex-shrink:0!important;white-space:nowrap!important;text-align:right!important;font-size:0.78rem!important}
[data-testid="stSidebar"] .status-row>div:first-child>span:last-child{font-size:0.78rem!important;font-weight:400!important;color:rgb(111,96,82)!important;opacity:1!important;overflow:hidden!important;text-overflow:ellipsis!important;white-space:nowrap!important}
[data-testid="stSidebar"] .status-row:not(.status-row-alert)>span:last-child{font-size:0.78rem!important;font-weight:400!important;color:rgba(22,163,74,0.85)!important}
[data-testid="stSidebar"] .status-row-alert>span:last-child{font-size:0.78rem!important;font-weight:400!important;color:rgba(217,119,6,0.85)!important}
[data-testid="stSidebar"] .status-row-alert>div:first-child>span:last-child{font-size:0.78rem!important;font-weight:400!important;color:rgba(217,119,6,0.75)!important}
[data-testid="stSidebar"] [data-testid="stElementContainer"]:not(:has(.status-row)) [class*="mdg660"]>div>span:first-child{font-size:0.78rem!important;font-weight:400!important;color:rgb(111,96,82)!important;opacity:1!important}
[data-testid="stSidebar"] [data-testid="stElementContainer"]:not(:has(.status-row)) [class*="mdg660"]>div>span:last-child{font-size:0.75rem!important;font-weight:400!important;color:rgb(138,122,102)!important}
[data-testid="stSidebar"] [data-testid="stElementContainer"]:not(:has(.status-row)) [class*="mdg660"]>div>span:first-child:has(.material-symbols-outlined){color:rgba(217,119,6,0.8)!important}
@keyframes pulse-status-dot{0%,100%{opacity:1;box-shadow:0 0 4px 1px rgba(22,163,74,0.5)}50%{opacity:0.65;box-shadow:0 0 8px 3px rgba(22,163,74,0.25)}}
@keyframes pulse-status-dot-alert{0%,100%{opacity:1;box-shadow:0 0 4px 1px rgba(217,119,6,0.5)}50%{opacity:0.65;box-shadow:0 0 8px 3px rgba(217,119,6,0.25)}}
[data-testid="stSidebar"] .status-row:not(.status-row-alert) span[style*="border-radius: 50%"]{animation:pulse-status-dot 2s ease infinite!important;transform:none!important;flex-shrink:0!important;display:inline-block!important;will-change:opacity,box-shadow!important}
[data-testid="stSidebar"] .status-row-alert span[style*="border-radius: 50%"]{animation:pulse-status-dot-alert 2s ease infinite!important;transform:none!important;flex-shrink:0!important;display:inline-block!important;will-change:opacity,box-shadow!important}
</style>""",
        unsafe_allow_html=True,
    )
    st.markdown(
        """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
@import url('https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@20,300,0,0');
.material-symbols-outlined {
    font-size: 1rem;
    vertical-align: middle;
    margin-right: 5px;
    font-variation-settings: 'FILL' 0, 'wght' 300, 'GRAD' 0, 'opsz' 20;
    color: inherit;
}

html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

.stApp { background: #ffffff; color: #3f3328; }

section[data-testid="stSidebar"] {
    background: #ffffff !important;
    border-right: 1px solid #e9cfc0;
}

/* ── Sidebar section headers ─────────────────────────────────────── */
.sidebar-section-header {
    font-size: 0.6rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 1.2px;
    color: #a4937f;
    margin: 4px 0 10px;
    display: flex;
    align-items: center;
    gap: 5px;
}

/* ── Source / preset pills ───────────────────────────────────────── */
section[data-testid="stSidebar"] [data-testid="stPills"] {
    flex-wrap: wrap;
    gap: 5px;
}
section[data-testid="stSidebar"] [data-testid="stPills"] button {
    font-size: 0.72rem !important;
    font-weight: 600 !important;
    border-radius: 8px !important;
    padding: 5px 10px !important;
    border: 1.5px solid rgba(51,39,30,0.12) !important;
    background: rgba(51,39,30,0.04) !important;
    color: #8a7a66 !important;
    transition: all 0.15s ease !important;
}
section[data-testid="stSidebar"] [data-testid="stPills"] button[aria-selected="true"] {
    background: rgba(168,78,39,0.15) !important;
    border-color: rgba(168,78,39,0.5) !important;
    color: #a05530 !important;
}

/* ── Date range visual block ─────────────────────────────────────── */
.date-range-block {
    background: rgba(51,39,30,0.03);
    border: 1px solid rgba(51,39,30,0.08);
    border-radius: 10px;
    padding: 10px 14px 8px;
    margin: 6px 0 10px;
}

/* ── Compact status rows ─────────────────────────────────────────── */
.status-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 6px 10px;
    border-radius: 7px;
    background: rgba(51,39,30,0.03);
    margin: 3px 0;
}
.status-row-alert {
    background: rgba(217,119,6,0.08) !important;
    border: 1px solid rgba(217,119,6,0.2) !important;
}

/* Metric cards */
[data-testid="stMetric"] {
    background: #ffffff;
    box-shadow: 0 1px 3px rgba(20,30,55,0.05);
    border: 1px solid #e9cfc0;
    border-radius: 12px;
    padding: 1rem 1.2rem;
    position: relative;
    overflow: hidden;
    transition: box-shadow 0.25s ease, transform 0.25s ease;
}
[data-testid="stMetric"]:hover { box-shadow: 0 4px 14px rgba(20,30,55,0.08); transform: translateY(-1px); }
[data-testid="stMetricLabel"] { color: #6f6052; font-size: 0.78rem; font-weight: 500; letter-spacing: 0.05em; }
[data-testid="stMetricValue"] { color: #1e3a52; font-size: 1.6rem; font-weight: 700; }
[data-testid="stMetricDelta"] { font-size: 0.75rem; }

/* Tabs */
.stTabs [data-baseweb="tab-list"] {
    background: #ffffff !important;
    border-bottom: 1px solid #e9cfc0 !important;
    gap: 4px !important;
    position: sticky !important;
    top: 0 !important;
    z-index: 100 !important;
    padding: 0 4px !important;
}
.stTabs [data-baseweb="tab"] {
    background: transparent !important;
    color: #a4937f !important;
    border-radius: 8px 8px 0 0 !important;
    padding: 10px 20px !important;
    min-height: 44px !important;
    font-size: 0.85rem !important;
    font-weight: 500 !important;
    border-top: 3px solid transparent !important;
    border-bottom: none !important;
    transition: all 0.15s ease !important;
    box-shadow: none !important;
}
.stTabs [data-baseweb="tab"]:hover {
    color: #6f6052 !important;
    background: rgba(51,39,30,0.04) !important;
}
.stTabs [aria-selected="true"] {
    background: rgba(168,78,39,0.08) !important;
    color: #a05530 !important;
    border-top: 3px solid #a84e27 !important;
    border-bottom: none !important;
    box-shadow: none !important;
}
.stTabs [data-baseweb="tab-highlight"] {
    display: none !important;
}

[data-testid="stDataFrame"] { border-radius: 10px; overflow: hidden; border: 1px solid #e9cfc0; }

.streamlit-expanderHeader {
    background: #ffffff;
    border: 1px solid #e9cfc0;
    border-radius: 8px;
    color: #6f6052;
}

::-webkit-scrollbar { width: 4px; }
::-webkit-scrollbar-track { background: #ffffff; }
::-webkit-scrollbar-thumb { background: #b4552d; border-radius: 2px; }

[data-testid="stDecoration"] { background-image: linear-gradient(90deg, #b4552d, #e9cfc0); }
header[data-testid="stHeader"] {
    background: rgba(255, 255, 255, 0.8) !important;
    backdrop-filter: blur(10px);
    border-bottom: 1px solid #e9cfc0;
}

.stButton > button {
    background: linear-gradient(135deg, #a84e27, #8f3f1d);
    color: white;
    border: none;
    border-radius: 8px;
    font-weight: 500;
    transition: all 0.2s ease;
}
.stButton > button:hover {
    background: linear-gradient(135deg, #b05570, #a84e27);
    box-shadow: 0 2px 8px rgba(70,50,35,0.15);
    transform: translateY(-1px);
}

h1 { color: #1e3a52 !important; font-weight: 700 !important; }
h2 { color: #1e3a52 !important; font-weight: 600 !important; }
h3 { color: #2c4a63 !important; font-weight: 600 !important; }

section[data-testid="stSidebar"] .stMarkdown { color: #6f6052; }

.soda-alert {
    background: rgba(217, 119, 6, 0.08);
    border: 1px solid rgba(217, 119, 6, 0.4);
    border-left: 4px solid #d97706;
    border-radius: 8px;
    padding: 12px 16px;
    margin: 12px 0;
    color: #b45309;
}

.health-banner {
    background: linear-gradient(135deg, rgba(22, 163, 74, 0.08), rgba(255, 255, 255, 0.9));
    border: 1px solid rgba(22, 163, 74, 0.25);
    border-radius: 12px;
    padding: 12px 20px;
    margin-bottom: 20px;
    display: flex;
    align-items: center;
    gap: 20px;
    flex-wrap: wrap;
}

@keyframes pulse-dot {
    0%, 100% { opacity: 1; transform: scale(1); }
    50% { opacity: 0.5; transform: scale(1.3); }
}
.pulse-dot {
    width: 8px; height: 8px;
    background: #16a34a;
    border-radius: 50%;
    animation: pulse-dot 2s infinite;
    display: inline-block;
    margin-right: 6px;
}

.badge {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 999px;
    font-size: 0.72rem;
    font-weight: 600;
    letter-spacing: 0.05em;
}
.badge-bronze { background: rgba(180, 100, 40, 0.2); color: #a05e22; border: 1px solid rgba(180,100,40,0.3); }
.badge-silver { background: rgba(100, 130, 170, 0.2); color: #6f6052; border: 1px solid rgba(100,130,170,0.3); }
.badge-gold   { background: rgba(245, 195, 40, 0.15); color: #b45309; border: 1px solid rgba(176,133,21,0.3); }

.metric-accent-violet::before { content:''; display:block; height:3px; background:#b4552d; border-radius:3px 3px 0 0; margin:-1rem -1.2rem 0.8rem; }
.metric-accent-cyan::before   { content:''; display:block; height:3px; background:#c2503a; border-radius:3px 3px 0 0; margin:-1rem -1.2rem 0.8rem; }
.metric-accent-green::before  { content:''; display:block; height:3px; background:#16a34a; border-radius:3px 3px 0 0; margin:-1rem -1.2rem 0.8rem; }
.metric-accent-amber::before  { content:''; display:block; height:3px; background:#d97706; border-radius:3px 3px 0 0; margin:-1rem -1.2rem 0.8rem; }

.panel-card {
    background: #ffffff;
    box-shadow: 0 1px 3px rgba(20,30,55,0.05);
    border: 1px solid #e9cfc0;
    border-radius: 12px;
    padding: 20px;
    margin: 16px 0;
}
.panel-title {
    color: #3a5670;
    font-size: 0.75rem;
    font-weight: 600;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    margin-bottom: 16px;
    display: flex;
    align-items: center;
    gap: 8px;
}

.gantt-row { display: flex; align-items: center; gap: 8px; margin: 6px 0; }
.gantt-label { width: 80px; font-size: 0.75rem; color: #8a7a66; text-align: right; flex-shrink: 0; }
.gantt-track { flex: 1; height: 24px; background: #f4f4f2; border-radius: 4px; position: relative; overflow: hidden; }
.gantt-block {
    position: absolute; top: 4px; height: 16px; border-radius: 3px;
    display: flex; align-items: center; padding: 0 6px;
    font-size: 0.65rem; font-weight: 600; color: white;
}
</style>
""",
        unsafe_allow_html=True,
    )

    # ── 3rd CSS block: Tessera UI refinements (logo, tabs, filters) ──
    st.markdown(
        """
<style>
/* ─── KILL outer sidebar frame (right border + radial halos) ─────────── */
section[data-testid="stSidebar"]{
    border-right:none !important;
    box-shadow:none !important;
}
[data-testid="stSidebar"]::before,
[data-testid="stSidebar"]::after{
    display:none !important;
    content:none !important;
}

/* ─── Sidebar logo header (SVG + wordmark) ───────────────────────────── */
/* Réduit l'espace du haut de la sidebar : logo plus haut, plus de marge sous */
section[data-testid="stSidebar"] [data-testid="stSidebarUserContent"]{
    padding-top:0.6rem !important;
}
.tessera-sidebar-header{
    display:flex; gap:12px; align-items:center;
    padding:0 2px 26px;
    margin-top:-0.6rem;
}
.tessera-sidebar-header svg{ flex-shrink:0; }
.tessera-wordmark{ display:flex; flex-direction:column; line-height:1.05; }
.tessera-title{ font-size:1.275rem; letter-spacing:-0.01em; color:#33271e; }
/* light + bold (sans gradient), style moderne */
.tessera-unified{ font-weight:300; color:rgba(51,39,30,0.62); }
.tessera-journey{ font-weight:800; color:#b4552d; margin-left:1px; }
.tessera-subtitle{
    text-transform:uppercase;
    color:rgba(51,39,30,0.45);
    font-weight:600;
    font-size:0.62rem;
    letter-spacing:0.14em;
    margin-top:5px;
}

/* ─── White section titles (FILTRES / STATUT SYSTÈME / FRAÎCHEUR) ────── */
section[data-testid="stSidebar"] .sidebar-section-header,
section[data-testid="stSidebar"] .sidebar-section-header .material-symbols-outlined{
    color:#2c4a63 !important;
}

/* ─── FILTRES bordered container (single encadré) ────────────────────── */
section[data-testid="stSidebar"]
    [data-testid="stVerticalBlockBorderWrapper"][style*="border"]{
    border:1px solid rgba(180,85,45,0.25) !important;
    border-radius:12px !important;
    background:rgba(180,85,45,0.03) !important;
    padding:8px 14px 18px !important;   /* moins haut, plus bas (respire "90j/Q1") */
    box-shadow:0 0 0 0 transparent !important;
}
/* titre FILTRES dans le bloc, pas d'encadré spécifique */
section[data-testid="stSidebar"]
    [data-testid="stVerticalBlockBorderWrapper"][style*="border"]
    .sidebar-section-header{
    border-bottom:none;
    padding-bottom:0;
    margin-bottom:0;
}

/* trait de séparation pleine largeur sous le titre FILTRES (resserré au-dessus) */
.tessera-filters-sep{
    height:1px;
    background:rgba(180,85,45,0.2);
    margin:8px -14px 16px;
}
/* "Sources :" et "Période :" : texte simple, AUCUN encadré
   (kill robuste de la règle initiale qui mettait fond + bordure + pill) */
section[data-testid="stSidebar"] div[style*="0.68rem"]{
    text-transform:uppercase !important;
    letter-spacing:0.12em !important;
    font-weight:600 !important;
    color:rgba(51,39,30,0.5) !important;
    background:none !important;
    background-color:transparent !important;
    border:none !important;
    border-radius:0 !important;
    box-shadow:none !important;
    padding:0 !important;
    margin:8px 0 6px !important;
    width:auto !important;
    display:flex !important;
    align-items:center !important;
    gap:4px !important;
}
section[data-testid="stSidebar"] div[style*="0.68rem"] .material-symbols-outlined{
    display:none !important;
}

/* refresh button (restart_alt) inside FILTRES, gray, transparent */
section[data-testid="stSidebar"] .st-key-reset_filters button,
section[data-testid="stSidebar"] .st-key-reset_filters .stButton > button{
    background:transparent !important;
    background-image:none !important;
    border:1px solid rgba(180,85,45,0.16) !important;
    color:rgb(164,147,127) !important;
    box-shadow:none !important;
    padding:4px 8px !important;
    min-height:28px !important;
    transform:none !important;
}
section[data-testid="stSidebar"] .st-key-reset_filters button:hover,
section[data-testid="stSidebar"] .st-key-reset_filters .stButton > button:hover{
    background:rgba(180,85,45,0.06) !important;
    color:rgb(111,96,82) !important;
    box-shadow:none !important;
    transform:none !important;
}
section[data-testid="stSidebar"] .st-key-reset_filters .material-symbols-outlined,
section[data-testid="stSidebar"] .st-key-reset_filters svg{
    color:rgb(164,147,127) !important;
    fill:rgb(164,147,127) !important;
}

/* preset buttons, wrap so they never overflow */
section[data-testid="stSidebar"] .st-key-preset_pills [data-testid="stPills"]{
    flex-wrap:wrap !important;
    gap:5px !important;
}

/* date-range block: integrate (no sub-frame inside FILTRES) */
section[data-testid="stSidebar"] .date-range-block{
    background:transparent !important;
    border:none !important;
    padding:6px 0 0 !important;
    margin:8px 0 0 !important;
}

/* ─── Closeable chips: × on hover (Sources only) ─────────────────────── */
section[data-testid="stSidebar"] .st-key-src_pills [data-testid="stBaseButton-pills"],
section[data-testid="stSidebar"] .st-key-src_pills [data-testid="stBaseButton-pillsActive"]{
    position:relative !important;
    overflow:visible !important;
}
section[data-testid="stSidebar"] .st-key-src_pills [data-testid="stBaseButton-pills"]::after,
section[data-testid="stSidebar"] .st-key-src_pills [data-testid="stBaseButton-pillsActive"]::after{
    content:'+';
    position:absolute;
    top:-8px; right:-8px;
    width:18px; height:18px;
    border-radius:50%;
    background:rgba(255,255,255,0.95);
    border:1px solid rgba(51,39,30,0.25);
    color:rgba(51,39,30,0.65);
    display:flex; align-items:center; justify-content:center;
    font-size:13px; line-height:1; font-weight:500;
    opacity:0;
    transform:scale(0.8);
    transition:opacity 0.18s ease, transform 0.18s ease, border-color 0.18s ease, color 0.18s ease;
    pointer-events:none;
    z-index:2;
}
section[data-testid="stSidebar"] .st-key-src_pills [data-testid="stBaseButton-pills"]:hover::after,
section[data-testid="stSidebar"] .st-key-src_pills [data-testid="stBaseButton-pillsActive"]:hover::after{
    opacity:1;
    transform:scale(1);
    border-color:rgba(51,39,30,0.45);
    color:rgba(51,39,30,0.9);
}
/* source affichée -> croix terracotta pour la retirer de la vue */
section[data-testid="stSidebar"] .st-key-src_pills [data-testid="stBaseButton-pillsActive"]::after{
    content:'×';
}
section[data-testid="stSidebar"] .st-key-src_pills [data-testid="stBaseButton-pillsActive"]:hover::after{
    border-color:#b4552d;
    color:#b4552d;
}
/* source masquée -> + vert pour la remettre */
section[data-testid="stSidebar"] .st-key-src_pills [data-testid="stBaseButton-pills"]:not([data-testid="stBaseButton-pillsActive"]):hover::after{
    border-color:#16a34a;
    color:#16a34a;
}

/* ─── Tabs : un seul cadre fermé (onglets en haut + contenu en dessous) ─ */
/* Tab-list = haut + côtés, coins arrondis en haut, pas de bordure basse */
.stTabs [data-baseweb="tab-list"]{
    border:1px solid rgba(180,85,45,0.25) !important;
    border-bottom:none !important;
    border-radius:14px 14px 0 0 !important;
    padding:0 !important;     /* zéro padding : onglet actif plaqué au rebord */
    background:rgba(255,255,255,0.85) !important;
    backdrop-filter:blur(8px);
    position:sticky !important;
    top:0 !important;
    z-index:50 !important;
    gap:0 !important;          /* pas de gap, sinon le 1er/dernier décolle */
    margin:14px 0 0 !important; /* respire un peu plus pour le « pop » du haut */
    display:flex !important;
    width:100% !important;
    overflow:visible !important; /* laisse l'onglet actif dépasser vers le haut */
}
/* Le 1er et le dernier onglet épousent l'arrondi du conteneur */
.stTabs [data-baseweb="tab"]:first-child{
    border-top-left-radius:13px !important;
}
.stTabs [data-baseweb="tab"]:last-child{
    border-top-right-radius:13px !important;
}
/* L'accent du haut (::before) sur ces onglets suit le même arrondi */
.stTabs [data-baseweb="tab"]:first-child::before{
    border-top-left-radius:13px !important;
}
.stTabs [data-baseweb="tab"]:last-child::before{
    border-top-right-radius:13px !important;
}

/* Tab-panel = côtés + bas, coins arrondis en bas, pas de bordure haute */
.stTabs [data-baseweb="tab-panel"]{
    border:1px solid rgba(180,85,45,0.25) !important;
    border-top:none !important;
    border-radius:0 0 14px 14px !important;
    padding:22px !important;
    background:#ffffff !important;
    margin-bottom:28px !important;
}

/* Onglets individuels */
.stTabs [data-baseweb="tab"]{
    background:transparent !important;
    color:rgba(51,39,30,0.6) !important;
    border:none !important;
    border-radius:8px 8px 0 0 !important;
    padding:10px 18px !important;
    min-height:42px !important;
    font-size:0.85rem !important;
    font-weight:500 !important;
    transition:all 0.15s ease !important;
}
.stTabs [data-baseweb="tab"]:hover{
    color:#3f3328 !important;
    background:rgba(20,35,65,0.04) !important;
}
.stTabs [aria-selected="true"]{
    color:#2c4a63 !important;
    /* fond plein (couleur du conteneur) : masque la bordure du tab-list
       derrière l'onglet quand il est levé : pas de double trait */
    background:#ffffff !important;
}

/* Trait fin pleine largeur sous les onglets (séparation onglets / contenu) : conservé */
.stTabs [data-baseweb="tab-border"]{
    display:block !important;
    height:1px !important;
    background:rgba(180,85,45,0.25) !important;
}
/* Indicateur gras sous l'onglet sélectionné : retiré */
.stTabs [data-baseweb="tab-highlight"]{
    display:none !important;
    height:0 !important;
}
/* Petits traits translucides sur les côtés gauche/droit de l'onglet actif,
   même teinte que la bordure extérieure du bloc.
   + Pop vers le haut : l'onglet actif dépasse de 6 px au-dessus du conteneur. */
.stTabs [aria-selected="true"]{
    box-shadow:
        inset 1px 0 0 rgba(180,85,45,0.25),
        inset -1px 0 0 rgba(180,85,45,0.25) !important;
    margin-top:0 !important;
    min-height:42px !important;     /* 42 + 6 : le bas reste aligné */
    padding-top:10px !important;    /* recentre le label dans la hauteur agrandie */
    z-index:2 !important;
    position:relative !important;
}
/* Accent SOLIDE violet en haut de l'onglet sélectionné (style border-left du
   bloc Soda, transposé en border-top, qui suit l'arrondi des coins). */
.stTabs [data-baseweb="tab"]{ position:relative !important; }
.stTabs [data-baseweb="tab"]::before{
    content:'';
    position:absolute;
    top:0; left:0; right:0;
    height:4px;
    background:transparent;
    border-radius:8px 8px 0 0;
    transition:background 0.15s ease;
    pointer-events:none;
}
.stTabs [aria-selected="true"]::before{
    background:#b4552d;
}

/* Icônes Material avant chaque onglet */
.stTabs [data-baseweb="tab"] [data-testid="stMarkdownContainer"] p::before,
.stTabs [data-baseweb="tab"] > div > div::before{
    font-family:'Material Symbols Outlined';
    font-size:1rem;
    margin-right:8px;
    vertical-align:middle;
    font-variation-settings:'FILL' 0,'wght' 400,'GRAD' 0,'opsz' 20;
}
.stTabs [data-baseweb="tab"]:nth-child(1) [data-testid="stMarkdownContainer"] p::before,
.stTabs [data-baseweb="tab"]:nth-child(1) > div > div::before{ content:'dashboard'; }
.stTabs [data-baseweb="tab"]:nth-child(2) [data-testid="stMarkdownContainer"] p::before,
.stTabs [data-baseweb="tab"]:nth-child(2) > div > div::before{ content:'shield'; }
.stTabs [data-baseweb="tab"]:nth-child(3) [data-testid="stMarkdownContainer"] p::before,
.stTabs [data-baseweb="tab"]:nth-child(3) > div > div::before{ content:'receipt_long'; }

/* ─── HERO : identification immédiate du dashboard ───────────────────── */
.tessera-hero{
    display:flex;
    align-items:flex-start;
    justify-content:space-between;
    gap:24px;
    padding:18px 0 24px;
    border-bottom:1px solid rgba(180,85,45,0.16);
    margin:0 0 30px;
    flex-wrap:wrap;
}
.tessera-hero-left{ flex:1 1 480px; min-width:0; }
.tessera-hero-eyebrow{
    font-size:0.7rem;
    font-weight:700;
    letter-spacing:0.18em;
    text-transform:uppercase;
    color:rgba(180,85,45,0.90);
    margin-bottom:10px;
}
.tessera-hero-title{
    font-size:1.85rem !important;
    font-weight:800 !important;
    color:#2c4a63 !important;
    margin:0 0 8px !important;
    letter-spacing:-0.01em;
    line-height:1.15;
}
.tessera-hero-sub{
    font-size:0.92rem;
    color:rgba(51,39,30,0.6);
    line-height:1.5;
    max-width:680px;
}
.tessera-hero-right{
    display:flex;
    flex-direction:column;
    gap:10px;
    align-items:flex-end;
}
.tessera-status-chip{
    display:inline-flex;
    align-items:center;
    gap:12px;
    background:linear-gradient(135deg, rgba(22,163,74,0.10), rgba(255,255,255,0.6));
    border:1px solid rgba(22,163,74,0.32);
    border-radius:10px;
    padding:10px 16px;
    color:#16a34a;
    font-size:0.82rem;
    font-weight:700;
    letter-spacing:0.04em;
    line-height:1.2;
}
.tessera-status-chip-sub{
    color:rgba(51,39,30,0.55);
    font-size:0.7rem;
    font-weight:500;
    letter-spacing:0;
    margin-top:3px;
}
.tessera-period-chip{
    display:inline-flex;
    align-items:center;
    gap:6px;
    background:rgba(180,85,45,0.06);
    border:1px solid rgba(180,85,45,0.22);
    border-radius:8px;
    padding:7px 12px;
    color:rgba(51,39,30,0.78);
    font-size:0.78rem;
    font-weight:500;
}
.tessera-period-chip .material-symbols-outlined{
    font-size:0.95rem;
    color:#b4552d;
    margin-right:2px;
}

/* ─── Sections : titre + sous-titre uniformes ────────────────────────── */
.tessera-block-head{
    margin:0 0 16px;
}
.tessera-block-head--spaced{ margin-top:36px; }
.tessera-block-title{
    color:#1e3a52;
    font-size:1.05rem;
    font-weight:700;
    letter-spacing:0.005em;
    display:flex;
    align-items:center;
    gap:10px;
    margin-bottom:5px;
}
.tessera-block-title .material-symbols-outlined{
    font-size:1.2rem;
    color:#b4552d;
    margin-right:0;
}
.tessera-block-sub{
    color:rgba(51,39,30,0.5);
    font-size:0.78rem;
    letter-spacing:0.01em;
    line-height:1.45;
    max-width:780px;
}

/* ─── Section header "Analyse détaillée" (au-dessus des onglets) ─────── */
.tessera-section-header{
    margin:42px 0 14px;
    padding-top:6px;
}
.tessera-section-title{
    color:#1e3a52;
    font-size:1.05rem;
    font-weight:700;
    letter-spacing:0.005em;
    display:flex;
    align-items:center;
    gap:10px;
    margin-bottom:4px;
}
.tessera-section-title .material-symbols-outlined{
    font-size:1.2rem;
    color:#b4552d;
    margin-right:0;
}
.tessera-section-subtitle{
    color:rgba(51,39,30,0.5);
    font-size:0.78rem;
    letter-spacing:0.01em;
    font-weight:400;
}

/* ─── Aération between main content sections ─────────────────────────── */
.main .block-container{ padding-top:2.2rem !important; }
.health-banner{ margin:0 0 32px !important; padding:16px 22px !important; }
.soda-alert{ margin:24px 0 28px !important; padding:14px 18px !important; }
.panel-card{ margin:28px 0 !important; padding:22px !important; }
.main hr,
.main [data-testid="stHorizontalBlock"] + [data-testid="stHorizontalBlock"]{
    margin-top:24px !important;
}
.main [data-testid="stMetric"]{ margin-bottom:8px !important; }
/* spacing between the metrics row and the tabs */
.main [data-testid="stHorizontalBlock"]:has([data-testid="stMetric"]){
    margin-bottom:24px !important;
}
/* spacing between charts row and identity-graph panel */
.main [data-testid="stHorizontalBlock"] + .panel-card{ margin-top:28px !important; }
/* sub-title margins inside tabs */
.main h4{ margin-top:24px !important; margin-bottom:12px !important; }

/* ─── Misc: align replaced violet primary with #b4552d ──────────────── */
.stButton > button{
    background:linear-gradient(135deg,#b4552d,#8f3f1d) !important;
}
.stButton > button:hover{
    background:linear-gradient(135deg,#b4552d,#b4552d) !important;
    box-shadow:0 0 15px rgba(180,85,45,0.2) !important;
}
::-webkit-scrollbar-thumb{ background:#b4552d !important; }
/* ─── Confort visuel : transitions douces au survol ─────────────────── */
.status-row{ transition:background 0.2s ease, border-color 0.2s ease !important; }
[data-testid="stSidebar"] [data-testid="stPills"] button{ transition:all 0.2s ease !important; }
.stTabs [data-baseweb="tab"]{ transition:color 0.18s ease, background 0.18s ease !important; }
.streamlit-expanderHeader{ transition:background 0.2s ease !important; }
</style>
""",
        unsafe_allow_html=True,
    )


# ── connexion warehouse (DuckDB read-only) ────────────────────────────────────
def _run_query(fn, *args):
    """Exécute `fn(conn, *args)` avec une connexion lecture seule éphémère.

    On ouvre/ferme à chaque requête (plutôt qu'un `st.cache_resource` persistant)
    pour ne jamais tenir de verrou sur le fichier DuckDB : dbt peut ainsi
    reconstruire le warehouse pendant que le dashboard tourne. Le coût est
    amorti par le cache de résultats 30 s (`st.cache_data`) sur chaque fetch.
    """
    conn = uj_db.get_connection()
    try:
        return fn(conn, *args)
    finally:
        conn.close()


def _cache_ttl_seconds() -> int:
    """Durée de cache des requêtes. 30 s : assez court pour voir les nouveaux
    runs du pipeline, assez long pour ne pas réinterroger DuckDB à chaque
    re-render."""
    return 30


@st.cache_data(ttl=_cache_ttl_seconds(), show_spinner=False)
def fetch_unification(start: date, end: date, sources: tuple[str, ...]) -> pd.DataFrame:
    return _run_query(uj_q.unification_per_source, start, end, list(sources) or None)


@st.cache_data(ttl=_cache_ttl_seconds(), show_spinner=False)
def fetch_quality_trend(start: date, end: date) -> pd.DataFrame:
    return _run_query(uj_q.quality_trend_weekly, start, end)


@st.cache_data(ttl=_cache_ttl_seconds(), show_spinner=False)
def fetch_rgpd_table(sources: tuple[str, ...]) -> pd.DataFrame:
    return _run_query(uj_q.rgpd_registry, list(sources) or None)


@st.cache_data(ttl=_cache_ttl_seconds(), show_spinner=False)
def fetch_pipeline_logs(start: date, end: date, sources: tuple[str, ...]) -> pd.DataFrame:
    return _run_query(uj_q.pipeline_logs, start, end, list(sources) or None)


@st.cache_data(ttl=_cache_ttl_seconds(), show_spinner=False)
def fetch_top_metrics(start: date, end: date, sources: tuple[str, ...]) -> dict:
    return _run_query(uj_q.top_metrics, start, end, list(sources) or None)


@st.cache_data(ttl=_cache_ttl_seconds(), show_spinner=False)
def fetch_health_banner(start: date, end: date) -> dict:
    return _run_query(uj_q.pipeline_health, start, end)


@st.cache_data(ttl=_cache_ttl_seconds(), show_spinner=False)
def fetch_identity_stats() -> dict:
    return _run_query(uj_q.identity_graph_stats)


@st.cache_data(ttl=_cache_ttl_seconds(), show_spinner=False)
def fetch_attribution(start: date, end: date) -> pd.DataFrame:
    return _run_query(uj_q.attribution_panel, start, end)


@st.cache_data(ttl=_cache_ttl_seconds(), show_spinner=False)
def fetch_gdpr_breakdown() -> dict:
    return _run_query(uj_q.gdpr_breakdown)


@st.cache_data(ttl=_cache_ttl_seconds(), show_spinner=False)
def fetch_soda_status() -> dict:
    return _run_query(uj_q.soda_status)


@st.cache_data(ttl=_cache_ttl_seconds(), show_spinner=False)
def fetch_pipeline_timeline() -> pd.DataFrame:
    return _run_query(uj_q.pipeline_timeline_24h)


# ── signal de santé ───────────────────────────────────────────────────────────
@dataclass
class HealthSignal:
    name: str
    status: str  # "ok" | "warn" | "error"
    detail: str


@st.cache_data(ttl=_cache_ttl_seconds(), show_spinner=False)
def get_system_health() -> list[HealthSignal]:
    return [HealthSignal(n, s, d) for (n, s, d) in _run_query(uj_q.system_signals)]


@st.cache_data(ttl=_cache_ttl_seconds(), show_spinner=False)
def get_source_freshness() -> list[tuple[str, str, int]]:
    return _run_query(uj_q.source_freshness)


# ── barre latérale ────────────────────────────────────────────────────────────
def render_sidebar():
    today = date.today()

    # valeurs par défaut du sélecteur "Perso.", relatives à aujourd'hui pour
    # tomber sur la fenêtre réellement couverte par les données (seed = 90 j glissants).
    if "date_debut" not in st.session_state:
        st.session_state.date_debut = today - timedelta(days=90)
    if "date_fin" not in st.session_state:
        st.session_state.date_fin = today

    with st.sidebar:
        # ── Logo Tessera (mark plein, dessiné, à charge symbolique) ───
        # Hexagone plein (le "hub" qui unifie les sources) + flèche en
        # négatif (le journey qui en sort), tracés en UN SEUL path avec
        # fill-rule:evenodd pour créer la découpe. Une seule couleur violet.
        st.markdown(
            """
<div class="tessera-sidebar-header">
  <svg viewBox="0 0 48 48" width="40" height="40" xmlns="http://www.w3.org/2000/svg">
    <g fill="none" stroke="#b4552d" stroke-width="2.6" stroke-linecap="round">
      <path d="M8 10 C 20 10, 16 22.5, 25 23.5"/>
      <path d="M8 24 L 21 24"/>
      <path d="M8 38 C 20 38, 16 25.5, 25 24.5"/>
      <path d="M34.5 24 L 42.5 24"/>
      <path d="M38.5 19.5 L 43 24 L 38.5 28.5"/>
    </g>
    <circle cx="8" cy="10" r="3" fill="#b4552d"/>
    <circle cx="8" cy="24" r="3" fill="#b4552d"/>
    <circle cx="8" cy="38" r="3" fill="#b4552d"/>
    <circle cx="28" cy="24" r="5.5" fill="#b4552d"/>
  </svg>
  <div class="tessera-wordmark">
    <div class="tessera-title"><span class="tessera-journey">Tessera</span></div>
    <div class="tessera-subtitle">CDP Monitoring</div>
  </div>
</div>
""",
            unsafe_allow_html=True,
        )

        # ── FILTRES (un seul encadré contenant titre + sources + période) ────
        with st.container(border=True):
            col_h, col_r = st.columns([4, 1], vertical_alignment="center")
            with col_h:
                st.markdown(_section_header("tune", "FILTRES"), unsafe_allow_html=True)
            with col_r:
                if st.button(
                    "",
                    key="reset_filters",
                    icon=":material/restart_alt:",
                    help="Réinitialiser les filtres",
                ):
                    for k in ("src_pills", "preset_pills"):
                        st.session_state.pop(k, None)
                    st.session_state.date_debut = today - timedelta(days=90)
                    st.session_state.date_fin = today
                    st.rerun()

            # ── séparation visuelle pleine largeur sous le titre ─────────────
            st.markdown('<div class="tessera-filters-sep"></div>', unsafe_allow_html=True)

            # ── label SOURCES : ──────────────────────────────────────────────
            st.markdown(
                """
<div style="font-size:0.68rem;color:#8a7a66;margin-bottom:4px;
     display:flex;align-items:center;gap:4px;">
  <span class="material-symbols-outlined"
        style="font-size:0.75rem;vertical-align:middle;">storage</span>
  Sources :
</div>""",
                unsafe_allow_html=True,
            )

            selected = st.pills(
                "sources",
                DATA_SOURCES,
                selection_mode="multi",
                default=list(DATA_SOURCES),
                key="src_pills",
                label_visibility="collapsed",
            )
            active_sources = list(selected) if selected else list(DATA_SOURCES)

            # ── label PÉRIODE : ──────────────────────────────────────────────
            st.markdown(
                """
<div style="font-size:0.68rem;color:#8a7a66;margin:8px 0 4px;
     display:flex;align-items:center;gap:4px;">
  <span class="material-symbols-outlined"
        style="font-size:0.75rem;vertical-align:middle;">date_range</span>
  Période :
</div>""",
                unsafe_allow_html=True,
            )

            preset = st.pills(
                "preset",
                list(PRESET_DAYS.keys()) + ["Perso."],
                selection_mode="single",
                default="90j",
                key="preset_pills",
                label_visibility="collapsed",
            )
            if preset is None:
                preset = "90j"

            if preset == "Perso.":
                date_debut = st.date_input("Début", value=st.session_state.date_debut)
                date_fin = st.date_input("Fin", value=st.session_state.date_fin)
            else:
                nb = PRESET_DAYS[preset]
                date_debut = today - timedelta(days=nb)
                date_fin = today

            st.session_state.date_debut = date_debut
            st.session_state.date_fin = date_fin

            # bloc visuel de la plage de dates (intégré, sans sous-bloc)
            nb_jours = max((date_fin - date_debut).days, 1)
            debut_str = format_date_fr(date_debut)
            fin_str = format_date_fr(date_fin)

            if nb_jours <= 7:
                ctx = "semaine en cours"
            elif nb_jours <= 31:
                ctx = MOIS_FR[date_debut.month - 1] + f" {date_debut.year}"
            elif nb_jours <= 95:
                q = (date_debut.month - 1) // 3 + 1
                ctx = f"Q{q} {date_debut.year}"
            elif nb_jours <= 185:
                ctx = f"S{1 if date_debut.month <= 6 else 2} {date_debut.year}"
            else:
                ctx = str(date_debut.year)

            st.markdown(
                f"""
<div class="date-range-block">
  <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;">
    <div>
      <div style="font-size:0.55rem;font-weight:700;text-transform:uppercase;
           letter-spacing:0.8px;color:#a4937f;margin-bottom:2px;">DE</div>
      <div style="font-size:0.78rem;font-weight:600;color:#4a3e31;">{debut_str}</div>
    </div>
    <div style="color:#b5a690;font-size:0.9rem;">→</div>
    <div style="text-align:right;">
      <div style="font-size:0.55rem;font-weight:700;text-transform:uppercase;
           letter-spacing:0.8px;color:#a4937f;margin-bottom:2px;">À</div>
      <div style="font-size:0.78rem;font-weight:600;color:#4a3e31;">{fin_str}</div>
    </div>
  </div>
  <div style="height:3px;background:linear-gradient(90deg,
       rgb(201,149,42),rgb(224,138,60),rgb(226,101,74));
       border-radius:2px;margin:8px 0 4px;"></div>
  <div style="text-align:center;font-size:0.65rem;color:#a4937f;">
    {nb_jours} jours ({ctx})
  </div>
</div>""",
                unsafe_allow_html=True,
            )

        st.divider()

        # ── STATUT SYSTÈME ───────────────────────────────────────────────────
        st.markdown(_section_header("monitor_heart", "STATUT SYSTÈME"), unsafe_allow_html=True)

        for signal in get_system_health():
            color = (
                "#16a34a"
                if signal.status == "ok"
                else "#d97706"
                if signal.status == "warn"
                else "#dc2626"
            )
            glow = (
                "rgba(22,163,74,0.4)"
                if signal.status == "ok"
                else "rgba(217,119,6,0.4)"
                if signal.status == "warn"
                else "rgba(220,38,38,0.4)"
            )
            is_alert = signal.status == "warn"
            row_extra = " status-row-alert" if is_alert else ""
            val_color = "#d97706" if is_alert else "#a4937f"
            val_weight = "600" if is_alert else "400"
            detail_html = (
                f'<span class="material-symbols-outlined" style="font-size:0.68rem;'
                f'vertical-align:middle;color:#d97706;">warning</span> {signal.detail}'
                if is_alert
                else signal.detail
            )
            st.markdown(
                f"""
<div class="status-row{row_extra}">
  <div style="display:flex;align-items:center;gap:8px;">
    <span style="background:{color};width:8px;height:8px;border-radius:50%;
          box-shadow:0 0 6px {glow};display:inline-block;flex-shrink:0;"></span>
    <span style="font-size:0.72rem;font-weight:500;color:#4a3e31;">{signal.name}</span>
  </div>
  <span style="font-size:0.68rem;color:{val_color};font-weight:{val_weight};">{detail_html}</span>
</div>""",
                unsafe_allow_html=True,
            )

        st.divider()

        # ── FRAÎCHEUR DES SOURCES ────────────────────────────────────────────
        st.markdown(_section_header("schedule", "FRAÎCHEUR DES SOURCES"), unsafe_allow_html=True)

        freshness = get_source_freshness()
        for src, age, minutes in freshness:
            over = minutes > FRESHNESS_THRESHOLD_MIN
            dot_color = "#d97706" if over else "#16a34a"
            text_color = "#d97706" if over else "#6f6052"
            text_weight = "600" if over else "400"
            warn_icon = (
                '<span class="material-symbols-outlined" style="font-size:0.7rem;'
                'vertical-align:middle;color:#d97706;margin-left:4px;">warning</span>'
                if over
                else ""
            )
            st.markdown(
                f"""
<div style="display:flex;justify-content:space-between;align-items:center;
     padding:6px 0;border-bottom:1px solid #fdfcfa;">
  <span style="color:#3f3328;font-size:0.8rem;">
    <span style="color:{dot_color};margin-right:6px;">●</span>{src}{warn_icon}
  </span>
  <span style="color:{text_color};font-size:0.75rem;font-weight:{text_weight};">{age}</span>
</div>""",
                unsafe_allow_html=True,
            )

        st.markdown(
            f"""
<div style="margin-top:20px;color:#a4937f;font-size:0.72rem;">
  Mise à jour : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
</div>""",
            unsafe_allow_html=True,
        )

    return active_sources, date_debut, date_fin


# ── métriques principales ─────────────────────────────────────────────────────
def render_top_metrics(metrics: dict) -> None:
    # ── Couleurs santé : neutre par défaut, rouge si vide, feu tricolore sur le taux de match ──
    neutre, vert, orange, rouge = "#1e3a52", "#16a34a", "#d97706", "#dc2626"

    def couleur_volume(v: float) -> str:
        # Un volume / revenu n'a pas de "bon seuil" universel -> neutre s'il y a des données,
        # rouge uniquement si c'est vide (0 = pipeline cassé, vrai signal d'alerte).
        return neutre if v and v > 0 else rouge

    def couleur_match(pct: float) -> str:
        # Seul indicateur de qualité gradué : >= 20 % bon, 10-20 % moyen, < 10 % faible.
        if pct >= 20:
            return vert
        if pct >= 10:
            return orange
        return rouge

    cartes = [
        (
            "Profils bruts ingérés",
            format_nombre_fr(metrics["profils_bruts"]),
            couleur_volume(metrics["profils_bruts"]),
        ),
        (
            "Profils unifiés",
            format_nombre_fr(metrics["profils_unifies"]),
            couleur_volume(metrics["profils_unifies"]),
        ),
        (
            "Taux de match moyen",
            f"{metrics['taux_match']:.1f} %",
            couleur_match(metrics["taux_match"]),
        ),
        (
            "Revenu Attribué",
            format_nombre_fr(metrics["revenu_eur"], suffix="€"),
            couleur_volume(metrics["revenu_eur"]),
        ),
    ]
    for col, (label, valeur, couleur) in zip(st.columns(4), cartes, strict=False):
        with col:
            st.markdown(
                f"""
<div style="background:#ffffff;box-shadow:0 1px 3px rgba(20,30,55,0.05);border:1px solid #e9cfc0;
            border-radius:12px;padding:1rem 1.2rem;">
  <div style="color:#6f6052;font-size:0.78rem;font-weight:500;letter-spacing:0.05em;">{label}</div>
  <div style="color:{couleur};font-size:1.6rem;font-weight:700;margin-top:4px;">{valeur}</div>
</div>""",
                unsafe_allow_html=True,
            )


# ── bannière de santé du pipeline ─────────────────────────────────────────────
def render_health_banner(health: dict) -> None:
    runs = health["runs"]
    success_pct = health["success_pct"]
    soda = health["soda_alerts"]
    rgpd_pct = health["rgpd_pct"]
    kestra_s = health["kestra_avg_s"]
    operational = soda == 0 and success_pct >= 90

    badge_lbl = "PIPELINE OPÉRATIONNEL" if operational else "PIPELINE EN ALERTE"
    badge_color = "#16a34a" if operational else "#d97706"
    soda_color = "#16a34a" if soda == 0 else "#d97706"
    soda_icon = (
        ""
        if soda == 0
        else ('<span class="material-symbols-outlined" style="font-size:0.8rem;">warning</span>')
    )

    st.markdown(
        f"""
<div class="health-banner">
  <div style="display:flex;align-items:center;gap:8px;">
    <span class="pulse-dot" style="background:{badge_color};"></span>
    <span style="color:{badge_color};font-size:0.78rem;font-weight:700;letter-spacing:0.1em;">{badge_lbl}</span>
  </div>
  <span style="color:#a4937f;font-size:0.72rem;">{datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}</span>
  <div style="display:flex;align-items:center;gap:20px;flex-wrap:wrap;margin-left:auto;">
    <span style="color:#6f6052;font-size:0.75rem;">Runs <strong style="color:#33271e;">{runs}</strong></span>
    <span style="color:#6f6052;font-size:0.75rem;">Succès <strong style="color:#16a34a;">{success_pct:.1f}%</strong></span>
    <span style="color:{soda_color};font-size:0.75rem;display:inline-flex;align-items:center;gap:3px;">{soda_icon}Soda <strong>{soda} alerte{'s' if soda>1 else ''}</strong></span>
    <span style="color:#6f6052;font-size:0.75rem;">RGPD <strong style="color:#16a34a;">{rgpd_pct:.0f}%</strong></span>
    <span style="color:#6f6052;font-size:0.75rem;">Kestra <strong style="color:#a05530;">{kestra_s:.0f}s</strong></span>
    <span class="badge badge-bronze">Bronze</span>
    <span class="badge badge-silver">Silver</span>
    <span class="badge badge-gold">Gold</span>
  </div>
</div>""",
        unsafe_allow_html=True,
    )


# ── alerte soda ───────────────────────────────────────────────────────────────
def render_soda_alert(soda: dict) -> None:
    """Alerte qualité Soda branchée sur les checks réels (audit_pipeline_runs)."""
    alerts = soda.get("alerts", []) if soda else []
    total = soda.get("total", 0) if soda else 0

    # Tous les contrôles au vert sur les dernières 24 h
    if not alerts:
        if total > 0:
            st.markdown(
                f"""
<div class="soda-alert" style="background:rgba(22,163,74,0.08);border-color:rgba(22,163,74,0.3);">
  <strong style="color:#16a34a;"><span class="material-symbols-outlined" style="font-size:0.9rem;vertical-align:middle;margin-right:4px;">check_circle</span>Soda Data Quality : {total} contrôles au vert</strong>
</div>""",
                unsafe_allow_html=True,
            )
        # Aucun scan récent, on n'affiche rien d'alarmant
        return

    n = len(alerts)
    lignes = ""
    for step, detail, mins in alerts:
        when = "" if mins is None else f", il y a {mins} min"
        detail_txt = f" {detail}" if detail else ""
        lignes += (
            f'<div style="font-size:0.8rem;color:#d97706;margin-top:4px;">'
            f'<code style="background:rgba(0,0,0,0.08);padding:1px 6px;border-radius:4px;">{step}</code>'
            f"{detail_txt}{when}</div>"
        )

    st.markdown(
        f"""
<div class="soda-alert">
  <strong><span class="material-symbols-outlined" style="font-size:0.9rem;vertical-align:middle;margin-right:4px;">warning</span>Soda Data Quality : {n} check{'s' if n > 1 else ''} en alerte</strong>
  {lignes}
  <a href="#logs" style="color:#b45309;font-size:0.78rem;text-decoration:none;">→ Voir logs</a>
</div>""",
        unsafe_allow_html=True,
    )


# ── panneau graphe d'identité ─────────────────────────────────────────────────
def render_identity_graph(unification_df: pd.DataFrame, stats: dict) -> None:
    """Graphe d'identité branché sur les vrais marts.

    `unification_df` : Source / Profils bruts / Profils unifiés / Taux de match (%).
    `stats`          : identity_graph_stats (raw_ids, unified_users, avg_ids_per_user).
    """
    # Lookup par nom d'affichage de source : (volume brut, taux de match %)
    by_src: dict[str, tuple[float, float]] = {}
    if unification_df is not None and not unification_df.empty:
        for _, r in unification_df.iterrows():
            by_src[str(r["Source"])] = (float(r["Profils bruts"]), float(r["Taux de match (%)"]))

    def cell(name: str) -> tuple[str, str]:
        raw, pct = by_src.get(name, (0.0, 0.0))
        return format_nombre_fr(raw), f"{pct:.1f}%"

    ga4_n, ga4_p = cell("GA4")
    meta_n, meta_p = cell("Meta Ads")
    shop_n, shop_p = cell("Shopify")
    mail_n, mail_p = cell("Mailchimp")

    hub_n = format_nombre_fr(stats.get("unified_users", 0))
    avg = stats.get("avg_ids_per_user", 0.0)

    st.markdown(
        f"""
<div class="panel-card">
  <div class="panel-title"><span class="material-symbols-outlined">hub</span>Identity Graph: Résolution d'entités</div>
  <svg width="100%" viewBox="0 0 700 200" xmlns="http://www.w3.org/2000/svg">
    <circle cx="350" cy="100" r="36" fill="url(#grad-cdp)" stroke="#a84e27" stroke-width="2"/>
    <text x="350" y="94" text-anchor="middle" fill="white" font-size="11" font-weight="700">CDP</text>
    <text x="350" y="108" text-anchor="middle" fill="#f3d9c8" font-size="9">{hub_n} users</text>
    <text x="350" y="120" text-anchor="middle" fill="#e8d2bf" font-size="7.5">{avg:.1f} ID/user</text>
    <defs>
      <radialGradient id="grad-cdp" cx="50%" cy="50%" r="50%">
        <stop offset="0%" stop-color="#a84e27"/>
        <stop offset="100%" stop-color="#7c3a1a"/>
      </radialGradient>
    </defs>
    <circle cx="80" cy="50" r="26" fill="#fdfcfa" stroke="#c2503a" stroke-width="1.5"/>
    <text x="80" y="46" text-anchor="middle" fill="#c2503a" font-size="10" font-weight="600">GA4</text>
    <text x="80" y="60" text-anchor="middle" fill="#8a7a66" font-size="8">{ga4_n}</text>
    <line x1="106" y1="60" x2="314" y2="88" stroke="#c2503a" stroke-width="1" stroke-dasharray="4"/>
    <text x="190" y="66" fill="#c2503a" font-size="9" text-anchor="middle">{ga4_p}</text>
    <circle cx="80" cy="150" r="26" fill="#fdfcfa" stroke="#b05570" stroke-width="1.5"/>
    <text x="80" y="146" text-anchor="middle" fill="#b05570" font-size="10" font-weight="600">Meta</text>
    <text x="80" y="160" text-anchor="middle" fill="#8a7a66" font-size="8">{meta_n}</text>
    <line x1="106" y1="143" x2="314" y2="110" stroke="#b05570" stroke-width="1" stroke-dasharray="4"/>
    <text x="190" y="135" fill="#b05570" font-size="9" text-anchor="middle">{meta_p}</text>
    <circle cx="620" cy="50" r="26" fill="#fdfcfa" stroke="#16a34a" stroke-width="1.5"/>
    <text x="620" y="46" text-anchor="middle" fill="#16a34a" font-size="10" font-weight="600">Shop</text>
    <text x="620" y="60" text-anchor="middle" fill="#8a7a66" font-size="8">{shop_n}</text>
    <line x1="594" y1="60" x2="386" y2="88" stroke="#16a34a" stroke-width="1" stroke-dasharray="4"/>
    <text x="510" y="66" fill="#16a34a" font-size="9" text-anchor="middle">{shop_p}</text>
    <circle cx="620" cy="150" r="26" fill="#fdfcfa" stroke="#d97706" stroke-width="1.5"/>
    <text x="620" y="146" text-anchor="middle" fill="#d97706" font-size="10" font-weight="600">Mail</text>
    <text x="620" y="160" text-anchor="middle" fill="#8a7a66" font-size="8">{mail_n}</text>
    <line x1="594" y1="143" x2="386" y2="110" stroke="#d97706" stroke-width="1" stroke-dasharray="4"/>
    <text x="510" y="135" fill="#d97706" font-size="9" text-anchor="middle">{mail_p}</text>
  </svg>
  <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-top:16px;">
    <div style="text-align:center;padding:10px;background:#f4f4f2;border-radius:8px;border:1px solid #e9cfc0;">
      <div style="color:#c2503a;font-size:1.1rem;font-weight:700;">{ga4_p}</div>
      <div style="color:#8a7a66;font-size:0.72rem;">GA4 match rate</div>
    </div>
    <div style="text-align:center;padding:10px;background:#f4f4f2;border-radius:8px;border:1px solid #e9cfc0;">
      <div style="color:#b05570;font-size:1.1rem;font-weight:700;">{meta_p}</div>
      <div style="color:#8a7a66;font-size:0.72rem;">Meta match rate</div>
    </div>
    <div style="text-align:center;padding:10px;background:#f4f4f2;border-radius:8px;border:1px solid #e9cfc0;">
      <div style="color:#16a34a;font-size:1.1rem;font-weight:700;">{shop_p}</div>
      <div style="color:#8a7a66;font-size:0.72rem;">Shopify match rate</div>
    </div>
    <div style="text-align:center;padding:10px;background:#f4f4f2;border-radius:8px;border:1px solid #e9cfc0;">
      <div style="color:#d97706;font-size:1.1rem;font-weight:700;">{mail_p}</div>
      <div style="color:#8a7a66;font-size:0.72rem;">Mailchimp match rate</div>
    </div>
  </div>
</div>""",
        unsafe_allow_html=True,
    )


# ── panneau lignage des données ───────────────────────────────────────────────
def render_data_lineage() -> None:
    st.markdown(
        """
<div class="panel-card">
  <div class="panel-title"><span class="material-symbols-outlined">account_tree</span>Data Lineage: Bronze → Silver → Gold</div>
  <div style="display:flex;align-items:center;gap:0;overflow-x:auto;padding:8px 0;">
    <div style="display:flex;flex-direction:column;gap:6px;flex-shrink:0;">
      <div style="background:#f4f4f2;border:1px solid #e9cfc0;border-radius:6px;padding:6px 12px;font-size:0.75rem;color:#c2503a;display:flex;align-items:center;gap:5px;"><span class="material-symbols-outlined" style="font-size:0.85rem;">analytics</span>GA4</div>
      <div style="background:#f4f4f2;border:1px solid #e9cfc0;border-radius:6px;padding:6px 12px;font-size:0.75rem;color:#b05570;display:flex;align-items:center;gap:5px;"><span class="material-symbols-outlined" style="font-size:0.85rem;">campaign</span>Meta Ads</div>
      <div style="background:#f4f4f2;border:1px solid #e9cfc0;border-radius:6px;padding:6px 12px;font-size:0.75rem;color:#16a34a;display:flex;align-items:center;gap:5px;"><span class="material-symbols-outlined" style="font-size:0.85rem;">storefront</span>Shopify</div>
      <div style="background:#f4f4f2;border:1px solid #e9cfc0;border-radius:6px;padding:6px 12px;font-size:0.75rem;color:#d97706;display:flex;align-items:center;gap:5px;"><span class="material-symbols-outlined" style="font-size:0.85rem;">mail</span>Mailchimp</div>
    </div>
    <div style="color:#a4937f;margin:0 8px;font-size:1.2rem;">→</div>
    <div style="text-align:center;flex-shrink:0;">
      <div style="background:rgba(180,100,40,0.15);border:1px solid rgba(180,100,40,0.3);border-radius:8px;padding:12px 18px;">
        <div style="color:#a05e22;font-weight:700;font-size:0.85rem;">Bronze</div>
        <div style="color:#8a7a66;font-size:0.7rem;margin-top:4px;">Raw ingestion</div>
        <div style="color:#8a7a66;font-size:0.68rem;">Kestra ETL</div>
      </div>
    </div>
    <div style="color:#a4937f;margin:0 8px;font-size:1.2rem;">→</div>
    <div style="text-align:center;flex-shrink:0;">
      <div style="background:rgba(100,130,170,0.15);border:1px solid rgba(100,130,170,0.3);border-radius:8px;padding:12px 18px;">
        <div style="color:#6f6052;font-weight:700;font-size:0.85rem;">Silver</div>
        <div style="color:#8a7a66;font-size:0.7rem;margin-top:4px;">Nettoyage + identité</div>
        <div style="color:#8a7a66;font-size:0.68rem;">dbt + DuckDB</div>
      </div>
    </div>
    <div style="color:#a4937f;margin:0 8px;font-size:1.2rem;">→</div>
    <div style="text-align:center;flex-shrink:0;">
      <div style="background:rgba(176,133,21,0.1);border:1px solid rgba(176,133,21,0.3);border-radius:8px;padding:12px 18px;">
        <div style="color:#b45309;font-weight:700;font-size:0.85rem;">Gold</div>
        <div style="color:#8a7a66;font-size:0.7rem;margin-top:4px;">Agrégats métier</div>
        <div style="color:#8a7a66;font-size:0.68rem;">Attribution models</div>
      </div>
    </div>
    <div style="color:#a4937f;margin:0 8px;font-size:1.2rem;">→</div>
    <div style="text-align:center;flex-shrink:0;">
      <div style="background:rgba(168,78,39,0.1);border:1px solid rgba(168,78,39,0.3);border-radius:8px;padding:12px 18px;">
        <div style="color:#a05530;font-weight:700;font-size:0.85rem;display:flex;align-items:center;gap:4px;"><span class="material-symbols-outlined" style="font-size:0.85rem;">dashboard</span>Dashboard</div>
        <div style="color:#8a7a66;font-size:0.7rem;margin-top:4px;">Streamlit CDP</div>
        <div style="color:#8a7a66;font-size:0.68rem;">Real-time</div>
      </div>
    </div>
  </div>
</div>""",
        unsafe_allow_html=True,
    )


# ── panneau d'attribution ─────────────────────────────────────────────────────
def render_attribution_panel(attr_df: pd.DataFrame) -> None:
    """Attribution multi-touch (modèle linéaire) branchée sur marts.fct_conversions.

    `attr_df` : colonnes [canal, revenu, part_pct] déjà triées décroissant.
    """
    _grads = [
        "linear-gradient(90deg,#c2503a,#a8412c)",
        "linear-gradient(90deg,#b05570,#b05570)",
        "linear-gradient(90deg,#16a34a,#059669)",
        "linear-gradient(90deg,#d97706,#d97706)",
        "linear-gradient(90deg,#a84e27,#8f3f1d)",
    ]

    if attr_df is None or attr_df.empty:
        st.markdown(
            """
<div class="panel-card">
  <div class="panel-title"><span class="material-symbols-outlined">ads_click</span>Attribution Multi-Touch: Data-Driven (Linéaire)</div>
  <div style="color:#8a7a66;font-size:0.85rem;padding:14px 0;">Aucune conversion attribuée sur la période sélectionnée.</div>
</div>""",
            unsafe_allow_html=True,
        )
        return

    total = float(attr_df["revenu"].sum())
    max_pct = float(attr_df["part_pct"].max()) or 1.0
    rows_html = ""
    for i, (_, r) in enumerate(attr_df.iterrows()):
        canal = str(r["canal"])
        revenu = float(r["revenu"])
        pct = float(r["part_pct"])
        bar_w = max(6.0, pct / max_pct * 100.0)  # largeur relative au plus gros canal
        grad = _grads[i % len(_grads)]
        rows_html += f"""
    <div style="display:flex;align-items:center;gap:10px;">
      <span style="width:120px;color:#6f6052;font-size:0.78rem;text-align:right;flex-shrink:0;">{canal}</span>
      <div style="flex:1;background:#f4f4f2;border-radius:4px;height:28px;overflow:hidden;">
        <div style="width:{bar_w:.0f}%;background:{grad};height:100%;border-radius:4px;display:flex;align-items:center;padding:0 10px;">
          <span style="color:white;font-size:0.75rem;font-weight:600;">{pct:.0f}% / {format_nombre_fr(revenu)}€</span>
        </div>
      </div>
    </div>"""

    st.markdown(
        f"""
<div class="panel-card">
  <div class="panel-title"><span class="material-symbols-outlined">ads_click</span>Attribution Multi-Touch: Data-Driven (Linéaire)</div>
  <div style="display:flex;flex-direction:column;gap:10px;">{rows_html}
  </div>
  <div style="margin-top:14px;text-align:right;color:#8a7a66;font-size:0.75rem;">
    Total attribué : <strong style="color:#33271e;">{format_nombre_fr(total)}€</strong>
  </div>
</div>""",
        unsafe_allow_html=True,
    )


# ── panneau score RGPD ────────────────────────────────────────────────────────
def render_gdpr_score(gdpr: dict) -> None:
    """Score RGPD branché sur marts.dim_users (statuts de consentement réels)."""
    score = int(gdpr.get("score_pct", 0))
    circumference = 314.0  # 2*pi*r, r=50
    offset = circumference * (1 - score / 100.0)
    conforme = score >= 99
    label = "CONFORME" if conforme else "À SURVEILLER"
    label_color = "#16a34a" if conforme else "#d97706"

    consent_ok = format_nombre_fr(gdpr.get("consent_ok", 0))
    anonymes = format_nombre_fr(gdpr.get("anonymes", 0))
    pseudo = format_nombre_fr(gdpr.get("pseudonymises", 0))
    total = format_nombre_fr(gdpr.get("total", 0))

    st.markdown(
        f"""
<div class="panel-card">
  <div class="panel-title"><span class="material-symbols-outlined">shield</span>GDPR Score: Conformité des données</div>
  <div style="display:flex;align-items:center;gap:32px;flex-wrap:wrap;">
    <div style="text-align:center;flex-shrink:0;">
      <svg width="120" height="120" viewBox="0 0 120 120">
        <defs>
          <linearGradient id="grad-gdpr" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stop-color="#34d399"/>
            <stop offset="100%" stop-color="#059669"/>
          </linearGradient>
        </defs>
        <circle cx="60" cy="60" r="50" fill="none" stroke="#e9cfc0" stroke-width="10"/>
        <circle cx="60" cy="60" r="50" fill="none" stroke="url(#grad-gdpr)" stroke-width="10"
          stroke-dasharray="{circumference:.0f}" stroke-dashoffset="{offset:.0f}"
          stroke-linecap="round" transform="rotate(-90 60 60)"/>
        <text x="60" y="56" text-anchor="middle" fill="#33271e" font-size="22" font-weight="700">{score}%</text>
        <text x="60" y="72" text-anchor="middle" fill="{label_color}" font-size="10">{label}</text>
      </svg>
    </div>
    <div style="display:grid;grid-template-columns:repeat(2,1fr);gap:10px;flex:1;min-width:280px;">
      <div style="background:#f4f4f2;border:1px solid #e9cfc0;border-radius:8px;padding:12px;">
        <div style="color:#a05530;font-size:1rem;font-weight:700;">{consent_ok}</div>
        <div style="color:#8a7a66;font-size:0.72rem;">Consentement OK</div>
      </div>
      <div style="background:#f4f4f2;border:1px solid #e9cfc0;border-radius:8px;padding:12px;">
        <div style="color:#c2503a;font-size:1rem;font-weight:700;">{pseudo}</div>
        <div style="color:#8a7a66;font-size:0.72rem;">PII pseudonymisés (hash)</div>
      </div>
      <div style="background:#f4f4f2;border:1px solid #e9cfc0;border-radius:8px;padding:12px;">
        <div style="color:#16a34a;font-size:1rem;font-weight:700;">{total}</div>
        <div style="color:#8a7a66;font-size:0.72rem;">Profils unifiés</div>
      </div>
      <div style="background:rgba(217,119,6,0.08);border:1px solid rgba(217,119,6,0.25);border-radius:8px;padding:12px;">
        <div style="color:#d97706;font-size:1rem;font-weight:700;">{anonymes}</div>
        <div style="color:#8a7a66;font-size:0.72rem;">Anonymes / à anonymiser</div>
      </div>
    </div>
  </div>
</div>""",
        unsafe_allow_html=True,
    )


# ── timeline pipeline (gantt) ─────────────────────────────────────────────────
def render_pipeline_gantt(timeline_df: pd.DataFrame) -> None:
    """Timeline des runs réels (audit_pipeline_runs) sur les dernières 24 h.

    Chaque bloc est positionné par son start_ts/end_ts réel dans la fenêtre
    glissante de 24 h, et coloré selon le statut du run.
    """
    status_colors = {
        "SUCCESS": "#059669",
        "FAILED": "#dc2626",
        "WARNING": "#d97706",
        "WARN": "#d97706",
        "RUNNING": "#a84e27",
    }

    header = """
<div class="panel-card" id="logs">
  <div class="panel-title"><span class="material-symbols-outlined">timeline</span>Pipeline Timeline: Dernières 24h</div>
  <div style="font-size:0.7rem;color:#a4937f;margin-bottom:12px;display:flex;justify-content:space-between;">
    <span>-24h</span><span>-18h</span><span>-12h</span><span>-6h</span><span>maintenant</span>
  </div>"""

    if timeline_df is None or timeline_df.empty:
        st.markdown(
            header
            + """
  <div style="color:#8a7a66;font-size:0.85rem;padding:10px 0;">Aucun run enregistré dans les dernières 24 h.</div>
</div>""",
            unsafe_allow_html=True,
        )
        return

    df = timeline_df.copy()
    # Normalise les timestamps en naïf-UTC pour le calcul de position
    for col in ("start_ts", "end_ts"):
        df[col] = pd.to_datetime(df[col], utc=True, errors="coerce").dt.tz_localize(None)
    window_end = pd.Timestamp.utcnow().tz_localize(None)
    window_start = window_end - pd.Timedelta(hours=24)
    span = 24 * 3600.0  # secondes

    # Ordre d'affichage des lignes
    order = ["GA4", "Meta Ads", "Shopify", "Mailchimp", "DBT", "SODA"]
    present = list(df["source"].unique())
    ordered = [s for s in order if s in present] + [s for s in present if s not in order]

    rows_html = ""
    for src in ordered:
        blocks = ""
        for _, r in df[df["source"] == src].iterrows():
            start = max(r["start_ts"], window_start)
            end = max(min(r["end_ts"], window_end), start)
            left = (start - window_start).total_seconds() / span * 100.0
            width = max(2.0, (end - start).total_seconds() / span * 100.0)
            color = status_colors.get(str(r["statut"]).upper(), "#a4937f")
            label = str(r["etape"])[:10]
            blocks += (
                f'<div class="gantt-block" style="left:{left:.1f}%;width:{width:.1f}%;'
                f'background:{color};">{label}</div>'
            )
        rows_html += f"""
  <div class="gantt-row">
    <span class="gantt-label">{src}</span>
    <div class="gantt-track">{blocks}</div>
  </div>"""

    legend = """
  <div style="display:flex;gap:16px;margin-top:16px;flex-wrap:wrap;">
    <span style="font-size:0.72rem;"><span style="color:#059669;">■</span> SUCCESS</span>
    <span style="font-size:0.72rem;"><span style="color:#dc2626;">■</span> FAILED</span>
    <span style="font-size:0.72rem;"><span style="color:#d97706;">■</span> WARNING</span>
    <span style="font-size:0.72rem;"><span style="color:#a84e27;">■</span> RUNNING</span>
  </div>
</div>"""
    st.markdown(header + rows_html + legend, unsafe_allow_html=True)


# ── onglet vue d'ensemble ─────────────────────────────────────────────────────
def render_tab_overview(
    unification_df: pd.DataFrame,
    quality_df: pd.DataFrame,
    identity_stats: dict,
    attr_df: pd.DataFrame,
) -> None:
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("#### Profils unifiés par source")
        chart_data = unification_df.set_index("Source")[["Profils bruts", "Profils unifiés"]]
        st.bar_chart(chart_data, color=["#a84e27", "#c9952a"])

    with col2:
        st.markdown("#### Évolution du score qualité")
        st.line_chart(quality_df, color=["#16a34a"])

    render_identity_graph(unification_df, identity_stats)
    render_data_lineage()
    render_attribution_panel(attr_df)

    with st.expander("Détail: Taux de match par source", expanded=False):
        st.dataframe(unification_df, use_container_width=True, hide_index=True)


# ── fonctions utilitaires ─────────────────────────────────────────────────────
def _color_status(val: str) -> str:
    if val == "SUCCESS":
        return "background-color: rgba(22,163,74,0.15); color: #16a34a"
    if val == "FAILED":
        return "background-color: rgba(220,38,38,0.15); color: #dc2626"
    if val == "WARNING":
        return "background-color: rgba(217,119,6,0.15); color: #d97706"
    return ""


# ── tab RGPD ──────────────────────────────────────────────────────────────────
def render_tab_rgpd(rgpd_df: pd.DataFrame, gdpr: dict) -> None:
    render_gdpr_score(gdpr)
    st.markdown("#### Registre des traitements RGPD")
    styled = rgpd_df.style.map(_color_status, subset=["Statut"])
    st.dataframe(styled, use_container_width=True, hide_index=True)


# ── onglet logs ───────────────────────────────────────────────────────────────
def render_tab_logs(logs_df: pd.DataFrame, timeline_df: pd.DataFrame) -> None:
    render_pipeline_gantt(timeline_df)
    st.markdown("#### Journal des runs pipeline")
    styled = logs_df.style.map(_color_status, subset=["Statut"])
    st.dataframe(styled, use_container_width=True, hide_index=True)


# ── point d'entrée ────────────────────────────────────────────────────────────
def _warehouse_unavailable(exc: Exception) -> None:
    """Affiche un panneau clair quand le warehouse n'a pas encore été matérialisé."""
    st.error(
        "**Warehouse DuckDB introuvable ou vide.** "
        "Le dashboard lit directement les marts dbt et l'historique des runs "
        "depuis `warehouse/tessera.duckdb`. "
        "Lance le pipeline une première fois :\n\n"
        "```bash\nmake pipeline   # ou : make ingest && make transform && make quality\n```\n\n"
        f"_Détail : {exc}_"
    )
    st.stop()


def main() -> None:
    inject_css()

    # Sanity-check warehouse avant de rendre la sidebar (sinon chaque widget
    # déclenche son propre crash et la page reste illisible)
    try:
        uj_db.get_connection().close()
    except FileNotFoundError as exc:
        _warehouse_unavailable(exc)
        return

    # La sidebar interroge déjà le warehouse (statut système, fraîcheur) :
    # on la protège aussi, sinon un warehouse présent mais sans marts dbt
    # (pipeline interrompu) affiche un traceback brut au lieu du panneau d'aide.
    try:
        sources, start_date, end_date = render_sidebar()
    except Exception as exc:  # noqa: BLE001
        _warehouse_unavailable(exc)
        return
    sources_key = tuple(sources)

    try:
        unification_df = fetch_unification(start_date, end_date, sources_key)
        quality_df = fetch_quality_trend(start_date, end_date)
        rgpd_df = fetch_rgpd_table(sources_key)
        logs_df = fetch_pipeline_logs(start_date, end_date, sources_key)
        top_kpis = fetch_top_metrics(start_date, end_date, sources_key)
        health = fetch_health_banner(start_date, end_date)
        identity_stats = fetch_identity_stats()
        attr_df = fetch_attribution(start_date, end_date)
        gdpr = fetch_gdpr_breakdown()
        soda = fetch_soda_status()
        timeline_df = fetch_pipeline_timeline()
    except Exception as exc:  # noqa: BLE001
        _warehouse_unavailable(exc)
        return

    debut_str = format_date_fr(start_date)
    fin_str = format_date_fr(end_date)
    nb_jours = max((end_date - start_date).days, 1)

    # ── Statut réel du pipeline (depuis health), plus de valeur codée en dur ──
    operational = health["soda_alerts"] == 0 and health["success_pct"] >= 90
    statut_label = "Pipeline opérationnel" if operational else "Pipeline en alerte"
    dot_color = "#16a34a" if operational else "#d97706"
    last_run = health.get("last_run_ts")
    if last_run is not None:
        last_run_dt = pd.to_datetime(last_run, utc=True, errors="coerce")
        maj_str = (
            "Dernier run : " + last_run_dt.strftime("%d/%m %H:%M UTC")
            if pd.notnull(last_run_dt)
            else "Dernier run : inconnu"
        )
    else:
        maj_str = "Aucun run enregistré"

    # ── HERO : qui je suis / où je suis / quel statut ────────────────────
    st.markdown(
        f"""
<div class="tessera-hero">
  <div class="tessera-hero-left">
    <div class="tessera-hero-eyebrow">Plateforme CDP : Monitoring</div>
    <h1 class="tessera-hero-title">Tableau de bord Tessera</h1>
    <div class="tessera-hero-sub">
      Vue temps réel de votre plateforme de données client : ingestion multi-sources,
      unification d'identité, conformité RGPD et attribution multi-touch.
    </div>
  </div>
  <div class="tessera-hero-right">
    <div class="tessera-status-chip">
      <span class="pulse-dot" style="background:{dot_color};"></span>
      <div>
        {statut_label}
        <div class="tessera-status-chip-sub">{maj_str}</div>
      </div>
    </div>
    <div class="tessera-period-chip">
      <span class="material-symbols-outlined">calendar_month</span>
      {debut_str} → {fin_str} ({nb_jours} jours)
    </div>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )

    # ── SECTION 1 : Santé du pipeline ────────────────────────────────────
    st.markdown(
        """
<div class="tessera-block-head">
  <div class="tessera-block-title"><span class="material-symbols-outlined">monitoring</span>Santé du pipeline</div>
  <div class="tessera-block-sub">
    Suivi en direct des runs, alertes qualité Soda, propagation du consentement RGPD,
    orchestration Kestra et couches du lakehouse (Bronze, Silver, Gold).
  </div>
</div>
""",
        unsafe_allow_html=True,
    )
    render_health_banner(health)

    # ── SECTION 2 : Indicateurs clés (KPIs métier) ───────────────────────
    st.markdown(
        """
<div class="tessera-block-head tessera-block-head--spaced">
  <div class="tessera-block-title"><span class="material-symbols-outlined">insights</span>Indicateurs clés</div>
  <div class="tessera-block-sub">
    Performance de l'unification d'identité et de l'attribution sur la période sélectionnée.
  </div>
</div>
""",
        unsafe_allow_html=True,
    )
    render_top_metrics(top_kpis)

    # ── SECTION 3 : Analyse détaillée (onglets) ──────────────────────────
    st.markdown(
        """
<div class="tessera-section-header">
  <div class="tessera-section-title"><span class="material-symbols-outlined">analytics</span>Analyse détaillée</div>
  <div class="tessera-section-subtitle">Explorez par thématique : performances, conformité RGPD, exécution du pipeline.</div>
</div>
""",
        unsafe_allow_html=True,
    )

    tab_overview, tab_rgpd, tab_logs = st.tabs(
        [
            "Vue d'ensemble",
            "RGPD & Confidentialité",
            "Logs Pipeline",
        ]
    )

    with tab_overview:
        render_soda_alert(soda)
        render_tab_overview(unification_df, quality_df, identity_stats, attr_df)

    with tab_rgpd:
        render_tab_rgpd(rgpd_df, gdpr)

    with tab_logs:
        render_tab_logs(logs_df, timeline_df)


if __name__ == "__main__":
    main()
