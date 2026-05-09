/*
  UDF: categorise_device
  Purpose: Maps GA4's device.category values ('desktop', 'mobile', 'tablet')
  to a standardised label with consistent casing and an explicit fallback.
  GA4 device.category is generally clean but can return NULL or unexpected
  values in certain data collection setups. Having a single function that
  applies consistent labelling avoids scattered CASE blocks across queries
  and makes dashboards consistent when device is used as a dimension.
*/
CREATE OR REPLACE FUNCTION `your_project.your_dataset.categorise_device`(
  device_category STRING
)
RETURNS STRING AS (
  CASE LOWER(device_category)
    WHEN 'desktop' THEN 'Desktop'
    WHEN 'mobile'  THEN 'Mobile'
    WHEN 'tablet'  THEN 'Tablet'
    ELSE 'Unknown'
  END
);