# GA4 Sample Data Generator

Generate realistic GA4-style ecommerce events, upload them to BigQuery, and run insight/anomaly SQL queries.

## Current Contents

- `ga4_data_generator.py`: Generates daily GA4-style NDJSON event files and supporting metadata.
- `upload_to_bigquery.py`: Uploads generated `.jsonl` files to BigQuery (one table per file).
- `sample_bigquery_insights_queries.md`: Ready-to-run BigQuery queries for KPI and anomaly analysis.
- `data_exploration.ipynb`: Notebook for ad-hoc validation/exploration.
- `outputs/`: Generated data files (`events_YYYYMMDD.jsonl`, schema, anomaly manifest).

## What Gets Generated

Running the generator writes:

- `outputs/events_YYYYMMDD.jsonl` (daily event files)
- `outputs/ga4_schema.json` (BigQuery JSON schema)
- `outputs/anomaly_manifest.csv` (anomaly registry)

Default generation window in code:

- Start: `2025-10-01`
- End: `2025-12-31`

## Setup

Install dependencies:

```bash
pip install -r requirements.txt
```

Create a `.env` file:

```bash
GOOGLE_CLOUD_PROJECT=your-gcp-project-id
BIGQUERY_DATASET_ID=your_dataset_name
GOOGLE_SERVICE_ACCOUNT_JSON={"type":"service_account", ...}
```

## Workflow

### 1) Generate GA4 sample data

```bash
python ga4_data_generator.py
```

### 2) Upload generated files to BigQuery

```bash
python upload_to_bigquery.py
```

Upload behavior:

- Reads all `.jsonl` files in `./outputs`
- Creates/overwrites one BigQuery table per file (for example `events_20251001`)
- Uses schema from `./outputs/ga4_schema.json`
- Uses `WRITE_TRUNCATE`

### 3) Query insights

Use:

- `sample_bigquery_insights_queries.md`

This file includes sample SQL for traffic trends, funnels, revenue, experiment analysis, and anomaly detection.

## Experiments

The generator emits `experience_impression` events with event parameter `exp_variant_string` (example `EXP-BF2025-01`).

Experiment configuration is in `ga4_data_generator.py` (`EXPERIMENTS` mapping).

## Injected Anomalies

The generator injects these anomalies by date window:

- A: PII leakage in URL/referrer params (`2025-10-22` to `2025-10-27`)
- B: Cross-domain attribution break (`2025-11-05` to `2025-11-30`)
- C: Missing `session_start` events (`2025-11-14` to `2025-11-21`)
- D: Missing attribution (`2025-12-03` to `2025-12-18`)
- E: Session-timeout style sessions (`2025-12-19` to `2025-12-29`)

See `outputs/anomaly_manifest.csv` for details.


## Reference

- GA4 BigQuery export schema overview:
  https://support.google.com/analytics/answer/7029846

