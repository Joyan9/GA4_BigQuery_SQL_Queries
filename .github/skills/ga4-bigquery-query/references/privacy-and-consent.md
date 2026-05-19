# Privacy, Consent Mode & Data Quality Impact

## Consent Mode Overview

GA4 respects user consent choices through `privacy_info` fields. This affects what data is available in BigQuery.

## privacy_info Fields

```sql
privacy_info.analytics_storage    -- 'Yes' or 'No'
privacy_info.ads_storage           -- 'Yes' or 'No'
privacy_info.uses_transient_token  -- 'Yes' or 'No'
```

## Two Consent Mode Implementations

### Basic Consent Mode
- Events only fire when `analytics_storage = 'Yes'`
- Clean data: all events have user_pseudo_id and session data
- **Trade-off**: No data for non-consented users (potential bias, especially in EU markets)

### Advanced Consent Mode
- Events fire for ALL users (consented and non-consented)
- Non-consented events (`analytics_storage = 'No'`) are "cookieless pings"
- These events:
  - LACK `user_pseudo_id` (or have a transient/meaningless value)
  - LACK `ga_session_id`
  - Each page view triggers a new `session_start` (massively inflates session counts)
  - Cannot be joined to form user journeys

## Checking Your Consent Mode Implementation

```sql
SELECT
  privacy_info.analytics_storage,
  privacy_info.ads_storage,
  COUNT(*) AS total_events,
  COUNT(DISTINCT user_pseudo_id) AS distinct_users,
  COUNT(DISTINCT CONCAT(user_pseudo_id, CAST(
    (SELECT value.int_value FROM UNNEST(event_params) WHERE key = 'ga_session_id') AS STRING))
  ) AS distinct_sessions,
  COUNTIF(event_name = 'session_start') AS session_starts,
  COUNTIF(event_name = 'page_view') AS page_views
FROM `{project}.{dataset}.events_YYYYMMDD`
GROUP BY 1, 2
ORDER BY 1, 2
```

**Interpretation**:
- If you see rows with `analytics_storage = 'No'` → Advanced consent mode is active
- Compare session_starts to distinct_sessions to see inflation
- Compare user counts across consent states to understand bias

## Strategy: Filter for Clean Data

When doing user/session-level analysis, filter to consented data only:

```sql
WHERE privacy_info.analytics_storage = 'Yes'
```

**Trade-off**: Introduces consent bias (over-represents users who accept cookies — typically older, less privacy-conscious). Be aware of this limitation.

## Strategy: Use Event-Level Metrics Only

For non-consented data, you can still analyze:
- Event counts and trends (total page_views, purchases)
- Event-level dimensions (page_location, event_name distribution)
- **Cannot analyze**: User journeys, sessions, retention, attribution

```sql
-- Event-level trend (works regardless of consent)
SELECT
  event_date,
  event_name,
  COUNT(*) AS event_count
FROM `{project}.{dataset}.events_*`
WHERE _table_suffix BETWEEN '{start}' AND '{end}'
GROUP BY 1, 2
```

## GA4 UI vs BigQuery: Consent Handling Differences

| Aspect | GA4 UI | BigQuery |
|--------|--------|----------|
| Behavioral modeling | Applied (fills gaps for non-consented) | NOT applied — raw data only |
| Non-consented events | Modeled and included in reports | Present as-is (if advanced mode) |
| User counts | May include modeled users | Only users with actual data |

This means GA4 UI reports will typically show HIGHER numbers than equivalent BigQuery queries when consent mode is active.

## Consent-Aware Query Template

```sql
WITH consented_events AS (
  SELECT *
  FROM `{project}.{dataset}.events_*`
  WHERE _table_suffix BETWEEN '{start}' AND '{end}'
    AND privacy_info.analytics_storage = 'Yes'
)
-- Use consented_events as your base table for clean user/session analysis
SELECT
  COUNT(DISTINCT user_pseudo_id) AS users,
  COUNT(DISTINCT CONCAT(user_pseudo_id, CAST(
    (SELECT value.int_value FROM UNNEST(event_params) WHERE key = 'ga_session_id') AS STRING))
  ) AS sessions
FROM consented_events
```

## Data Completeness Considerations

- **Late-arriving events**: Daily tables update for up to 3 days. Queries on recent data may be incomplete.
- **Intraday gaps**: Streaming tables lack user-attribution for new users.
- **Historical changes**: Google may retroactively update schema or add new fields. Always check field availability dates.

## When to Mention Consent Limitations

Include a consent note in analysis results when:
1. The property has Advanced Consent Mode enabled
2. The percentage of non-consented traffic is significant (>15%)
3. The analysis involves user counts, session counts, or attribution
4. Results differ significantly from GA4 UI reports
