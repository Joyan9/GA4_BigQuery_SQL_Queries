# Attribution Models: Rule-Based Custom Attribution in BigQuery

## Overview

GA4's BigQuery export enables building custom attribution models that go beyond what's available in the GA4 UI. This reference covers 5 rule-based models with full SQL implementation.

## Base: Session Interaction Table

All models start from the same base — a table of all marketing touchpoints (sessions) within a lookback window before each conversion:

```sql
WITH conversions AS (
  -- Get all conversion events with their timestamp
  SELECT
    user_pseudo_id,
    event_timestamp AS conversion_timestamp,
    ecommerce.purchase_revenue AS revenue,
    ecommerce.transaction_id
  FROM `{project}.{dataset}.events_*`
  WHERE event_name = 'purchase'
    AND _table_suffix BETWEEN '{start}' AND '{end}'
    AND ecommerce.transaction_id IS NOT NULL
),
sessions AS (
  -- Get all sessions with their traffic source
  SELECT
    user_pseudo_id,
    (SELECT value.int_value FROM UNNEST(event_params) WHERE key = 'ga_session_id') AS session_id,
    MIN(event_timestamp) AS session_start_timestamp,
    session_traffic_source_last_click.manual_campaign.source AS source,
    session_traffic_source_last_click.manual_campaign.medium AS medium,
    session_traffic_source_last_click.manual_campaign.campaign_name AS campaign
  FROM `{project}.{dataset}.events_*`
  WHERE _table_suffix BETWEEN '{start}' AND '{end}'
  GROUP BY user_pseudo_id, session_id, source, medium, campaign
),
touchpoints AS (
  -- Join sessions to conversions within lookback window
  SELECT
    c.transaction_id,
    c.revenue,
    c.conversion_timestamp,
    s.session_id,
    s.source,
    s.medium,
    s.campaign,
    s.session_start_timestamp,
    TIMESTAMP_DIFF(
      TIMESTAMP_MICROS(c.conversion_timestamp),
      TIMESTAMP_MICROS(s.session_start_timestamp),
      MINUTE
    ) AS minutes_before_conversion,
    ROW_NUMBER() OVER (
      PARTITION BY c.transaction_id ORDER BY s.session_start_timestamp ASC
    ) AS interaction_number,
    ROW_NUMBER() OVER (
      PARTITION BY c.transaction_id ORDER BY s.session_start_timestamp DESC
    ) AS interaction_number_desc,
    COUNT(*) OVER (PARTITION BY c.transaction_id) AS total_interactions
  FROM conversions c
  JOIN sessions s
    ON c.user_pseudo_id = s.user_pseudo_id
    AND s.session_start_timestamp <= c.conversion_timestamp
    AND s.session_start_timestamp >= c.conversion_timestamp - (30 * 24 * 60 * 60 * 1000000)  -- 30-day lookback in microseconds
)
```

## Model 1: Last-Touch Attribution

100% credit to the last touchpoint before conversion.

```sql
SELECT
  source,
  medium,
  campaign,
  COUNT(DISTINCT transaction_id) AS conversions,
  SUM(revenue) AS attributed_revenue
FROM touchpoints
WHERE interaction_number_desc = 1
GROUP BY 1, 2, 3
ORDER BY attributed_revenue DESC
```

## Model 2: First-Touch Attribution

100% credit to the first touchpoint in the path.

```sql
SELECT
  source,
  medium,
  campaign,
  COUNT(DISTINCT transaction_id) AS conversions,
  SUM(revenue) AS attributed_revenue
FROM touchpoints
WHERE interaction_number = 1
GROUP BY 1, 2, 3
ORDER BY attributed_revenue DESC
```

## Model 3: Linear Attribution

Equal credit split among all touchpoints in the path.

```sql
SELECT
  source,
  medium,
  campaign,
  SUM(1.0 / total_interactions) AS attributed_conversions,
  SUM(revenue / total_interactions) AS attributed_revenue
FROM touchpoints
GROUP BY 1, 2, 3
ORDER BY attributed_revenue DESC
```

## Model 4: Position-Based Attribution (40-20-40)

40% credit to first touchpoint, 40% to last, 20% split evenly among middle touchpoints.

