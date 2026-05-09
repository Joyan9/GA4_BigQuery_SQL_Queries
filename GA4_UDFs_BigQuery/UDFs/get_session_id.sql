/*
  UDF: get_session_id
  Purpose: Extracts the GA4 session ID from event_params so queries can group
  or join events by session without repeating the UNNEST logic everywhere.
*/
CREATE OR REPLACE FUNCTION `your_project.your_dataset.get_session_id`(
  event_params ARRAY<STRUCT<
    key STRING,
    value STRUCT<
      string_value STRING,
      int_value INT64,
      float_value FLOAT64,
      double_value FLOAT64
    >
  >>
)
RETURNS INT64 AS ((
  SELECT ep.value.int_value
  FROM UNNEST(event_params) AS ep
  WHERE ep.key = 'ga_session_id'
  LIMIT 1
));