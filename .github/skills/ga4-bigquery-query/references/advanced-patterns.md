# Advanced Analysis Patterns

## 1. Cohort Revenue Analysis (Month-by-Month)

Track how user cohorts (grouped by acquisition month) generate revenue over time:

```sql
WITH user_cohorts AS (
  SELECT
    user_pseudo_id,
    FORMAT_DATE('%Y-%m', DATE(TIMESTAMP_MICROS(user_first_touch_timestamp))) AS cohort_month
  FROM `{project}.{dataset}.events_*`
  WHERE _table_suffix BETWEEN '{start}' AND '{end}'
  GROUP BY user_pseudo_id, cohort_month
),
purchases AS (
  SELECT
    user_pseudo_id,
    FORMAT_DATE('%Y-%m', PARSE_DATE('%Y%m%d', event_date)) AS purchase_month,
    SUM(ecommerce.purchase_revenue) AS revenue
  FROM `{project}.{dataset}.events_*`
  WHERE event_name = 'purchase'
    AND _table_suffix BETWEEN '{start}' AND '{end}'
  GROUP BY user_pseudo_id, purchase_month
)
SELECT
  c.cohort_month,
  DATE_DIFF(
    PARSE_DATE('%Y-%m', p.purchase_month),
    PARSE_DATE('%Y-%m', c.cohort_month),
    MONTH
  ) AS months_after_acquisition,
  COUNT(DISTINCT c.user_pseudo_id) AS users,
  SUM(p.revenue) AS cohort_revenue,
  SAFE_DIVIDE(SUM(p.revenue), COUNT(DISTINCT c.user_pseudo_id)) AS revenue_per_user
FROM user_cohorts c
JOIN purchases p ON c.user_pseudo_id = p.user_pseudo_id
GROUP BY 1, 2
ORDER BY 1, 2
```

## 2. User Journey / Path Analysis

Map page-by-page journeys within sessions:

```sql
WITH page_sequence AS (
  SELECT
    CONCAT(user_pseudo_id, CAST(
      (SELECT value.int_value FROM UNNEST(event_params) WHERE key = 'ga_session_id') AS STRING)
    ) AS session_key,
    (SELECT value.string_value FROM UNNEST(event_params) WHERE key = 'page_location') AS page,
    event_timestamp,
    ROW_NUMBER() OVER (
      PARTITION BY user_pseudo_id,
        (SELECT value.int_value FROM UNNEST(event_params) WHERE key = 'ga_session_id')
      ORDER BY event_timestamp ASC
    ) AS step_number
  FROM `{project}.{dataset}.events_*`
  WHERE event_name = 'page_view'
    AND _table_suffix BETWEEN '{start}' AND '{end}'
),
journeys AS (
  SELECT
    session_key,
    STRING_AGG(
      REGEXP_EXTRACT(page, r'^https?://[^/]+(\/[^?#]*)'),  -- path only
      ' > ' ORDER BY step_number
    ) AS full_path,
    MAX(step_number) AS path_length
  FROM page_sequence
  GROUP BY session_key
)
SELECT
  full_path,
  COUNT(*) AS sessions,
  path_length
FROM journeys
GROUP BY full_path, path_length
ORDER BY sessions DESC
LIMIT 100
```

### Conversion paths only (sessions ending in purchase):
```sql
-- Add a filter to only include sessions that had a purchase event
WITH converting_sessions AS (
  SELECT DISTINCT
    CONCAT(user_pseudo_id, CAST(
      (SELECT value.int_value FROM UNNEST(event_params) WHERE key = 'ga_session_id') AS STRING)
    ) AS session_key
  FROM `{project}.{dataset}.events_*`
  WHERE event_name = 'purchase'
    AND _table_suffix BETWEEN '{start}' AND '{end}'
)
-- Then INNER JOIN with page_sequence on session_key
```

## 3. Checkout Abandonment & Recovery Time

Identify abandoned checkouts and measure how long until users return to purchase:

```sql
WITH session_flags AS (
  SELECT
    user_pseudo_id,
    CONCAT(user_pseudo_id, CAST(
      (SELECT value.int_value FROM UNNEST(event_params) WHERE key = 'ga_session_id') AS STRING)
    ) AS session_key,
    PARSE_DATE('%Y%m%d', event_date) AS event_date,
    MAX(CASE WHEN event_name = 'begin_checkout' THEN 1 ELSE 0 END) AS has_checkout,
    MAX(CASE WHEN event_name = 'purchase' THEN 1 ELSE 0 END) AS has_purchase
  FROM `{project}.{dataset}.events_*`
  WHERE _table_suffix BETWEEN '{start}' AND '{end}'
  GROUP BY user_pseudo_id, session_key, event_date
),
abandoners AS (
  SELECT user_pseudo_id, MIN(event_date) AS abandon_date
  FROM session_flags
  WHERE has_checkout = 1 AND has_purchase = 0
  GROUP BY user_pseudo_id
),
recoverers AS (
  SELECT user_pseudo_id, MIN(event_date) AS purchase_date
  FROM session_flags
  WHERE has_purchase = 1
  GROUP BY user_pseudo_id
)
SELECT
  DATE_DIFF(r.purchase_date, a.abandon_date, DAY) AS days_to_recover,
  COUNT(DISTINCT a.user_pseudo_id) AS users
FROM abandoners a
JOIN recoverers r
  ON a.user_pseudo_id = r.user_pseudo_id
  AND r.purchase_date > a.abandon_date
GROUP BY 1
ORDER BY 1
```

## 4. Days to Key Action by Traffic Source

Average time from first touch to purchase, segmented by acquisition source:

