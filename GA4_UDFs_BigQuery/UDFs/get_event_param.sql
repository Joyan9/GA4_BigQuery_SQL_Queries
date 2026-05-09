
/*
  UDF: get_event_param
  Purpose: Returns the requested event parameter from event_params by key,
  normalising the stored value to a string for easier reuse in queries.
*/
CREATE OR REPLACE FUNCTION `your_project.your_dataset.get_event_param`(
  event_params ARRAY<STRUCT<
    key STRING,
    value STRUCT<
      string_value STRING,
      int_value INT64,
      float_value FLOAT64,
      double_value FLOAT64
    >
  >>,
  param_key STRING
)
RETURNS STRING AS ((
  SELECT
    COALESCE(
      ep.value.string_value,
      CAST(ep.value.int_value AS STRING),
      CAST(ep.value.float_value AS STRING),
      CAST(ep.value.double_value AS STRING)
    )
  FROM UNNEST(event_params) AS ep
  WHERE ep.key = param_key
  LIMIT 1
));