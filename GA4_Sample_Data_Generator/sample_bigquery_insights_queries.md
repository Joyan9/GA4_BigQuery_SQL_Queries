# GA4 Generated Dataset: Sample BigQuery Insight Queries

This file contains practical queries for the generated GA4-style dataset.

## Before You Run

- Replace `your-project.your_dataset.ga4_events` with your actual table.
- If you uploaded into daily tables (for example `events_20251001`), use a wildcard source such as:

```sql
FROM `your-project.your_dataset.events_*`
WHERE _TABLE_SUFFIX BETWEEN '20251001' AND '20251231'
```


## 1) Daily traffic and users

```sql
SELECT
  PARSE_DATE('%Y%m%d', event_date) AS date,
  COUNT(*) AS events,
  COUNT(DISTINCT user_pseudo_id) AS users,
  COUNT(DISTINCT CONCAT(
    user_pseudo_id, '-',
    CAST((
      SELECT ep.value.int_value
      FROM UNNEST(event_params) ep
      WHERE ep.key = 'ga_session_id'
      LIMIT 1
    ) AS STRING)
  )) AS sessions
FROM `your-project.your_dataset.events_*`
WHERE _TABLE_SUFFIX BETWEEN '20251001' AND '20251231'
GROUP BY date
ORDER BY date;
```

## 2) Top landing pages by sessions

```sql
WITH entrances AS (
  SELECT
    PARSE_DATE('%Y%m%d', event_date) AS date,
    user_pseudo_id,
    (
      SELECT ep.value.int_value
      FROM UNNEST(event_params) ep
      WHERE ep.key = 'ga_session_id'
      LIMIT 1
    ) AS ga_session_id,
    (
      SELECT ep.value.string_value
      FROM UNNEST(event_params) ep
      WHERE ep.key = 'page_location'
      LIMIT 1
    ) AS page_location
  FROM `your-project.your_dataset.events_*`
    WHERE _TABLE_SUFFIX BETWEEN '20251001' AND '20251231'
    AND event_name = 'page_view'
    AND EXISTS (
      SELECT 1
      FROM UNNEST(event_params) ep
      WHERE ep.key = 'entrances' AND ep.value.int_value = 1
    )
)
SELECT
  page_location,
  COUNT(DISTINCT CONCAT(user_pseudo_id, '-', CAST(ga_session_id AS STRING))) AS landing_sessions
FROM entrances
GROUP BY page_location
ORDER BY landing_sessions DESC
LIMIT 20;
```

## 3) Funnel (session-level): view_item -> add_to_cart -> begin_checkout -> purchase

```sql
WITH session_events AS (
  SELECT
    PARSE_DATE('%Y%m%d', event_date) AS date,
    CONCAT(
      user_pseudo_id, '-',
      CAST((
        SELECT ep.value.int_value
        FROM UNNEST(event_params) ep
        WHERE ep.key = 'ga_session_id'
        LIMIT 1
      ) AS STRING)
    ) AS session_key,
    MAX(IF(event_name = 'view_item', 1, 0)) AS has_view_item,
    MAX(IF(event_name = 'add_to_cart', 1, 0)) AS has_add_to_cart,
    MAX(IF(event_name = 'begin_checkout', 1, 0)) AS has_begin_checkout,
    MAX(IF(event_name = 'purchase', 1, 0)) AS has_purchase
  FROM `your-project.your_dataset.events_*`
    WHERE _TABLE_SUFFIX BETWEEN '20251001' AND '20251231'
    GROUP BY date, session_key
)
SELECT
  date,
  COUNT(*) AS sessions,
  SUM(has_view_item) AS view_item_sessions,
  SUM(has_add_to_cart) AS add_to_cart_sessions,
  SUM(has_begin_checkout) AS begin_checkout_sessions,
  SUM(has_purchase) AS purchase_sessions,
  ROUND(SAFE_DIVIDE(SUM(has_add_to_cart), SUM(has_view_item)) * 100, 2) AS view_to_cart_rate_pct,
  ROUND(SAFE_DIVIDE(SUM(has_begin_checkout), SUM(has_add_to_cart)) * 100, 2) AS cart_to_checkout_rate_pct,
  ROUND(SAFE_DIVIDE(SUM(has_purchase), SUM(has_begin_checkout)) * 100, 2) AS checkout_to_purchase_rate_pct
FROM session_events
GROUP BY date
ORDER BY date;
```

