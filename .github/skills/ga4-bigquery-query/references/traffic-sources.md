# Traffic Sources: All 4 Scopes + Channel Grouping

## The 4 Traffic Source Scopes

GA4 BigQuery export contains traffic source data in FOUR different locations. Using the wrong one produces incorrect reports.

---

## 1. `traffic_source` — User-Scoped (First-Touch Acquisition)

**Scope**: User — set ONCE when user_pseudo_id is first seen, never updated
**Available since**: Start of GA4 export
**GA4 UI equivalent**: "First user source/medium/campaign"

**Fields**:
- `traffic_source.source`
- `traffic_source.medium`
- `traffic_source.name` (campaign)

```sql
-- User acquisition report
SELECT
  traffic_source.source AS first_user_source,
  traffic_source.medium AS first_user_medium,
  traffic_source.name AS first_user_campaign,
  COUNT(DISTINCT user_pseudo_id) AS new_users
FROM `{project}.{dataset}.events_*`
WHERE _table_suffix BETWEEN '{start}' AND '{end}'
  AND (SELECT value.int_value FROM UNNEST(event_params) WHERE key = 'ga_session_number') = 1
GROUP BY 1, 2, 3
ORDER BY new_users DESC
```

---

## 2. `session_traffic_source_last_click` — Session-Scoped (RECOMMENDED)

**Scope**: Session — same value on ALL events within a session
**Available since**: July 2024 (manual_campaign, google_ads), October 2024 (cross_channel)
**GA4 UI equivalent**: "Session source/medium/campaign" — matches GA4 UI reports
**Attribution**: Last non-direct click (direct visits inherit most recent non-direct source)

**Sub-records**:
- `.manual_campaign` — UTM-based parameters
- `.google_ads_campaign` — Google Ads data
- `.cross_channel_campaign` — Default channel grouping data

### Manual campaign fields:
```sql
session_traffic_source_last_click.manual_campaign.source
session_traffic_source_last_click.manual_campaign.medium
session_traffic_source_last_click.manual_campaign.campaign_id
session_traffic_source_last_click.manual_campaign.campaign_name
session_traffic_source_last_click.manual_campaign.term
session_traffic_source_last_click.manual_campaign.content
session_traffic_source_last_click.manual_campaign.source_platform
session_traffic_source_last_click.manual_campaign.creative_format
session_traffic_source_last_click.manual_campaign.marketing_tactic
```

### Google Ads fields:
```sql
session_traffic_source_last_click.google_ads_campaign.customer_id
session_traffic_source_last_click.google_ads_campaign.account_name
session_traffic_source_last_click.google_ads_campaign.campaign_id
session_traffic_source_last_click.google_ads_campaign.campaign_name
session_traffic_source_last_click.google_ads_campaign.ad_group_id
session_traffic_source_last_click.google_ads_campaign.ad_group_name
```

### Session source/medium report:
```sql
SELECT
  session_traffic_source_last_click.manual_campaign.source AS session_source,
  session_traffic_source_last_click.manual_campaign.medium AS session_medium,
  session_traffic_source_last_click.manual_campaign.campaign_name AS session_campaign,
  COUNT(DISTINCT CONCAT(user_pseudo_id, CAST(
    (SELECT value.int_value FROM UNNEST(event_params) WHERE key = 'ga_session_id') AS STRING))
  ) AS sessions,
  COUNT(DISTINCT user_pseudo_id) AS users
FROM `{project}.{dataset}.events_*`
WHERE _table_suffix BETWEEN '{start}' AND '{end}'
GROUP BY 1, 2, 3
ORDER BY sessions DESC
```

---

## 3. `collected_traffic_source` — Event-Scoped (Raw)

**Scope**: Event — can differ per event within a session
**Available since**: May 2023 (but only on session_start for some properties since Nov 2023)
**GA4 UI equivalent**: No direct equivalent — raw unprocessed data
**Key characteristic**: NO attribution model applied. Raw values as collected.

**Fields**:
```sql
collected_traffic_source.manual_campaign_id
collected_traffic_source.manual_campaign_name
collected_traffic_source.manual_source
collected_traffic_source.manual_medium
collected_traffic_source.manual_term
collected_traffic_source.manual_content
collected_traffic_source.gclid
collected_traffic_source.dclid
collected_traffic_source.srsltid
collected_traffic_source.manual_source_platform     -- from July 2024
collected_traffic_source.manual_creative_format     -- from July 2024
collected_traffic_source.manual_marketing_tactic    -- from July 2024
```

