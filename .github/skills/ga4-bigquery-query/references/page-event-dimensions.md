# Page, Event & Date/Time Dimensions

## Page Dimensions

### Page URL (page_location)
```sql
(SELECT value.string_value FROM UNNEST(event_params) WHERE key = 'page_location') AS page_url
```

### Page title
```sql
(SELECT value.string_value FROM UNNEST(event_params) WHERE key = 'page_title') AS page_title
```

### Hostname
```sql
device.web_info.hostname
```

### Page path (extracted from URL)
```sql
-- Full path without query string
REGEXP_EXTRACT(
  (SELECT value.string_value FROM UNNEST(event_params) WHERE key = 'page_location'),
  r'^https?://[^/]+(\/[^?#]*)'
) AS page_path
```

### Page path levels
```sql
-- Level 1: /category/
CONCAT('/',
  SPLIT(SPLIT(
    (SELECT value.string_value FROM UNNEST(event_params) WHERE key = 'page_location'),
  '/')[SAFE_ORDINAL(4)], '?')[SAFE_ORDINAL(1)]
) AS pagepath_level_1

-- Level 2: /category/subcategory/
CONCAT('/',
  SPLIT(SPLIT(page_location, '/')[SAFE_ORDINAL(4)], '?')[SAFE_ORDINAL(1)], '/',
  SPLIT(SPLIT(page_location, '/')[SAFE_ORDINAL(5)], '?')[SAFE_ORDINAL(1)]
) AS pagepath_level_2
```

### Landing page (first page of session)
```sql
CASE
  WHEN (SELECT value.int_value FROM UNNEST(event_params) WHERE key = 'entrances') = 1
  THEN (SELECT value.string_value FROM UNNEST(event_params) WHERE key = 'page_location')
END AS landing_page
```

### Landing page per session (alternative using ARRAY_AGG)
```sql
WITH session_pages AS (
  SELECT
    CONCAT(user_pseudo_id, CAST(
      (SELECT value.int_value FROM UNNEST(event_params) WHERE key = 'ga_session_id') AS STRING)
    ) AS session_key,
    ARRAY_AGG(
      (SELECT value.string_value FROM UNNEST(event_params) WHERE key = 'page_location')
      IGNORE NULLS ORDER BY event_timestamp ASC
    )[SAFE_OFFSET(0)] AS landing_page
  FROM `{project}.{dataset}.events_*`
  WHERE _table_suffix BETWEEN '{start}' AND '{end}'
    AND event_name = 'page_view'
  GROUP BY session_key
)
```

### Exit page (last page of session)
```sql
ARRAY_AGG(
  (SELECT value.string_value FROM UNNEST(event_params) WHERE key = 'page_location')
  IGNORE NULLS ORDER BY event_timestamp DESC
)[SAFE_OFFSET(0)] AS exit_page
```

### Previous page (using LAG window function)
```sql
LAG(
  (SELECT value.string_value FROM UNNEST(event_params) WHERE key = 'page_location'), 1
) OVER (
  PARTITION BY user_pseudo_id,
    (SELECT value.int_value FROM UNNEST(event_params) WHERE key = 'ga_session_id')
  ORDER BY event_timestamp ASC
) AS previous_page
```

### Second page (page after landing)
```sql
LEAD(
  (SELECT value.string_value FROM UNNEST(event_params) WHERE key = 'page_location'), 1
) OVER (
  PARTITION BY user_pseudo_id,
    (SELECT value.int_value FROM UNNEST(event_params) WHERE key = 'ga_session_id')
  ORDER BY event_timestamp ASC
) AS second_page
-- Apply only to rows where entrances = 1
```

## Page Metrics

```sql
-- Page views
COUNTIF(event_name = 'page_view') AS pageviews

-- Unique pageviews (unique sessions with that page)
COUNT(DISTINCT CASE
  WHEN event_name = 'page_view'
  THEN CONCAT(user_pseudo_id, CAST(session_id AS STRING), page_location)
END) AS unique_pageviews

-- Pages per session
SAFE_DIVIDE(
  COUNTIF(event_name = 'page_view'),
  COUNT(DISTINCT session_key)
) AS pages_per_session

-- Entrances (sessions starting on a page)
COUNTIF(
  (SELECT value.int_value FROM UNNEST(event_params) WHERE key = 'entrances') = 1
) AS entrances

-- Exit rate for a page (requires session-level exit page calculation)
-- Exits / Pageviews for that page
```

## Date & Time Dimensions

### Key distinction
- `event_date`: STRING (YYYYMMDD) in **property timezone**
- `event_timestamp`: INTEGER (microseconds since epoch) in **UTC**