## 4) Revenue, orders, and AOV by day

```sql
SELECT
  PARSE_DATE('%Y%m%d', event_date) AS date,
  COUNT(DISTINCT ecommerce.transaction_id) AS orders,
  ROUND(SUM(ecommerce.purchase_revenue), 2) AS revenue_eur,
  ROUND(SAFE_DIVIDE(SUM(ecommerce.purchase_revenue), COUNT(DISTINCT ecommerce.transaction_id)), 2) AS aov_eur
FROM `your-project.your_dataset.events_*`
    WHERE _TABLE_SUFFIX BETWEEN '20251001' AND '20251231' AND event_name = 'purchase'
    GROUP BY date
    ORDER BY date;
```

## 5) Channel performance (sessions, orders, CVR, revenue)

```sql
WITH session_rollup AS (
  SELECT
    CONCAT(
      user_pseudo_id, '-',
      CAST((
        SELECT ep.value.int_value
        FROM UNNEST(event_params) ep
        WHERE ep.key = 'ga_session_id'
        LIMIT 1
      ) AS STRING)
    ) AS session_key,
    COALESCE(session_traffic_source_last_click.manual_campaign.source, '(not set)') AS source,
    COALESCE(session_traffic_source_last_click.manual_campaign.medium, '(not set)') AS medium,
    MAX(IF(event_name = 'purchase', 1, 0)) AS has_purchase,
    MAX(IF(event_name = 'purchase', ecommerce.purchase_revenue, 0)) AS purchase_revenue
  FROM `your-project.your_dataset.events_*`
    WHERE _TABLE_SUFFIX BETWEEN '20251001' AND '20251231'
  GROUP BY session_key, source, medium
)
SELECT
  source,
  medium,
  COUNT(*) AS sessions,
  SUM(has_purchase) AS purchasing_sessions,
  ROUND(SAFE_DIVIDE(SUM(has_purchase), COUNT(*)) * 100, 2) AS session_cvr_pct,
  ROUND(SUM(purchase_revenue), 2) AS revenue_eur
FROM session_rollup
GROUP BY source, medium
ORDER BY revenue_eur DESC;
```

## 6) Top products by item revenue

```sql
SELECT
  i.item_id,
  i.item_name,
  i.item_brand,
  i.item_category,
  SUM(i.quantity) AS units,
  ROUND(SUM(i.item_revenue), 2) AS item_revenue_eur
FROM `your-project.your_dataset.events_*`
UNNEST(items) AS i
WHERE _TABLE_SUFFIX BETWEEN '20251001' AND '20251231',
AND event_name = 'purchase'
GROUP BY i.item_id, i.item_name, i.item_brand, i.item_category
ORDER BY item_revenue_eur DESC
LIMIT 20;
```

## 7) Device conversion rate

```sql
WITH session_rollup AS (
  SELECT
    CONCAT(
      user_pseudo_id, '-',
      CAST((
        SELECT ep.value.int_value
        FROM UNNEST(event_params) ep
        WHERE ep.key = 'ga_session_id'
        LIMIT 1
      ) AS STRING)
    ) AS session_key,
    device.category AS device_category,
    MAX(IF(event_name = 'purchase', 1, 0)) AS has_purchase
  FROM `your-project.your_dataset.events_*`
WHERE _TABLE_SUFFIX BETWEEN '20251001' AND '20251231'
  GROUP BY session_key, device_category
)
SELECT
  device_category,
  COUNT(*) AS sessions,
  SUM(has_purchase) AS purchasing_sessions,
  ROUND(SAFE_DIVIDE(SUM(has_purchase), COUNT(*)) * 100, 2) AS cvr_pct
FROM session_rollup
GROUP BY device_category
ORDER BY sessions DESC;
```