**Use case**: When you need raw click IDs (gclid) or want to build custom attribution:
```sql
SELECT
  collected_traffic_source.manual_source AS source,
  collected_traffic_source.manual_medium AS medium,
  collected_traffic_source.gclid,
  COUNT(*) AS events
FROM `{project}.{dataset}.events_*`
WHERE _table_suffix BETWEEN '{start}' AND '{end}'
  AND collected_traffic_source.manual_source IS NOT NULL
GROUP BY 1, 2, 3
```

**Known bug**: Since summer 2023, many properties see most events losing collected_traffic_source (becoming NULL). It may only populate on `session_start` and `page_view` events.

---

## 4. Event Parameters (Legacy)

**Scope**: Event
**Available since**: Start of GA4 export
**Use case**: Pre-2023 data or when other fields aren't available

```sql
(SELECT value.string_value FROM UNNEST(event_params) WHERE key = 'source') AS source,
(SELECT value.string_value FROM UNNEST(event_params) WHERE key = 'medium') AS medium,
(SELECT value.string_value FROM UNNEST(event_params) WHERE key = 'campaign') AS campaign,
(SELECT value.string_value FROM UNNEST(event_params) WHERE key = 'gclid') AS gclid
```

---

## Decision Guide: Which Source to Use

| Use case | Recommended field | Why |
|----------|-------------------|-----|
| Standard session reports | `session_traffic_source_last_click` | Matches GA4 UI, proper attribution |
| User acquisition analysis | `traffic_source` | Shows first-touch only |
| Custom attribution models | `collected_traffic_source` | Raw data, no model applied |
| Pre-July 2024 session data | Calculated from event_params (see below) | session_traffic_source_last_click didn't exist |
| Google Ads campaign details | `session_traffic_source_last_click.google_ads_campaign` | Campaign/ad group names |

---

## Legacy: Calculating Session Source/Medium (Pre-July 2024)

Before `session_traffic_source_last_click` existed, session-level source/medium had to be computed:

```sql
WITH session_sources AS (
  SELECT
    user_pseudo_id,
    (SELECT value.int_value FROM UNNEST(event_params) WHERE key = 'ga_session_id') AS session_id,
    ARRAY_AGG(
      (SELECT value.string_value FROM UNNEST(event_params) WHERE key = 'source')
      IGNORE NULLS ORDER BY event_timestamp ASC
    )[SAFE_OFFSET(0)] AS source,
    ARRAY_AGG(
      (SELECT value.string_value FROM UNNEST(event_params) WHERE key = 'medium')
      IGNORE NULLS ORDER BY event_timestamp ASC
    )[SAFE_OFFSET(0)] AS medium,
    ARRAY_AGG(
      (SELECT value.string_value FROM UNNEST(event_params) WHERE key = 'campaign')
      IGNORE NULLS ORDER BY event_timestamp ASC
    )[SAFE_OFFSET(0)] AS campaign
  FROM `{project}.{dataset}.events_*`
  WHERE _table_suffix BETWEEN '{start}' AND '{end}'
  GROUP BY user_pseudo_id, session_id
)
SELECT
  COALESCE(source, '(direct)') AS session_source,
  COALESCE(medium, '(none)') AS session_medium,
  campaign AS session_campaign,
  COUNT(DISTINCT CONCAT(user_pseudo_id, CAST(session_id AS STRING))) AS sessions
FROM session_sources
GROUP BY 1, 2, 3
ORDER BY sessions DESC
```

---

## Default Channel Grouping (CASE WHEN Logic)

Channel grouping must be calculated manually in BigQuery. Apply this to your source/medium values. **Order matters** — paid channels must be checked before organic.

