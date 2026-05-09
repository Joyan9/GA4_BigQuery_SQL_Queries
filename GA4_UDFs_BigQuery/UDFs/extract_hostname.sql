/*
  UDF: extract_hostname
  Purpose: Extracts just the hostname from a full page_location URL.
  GA4 captures the full URL including protocol and hostname in page_location,
  which becomes noise when you have a single-domain property and just want
  the path. Also useful for multi-domain setups where you need to filter or
  group by hostname before analysing paths.
*/
CREATE OR REPLACE FUNCTION `your_project.your_dataset.extract_hostname`(
  page_location STRING
)
RETURNS STRING AS (
  REGEXP_EXTRACT(page_location, r'^(?:https?://)?([^/?#]+)')
);
