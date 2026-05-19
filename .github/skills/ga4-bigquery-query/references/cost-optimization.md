# Cost Optimization for GA4 BigQuery Queries

## The #1 Rule: Always Use _table_suffix

GA4 stores one table per day. Using `events_*` wildcard without filtering scans ALL historical tables. A property with 3 years of data could scan 1000+ tables unnecessarily.

```sql
-- ALWAYS include this pattern
FROM `{project}.{dataset}.events_*`
WHERE _table_suffix BETWEEN '{start}' AND '{end}'
```

## Date Filtering Patterns (from cheapest to most flexible)

### Static date range
```sql
WHERE _table_suffix BETWEEN '20240701' AND '20240731'
```
Best for: One-time analyses, reports for specific periods.

### Dynamic rolling window
```sql
WHERE _table_suffix BETWEEN
  FORMAT_DATE('%Y%m%d', DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY))
  AND FORMAT_DATE('%Y%m%d', DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY))
```
Best for: Scheduled queries, dashboards. Excludes today (incomplete data).

### Fixed start + dynamic end (RECOMMENDED default)
```sql
WHERE _table_suffix BETWEEN '20240101'
  AND FORMAT_DATE('%Y%m%d', DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY))
```
BigQuery only scans tables that exist — won't error on future dates.

### Including intraday (streaming) data
```sql
WHERE REGEXP_EXTRACT(_table_suffix, r'[0-9]+') BETWEEN
  FORMAT_DATE('%Y%m%d', DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY))
  AND FORMAT_DATE('%Y%m%d', CURRENT_DATE())
```
Use `REGEXP_REPLACE(_table_suffix, 'intraday_', '')` to normalize the date in results.

## Column Selection

BigQuery is columnar — you pay for every column you SELECT regardless of row count.

**Bad** (scans every column):
```sql
SELECT * FROM `{project}.{dataset}.events_*`
```

**Good** (scans only needed columns):
```sql
SELECT event_date, event_name, user_pseudo_id
FROM `{project}.{dataset}.events_*`
```

## Early Filtering with event_name

Filter `event_name` in WHERE clause to dramatically reduce rows processed before any joins or aggregations:

```sql
-- Good: filter early
WHERE _table_suffix BETWEEN '{start}' AND '{end}'
  AND event_name = 'purchase'

-- Also good for multiple events:
WHERE _table_suffix BETWEEN '{start}' AND '{end}'
  AND event_name IN ('purchase', 'begin_checkout', 'add_to_cart')
```

## Avoid Repeated Subqueries

If you need multiple event_params in the same query, extract them once in a CTE:

```sql
-- Efficient: extract once
WITH base AS (
  SELECT
    user_pseudo_id,
    event_name,
    event_timestamp,
    (SELECT value.int_value FROM UNNEST(event_params) WHERE key = 'ga_session_id') AS session_id,
    (SELECT value.string_value FROM UNNEST(event_params) WHERE key = 'page_location') AS page,
    (SELECT value.string_value FROM UNNEST(event_params) WHERE key = 'session_engaged') AS engaged
  FROM `{project}.{dataset}.events_*`
  WHERE _table_suffix BETWEEN '{start}' AND '{end}'
)
SELECT ... FROM base ...
```

## Use SAFE Functions

Prevent query failures on edge cases:

```sql
-- Division by zero → NULL instead of error
SAFE_DIVIDE(revenue, sessions)

-- Parse errors → NULL instead of error
SAFE.PARSE_DATE('%Y%m%d', event_date)

-- Cast errors → NULL
SAFE_CAST(value AS INT64)
```

## Approximate Aggregations for Large Datasets

When exact counts aren't necessary (exploring data, rough estimates):

```sql
-- Approximate distinct count (faster on large datasets)
APPROX_COUNT_DISTINCT(user_pseudo_id) AS approx_users

-- Approximate quantiles
APPROX_QUANTILES(revenue, 100)[OFFSET(50)] AS median_revenue
```

## Materialization Strategy

For frequently-used base queries, consider materializing intermediate results:

1. **Scheduled queries**: Run daily to create a session-level summary table
2. **Clustered tables**: Cluster by event_name, event_date for faster subsequent queries
3. **Partitioned views**: Create views with built-in _table_suffix logic

## Query Validation Before Full Run

Use LIMIT or a single day to validate query logic before running on large date ranges:

```sql
-- Test on one day first
WHERE _table_suffix = FORMAT_DATE('%Y%m%d', DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY))
LIMIT 100
```

Then remove LIMIT and expand date range once logic is confirmed.

## Cost Estimation

Before running expensive queries:
1. BigQuery shows estimated bytes scanned before execution in the query UI, and dry runs can estimate bytes programmatically.
2. Current on-demand query pricing is $6.25 per TiB scanned in `us-central1`, with the first 1 TiB per month free per billing account. Pricing varies by region and can change, so verify against the live BigQuery pricing page.
3. A GA4 property with 1M events per day might store roughly 1-3 GB in a daily export table, but this varies significantly with event parameter density, custom dimensions, user properties, and app vs. web instrumentation.
4. For guardrails on large exploratory queries, use dry runs and `maximum_bytes_billed` where possible.

## Intraday Table Limitations

`events_intraday_*` tables:
- Continuously updated (real-time)
- Deleted when daily table is finalized
- Do NOT have user-attribution data for new users (traffic_source.medium will be NULL)
- Each intraday table replaces itself throughout the day

**Recommendation**: Don't use intraday for attribution or user analysis. Use for real-time event monitoring only.
