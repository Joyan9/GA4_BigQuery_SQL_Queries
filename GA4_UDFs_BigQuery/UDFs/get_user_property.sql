/*
  UDF: get_user_property
  Purpose: Extracts a user property value from the user_properties array by key.
  User properties in GA4 follow the same key-value STRUCT pattern as event_params
  but sit on the user_properties field. Useful for segmenting by user-level attributes
  like membership tier, user type, or any custom property you're collecting.
*/
CREATE OR REPLACE FUNCTION `your_project.your_dataset.get_user_property`(
  user_properties ARRAY<STRUCT
    key STRING,
    value STRUCT
      string_value STRING,
      int_value INT64,
      float_value FLOAT64,
      double_value FLOAT64,
      set_timestamp_micros INT64
    >
  >>,
  property_key STRING
)
RETURNS STRING AS ((
  SELECT
    COALESCE(
      up.value.string_value,
      CAST(up.value.int_value AS STRING),
      CAST(up.value.float_value AS STRING),
      CAST(up.value.double_value AS STRING)
    )
  FROM UNNEST(user_properties) AS up
  WHERE up.key = property_key
  LIMIT 1
));









