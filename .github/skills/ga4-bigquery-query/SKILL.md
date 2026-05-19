---
name: ga4-bigquery-query
description: >
  Write SQL queries for Google Analytics 4 (GA4) data exported to BigQuery. 
  Covers schema knowledge, event parameter extraction, session/user metrics, 
  traffic source attribution (all 4 scopes), ecommerce analysis, funnel/path 
  analysis, custom attribution models, and cost optimization patterns.
---

# GA4 BigQuery Query Skill

You are an expert at writing BigQuery SQL to analyze Google Analytics 4 data. GA4 exports event-level data to BigQuery in a specific nested schema. This skill gives you the knowledge to write correct, performant, and cost-efficient queries.

## Required Query Context

Before writing runnable SQL, make sure you have the BigQuery project ID and either:
- the GA4 dataset name, or
- the GA4 property ID

If the user provides a property ID but not a dataset name, infer the dataset as `analytics_<property_id>`.

If the user has not provided enough information to identify the source tables, ask for the missing project ID and dataset or property ID before continuing. Use `{project}` and `{dataset}` only as documentation placeholders or when showing a reusable template.

## Dataset & Table Convention

Use `{project}.{dataset}.events_*` as the base table reference. For runnable queries, replace these placeholders with the user's actual BigQuery project and GA4 dataset. GA4 datasets normally use the format `analytics_<property_id>`.

**Table types:**
- `events_YYYYMMDD` — daily export (complete, use this by default)
- `events_intraday_YYYYMMDD` — streaming, incomplete, lacks user-attribution for new users

## Mandatory: Cost Control with _table_suffix

**ALWAYS** filter with `_table_suffix` when using wildcard tables. Without it, every query scans ALL historical data.

```sql
-- Standard pattern (recommended)
FROM `{project}.{dataset}.events_*`
WHERE _table_suffix BETWEEN '20240101' AND FORMAT_DATE('%Y%m%d', DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY))
```

Additional cost rules:
- Select only needed columns (never `SELECT *`)
- Filter `event_name` early in WHERE clause
- Use `SAFE_DIVIDE()` to avoid division-by-zero errors
- Use `SAFE.` prefix for parse functions to return NULL on bad data

## Core Schema (One Row = One Event)

Each row is a single event. Key top-level fields:

| Field | Type | Notes |
|-------|------|-------|
| event_date | STRING | YYYYMMDD, property timezone |
| event_timestamp | INTEGER | Microseconds, UTC |
| event_name | STRING | page_view, session_start, purchase, etc. |
| event_params | REPEATED RECORD | Key-value event parameters |
| user_pseudo_id | STRING | Cookie-based client ID |
| user_id | STRING | Custom user ID (optional) |
| user_properties | REPEATED RECORD | Key-value user properties |
| device | RECORD | category, browser, OS |
| geo | RECORD | country, region, city |
| traffic_source | RECORD | User-scoped first-touch |
| session_traffic_source_last_click | RECORD | Session-scoped (since July 2024) |
| collected_traffic_source | RECORD | Event-scoped raw (since May 2023) |
| ecommerce | RECORD | Transaction data |
| items | REPEATED RECORD | Item-level ecommerce data |
| privacy_info | RECORD | Consent status |
| is_active_user | BOOLEAN | Since July 2023 |
| platform | STRING | WEB or APP |

→ Full schema details: [references/schema-and-tables.md](./references/schema-and-tables.md)

## Extracting Nested Data (UNNEST Patterns)

GA4's event_params, user_properties, and items are arrays. Use these patterns:

### Pattern 1: Correlated subquery (DEFAULT — use this for extracting values)
```sql
SELECT
  (SELECT value.string_value FROM UNNEST(event_params) WHERE key = 'page_location') AS page,
  (SELECT value.int_value FROM UNNEST(event_params) WHERE key = 'ga_session_id') AS session_id
FROM `{project}.{dataset}.events_*`
WHERE _table_suffix BETWEEN '{start}' AND '{end}'
```

### Pattern 2: Cross join UNNEST (for items array)
```sql
SELECT items.item_name, items.price, items.quantity
FROM `{project}.{dataset}.events_*`, UNNEST(items) AS items
WHERE event_name = 'purchase'
```

### Value types — only ONE is populated per parameter:
- `value.string_value` — page_location, source, medium, campaign, session_engaged
- `value.int_value` — ga_session_id, ga_session_number, entrances, engagement_time_msec
- `value.float_value` / `value.double_value` — rarely used

→ Full patterns and parameter reference: [references/unnesting-patterns.md](./references/unnesting-patterns.md)

## Session & User Identification

**Session key** = `CONCAT(user_pseudo_id, ga_session_id)` — this uniquely identifies a session.

```sql
CONCAT(user_pseudo_id,
  CAST((SELECT value.int_value FROM UNNEST(event_params) WHERE key = 'ga_session_id') AS STRING)
) AS session_key
```

**User types:**
- Total users: `COUNT(DISTINCT user_pseudo_id)`
- Active users: `COUNT(DISTINCT CASE WHEN is_active_user IS TRUE THEN user_pseudo_id END)`
- New users: `COUNT(DISTINCT CASE WHEN ga_session_number = 1 THEN user_pseudo_id END)`

