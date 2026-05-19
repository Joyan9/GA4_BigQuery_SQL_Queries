# GA4 BigQuery Export: Schema & Table Structure

## Dataset Naming
- Dataset: `analytics_<property_id>` (e.g., `analytics_250794857`)
- Property ID = GA4 property ID from Admin > Property Settings

## Table Types

| Table pattern | Description | Update frequency |
|---------------|-------------|-----------------|
| `events_YYYYMMDD` | Daily export (complete) | Created ~5-6 AM property timezone |
| `events_intraday_YYYYMMDD` | Streaming/real-time | Continuous; deleted when daily table is ready |
| `pseudonymous_users_YYYYMMDD` | User-level data (optional) | Daily, must be activated separately |
| `users_YYYYMMDD` | Identified user data (optional) | Daily, must be activated separately |

## Late-Arriving Events
Daily tables update for up to **3 days** after the event date. Events arriving after that window are dropped. Consequence: queries on "yesterday" may not have complete data.

## Row Structure
Each row = one event. A single page_view event contains many nested key-value pairs in event_params. The items array creates multiple nested rows within one event for ecommerce.

## Complete Top-Level Field Reference

### Event fields
| Field | Type | Description |
|-------|------|-------------|
| event_date | STRING | YYYYMMDD in property timezone |
| event_timestamp | INTEGER | Microseconds since epoch, UTC |
| event_name | STRING | Event type (page_view, session_start, purchase, scroll, click, etc.) |
| event_params | RECORD (REPEATED) | Array of {key, value} structs |
| event_previous_timestamp | INTEGER | Previous event timestamp for user |
| event_value_in_usd | FLOAT | Currency-converted event value |
| event_bundle_sequence_id | INTEGER | Sequential ID for event bundle |
| event_server_timestamp_offset | INTEGER | Server timestamp offset in microseconds |
| batch_page_id | INTEGER | Page batch ID (from 2024-07-11) |
| batch_ordering_id | INTEGER | Ordering within batch (from 2024-07-11) |
| batch_event_index | INTEGER | Event index in batch (from 2024-07-11) |

### User fields
| Field | Type | Description |
|-------|------|-------------|
| user_pseudo_id | STRING | Client ID / cookie-based |
| user_id | STRING | Custom user ID via setUserId (optional) |
| user_properties | RECORD (REPEATED) | Array of {key, value} user properties |
| user_first_touch_timestamp | INTEGER | First visit timestamp (microseconds) |
| user_ltv | RECORD | {revenue, currency} lifetime value |
| is_active_user | BOOLEAN | Engagement-based active flag (since July 2023) |

### Traffic source fields
| Field | Type | Scope | Description |
|-------|------|-------|-------------|
| traffic_source | RECORD | User | First-touch: source, medium, name |
| session_traffic_source_last_click | RECORD | Session | Last non-direct click (since July 2024) |
| collected_traffic_source | RECORD | Event | Raw unprocessed traffic data (since May 2023) |

### Device & geo fields
| Field | Type | Sub-fields |
|-------|------|------------|
| device | RECORD | category, mobile_brand_name, mobile_model_name, mobile_marketing_name, mobile_os_hardware_model, operating_system, operating_system_version, vendor_id, advertising_id, language, is_limited_ad_tracking, time_zone_offset_seconds, browser, browser_version, web_info.browser, web_info.hostname |
| geo | RECORD | continent, sub_continent, country, region, city, metro |

### Ecommerce fields
| Field | Type | Description |
|-------|------|-------------|
| ecommerce | RECORD | transaction_id, total_item_quantity, purchase_revenue_in_usd, purchase_revenue, refund_value_in_usd, refund_value, shipping_value_in_usd, shipping_value, tax_value_in_usd, tax_value, unique_items |
| items | RECORD (REPEATED) | Array of item structs (see ecommerce reference) |

### Other fields
| Field | Type | Description |
|-------|------|-------------|
| privacy_info | RECORD | analytics_storage, ads_storage, uses_transient_token |
| stream_id | STRING | Data stream ID |
| platform | STRING | WEB or APP |

## Four Data Scopes
GA4 data has four scopes. Mixing scopes incorrectly produces meaningless results:

1. **User scope**: Applies across all sessions (traffic_source, user_properties, user_first_touch_timestamp)
2. **Session scope**: Applies to one session (session_traffic_source_last_click, ga_session_id)
3. **Event scope**: Applies to individual events (event_params, collected_traffic_source, event_timestamp)
4. **Item scope**: Applies to items within ecommerce events (items array)

## Nested/Repeated Field Structure

### event_params
```
event_params[].key: STRING
event_params[].value.string_value: STRING
event_params[].value.int_value: INTEGER
event_params[].value.float_value: FLOAT
event_params[].value.double_value: FLOAT
```
Only ONE value type is populated per parameter.

### user_properties
Same structure as event_params. In export data, user properties are often populated only on events where the value was set or updated, so do not assume they are present on every event.

### items
Flat struct with named fields (item_id, item_name, price, etc.) plus nested item_params (from 2023-10-25).

## Sample Public Datasets
- **Web ecommerce**: `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*` (Nov 2020 - Jan 2021)
- **App gaming**: `firebase-public-project.analytics_153293282.events_*` (Jun - Oct 2018)
- Data is obfuscated; cannot be compared to GA4 demo account reports
