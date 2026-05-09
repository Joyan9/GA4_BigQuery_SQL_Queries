/*
  UDF: get_session_source_medium
  Purpose: Constructs a source / medium string from the collected_traffic_source
  field available in GA4 BigQuery exports. Returns in the standard GA format
  "source / medium" (e.g. "google / cpc", "newsletter / email").
  Falls back to "(direct) / (none)" when both values are null, matching how
  GA4 itself handles unattributed sessions.
*/
CREATE OR REPLACE FUNCTION `your_project.your_dataset.get_session_source_medium`(
  manual_source STRING,
  manual_medium STRING
)
RETURNS STRING AS (
  CONCAT(
    COALESCE(manual_source, '(direct)'),
    ' / ',
    COALESCE(manual_medium, '(none)')
  )
);