```sql
WITH first_touch AS (
  SELECT
    user_pseudo_id,
    traffic_source.source,
    traffic_source.medium,
    DATE(TIMESTAMP_MICROS(user_first_touch_timestamp)) AS first_visit_date
  FROM `{project}.{dataset}.events_*`
  WHERE _table_suffix BETWEEN '{start}' AND '{end}'
  GROUP BY user_pseudo_id, source, medium, first_visit_date
),
first_purchase AS (
  SELECT
    user_pseudo_id,
    MIN(PARSE_DATE('%Y%m%d', event_date)) AS first_purchase_date
  FROM `{project}.{dataset}.events_*`
  WHERE event_name = 'purchase'
    AND _table_suffix BETWEEN '{start}' AND '{end}'
  GROUP BY user_pseudo_id
)
SELECT
  ft.source,
  ft.medium,
  COUNT(DISTINCT ft.user_pseudo_id) AS converting_users,
  AVG(DATE_DIFF(fp.first_purchase_date, ft.first_visit_date, DAY)) AS avg_days_to_purchase,
  APPROX_QUANTILES(DATE_DIFF(fp.first_purchase_date, ft.first_visit_date, DAY), 100)[OFFSET(50)] AS median_days
FROM first_touch ft
JOIN first_purchase fp ON ft.user_pseudo_id = fp.user_pseudo_id
GROUP BY 1, 2
HAVING COUNT(DISTINCT ft.user_pseudo_id) >= 10
ORDER BY converting_users DESC
```

## 5. Multi-Item Purchase Patterns

Identify products that frequently appear as companions in multi-item checkouts:

```sql
WITH multi_item_purchases AS (
  SELECT
    ecommerce.transaction_id,
    ARRAY_AGG(DISTINCT items.item_name) AS item_list,
    COUNT(DISTINCT items.item_name) AS unique_items
  FROM `{project}.{dataset}.events_*`,
    UNNEST(items) AS items
  WHERE event_name = 'purchase'
    AND _table_suffix BETWEEN '{start}' AND '{end}'
    AND ecommerce.transaction_id IS NOT NULL
  GROUP BY transaction_id
  HAVING unique_items >= 2
),
item_frequency AS (
  SELECT
    item,
    COUNT(DISTINCT transaction_id) AS multi_item_appearances,
    COUNT(DISTINCT transaction_id) / (SELECT COUNT(DISTINCT transaction_id) FROM multi_item_purchases) AS pct_of_multi_item_orders
  FROM multi_item_purchases, UNNEST(item_list) AS item
  GROUP BY item
)
SELECT * FROM item_frequency
ORDER BY multi_item_appearances DESC
```

## 6. First-Viewed Product Analysis

Which first-viewed products lead to the highest customer lifetime value?

```sql
WITH first_product_viewed AS (
  SELECT
    user_pseudo_id,
    ARRAY_AGG(items.item_name IGNORE NULLS ORDER BY event_timestamp ASC)[SAFE_OFFSET(0)] AS first_product
  FROM `{project}.{dataset}.events_*`,
    UNNEST(items) AS items
  WHERE event_name = 'view_item'
    AND _table_suffix BETWEEN '{start}' AND '{end}'
  GROUP BY user_pseudo_id
),
user_revenue AS (
  SELECT
    user_pseudo_id,
    SUM(ecommerce.purchase_revenue) AS total_revenue,
    COUNT(DISTINCT ecommerce.transaction_id) AS transactions
  FROM `{project}.{dataset}.events_*`
  WHERE event_name = 'purchase'
    AND _table_suffix BETWEEN '{start}' AND '{end}'
  GROUP BY user_pseudo_id
)
SELECT
  fpv.first_product,
  COUNT(DISTINCT fpv.user_pseudo_id) AS users_who_first_viewed,
  COUNT(DISTINCT ur.user_pseudo_id) AS users_who_purchased,
  SAFE_DIVIDE(COUNT(DISTINCT ur.user_pseudo_id), COUNT(DISTINCT fpv.user_pseudo_id)) AS conversion_rate,
  AVG(ur.total_revenue) AS avg_ltv
FROM first_product_viewed fpv
LEFT JOIN user_revenue ur ON fpv.user_pseudo_id = ur.user_pseudo_id
GROUP BY 1
HAVING COUNT(DISTINCT fpv.user_pseudo_id) >= 10
ORDER BY conversion_rate DESC
```

## 7. Rolling Retention Analysis

Track what percentage of users return in subsequent weeks after acquisition:

```sql
WITH user_activity AS (
  SELECT
    user_pseudo_id,
    DATE(TIMESTAMP_MICROS(user_first_touch_timestamp)) AS acquisition_date,
    PARSE_DATE('%Y%m%d', event_date) AS activity_date
  FROM `{project}.{dataset}.events_*`
  WHERE _table_suffix BETWEEN '{start}' AND '{end}'
  GROUP BY user_pseudo_id, acquisition_date, activity_date
),
weekly_retention AS (
  SELECT
    acquisition_date,
    DATE_DIFF(activity_date, acquisition_date, WEEK) AS weeks_after,
    COUNT(DISTINCT user_pseudo_id) AS active_users
  FROM user_activity
  GROUP BY 1, 2
),
cohort_sizes AS (
  SELECT acquisition_date, COUNT(DISTINCT user_pseudo_id) AS cohort_size
  FROM user_activity
  WHERE activity_date = acquisition_date
  GROUP BY 1
)
SELECT
  wr.acquisition_date,
  wr.weeks_after,
  wr.active_users,
  cs.cohort_size,
  SAFE_DIVIDE(wr.active_users, cs.cohort_size) AS retention_rate
FROM weekly_retention wr
JOIN cohort_sizes cs ON wr.acquisition_date = cs.acquisition_date
WHERE wr.weeks_after BETWEEN 0 AND 12
ORDER BY 1, 2
```
