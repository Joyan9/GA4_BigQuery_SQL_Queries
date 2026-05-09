/*
  UDF: micros_to_seconds
  Purpose: Converts a microsecond timestamp or duration into seconds.
  GA4 exports several fields in microseconds: event_timestamp, user_first_touch_timestamp,
  and engagement_time_msec (which is actually in microseconds despite the name).
  Having this as a UDF avoids the repeated SAFE_DIVIDE or division pattern
  and makes the intent explicit in the query.
*/
CREATE OR REPLACE FUNCTION `your_project.your_dataset.micros_to_seconds`(
  micros INT64
)
RETURNS FLOAT64 AS (
  SAFE_DIVIDE(micros, 1000000)
);