# Ecommerce: Transactions, Items & Revenue Analysis

## Ecommerce Event Hierarchy

| Event | Trigger | Contains items? | Has revenue? |
|-------|---------|----------------|--------------|
| view_item | Product page | Yes | No |
| view_item_list | Product list/category | Yes | No |
| select_item | Product click from list | Yes | No |
| add_to_cart | Add item to cart | Yes | No |
| remove_from_cart | Remove item from cart | Yes | No |
| view_cart | View cart page | Yes | No |
| begin_checkout | Start checkout | Yes | No |
| add_shipping_info | Enter shipping details | Yes | No |
| add_payment_info | Enter payment details | Yes | No |
| purchase | Complete transaction | Yes | **Yes** |
| refund | Process refund | Yes | Yes (negative) |

**CRITICAL**: Revenue fields (`ecommerce.purchase_revenue`, `items.item_revenue`) are ONLY populated on `purchase` events. Always filter `event_name = 'purchase'` when querying revenue.

## Transaction-Level Query Template

```sql
SELECT
  event_date,
  ecommerce.transaction_id,
  ecommerce.total_item_quantity,
  ecommerce.purchase_revenue_in_usd,
  ecommerce.purchase_revenue,
  ecommerce.shipping_value_in_usd,
  ecommerce.shipping_value,
  ecommerce.tax_value_in_usd,
  ecommerce.tax_value,
  ecommerce.refund_value_in_usd,
  ecommerce.refund_value,
  ecommerce.unique_items
FROM `{project}.{dataset}.events_*`
WHERE event_name = 'purchase'
  AND _table_suffix BETWEEN '{start}' AND '{end}'
  AND ecommerce.transaction_id IS NOT NULL
```

### Revenue summary:
```sql
SELECT
  COUNT(DISTINCT ecommerce.transaction_id) AS transactions,
  SUM(ecommerce.purchase_revenue) AS total_revenue,
  AVG(ecommerce.purchase_revenue) AS avg_order_value,
  SUM(ecommerce.total_item_quantity) AS total_items_sold
FROM `{project}.{dataset}.events_*`
WHERE event_name = 'purchase'
  AND _table_suffix BETWEEN '{start}' AND '{end}'
  AND ecommerce.transaction_id IS NOT NULL
```

## Item-Level Query Template

Must UNNEST the items array:

```sql
SELECT
  items.item_id,
  items.item_name,
  items.item_brand,
  items.item_variant,
  items.item_category,
  items.item_category2,
  items.item_category3,
  items.item_category4,
  items.item_category5,
  items.price,
  items.price_in_usd,
  items.quantity,
  items.item_revenue,
  items.item_revenue_in_usd,
  items.item_refund,
  items.item_refund_in_usd,
  items.coupon,
  items.affiliation,
  items.item_list_id,
  items.item_list_name,
  items.item_list_index,
  items.promotion_id,
  items.promotion_name,
  items.creative_name,
  items.creative_slot,
  items.location_id
FROM `{project}.{dataset}.events_*`,
  UNNEST(items) AS items
WHERE event_name = 'purchase'
  AND _table_suffix BETWEEN '{start}' AND '{end}'
```

### Top products by revenue:
```sql
SELECT
  items.item_name,
  items.item_brand,
  items.item_category,
  SUM(items.quantity) AS total_quantity,
  SUM(items.item_revenue) AS total_revenue,
  COUNT(DISTINCT ecommerce.transaction_id) AS transaction_count,
  SAFE_DIVIDE(SUM(items.item_revenue), SUM(items.quantity)) AS avg_price_paid
FROM `{project}.{dataset}.events_*`,
  UNNEST(items) AS items
WHERE event_name = 'purchase'
  AND _table_suffix BETWEEN '{start}' AND '{end}'
  AND items.item_name IS NOT NULL
GROUP BY 1, 2, 3
ORDER BY total_revenue DESC
```

## Ecommerce Funnel Analysis (PIVOT)

Session-level funnel showing how many sessions reach each step:

```sql
WITH funnel_events AS (
  SELECT
    CONCAT(user_pseudo_id, CAST(
      (SELECT value.int_value FROM UNNEST(event_params) WHERE key = 'ga_session_id') AS STRING)
    ) AS session_key,
    event_name
  FROM `{project}.{dataset}.events_*`
  WHERE _table_suffix BETWEEN '{start}' AND '{end}'
    AND event_name IN ('view_item', 'add_to_cart', 'begin_checkout', 'purchase')
)
SELECT * FROM (
  SELECT session_key, event_name
  FROM funnel_events
)
PIVOT (
  COUNT(DISTINCT session_key)
  FOR event_name IN ('view_item', 'add_to_cart', 'begin_checkout', 'purchase')
)
```