**Best practice**: Always use `event_timestamp` as source for time dimensions to prevent timezone confusion. Convert to desired timezone explicitly.

### Date parsing
```sql
-- Parse event_date to DATE type
PARSE_DATE('%Y%m%d', event_date) AS date_parsed

-- From event_timestamp (UTC)
DATE(TIMESTAMP_MICROS(event_timestamp)) AS date_utc

-- From event_timestamp with timezone
DATE(TIMESTAMP_MICROS(event_timestamp), 'America/New_York') AS date_local
```

### Date formatting patterns
```sql
-- Year
FORMAT_DATE('%Y', PARSE_DATE('%Y%m%d', event_date)) AS year
-- e.g., "2024"

-- Month (YYYYMM)
FORMAT_DATE('%Y%m', PARSE_DATE('%Y%m%d', event_date)) AS year_month
-- e.g., "202407"

-- Month name
FORMAT_DATE('%B', PARSE_DATE('%Y%m%d', event_date)) AS month_name
-- e.g., "July"

-- ISO week (YYYYWW)
FORMAT_DATE('%G%V', PARSE_DATE('%Y%m%d', event_date)) AS iso_year_week
-- e.g., "202428"

-- Day of week (number, Sunday=1)
EXTRACT(DAYOFWEEK FROM PARSE_DATE('%Y%m%d', event_date)) AS day_of_week_num

-- Day of week (name)
FORMAT_DATE('%A', PARSE_DATE('%Y%m%d', event_date)) AS day_name
-- e.g., "Monday"

-- Hour (from timestamp, UTC)
EXTRACT(HOUR FROM TIMESTAMP_MICROS(event_timestamp)) AS hour_utc

-- Hour (with timezone)
EXTRACT(HOUR FROM TIMESTAMP_MICROS(event_timestamp) AT TIME ZONE 'Europe/London') AS hour_local

-- Minute
EXTRACT(MINUTE FROM TIMESTAMP_MICROS(event_timestamp)) AS minute

-- Date + hour combined
FORMAT_TIMESTAMP('%Y%m%d %H:00', TIMESTAMP_MICROS(event_timestamp)) AS date_hour
```

### Useful date calculations
```sql
-- Days since first visit
DATE_DIFF(
  PARSE_DATE('%Y%m%d', event_date),
  DATE(TIMESTAMP_MICROS(user_first_touch_timestamp)),
  DAY
) AS days_since_first_visit

-- Timestamp to readable datetime
FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S', TIMESTAMP_MICROS(event_timestamp)) AS event_datetime
```

## Device Dimensions

```sql
device.category              -- 'desktop', 'mobile', 'tablet'
device.operating_system      -- 'Android', 'iOS', 'Windows', 'Macintosh', 'Linux'
device.operating_system_version
device.browser               -- 'Chrome', 'Safari', 'Firefox', 'Edge'
device.browser_version
device.language              -- 'en-us', 'fr', etc.
device.mobile_brand_name     -- 'Samsung', 'Apple', etc.
device.mobile_model_name
device.mobile_marketing_name
device.is_limited_ad_tracking -- BOOLEAN
```

## Geo Dimensions

```sql
geo.continent       -- 'Americas', 'Europe', 'Asia'
geo.sub_continent   -- 'Northern America', 'Western Europe'
geo.country         -- 'United States', 'United Kingdom'
geo.region          -- 'California', 'England'
geo.city            -- 'San Francisco', 'London'
geo.metro           -- 'San Francisco-Oakland-San Jose CA' (US DMA)
```

## Platform & Stream

```sql
platform    -- 'WEB' or 'APP' (iOS/Android)
stream_id   -- Numeric data stream identifier
```

## Common Event Names

| Event | Description | Auto-collected? |
|-------|-------------|-----------------|
| page_view | Page load | Yes (enhanced measurement) |
| session_start | New session begins | Yes |
| first_visit | First visit by user | Yes |
| user_engagement | User actively engaged | Yes |
| scroll | 90% page scroll | Yes (enhanced measurement) |
| click | Outbound link click | Yes (enhanced measurement) |
| view_search_results | Site search | Yes (enhanced measurement) |
| file_download | File download | Yes (enhanced measurement) |
| video_start | Video started | Yes (enhanced measurement) |
| video_progress | Video 10/25/50/75% | Yes (enhanced measurement) |
| video_complete | Video finished | Yes (enhanced measurement) |
| form_start | Form interaction began | Yes (enhanced measurement) |
| form_submit | Form submitted | Yes (enhanced measurement) |
