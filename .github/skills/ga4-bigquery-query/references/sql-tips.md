# BigQuery SQL Tips for GA4 Analysis

## SAFE Functions

### SAFE_DIVIDE — Prevent division by zero
```sql
-- Returns NULL instead of error when divisor is 0
SAFE_DIVIDE(revenue, sessions) AS revenue_per_session
SAFE_DIVIDE(purchases, users) AS conversion_rate
```

### SAFE. prefix — Error-tolerant parsing
```sql
-- Returns NULL instead of error on invalid input
SAFE.PARSE_DATE('%Y%m%d', event_date)
SAFE_CAST(string_value AS INT64)
SAFE.PARSE_TIMESTAMP('%Y%m%d%H%M%S', some_field)
```

## MAX_BY — Get value from row with max of another column

Replaces common ROW_NUMBER() + WHERE rn = 1 pattern:

```sql
-- Old way (verbose):
WITH ranked AS (
  SELECT *, ROW_NUMBER() OVER (PARTITION BY user_pseudo_id ORDER BY event_timestamp DESC) AS rn
  FROM events
)
SELECT * FROM ranked WHERE rn = 1

-- New way (concise):
SELECT
  user_pseudo_id,
  MAX_BY(page_location, event_timestamp) AS last_page
FROM events
GROUP BY user_pseudo_id
```

## QUALIFY — Filter on window function results

Eliminates need for a CTE/subquery just to filter on ROW_NUMBER():

```sql
-- Old way:
WITH ranked AS (
  SELECT *, ROW_NUMBER() OVER (PARTITION BY user ORDER BY ts DESC) AS rn FROM t
)
SELECT * FROM ranked WHERE rn = 1

-- With QUALIFY:
SELECT *
FROM t
QUALIFY ROW_NUMBER() OVER (PARTITION BY user ORDER BY ts DESC) = 1
```

Works with any window function:
```sql
-- Get only users with more than 5 sessions
SELECT user_pseudo_id, session_id
FROM sessions_table
QUALIFY COUNT(*) OVER (PARTITION BY user_pseudo_id) > 5
```

## PIVOT — Reshape rows to columns

```sql
SELECT * FROM (
  SELECT session_key, event_name
  FROM events_table
)
PIVOT (
  COUNT(DISTINCT session_key)
  FOR event_name IN ('view_item', 'add_to_cart', 'begin_checkout', 'purchase')
)
```

**Limitation**: Values in `IN()` must be static literals. Cannot use subqueries or variables.

## Named Windows (WINDOW clause)

Avoid repeating identical window definitions:

```sql
SELECT
  user_pseudo_id,
  event_timestamp,
  ROW_NUMBER() OVER w AS event_number,
  LAG(event_timestamp) OVER w AS prev_timestamp,
  LEAD(event_timestamp) OVER w AS next_timestamp
FROM events_table
WINDOW w AS (PARTITION BY user_pseudo_id ORDER BY event_timestamp ASC)
```

## ARRAY_AGG — Flexible aggregation

### Get first value in group (ordered)
```sql
ARRAY_AGG(source IGNORE NULLS ORDER BY event_timestamp ASC)[SAFE_OFFSET(0)] AS first_source
```

### Get last value in group
```sql
ARRAY_AGG(source IGNORE NULLS ORDER BY event_timestamp DESC)[SAFE_OFFSET(0)] AS last_source
```

### Collect all values
```sql
ARRAY_AGG(DISTINCT item_name IGNORE NULLS) AS all_items_purchased
```

## STRING_AGG — Concatenate values with separator

```sql
-- Build page path string
STRING_AGG(page_location, ' > ' ORDER BY event_timestamp) AS user_journey

-- Comma-separated list
STRING_AGG(DISTINCT item_name, ', ') AS products_list
```

## REGEXP Functions

### REGEXP_CONTAINS — Test for pattern match
```sql
WHERE REGEXP_CONTAINS(source, 'google|bing|yahoo')
```

### REGEXP_EXTRACT — Pull out matched portion
```sql
-- Extract path from URL
REGEXP_EXTRACT(page_url, r'^https?://[^/]+(\/[^?#]*)') AS page_path

-- Extract domain
REGEXP_EXTRACT(page_url, r'^https?://([^/]+)') AS domain

-- Extract query parameter
REGEXP_EXTRACT(page_url, r'[?&]utm_source=([^&]+)') AS utm_source
```

### REGEXP_REPLACE — Pattern-based replacement
```sql
-- Remove query string
REGEXP_REPLACE(page_url, r'\?.*$', '') AS clean_url

-- Normalize intraday suffix
REGEXP_REPLACE(_table_suffix, 'intraday_', '') AS date_suffix
```

## Date & Timestamp Functions

```sql
-- Current date/time
CURRENT_DATE()
CURRENT_TIMESTAMP()

-- Date arithmetic
DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
DATE_ADD(some_date, INTERVAL 7 DAY)
DATE_DIFF(end_date, start_date, DAY)

-- Timestamp conversion
TIMESTAMP_MICROS(event_timestamp)          -- INT64 → TIMESTAMP
UNIX_MICROS(some_timestamp)                -- TIMESTAMP → INT64
DATE(TIMESTAMP_MICROS(event_timestamp))    -- INT64 → DATE

-- Timezone conversion
TIMESTAMP_MICROS(event_timestamp) AT TIME ZONE 'America/New_York'

-- Formatting
FORMAT_DATE('%Y%m%d', some_date)
FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S', some_timestamp)
PARSE_DATE('%Y%m%d', event_date)
```

## Conditional Aggregation

```sql
-- Count specific events
COUNTIF(event_name = 'purchase') AS purchases
COUNTIF(event_name = 'page_view') AS pageviews

-- Sum with condition
SUM(IF(event_name = 'purchase', ecommerce.purchase_revenue, 0)) AS purchase_revenue

-- Distinct count with condition
COUNT(DISTINCT IF(session_engaged = '1', session_key, NULL)) AS engaged_sessions
```

## APPROX Functions (for large datasets)

```sql
-- Approximate distinct count (much faster on large tables)
APPROX_COUNT_DISTINCT(user_pseudo_id) AS approx_users

-- Approximate percentiles
APPROX_QUANTILES(revenue, 100)[OFFSET(50)] AS median_revenue
APPROX_QUANTILES(session_duration, 4)[OFFSET(3)] AS p75_duration
```

## Useful Patterns for GA4

### Deduplicate events (same event sent twice)
```sql
SELECT * FROM events_table
QUALIFY ROW_NUMBER() OVER (
  PARTITION BY user_pseudo_id, event_name, event_timestamp
  ORDER BY event_timestamp
) = 1
```

### Last non-null value (forward fill)
```sql
LAST_VALUE(source IGNORE NULLS) OVER (
  PARTITION BY user_pseudo_id
  ORDER BY event_timestamp
  ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
) AS last_known_source
```

### Sessionize with custom timeout (30-min gap)
```sql
WITH events_with_gap AS (
  SELECT *,
    CASE WHEN event_timestamp - LAG(event_timestamp) OVER (
      PARTITION BY user_pseudo_id ORDER BY event_timestamp
    ) > 30 * 60 * 1000000  -- 30 min in microseconds
    THEN 1 ELSE 0 END AS new_session_flag
  FROM events_table
)
SELECT *,
  SUM(new_session_flag) OVER (
    PARTITION BY user_pseudo_id ORDER BY event_timestamp
    ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
  ) AS custom_session_id
FROM events_with_gap
```