```sql
CASE
  -- Direct
  WHEN (source IS NULL OR source = '(direct)')
    AND (medium IS NULL OR medium IN ('(not set)', '(none)'))
    THEN 'Direct'

  -- Cross-network
  WHEN campaign LIKE '%cross-network%'
    THEN 'Cross-network'

  -- Paid Shopping
  WHEN (REGEXP_CONTAINS(source, 'alibaba|amazon|google shopping|shopify|etsy|ebay|stripe|walmart')
    OR REGEXP_CONTAINS(campaign, '^(.*(([^a-df-z]|^)shop|shopping).*)$'))
    AND REGEXP_CONTAINS(medium, '^(.*cp.*|ppc|retargeting|paid.*)$')
    THEN 'Paid Shopping'

  -- Paid Search
  WHEN REGEXP_CONTAINS(source, 'baidu|bing|duckduckgo|ecosia|google|yahoo|yandex')
    AND REGEXP_CONTAINS(medium, '^(.*cp.*|ppc|retargeting|paid.*)$')
    THEN 'Paid Search'

  -- Paid Social
  WHEN REGEXP_CONTAINS(source, 'badoo|facebook|fb|instagram|linkedin|pinterest|tiktok|twitter|whatsapp')
    AND REGEXP_CONTAINS(medium, '^(.*cp.*|ppc|retargeting|paid.*)$')
    THEN 'Paid Social'

  -- Paid Video
  WHEN REGEXP_CONTAINS(source, 'dailymotion|disneyplus|netflix|youtube|vimeo|twitch')
    AND REGEXP_CONTAINS(medium, '^(.*cp.*|ppc|retargeting|paid.*)$')
    THEN 'Paid Video'

  -- Display
  WHEN medium IN ('display', 'banner', 'expandable', 'interstitial', 'cpm')
    THEN 'Display'

  -- Paid Other
  WHEN REGEXP_CONTAINS(medium, '^(.*cp.*|ppc|retargeting|paid.*)$')
    THEN 'Paid Other'

  -- Organic Shopping
  WHEN REGEXP_CONTAINS(source, 'alibaba|amazon|google shopping|shopify|etsy|ebay|stripe|walmart')
    OR REGEXP_CONTAINS(campaign, '^(.*(([^a-df-z]|^)shop|shopping).*)$')
    THEN 'Organic Shopping'

  -- Organic Social
  WHEN REGEXP_CONTAINS(source, 'badoo|facebook|fb|instagram|linkedin|pinterest|tiktok|twitter|whatsapp')
    OR medium IN ('social', 'social-network', 'social-media', 'sm', 'social network', 'social media')
    THEN 'Organic Social'

  -- Organic Video
  WHEN REGEXP_CONTAINS(source, 'dailymotion|disneyplus|netflix|youtube|vimeo|twitch')
    OR REGEXP_CONTAINS(medium, '^(.*video.*)$')
    THEN 'Organic Video'

  -- Organic Search
  WHEN REGEXP_CONTAINS(source, 'baidu|bing|duckduckgo|ecosia|google|yahoo|yandex')
    OR medium = 'organic'
    THEN 'Organic Search'

  -- Referral
  WHEN medium IN ('referral', 'app', 'link')
    THEN 'Referral'

  -- Email
  WHEN REGEXP_CONTAINS(source, 'email|e-mail|e_mail|e mail')
    OR REGEXP_CONTAINS(medium, 'email|e-mail|e_mail|e mail')
    THEN 'Email'

  -- Affiliates
  WHEN medium = 'affiliate'
    THEN 'Affiliates'

  -- Audio
  WHEN medium = 'audio'
    THEN 'Audio'

  -- SMS
  WHEN source = 'sms' OR medium = 'sms'
    THEN 'SMS'

  -- Mobile Push
  WHEN medium LIKE '%push'
    OR REGEXP_CONTAINS(medium, 'mobile|notification')
    OR source = 'firebase'
    THEN 'Mobile Push Notifications'

  ELSE 'Unassigned'
END AS default_channel_grouping
```

### Notes on channel grouping:
- Based on Google's official documentation
- Order of CASE WHEN matters — paid channels must be checked before organic equivalents
- Google periodically updates classifications — this may need maintenance
- Not all variables used by GA4 UI are available in BigQuery export
- Apply this to whichever source/medium field matches your scope (user/session/event)

---

## Known Issues

1. **Misattribution bug**: Some paid search traffic (with gclid) can appear as organic or direct. If suspecting this, check `collected_traffic_source.gclid IS NOT NULL` for events classified as organic.

2. **collected_traffic_source NULL**: Since summer 2023, values often NULL on most events. Check `session_start` events specifically.

3. **Intraday lacks attribution**: `events_intraday_*` tables don't have user-attribution (traffic_source) for new users. Use daily export for attribution analysis.
