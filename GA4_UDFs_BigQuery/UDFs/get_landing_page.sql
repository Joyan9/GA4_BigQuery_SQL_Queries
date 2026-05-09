/*
  UDF: get_landing_page
  Purpose: Identifies the landing page for a session by extracting page_location
  on the first page_view event of the session. In GA4 BigQuery exports there is
  no native landing_page column at the event level. The common workaround is a
  subquery or window function, but this UDF wraps the path-cleaning logic so it
  can be applied consistently once the first page_view has been identified.
  Strips query parameters to return a clean path only.
*/
CREATE OR REPLACE FUNCTION `your_project.your_dataset.get_landing_page`(
  page_location STRING
)
RETURNS STRING AS (
  REGEXP_EXTRACT(page_location, r'^(?:https?://[^/]+)?(/[^?#]*)')
);
