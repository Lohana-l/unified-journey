# Tessera CDP - Streamlit CDP monitoring dashboard.
# Single-page Streamlit app (`app.py`) exposing :
#   * sidebar filters + system health
#   * top KPI row (Utilisateurs Unifiés / PII Masqués / Qualité Data %)
#   * tabs : Vue d'ensemble, Conformité RGPD, Logs du pipeline
#
# Port 8501 is the Streamlit default and is preserved across the migration
# so docker-compose / Terraform mappings don't change.

FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

# Application code - Streamlit entrypoint + shared lib (DuckDB queries).
COPY app.py /app/app.py
COPY app /app/app

EXPOSE 8501

# Streamlit exposes a built-in healthcheck at /_stcore/health.
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
  CMD curl -fsS http://localhost:8501/_stcore/health || exit 1

CMD ["streamlit", "run", "app.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true", \
     "--browser.gatherUsageStats=false"]
