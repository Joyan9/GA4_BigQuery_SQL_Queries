# Users & Sessions: Identification and Metric Calculations

## User Concepts

GA4 has THREE user concepts — always clarify which one:

| Concept | Calculation | When to use |
|---------|-------------|-------------|
| Total users | `COUNT(DISTINCT user_pseudo_id)` | Default, all visitors |
| Active users | `COUNT(DISTINCT CASE WHEN is_active_user IS TRUE THEN user_pseudo_id END)` | Matches GA4 UI "Users" metric |
| New users | `COUNT(DISTINCT CASE WHEN ga_session_number = 1 THEN user_pseudo_id END)` | First-time visitors |
| Returning users | `COUNT(DISTINCT CASE WHEN ga_session_number > 1 THEN user_pseudo_id END)` | Repeat visitors |
| Identified users | `COUNT(DISTINCT user_id)` | Users with custom user_id set |

**Default**: Use total users (`user_pseudo_id`) unless engagement-based active users are specifically needed.

## Session Identification

A session is uniquely identified by combining user and session ID:

```sql
CONCAT(user_pseudo_id, CAST(
  (SELECT value.int_value FROM UNNEST(event_params) WHERE key = 'ga_session_id') AS STRING)
) AS session_key
```

**ga_session_id**: Random integer assigned at session start. NOT globally unique — only unique per user.
**ga_session_number**: Sequential count of sessions for a user (1 = first session, 2 = second, etc.)

## Session Metrics

### Total sessions
```sql
COUNT(DISTINCT
  CONCAT(user_pseudo_id, CAST(
    (SELECT value.int_value FROM UNNEST(event_params) WHERE key = 'ga_session_id') AS STRING))
) AS sessions
```

### Engaged sessions
A session is "engaged" if `session_engaged = '1'` (engagement criteria: >10 seconds, 2+ page views, or conversion event).

```sql
COUNT(DISTINCT CASE
  WHEN (SELECT value.string_value FROM UNNEST(event_params) WHERE key = 'session_engaged') = '1'
  THEN CONCAT(user_pseudo_id, CAST(
    (SELECT value.int_value FROM UNNEST(event_params) WHERE key = 'ga_session_id') AS STRING))
END) AS engaged_sessions
```

### Engagement rate
```sql
SAFE_DIVIDE(engaged_sessions, sessions) AS engagement_rate
```

### Bounce rate (GA4 definition: inverse of engagement rate)
```sql
SAFE_DIVIDE(sessions - engaged_sessions, sessions) AS bounce_rate
```

### Average session duration (timestamp-based)
```sql
WITH session_durations AS (
  SELECT
    CONCAT(user_pseudo_id, CAST(
      (SELECT value.int_value FROM UNNEST(event_params) WHERE key = 'ga_session_id') AS STRING)
    ) AS session_key,
    (MAX(event_timestamp) - MIN(event_timestamp)) / 1000000 AS duration_seconds
  FROM `{project}.{dataset}.events_*`
  WHERE _table_suffix BETWEEN '{start}' AND '{end}'
  GROUP BY session_key
)
SELECT AVG(duration_seconds) AS avg_session_duration_seconds
FROM session_durations
WHERE duration_seconds > 0
```

### Average engagement time per session
```sql
WITH session_engagement AS (
  SELECT
    CONCAT(user_pseudo_id, CAST(
      (SELECT value.int_value FROM UNNEST(event_params) WHERE key = 'ga_session_id') AS STRING)
    ) AS session_key,
    MAX((SELECT value.string_value FROM UNNEST(event_params) WHERE key = 'session_engaged')) AS is_engaged,
    SUM((SELECT value.int_value FROM UNNEST(event_params) WHERE key = 'engagement_time_msec')) / 1000 AS engagement_seconds
  FROM `{project}.{dataset}.events_*`
  WHERE _table_suffix BETWEEN '{start}' AND '{end}'
  GROUP BY session_key
)
SELECT SAFE_DIVIDE(
  SUM(engagement_seconds),
  COUNTIF(is_engaged = '1')
) AS avg_engagement_time_seconds
FROM session_engagement
```

### Sessions per user
```sql
SAFE_DIVIDE(
  COUNT(DISTINCT session_key),
  COUNT(DISTINCT user_pseudo_id)
) AS sessions_per_user
```

### Page views per session
```sql
SAFE_DIVIDE(
  COUNTIF(event_name = 'page_view'),
  COUNT(DISTINCT session_key)
) AS views_per_session
```

## User Type Dimension (New vs Returning)
```sql
CASE
  WHEN (SELECT value.int_value FROM UNNEST(event_params) WHERE key = 'ga_session_number') = 1
    THEN 'new visitor'
  WHEN (SELECT value.int_value FROM UNNEST(event_params) WHERE key = 'ga_session_number') > 1
    THEN 'returning visitor'
END AS user_type
```

## Full Session-Level Base Query Template
Commonly used CTE pattern for building session-level reports:

```sql
WITH sessions AS (
  SELECT
    user_pseudo_id,
    CONCAT(user_pseudo_id, CAST(
      (SELECT value.int_value FROM UNNEST(event_params) WHERE key = 'ga_session_id') AS STRING)
    ) AS session_key,
    (SELECT value.int_value FROM UNNEST(event_params) WHERE key = 'ga_session_number') AS session_number,
    MAX((SELECT value.string_value FROM UNNEST(event_params) WHERE key = 'session_engaged')) AS session_engaged,
    MIN(event_timestamp) AS session_start_timestamp,
    MAX(event_timestamp) AS session_end_timestamp,
    COUNTIF(event_name = 'page_view') AS pageviews,
    COUNTIF(event_name = 'purchase') AS purchases,
    SUM(ecommerce.purchase_revenue) AS revenue
  FROM `{project}.{dataset}.events_*`
  WHERE _table_suffix BETWEEN '{start}' AND '{end}'
  GROUP BY user_pseudo_id, session_key, session_number
)
SELECT
  COUNT(DISTINCT session_key) AS sessions,
  COUNT(DISTINCT user_pseudo_id) AS users,
  COUNT(DISTINCT CASE WHEN session_number = 1 THEN user_pseudo_id END) AS new_users,
  COUNTIF(session_engaged = '1') AS engaged_sessions,
  SAFE_DIVIDE(COUNTIF(session_engaged = '1'), COUNT(*)) AS engagement_rate,
  SUM(pageviews) AS total_pageviews,
  SUM(purchases) AS total_purchases,
  SUM(revenue) AS total_revenue
FROM sessions
```
