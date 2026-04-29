WITH session_base AS (
  SELECT
    user_pseudo_id,
    (SELECT value.int_value FROM UNNEST(event_params) WHERE key = 'ga_session_id') AS ga_session_id,
    MIN(event_timestamp) AS session_first_event_ts,
    MAX(event_timestamp) AS session_last_event_ts,
    COUNTIF(event_name = 'session_start') AS has_session_start,
    ARRAY_AGG(traffic_source.source ORDER BY event_timestamp ASC LIMIT 1)[OFFSET(0)] AS source,
    ARRAY_AGG((SELECT value.string_value FROM UNNEST(event_params) WHERE key = 'page_location') ORDER BY event_timestamp ASC LIMIT 1)[OFFSET(0)] AS first_page_location,
    ARRAY_AGG((SELECT value.string_value FROM UNNEST(event_params) WHERE key = 'page_location') ORDER BY event_timestamp DESC LIMIT 1)[OFFSET(0)] AS last_page_location,
    DATE(TIMESTAMP_MICROS(MIN(event_timestamp)), 'Europe/Berlin') AS session_date
  FROM `your_project.your_dataset.events_*`
  WHERE _TABLE_SUFFIX BETWEEN '20250101' AND '20250425'
  GROUP BY user_pseudo_id, ga_session_id
),

session_with_rank AS (
  SELECT
    *,
    ROW_NUMBER() OVER (PARTITION BY user_pseudo_id ORDER BY session_first_event_ts ASC) AS session_rn
  FROM session_base
),

session_with_prev AS (
  SELECT
    curr.*,
    prev.last_page_location AS prev_last_page_location
  FROM session_with_rank curr
  LEFT JOIN session_with_rank prev
    ON  curr.user_pseudo_id = prev.user_pseudo_id
    AND curr.session_rn     = prev.session_rn + 1
)

-- AGGREGATION LAYER
SELECT
  COUNT(*) AS total_sessions,

  -- 1. % of total sessions that start without a session_start event
  COUNTIF(has_session_start = 0) AS sessions_missing_start,
  ROUND(100 * COUNTIF(has_session_start = 0) / COUNT(*), 2) AS pct_sessions_missing_start,

  -- 2. % of sessions with no attribution due to missing session_start
  COUNTIF(has_session_start = 0 AND (source IS NULL OR source = '(not set)')) AS sessions_no_attribution_missing_start,
  ROUND(100 * COUNTIF(has_session_start = 0 AND (source IS NULL OR source = '(not set)')) / COUNT(*), 2) AS pct_no_attribution_due_to_missing_start,

  -- 3. Diagnostic: % of "missing start" sessions that are actually same-page continuations
  ROUND(100 * COUNTIF(has_session_start = 0 AND prev_last_page_location = first_page_location) / NULLIF(COUNTIF(has_session_start = 0), 0), 2) AS pct_missing_start_caused_by_continuation

FROM session_with_prev