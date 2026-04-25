-- To do
-- 1. add filter where prev_session_last_event_ts is NULL
-- 2. narrow the query to focus not just on source but medium and campaign name as well

WITH session_base AS (
  SELECT
    user_pseudo_id,
    (SELECT value.int_value FROM UNNEST(event_params) WHERE key = 'ga_session_id') AS ga_session_id,
    MIN(event_timestamp) AS session_first_event_ts,
    MAX(event_timestamp) AS session_last_event_ts,

    -- Was there a session_start event in this session?
    COUNTIF(event_name = 'session_start') AS has_session_start,

    -- Traffic source from the first event in session (most reliable)
    ARRAY_AGG(
      traffic_source.source ORDER BY event_timestamp ASC LIMIT 1
    )[OFFSET(0)] AS source,
    ARRAY_AGG(
      traffic_source.medium ORDER BY event_timestamp ASC LIMIT 1
    )[OFFSET(0)] AS medium,

    -- Page where session effectively started (first event's page)
    ARRAY_AGG(
      (SELECT value.string_value FROM UNNEST(event_params) WHERE key = 'page_location')
      ORDER BY event_timestamp ASC LIMIT 1
    )[OFFSET(0)] AS first_page_location,

    -- Page where session ended (last event's page)
    ARRAY_AGG(
      (SELECT value.string_value FROM UNNEST(event_params) WHERE key = 'page_location')
      ORDER BY event_timestamp DESC LIMIT 1
    )[OFFSET(0)] AS last_page_location,

    DATE(TIMESTAMP_MICROS(MIN(event_timestamp)), 'Europe/Berlin') AS session_date

  FROM `your_project.your_dataset.events_*`
  WHERE _TABLE_SUFFIX BETWEEN '20250101' AND '20250425'
  GROUP BY user_pseudo_id, ga_session_id
),

session_with_rank AS (
  SELECT
    *,
    ROW_NUMBER() OVER (
      PARTITION BY user_pseudo_id
      ORDER BY session_first_event_ts ASC
    ) AS session_rn
  FROM session_base
),

session_with_prev AS (
  SELECT
    curr.*,

    -- Previous session attributes
    prev.ga_session_id        AS prev_session_id,
    prev.source               AS prev_source,
    prev.medium               AS prev_medium,
    prev.last_page_location   AS prev_last_page_location,
    prev.session_last_event_ts AS prev_session_last_event_ts,
    prev.session_date         AS prev_session_date,
    prev.has_session_start    AS prev_has_session_start

  FROM session_with_rank curr
  LEFT JOIN session_with_rank prev
    ON  curr.user_pseudo_id = prev.user_pseudo_id
    AND curr.session_rn     = prev.session_rn + 1
)

SELECT
  user_pseudo_id,
  ga_session_id,
  source,
  medium,
  has_session_start,
  session_first_event_ts,
  session_date,
  first_page_location,

  -- Previous session context
  prev_session_id,
  prev_source,
  prev_medium,
  prev_last_page_location,
  prev_session_date,

  -- Diagnostic flags
  (source IS NULL OR source = '(not set)')           AS is_source_not_set,
  (has_session_start = 0)                             AS missing_session_start,
  (prev_source IS NOT NULL AND prev_source != '(not set)') AS prev_had_source,

  -- Did the previous session end on the same page this one started?
  (prev_last_page_location = first_page_location)    AS same_page_continuation,

  -- Same calendar day?
  (session_date = prev_session_date)                  AS same_day_as_prev,

  -- Gap between sessions in minutes
  ROUND(
    (session_first_event_ts - prev_session_last_event_ts) / 1e6 / 60,
    1
  ) AS gap_minutes_from_prev

FROM session_with_prev

WHERE
  -- Core condition: no traffic source
  (source IS NULL OR source = '(not set)')
  -- And the session has no session_start (strong signal of timeout continuation)
  AND has_session_start = 0

ORDER BY user_pseudo_id, session_first_event_ts