## 8) Experiment variant performance (experience_impression)

```sql
WITH impressions AS (
  SELECT
    CONCAT(
      user_pseudo_id, '-',
      CAST((
        SELECT ep.value.int_value
        FROM UNNEST(event_params) ep
        WHERE ep.key = 'ga_session_id'
        LIMIT 1
      ) AS STRING)
    ) AS session_key,
    (
      SELECT ep.value.string_value
      FROM UNNEST(event_params) ep
      WHERE ep.key = 'exp_variant_string'
      LIMIT 1
    ) AS exp_variant_string
  FROM `your-project.your_dataset.events_*`
    WHERE _TABLE_SUFFIX BETWEEN '20251001' AND '20251231'
    AND event_name = 'experience_impression'
),
purchases AS (
  SELECT DISTINCT
    CONCAT(
      user_pseudo_id, '-',
      CAST((
        SELECT ep.value.int_value
        FROM UNNEST(event_params) ep
        WHERE ep.key = 'ga_session_id'
        LIMIT 1
      ) AS STRING)
    ) AS session_key
  FROM `your-project.your_dataset.events_*`
    WHERE _TABLE_SUFFIX BETWEEN '20251001' AND '20251231'
    AND event_name = 'purchase'
)
SELECT
  exp_variant_string,
  COUNT(DISTINCT i.session_key) AS impression_sessions,
  COUNT(DISTINCT p.session_key) AS purchasing_sessions,
  ROUND(SAFE_DIVIDE(COUNT(DISTINCT p.session_key), COUNT(DISTINCT i.session_key)) * 100, 2) AS cvr_pct
FROM impressions i
LEFT JOIN purchases p
  ON i.session_key = p.session_key
WHERE exp_variant_string IS NOT NULL
GROUP BY exp_variant_string
ORDER BY impression_sessions DESC;
```

## 9) PII leakage check in URL/referrer (Anomaly A)

```sql
SELECT
  PARSE_DATE('%Y%m%d', event_date) AS date,
  COUNT(*) AS impacted_events
FROM `your-project.your_dataset.events_*`
WHERE _TABLE_SUFFIX BETWEEN '20251001' AND '20251231'
AND EXISTS (
  SELECT 1
  FROM UNNEST(event_params) ep
  WHERE ep.key IN ('page_location', 'page_referrer')
    AND REGEXP_CONTAINS(
      LOWER(COALESCE(ep.value.string_value, '')),
      r'(email=|user_email=|customer_email=|phone=|tel=|mobile=|name=|@)'
    )
)
GROUP BY date
ORDER BY date;
```

## 10) Cross-domain tracking failure indicator (Anomaly B)

```sql
WITH session_flags AS (
  SELECT
    PARSE_DATE('%Y%m%d', event_date) AS date,
    CONCAT(
      user_pseudo_id, '-',
      CAST((
        SELECT ep.value.int_value
        FROM UNNEST(event_params) ep
        WHERE ep.key = 'ga_session_id'
        LIMIT 1
      ) AS STRING)
    ) AS session_key,
    MAX(IF(
      EXISTS (
        SELECT 1
        FROM UNNEST(event_params) ep
        WHERE ep.key = 'page_referrer'
          AND ep.value.string_value LIKE '%pay.stripe.com%'
      ), 1, 0
    )) AS has_payment_referrer,
    MAX(IF(event_name = 'purchase', 1, 0)) AS has_purchase
  FROM `your-project.your_dataset.events_*`
    WHERE _TABLE_SUFFIX BETWEEN '20251001' AND '20251231'
  GROUP BY date, session_key
)
SELECT
  date,
  COUNTIF(has_payment_referrer = 1) AS payment_referrer_sessions,
  COUNTIF(has_payment_referrer = 1 AND has_purchase = 0) AS payment_referrer_no_purchase,
  ROUND(
    SAFE_DIVIDE(
      COUNTIF(has_payment_referrer = 1 AND has_purchase = 0),
      COUNTIF(has_payment_referrer = 1)
    ) * 100,
    2
  ) AS dropoff_pct
FROM session_flags
GROUP BY date
ORDER BY date;
```

