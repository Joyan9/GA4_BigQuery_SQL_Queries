import duckdb

JSONL_PATH   = "./GA4_BigQuery_SQL_Queries/GA4_Sample_Data_Generator/outputs/ga4_events.jsonl"

con = duckdb.connect()
con.execute("SET memory_limit='1GB'")
con.execute("SET threads=4")

# Macros for extracting params
con.execute("""
    CREATE OR REPLACE MACRO ep_str(params, k) AS (
        (SELECT p.value.string_value FROM (SELECT unnest(params) AS p) WHERE p.key = k LIMIT 1)
    )
""")
con.execute("""
    CREATE OR REPLACE MACRO ep_int(params, k) AS (
        (SELECT p.value.int_value FROM (SELECT unnest(params) AS p) WHERE p.key = k LIMIT 1)
    )
""")

JSONL_SOURCE = f"read_json('{JSONL_PATH}', format='newline_delimited')"

# We use the existing CTE logic but change the final output to an AGGREGATE
sql = f"""
WITH session_base AS (
    SELECT
        user_pseudo_id,
        ep_int(event_params, 'ga_session_id') AS ga_session_id,
        MIN(event_timestamp) AS session_first_event_ts,
        -- Check if 'session_start' exists for this session
        MAX(CASE WHEN event_name = 'session_start' THEN 1 ELSE 0 END) AS has_session_start,
        -- Check for attribution
        FIRST(collected_traffic_source.manual_source ORDER BY event_timestamp) AS collected_source
    FROM {JSONL_SOURCE}
    GROUP BY user_pseudo_id, ga_session_id
)
SELECT 
    COUNT(*) AS total_sessions,
    
    -- Sessions without session_start
    SUM(CASE WHEN has_session_start = 0 THEN 1 ELSE 0 END) AS sessions_missing_start,
    ROUND(100.0 * SUM(CASE WHEN has_session_start = 0 THEN 1 ELSE 0 END) / COUNT(*), 2) AS pct_missing_start,

    -- Sessions missing attribution specifically when session_start is missing
    SUM(CASE WHEN has_session_start = 0 AND collected_source IS NULL THEN 1 ELSE 0 END) AS sessions_no_attribution_no_start,
    ROUND(100.0 * SUM(CASE WHEN has_session_start = 0 AND collected_source IS NULL THEN 1 ELSE 0 END) / COUNT(*), 2) AS pct_no_attribution_due_to_missing_start

FROM session_base
"""

def run(label, sql):
    print(f"\n{'='*80}")
    print(f"  {label}")
    print('='*80)
    result = con.execute(sql).df()
    print(result.to_string(index=False))

run("GA4 Session Integrity Analysis", sql)

con.close()