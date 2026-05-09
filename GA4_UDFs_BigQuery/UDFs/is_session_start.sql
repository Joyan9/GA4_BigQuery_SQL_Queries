/*
  UDF: is_session_start
  Purpose: Returns TRUE if the event is a session_start event, which marks
  the beginning of a new session in GA4. Useful when building session-level
  aggregations where you need to count sessions or join on session-level
  attributes (e.g. traffic source, landing page) that are only reliably
  captured on the session_start event.
*/
CREATE OR REPLACE FUNCTION `your_project.your_dataset.is_session_start`(
  event_name STRING
)
RETURNS BOOL AS (
  event_name = 'session_start'
);