```sql
SELECT
  source,
  medium,
  campaign,
  SUM(
    CASE
      WHEN total_interactions = 1 THEN 1.0
      WHEN total_interactions = 2 THEN 0.5
      WHEN interaction_number = 1 THEN 0.4
      WHEN interaction_number_desc = 1 THEN 0.4
      ELSE 0.2 / (total_interactions - 2)
    END
  ) AS attributed_conversions,
  SUM(
    revenue * CASE
      WHEN total_interactions = 1 THEN 1.0
      WHEN total_interactions = 2 THEN 0.5
      WHEN interaction_number = 1 THEN 0.4
      WHEN interaction_number_desc = 1 THEN 0.4
      ELSE 0.2 / (total_interactions - 2)
    END
  ) AS attributed_revenue
FROM touchpoints
GROUP BY 1, 2, 3
ORDER BY attributed_revenue DESC
```

## Model 5: Time Decay Attribution (7-Day Half-Life)

Credit decreases as time between touchpoint and conversion increases. Each 7-day period halves the credit.

```sql
WITH decay_weights AS (
  SELECT
    *,
    POW(0.5, minutes_before_conversion / (7.0 * 24 * 60)) AS raw_weight,
    SUM(POW(0.5, minutes_before_conversion / (7.0 * 24 * 60))) OVER (
      PARTITION BY transaction_id
    ) AS total_weight
  FROM touchpoints
)
SELECT
  source,
  medium,
  campaign,
  SUM(raw_weight / total_weight) AS attributed_conversions,
  SUM(revenue * raw_weight / total_weight) AS attributed_revenue
FROM decay_weights
GROUP BY 1, 2, 3
ORDER BY attributed_revenue DESC
```

## Comparing Models Side-by-Side

```sql
WITH -- [use touchpoints CTE from base above]
model_comparison AS (
  SELECT
    source,
    medium,
    -- Last-touch
    SUM(CASE WHEN interaction_number_desc = 1 THEN revenue ELSE 0 END) AS last_touch_revenue,
    -- First-touch
    SUM(CASE WHEN interaction_number = 1 THEN revenue ELSE 0 END) AS first_touch_revenue,
    -- Linear
    SUM(revenue / total_interactions) AS linear_revenue,
    -- Position-based
    SUM(revenue * CASE
      WHEN total_interactions = 1 THEN 1.0
      WHEN total_interactions = 2 THEN 0.5
      WHEN interaction_number = 1 THEN 0.4
      WHEN interaction_number_desc = 1 THEN 0.4
      ELSE 0.2 / (total_interactions - 2)
    END) AS position_based_revenue
  FROM touchpoints
  GROUP BY 1, 2
)
SELECT *,
  ROUND(position_based_revenue - last_touch_revenue, 2) AS position_vs_last_diff
FROM model_comparison
ORDER BY position_based_revenue DESC
```

## Lookback Window Considerations

The 30-day lookback in the base query can be adjusted:

```sql
-- 7-day lookback (short sales cycle)
AND s.session_start_timestamp >= c.conversion_timestamp - (7 * 24 * 60 * 60 * 1000000)

-- 90-day lookback (long sales cycle, e.g., B2B)
AND s.session_start_timestamp >= c.conversion_timestamp - (90 * 24 * 60 * 60 * 1000000)
```

**Guidance**:
- Short lookback (7-14 days): Impulse purchases, low-consideration products
- Medium lookback (30 days): Standard e-commerce
- Long lookback (60-90 days): B2B, high-value purchases, complex buyer journeys

## Filtering Direct Traffic

Some attribution models exclude direct traffic (since it represents returning without a new marketing touchpoint):

```sql
-- Add to touchpoints WHERE clause to exclude direct:
WHERE s.source IS NOT NULL
  AND NOT (s.source = '(direct)' AND s.medium IN ('(none)', '(not set)'))
```

## Notes

- These models use **session-level** touchpoints (one touchpoint per session, not per page view)
- All models should sum to the same total revenue — they only redistribute credit
- For production use, consider materializing the touchpoints CTE as a table to avoid recomputing
- Custom events other than `purchase` can be used as conversions by changing the `event_name` filter
