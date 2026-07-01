# Observabilité

Délibérément minimale et native de l'entrepôt. Trois primitives, pas d'OTel, pas
de Prometheus, pas de Grafana, qui seraient tous du sur-ingénierie à cette
échelle :

1. **Journaux structurés** : un objet JSON par ligne en production.
2. **Une table d'audit** dans DuckDB (`audit_pipeline_runs`), interrogeable depuis
   le tableau de bord et n'importe quel client SQL.
3. **Une métrique alarmable** (`PipelineErrors`), prête à être branchée sur CloudWatch et SNS en production.

<div align="center">
  <img src="img/pipeline-timeline.png" alt="Pipeline timeline: last 24h runs with status" width="760">
</div>

---

## 1. Journalisation structurée

`ingestion/observability.py` expose `configure_logger()` ; la forme de la
destination est contrôlée par `TESSERA_LOG_FORMAT` : `pretty` (dev, par défaut)
ou `json` (prod / CloudWatch). Chaque enregistrement porte des clés liées :

```json
{"ts": "...", "level": "INFO", "logger": "ingestion.ga4.extractor",
 "message": "[ingest:ga4] success in 8412 ms",
 "x_run_id": "ingest:ga4:1745632801842", "x_status": "success", "x_duration_ms": 8412}
```

Le JSON est ce qu'attendent les filtres de métriques CloudWatch (`{ $.level = "ERROR" }`).

## 2. Table d'audit

`audit_pipeline_runs` (run_id, pipeline, step, start/end, duration, status,
rows in/out, error, extra JSON), créée paresseusement dans le même fichier
DuckDB que les marts, ce qui permet au tableau de bord d'afficher l'historique
des exécutions sans service supplémentaire. Utilisation depuis n'importe quelle
étape :

```python
from ingestion.observability import pipeline_run

with pipeline_run("ingest", "ga4", source="ga4") as run:
    run.rows_out = extract_and_write(...)
```

En cas d'exception, la ligne est enregistrée avec `status='failed'` et l'erreur,
et l'exception est relancée telle quelle. Exemple de requête :

```sql
SELECT pipeline, step, status, duration_ms, error
FROM audit_pipeline_runs ORDER BY start_ts DESC LIMIT 20;
```

## 3. Métrique + alarme

`emit_metric("rows_ingested", n, tags={"source": "ga4"})` affiche une ligne
JSON. En production, le filtre de métriques CloudWatch transforme les lignes
`level="ERROR"` en la métrique `PipelineErrors` ; l'alarme
`tessera-${env}-pipeline-errors` se déclenche sur `Sum > 3` sur 15 min et publie
sur le topic SNS `tessera-${env}-alerts` (e-mail de l'opérateur).

## 4. Vérifier en local

```bash
TESSERA_LOG_FORMAT=json make pipeline          # journaux JSON sur stdout
duckdb warehouse/tessera.duckdb \
  "SELECT pipeline, step, status, duration_ms FROM audit_pipeline_runs ORDER BY start_ts DESC LIMIT 10;"
```

---

*Retour :* [`../README.md`](../README.md)
