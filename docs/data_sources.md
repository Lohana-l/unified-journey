# Sources de données

Quatre sources marketing, un principe : **des API réelles quand c'est faisable,
des données synthétiques réalistes sinon**, et de la transparence sur ce qui
relève de l'une ou de l'autre.

---

## 1. Modes par source

| Source   | Mode par défaut | Mode API réelle (opt-in) |
| -------- | --------------- | ------------------------ |
| GA4      | propriété de démonstration Google Merchandise Store (publique, gratuite) | votre propriété GA4 via un compte de service, GA4 Data API v1 |
| Meta Ads | événements synthétiques au schéma exact du Pixel / de la Conversion API | Meta Graph API v21 avec un jeton Business |
| Shopify  | jeu de données d'exemple fourni au schéma de l'Admin API | boutique de développement Shopify via l'Admin API (gratuite, programme Partners) |
| Email    | événements synthétiques au schéma de l'API Mailchimp | compte gratuit Mailchimp via clé API |

Les modes se basculent par des variables d'environnement documentées dans
`.env.example`. Le mode par défaut exécute le pipeline complet hors ligne (CI,
proxy, sans identifiants) via `seed/generate_sample_data.py`.

## 2. Ce que chaque source apporte

- **GA4** : `page_view`, `session_start`, événements e-commerce (`view_item`,
  `add_to_cart`, `begin_checkout`, `purchase`), dimensions UTM ;
  identifiants `ga_client_id`, `ga_user_id`.
- **Meta Ads** : événements Pixel/CAPI (`PageView` à `Purchase`) avec `email`/`phone`
  hachés, `fbp`, `fbc`, données de valeur et de contenu.
- **Shopify** : `customers`, `orders` (+ lignes de commande), `products` ;
  identifiants `customer_id`, `email`.
- **Email** : événements subscribe / send / open / click / unsubscribe ;
  identifiants `subscriber_id`, `email`.

Chaque champ bronze correspond à un champ réel du schéma de l'API en amont.

## 3. Partitionnement

```
s3://tessera-bronze/<source>/<table>/dt=YYYY-MM-DD/part-0000.parquet
```

Une partition par jour d'ingestion : des chargements incrémentaux sans
réécriture de l'historique, l'élagage de partitions dans DuckDB, et la
suppression au niveau partition pour la rétention RGPD. Le volume varie avec
`PIPELINE_LOOKBACK_DAYS` dans `.env`.

## 4. Évolution de schéma

Silver applique un `CAST` explicite par colonne. Une nouvelle colonne apparaissant
en amont ne casse jamais le pipeline : elle n'atteint tout simplement pas silver
tant qu'un modèle de staging ne la référence pas.

---

*Suite :* [`governance_gdpr.md`](governance_gdpr.md)
