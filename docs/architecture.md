# Architecture

Lakehouse en couches, cartographie des composants et la portabilité AWS / GCP.

<div align="center">
  <img src="img/architecture.en.svg" alt="Tessera CDP architecture overview" width="900">
</div>

---

## 1. Lakehouse médaillon

| Couche | Chemin | Format | Contenu | Règle |
| ------ | ------ | ------ | ------- | ----- |
| bronze | `s3://tessera-bronze/<source>/dt=YYYY-MM-DD/` | Parquet | exactement ce que l'API a retourné, doublons inclus | ajout seul, jamais modifié : auditable, rejouable |
| silver | `s3://tessera-silver/<model>/` | Parquet | modèles de préparation typés et nettoyés, un fichier Parquet chacun | reconstruit à chaque exécution dbt |
| gold   | `s3://tessera-gold/<mart>/` | Parquet | schéma en étoile : `dim_users`, `dim_channels`, `dim_dates` + `fct_touchpoints`, `fct_sessions`, `fct_conversions`, `fct_funnel_steps` | conservé aussi sous forme de tables DuckDB, lues par Streamlit |

dbt gère bronze vers silver vers gold. Les contrôles Soda Core s'exécutent entre silver et gold.

## 2. Services (Docker Compose)

| Service           | Rôle                             | Port       |
| ----------------- | -------------------------------- | ---------- |
| `minio`           | API S3 + console d'administration | 9000, 9001 |
| `minio-mc`        | amorçage ponctuel des buckets    | n/a        |
| `kestra`          | interface d'orchestration + exécution | 8080  |
| `kestra-postgres` | stockage des métadonnées Kestra (interne) | n/a |
| `streamlit`       | tableau de bord                  | 8501       |

DuckDB s'exécute en processus (sans serveur) ; l'entrepôt est un fichier unique
`warehouse/tessera.duckdb`, monté (bind-mount) sur l'hôte.

## 3. Correspondance cloud

| Composant | AWS | GCP |
| --------- | --- | --- |
| MinIO | S3 | Cloud Storage |
| Parquet (stockage) | S3 + Glue / Iceberg | GCS + BigLake |
| DuckDB | Athena / Redshift Serverless | BigQuery |
| dbt-duckdb | dbt-athena | dbt-bigquery |
| Kestra | MWAA | Cloud Composer |
| Soda Core | Soda Cloud | Soda Cloud |
| Streamlit | App Runner / ECS Fargate | Cloud Run |

Le portage = remplacer le point d'accès de stockage, l'adaptateur dbt et le
runtime de l'orchestrateur ; le Python et le SQL restent inchangés. Environ un
sprint pour un ingénieur.

## 4. Choix d'outillage, une ligne chacun

- **MinIO** : impose le protocole S3 partout, de sorte que le même code s'exécute sur du vrai S3.
- **Parquet** : format colonnaire ouvert lu par tous les moteurs (Athena, Snowflake, BigQuery, DuckDB) ; la disposition partitionnée par date fait des suppressions de rétention une opération de stockage objet peu coûteuse.
- **DuckDB** : colonnaire, en processus, dialecte SQL proche de Snowflake/BigQuery.
- **Kestra** : DAG natifs en YAML, mêmes concepts qu'Airflow avec moins de code répétitif.
- **dbt-duckdb** : seul l'adaptateur change d'un entrepôt à l'autre.
- **Soda Core** : contrôles définis en YAML d'abord, appelés comme une étape shell depuis Kestra.
- **Streamlit** : le moyen le plus rapide, natif en Python, de livrer l'interface de supervision.

## 5. Séquence d'une exécution de pipeline

1. Kestra `01_ingest_all.yaml` : chaque extracteur de source interroge son API (ou
   les données de repli fournies) et écrit du Parquet dans le bucket bronze.
2. Kestra `02_transform_dbt.yaml` : `dbt seed` puis `dbt run`
   (staging, intermediate, marts), puis `dbt test`.
3. Kestra `03_quality_checks.yaml` : `soda scan` sur les marts gold.
4. Streamlit lit gold via DuckDB, avec mise en cache par `@st.cache_data`.

De bout en bout sur les données d'exemple : **~90 secondes** sur un ordinateur portable.

## 6. Passage à l'échelle

Les ajouts en bronze se parallélisent trivialement ; le Parquet partitionné par
date offre un élagage de partitions peu coûteux ; DuckDB traite ~10 M
d'événements sur un ordinateur portable de 16 Go. Au-delà, le même projet dbt
s'exécute sur Athena / Snowflake / BigQuery : même dépôt, même SQL, on remplace
l'adaptateur + le stockage.

---

*Suite :* [`identity_resolution.md`](identity_resolution.md)