### Product-level funnel:
```sql
WITH product_funnel AS (
  SELECT
    items.item_name,
    CONCAT(user_pseudo_id, CAST(
      (SELECT value.int_value FROM UNNEST(event_params) WHERE key = 'ga_session_id') AS STRING)
    ) AS session_key,
    event_name
  FROM `{project}.{dataset}.events_*`,
    UNNEST(items) AS items
  WHERE _table_suffix BETWEEN '{start}' AND '{end}'
    AND event_name IN ('view_item', 'add_to_cart', 'begin_checkout', 'purchase')
)
SELECT * FROM product_funnel
PIVOT (
  COUNT(DISTINCT session_key)
  FOR event_name IN ('view_item', 'add_to_cart', 'begin_checkout', 'purchase')
)
ORDER BY view_item DESC
```

## Market Basket Analysis (Co-Purchase Pairs)

Find products frequently bought together:

```sql
WITH purchase_items AS (
  SELECT
    ecommerce.transaction_id,
    items.item_name
  FROM `{project}.{dataset}.events_*`,
    UNNEST(items) AS items
  WHERE event_name = 'purchase'
    AND ecommerce.transaction_id IS NOT NULL
    AND items.item_name IS NOT NULL
    AND _table_suffix BETWEEN '{start}' AND '{end}'
),
product_pairs AS (
  SELECT
    a.item_name AS product_a,
    b.item_name AS product_b,
    a.transaction_id
  FROM purchase_items a
  JOIN purchase_items b ON a.transaction_id = b.transaction_id
  WHERE a.item_name < b.item_name  -- avoid duplicate pairs and self-joins
)
SELECT
  product_a,
  product_b,
  COUNT(DISTINCT transaction_id) AS times_bought_together
FROM product_pairs
GROUP BY 1, 2
ORDER BY 3 DESC
LIMIT 50
```

## Conversion Rate by Product (View → Purchase)

```sql
WITH product_views AS (
  SELECT items.item_name, COUNT(DISTINCT user_pseudo_id) AS viewers
  FROM `{project}.{dataset}.events_*`, UNNEST(items) AS items
  WHERE event_name = 'view_item'
    AND _table_suffix BETWEEN '{start}' AND '{end}'
  GROUP BY 1
),
product_purchases AS (
  SELECT items.item_name, COUNT(DISTINCT user_pseudo_id) AS buyers
  FROM `{project}.{dataset}.events_*`, UNNEST(items) AS items
  WHERE event_name = 'purchase'
    AND _table_suffix BETWEEN '{start}' AND '{end}'
  GROUP BY 1
)
SELECT
  v.item_name,
  v.viewers,
  COALESCE(p.buyers, 0) AS buyers,
  SAFE_DIVIDE(p.buyers, v.viewers) AS conversion_rate
FROM product_views v
LEFT JOIN product_purchases p ON v.item_name = p.item_name
ORDER BY viewers DESC
```

## Revenue by Traffic Source

```sql
SELECT
  session_traffic_source_last_click.manual_campaign.source AS source,
  session_traffic_source_last_click.manual_campaign.medium AS medium,
  COUNT(DISTINCT CASE WHEN event_name = 'purchase' THEN ecommerce.transaction_id END) AS transactions,
  SUM(CASE WHEN event_name = 'purchase' THEN ecommerce.purchase_revenue END) AS revenue,
  COUNT(DISTINCT user_pseudo_id) AS users,
  SAFE_DIVIDE(
    COUNT(DISTINCT CASE WHEN event_name = 'purchase' THEN ecommerce.transaction_id END),
    COUNT(DISTINCT CONCAT(user_pseudo_id, CAST(
      (SELECT value.int_value FROM UNNEST(event_params) WHERE key = 'ga_session_id') AS STRING)))
  ) AS ecommerce_conversion_rate
FROM `{project}.{dataset}.events_*`
WHERE _table_suffix BETWEEN '{start}' AND '{end}'
GROUP BY 1, 2
ORDER BY revenue DESC
```

## Common Mistakes

1. **Missing event_name filter**: Querying `items.quantity` without filtering purchase event includes view_item, add_to_cart quantities
2. **Double-counting revenue**: Using `SUM(ecommerce.purchase_revenue)` after UNNEST items multiplies revenue by item count
3. **NULL transaction_id**: Some purchase events may have NULL transaction_id — filter with `AND ecommerce.transaction_id IS NOT NULL`
4. **Refund handling**: Refund events have positive `refund_value` — subtract from revenue, don't add
