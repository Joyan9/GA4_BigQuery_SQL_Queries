# Unnesting Event Parameters, User Properties & Items

## The Core Challenge
GA4 stores event_params, user_properties, and items as REPEATED RECORD fields (arrays of structs). You must UNNEST or use correlated subqueries to access individual values.

## Pattern 1: Correlated Subquery (DEFAULT)
Use this whenever extracting specific parameter values alongside other event fields.

```sql
SELECT
  event_date,
  event_name,
  user_pseudo_id,
  (SELECT value.string_value FROM UNNEST(event_params) WHERE key = 'page_location') AS page_location,
  (SELECT value.int_value FROM UNNEST(event_params) WHERE key = 'ga_session_id') AS session_id,
  (SELECT value.int_value FROM UNNEST(event_params) WHERE key = 'ga_session_number') AS session_number,
  (SELECT value.string_value FROM UNNEST(event_params) WHERE key = 'session_engaged') AS session_engaged,
  (SELECT value.int_value FROM UNNEST(event_params) WHERE key = 'engagement_time_msec') AS engagement_time_msec
FROM `{project}.{dataset}.events_*`
WHERE _table_suffix BETWEEN '{start}' AND '{end}'
```

**Why preferred**: Does not multiply rows. Each subquery returns exactly one value per event row.

## Pattern 2: Cross Join UNNEST (for items)
Use when you need to flatten items into individual rows.

```sql
SELECT
  event_date,
  ecommerce.transaction_id,
  items.item_id,
  items.item_name,
  items.item_brand,
  items.item_category,
  items.price,
  items.quantity,
  items.item_revenue
FROM `{project}.{dataset}.events_*`,
  UNNEST(items) AS items
WHERE event_name = 'purchase'
  AND _table_suffix BETWEEN '{start}' AND '{end}'
```

**Warning**: This multiplies rows — one row per item per event. Aggregating event-level fields (like ecommerce.purchase_revenue) after UNNEST will produce wrong totals unless handled carefully.

## Pattern 3: UNNEST in FROM (for exploration)
Use when discovering what parameters exist or analyzing parameter distributions.

```sql
SELECT
  ep.key,
  COUNT(*) AS occurrences,
  COUNTIF(ep.value.string_value IS NOT NULL) AS has_string,
  COUNTIF(ep.value.int_value IS NOT NULL) AS has_int,
  COUNTIF(ep.value.float_value IS NOT NULL) AS has_float
FROM `{project}.{dataset}.events_*`,
  UNNEST(event_params) AS ep
WHERE _table_suffix = FORMAT_DATE('%Y%m%d', CURRENT_DATE() - 1)
  AND event_name = 'page_view'
GROUP BY 1
ORDER BY 2 DESC
```

## Value Type Reference

Only ONE value type is populated per parameter key:

| Parameter key | Value type | Typical values |
|---------------|-----------|----------------|
| ga_session_id | int_value | Random integer |
| ga_session_number | int_value | 1, 2, 3... |
| page_location | string_value | Full URL |
| page_title | string_value | HTML title |
| page_referrer | string_value | Referrer URL |
| source | string_value | google, facebook, (direct) |
| medium | string_value | organic, cpc, referral, (none) |
| campaign | string_value | Campaign name |
| term | string_value | Search term |
| content | string_value | Ad content |
| session_engaged | string_value | '1' if engaged |
| engagement_time_msec | int_value | Milliseconds |
| entrances | int_value | 1 for landing page hit |
| percent_scrolled | int_value | 90 (for scroll event) |
| link_url | string_value | Clicked outbound URL |
| link_domain | string_value | Clicked outbound domain |
| file_name | string_value | Downloaded file name |
| video_title | string_value | YouTube video title |
| video_percent | int_value | Video progress percentage |
| search_term | string_value | Site search query |

## User Properties

Same nested structure as event_params but accessed via `user_properties`:

```sql
(SELECT value.string_value FROM UNNEST(user_properties) WHERE key = 'membership_level') AS membership
```

### CRITICAL: User Properties Don't Persist
In export data, user properties are often only populated on the event where they were set or updated. To apply a user property across all events for that user, propagate with a window function:

```sql
WITH base AS (
  SELECT
    *,
    (SELECT value.string_value FROM UNNEST(user_properties) WHERE key = 'membership_level') AS raw_membership
  FROM `{project}.{dataset}.events_*`
  WHERE _table_suffix BETWEEN '{start}' AND '{end}'
)
SELECT
  *,
  MAX(raw_membership) OVER (PARTITION BY user_pseudo_id) AS membership_level
FROM base
```

Alternative for time-varying properties (use last known value):
```sql
LAST_VALUE(raw_membership IGNORE NULLS) OVER (
  PARTITION BY user_pseudo_id ORDER BY event_timestamp
  ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
) AS membership_level
```

## Item Parameters (from 2023-10-25)
Items have their own nested params array:

```sql
SELECT
  items.item_name,
  (SELECT value.string_value FROM UNNEST(items.item_params) WHERE key = 'color') AS item_color
FROM `{project}.{dataset}.events_*`,
  UNNEST(items) AS items
WHERE event_name = 'purchase'
  AND _table_suffix BETWEEN '{start}' AND '{end}'
```

## Common Mistakes

1. **Wrong value type**: Using `value.string_value` for ga_session_id (it's int_value) → returns NULL
2. **Forgetting UNNEST**: `event_params.key` without UNNEST → SQL error
3. **Double-counting with items UNNEST**: Summing event-level fields after UNNEST items multiplies the total
4. **Assuming user_properties persist on every event**: They often do not — propagate manually when analyzing across events