## 11) Sessions missing session_start (Anomaly C)

```sql
WITH session_flags AS (
  SELECT
    PARSE_DATE('%Y%m%d', event_date) AS date,
    CONCAT(
      user_pseudo_id, '-',
      CAST((
        SELECT ep.value.int_value
        FROM UNNEST(event_params) ep
        WHERE ep.key = 'ga_session_id'
        LIMIT 1
      ) AS STRING)
    ) AS session_key,
    MAX(IF(event_name = 'session_start', 1, 0)) AS has_session_start,
    MAX(IF(event_name = 'page_view', 1, 0)) AS has_page_view
  FROM `your-project.your_dataset.events_*`
    WHERE _TABLE_SUFFIX BETWEEN '20251001' AND '20251231'
  GROUP BY date, session_key
)
SELECT
  date,
  COUNT(*) AS sessions,
  COUNTIF(has_page_view = 1 AND has_session_start = 0) AS missing_session_start_sessions,
  ROUND(SAFE_DIVIDE(COUNTIF(has_page_view = 1 AND has_session_start = 0), COUNT(*)) * 100, 2) AS missing_rate_pct
FROM session_flags
GROUP BY date
ORDER BY date;
```

## 12) Missing attribution trend (Anomaly D)

```sql
WITH session_attr AS (
  SELECT
    PARSE_DATE('%Y%m%d', event_date) AS date,
    CONCAT(
      user_pseudo_id, '-',
      CAST((
        SELECT ep.value.int_value
        FROM UNNEST(event_params) ep
        WHERE ep.key = 'ga_session_id'
        LIMIT 1
      ) AS STRING)
    ) AS session_key,
    MAX(IF(collected_traffic_source IS NOT NULL, 1, 0)) AS has_collected_ts,
    MAX(IF(session_traffic_source_last_click IS NOT NULL, 1, 0)) AS has_last_click
  FROM `your-project.your_dataset.events_*`
    WHERE _TABLE_SUFFIX BETWEEN '20251001' AND '20251231'
  GROUP BY date, session_key
)
SELECT
  date,
  COUNT(*) AS sessions,
  COUNTIF(has_collected_ts = 0 AND has_last_click = 0) AS unattributed_sessions,
  ROUND(SAFE_DIVIDE(COUNTIF(has_collected_ts = 0 AND has_last_click = 0), COUNT(*)) * 100, 2) AS unattributed_rate_pct
FROM session_attr
GROUP BY date
ORDER BY date;
```

## 13) Session-timeout style anomalies (Anomaly E)

Definition in generator logic:
- `page_view` exists
- `session_start` missing
- no attribution (`collected_traffic_source` and `session_traffic_source_last_click` both null)

```sql
WITH session_flags AS (
  SELECT
    PARSE_DATE('%Y%m%d', event_date) AS date,
    CONCAT(
      user_pseudo_id, '-',
      CAST((
        SELECT ep.value.int_value
        FROM UNNEST(event_params) ep
        WHERE ep.key = 'ga_session_id'
        LIMIT 1
      ) AS STRING)
    ) AS session_key,
    MAX(IF(event_name = 'session_start', 1, 0)) AS has_session_start,
    MAX(IF(event_name = 'page_view', 1, 0)) AS has_page_view,
    MAX(IF(collected_traffic_source IS NOT NULL, 1, 0)) AS has_collected_ts,
    MAX(IF(session_traffic_source_last_click IS NOT NULL, 1, 0)) AS has_last_click
  FROM `your-project.your_dataset.events_*`
    WHERE _TABLE_SUFFIX BETWEEN '20251001' AND '20251231'
  GROUP BY date, session_key
)
SELECT
  date,
  COUNTIF(
    has_page_view = 1
    AND has_session_start = 0
    AND has_collected_ts = 0
    AND has_last_click = 0
  ) AS timeout_like_sessions
FROM session_flags
GROUP BY date
ORDER BY date;
```