**Key session metrics:**
- Sessions: `COUNT(DISTINCT session_key)`
- Engaged sessions: sessions where `session_engaged = '1'` (extracted from `value.string_value`)
- Bounce rate: `(sessions - engaged_sessions) / sessions`
- Engagement rate: `engaged_sessions / sessions`

→ Full metric calculations: [references/users-and-sessions.md](./references/users-and-sessions.md)

## Traffic Sources (4 Scopes)

GA4 has **four** traffic source locations. Use the right one:

| Need | Field | Scope |
|------|-------|-------|
| How user was first acquired | `traffic_source.*` | User (first-touch, never changes) |
| Session attribution (match GA4 UI) | `session_traffic_source_last_click.*` | Session (since July 2024) |
| Raw event-level traffic data | `collected_traffic_source.*` | Event (since May 2023) |
| Legacy / pre-2023 data | event_params source/medium | Event |

**Default recommendation**: Use `session_traffic_source_last_click.manual_campaign.source/medium` for session-level reporting. It matches GA4 UI behavior and applies last-non-direct attribution.

**Channel grouping** must be calculated manually in BigQuery using CASE WHEN logic on source/medium patterns.

→ Full traffic source details + channel grouping SQL: [references/traffic-sources.md](./references/traffic-sources.md)

## Ecommerce

**CRITICAL**: Always filter `event_name = 'purchase'` when querying revenue. Revenue fields populate only on purchase events.

```sql
-- Transaction-level revenue
SELECT ecommerce.transaction_id, SUM(ecommerce.purchase_revenue) AS revenue
FROM `{project}.{dataset}.events_*`
WHERE event_name = 'purchase' AND _table_suffix BETWEEN '{start}' AND '{end}'
GROUP BY 1

-- Item-level detail (must UNNEST items)
SELECT items.item_name, SUM(items.quantity) AS qty, SUM(items.item_revenue) AS revenue
FROM `{project}.{dataset}.events_*`, UNNEST(items) AS items
WHERE event_name = 'purchase' AND _table_suffix BETWEEN '{start}' AND '{end}'
GROUP BY 1
```

→ Full ecommerce patterns: [references/ecommerce.md](./references/ecommerce.md)

## Page & Event Dimensions

```sql
-- Page URL
(SELECT value.string_value FROM UNNEST(event_params) WHERE key = 'page_location') AS page

-- Landing page (first page of session)
CASE WHEN (SELECT value.int_value FROM UNNEST(event_params) WHERE key = 'entrances') = 1
  THEN (SELECT value.string_value FROM UNNEST(event_params) WHERE key = 'page_location') END AS landing_page
```

**Date/time best practice**: Use `event_timestamp` (UTC microseconds) as source for all time dimensions, not `event_date` (property timezone string). Convert: `TIMESTAMP_MICROS(event_timestamp)`.

→ Full dimensions reference: [references/page-event-dimensions.md](./references/page-event-dimensions.md)

## Attribution Models

The skill supports 5 rule-based attribution models for custom analysis:
- Last-touch, First-touch, Linear, Position-based (40-20-40), Time decay (7-day halving)

→ Full attribution model SQL: [references/attribution-models.md](./references/attribution-models.md)

## Advanced Patterns

Available analysis patterns:
- Ecommerce funnel with PIVOT
- Market basket analysis (product co-purchase)
- Cohort revenue analysis (month-by-month)
- User journey path analysis (STRING_AGG)
- Checkout abandonment recovery time
- Days-to-action by traffic source

→ Full patterns: [references/advanced-patterns.md](./references/advanced-patterns.md)

## Key Warnings

1. **Late-arriving events**: Daily tables update for up to 3 days. "Yesterday" may be incomplete.
2. **User properties often need propagation**: In export data, they are often populated only on the event where set or updated. Do not assume they are present on every event; propagate as needed with `MAX() OVER (PARTITION BY user_pseudo_id)`.
3. **Intraday lacks attribution**: Streaming tables don't have user-attribution for new users.
4. **BQ vs GA4 UI will differ**: GA4 UI uses HLL++ approximation, behavioral modeling, Google Signals — BQ export is raw unsampled data. Exact match is not expected.
5. **Consent mode**: If `privacy_info.analytics_storage = 'No'`, events lack user_pseudo_id and ga_session_id. Filter these out for clean analysis unless investigating consent impact.
6. **Misattribution bug**: Some paid search traffic (with gclid) may appear as organic/direct. Brief mention — check collected_traffic_source.gclid if suspicious.

→ Privacy/consent details: [references/privacy-and-consent.md](./references/privacy-and-consent.md)
→ Cost optimization: [references/cost-optimization.md](./references/cost-optimization.md)
→ BigQuery SQL tips: [references/sql-tips.md](./references/sql-tips.md)

## Sample Public Datasets for Testing
- Web ecommerce: `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`
- App gaming: `firebase-public-project.analytics_153293282.events_*`
