# GA4 Data Generator & dlt BigQuery Uploader

This project has been separated into two independent scripts:

## 1. **ga4_generator.py** — Data Generation
Generates 90 days of realistic GA4 e-commerce event data with injected anomalies.

**Outputs:**
- `outputs/events_YYYYMMDD.jsonl` — Daily event files in BigQuery-ready NDJSON format (one file per day)
- `outputs/ga4_schema.json` — BigQuery JSON schema
- `outputs/anomaly_manifest.csv` — Anomaly registry with metadata

**Run:**
```bash
python ga4_generator.py
```

## 2. **ga4_uploader_dlt.py** — dlt-Based BigQuery Upload
Uses the [dlt (Data Load Tool)](https://dlthub.com) library to load events into BigQuery.

**Key Features:**
- ✅ **NO UNNESTING** — Nested structures (`event_params`, `items`, etc.) preserved as-is
- Processes all daily event files from the outputs directory
- Configurable via `.env` file
- Progress logging and error handling
- Supports `WRITE_TRUNCATE`, `WRITE_APPEND`, `WRITE_EMPTY` dispositions

**Run:**
```bash
python ga4_uploader_dlt.py [path_to_jsonl_or_directory]

# Default (uses ./outputs/ directory with all events_*.jsonl files):
python ga4_uploader_dlt.py
```

---

## Setup

### Prerequisites
```bash
pip install -r requirements.txt
```

### Configure BigQuery Credentials

Create a `.env` file in the project root with BigQuery configuration:

```bash
# BigQuery Credentials (choose one):
# Option A: Path to service account JSON file
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account-key.json

# Option B: Inline service account JSON
GOOGLE_SERVICE_ACCOUNT_JSON={"type": "service_account", ...}

# BigQuery Configuration
GOOGLE_CLOUD_PROJECT=your-gcp-project-id
BIGQUERY_DATASET_ID=your_dataset_name
BIGQUERY_TABLE_ID=ga4_events          # Optional, defaults to ga4_events
BIGQUERY_LOCATION=US                  # Optional, defaults to US
BQ_WRITE_DISPOSITION=WRITE_TRUNCATE   # WRITE_TRUNCATE (default), WRITE_APPEND, or WRITE_EMPTY
```

### Service Account Setup

If you don't have a service account yet:

1. **Create a service account in GCP:**
   ```bash
   gcloud iam service-accounts create ga4-loader \
     --display-name="GA4 Data Loader"
   ```

2. **Grant BigQuery Admin role:**
   ```bash
   gcloud projects add-iam-policy-binding YOUR_PROJECT \
     --member="serviceAccount:ga4-loader@YOUR_PROJECT.iam.gserviceaccount.com" \
     --role="roles/bigquery.admin"
   ```

3. **Create and download key:**
   ```bash
   gcloud iam service-accounts keys create sa-key.json \
     --iam-account=ga4-loader@YOUR_PROJECT.iam.gserviceaccount.com
   ```

4. **Add to `.env`:**
   ```bash
   GOOGLE_APPLICATION_CREDENTIALS=./sa-key.json
   ```

---

## Workflow

### Step 1: Generate Data
```bash
$ python ga4_generator.py
GA4 Sample Data Generator
Generating 91 days of data (2024-10-01 → 2024-12-30)

Generating events...
  Processing day 1/91: 2024-10-01
  ...
  Processing day 91/2024-12-30

Writing 412,857 events across 91 days...
  20241001: 4,520 events → events_20241001.jsonl
  20241002: 5,180 events → events_20241002.jsonl
  ...
  20241230: 4,890 events → events_20241230.jsonl
  Done.
Writing schema to ./outputs/ga4_schema.json ...
  Done.
Writing anomaly manifest to ./outputs/anomaly_manifest.csv ...
  Done.

[Output summary with anomaly statistics]
```

### Step 2: Upload to BigQuery
```bash
$ python ga4_uploader_dlt.py
======================================================================
GA4 Events BigQuery Uploader (dlt)
======================================================================

Configuration:
  Dataset ID: your_dataset_name
  Table ID:   ga4_events
  Project ID: your-gcp-project-id

Loading events from ./outputs/...
  Found 91 daily event files

Setting up dlt pipeline...
  Destination: BigQuery
  Table: your_dataset_name.ga4_events
  Data flattening depth: 0 (NO UNNESTING — preserves nested structures)

Uploading 412,857 events to BigQuery ...

======================================================================
Upload Complete!
======================================================================
  Events loaded: 412,857
  Status: Succeeded
  
✓ All events successfully uploaded!
======================================================================
```

---

## Important: NO UNNESTING

By default, dlt **unnests** nested records, flattening them into separate tables or columns. 

This pipeline **explicitly disables unnesting** with:
```python
"data_flattening_depth": 0
```

This ensures nested structures remain intact:
- ✅ `event_params` stays as ARRAY<STRUCT<key, value>>
- ✅ `items` stays as ARRAY<STRUCT<...>>
- ✅ `device` stays as STRUCT<category, os, web_info, ...>

If you **want unnesting**, modify `ga4_uploader_dlt.py`:
```python
# Change:
"data_flattening_depth": 0,
# To:
"data_flattening_depth": 2,  # or higher for deeper unnesting
```

---

## Project Structure

```
.
├── ga4_data_generator.py         # Data generation script
├── ga4_uploader_dlt.py           # dlt-based uploader
├── requirements.txt              # Python dependencies
├── .env                          # Configuration (create this)
├── outputs/
│   ├── events_20251001.jsonl     # Daily event files (NDJSON)
│   ├── events_20251002.jsonl
│   ├── ...
│   ├── events_20251231.jsonl
│   ├── ga4_schema.json           # BigQuery schema
│   └── anomaly_manifest.csv      # Anomaly metadata
└── README.md                     # This file
```

---

## Troubleshooting

### Error: "BIGQUERY_DATASET_ID not set"
Make sure your `.env` file exists and contains `BIGQUERY_DATASET_ID`.

### Error: "No BigQuery credentials found"
Verify one of these is set in `.env`:
- `GOOGLE_APPLICATION_CREDENTIALS` (path to JSON file)
- `GOOGLE_SERVICE_ACCOUNT_JSON` (inline JSON)

### Error: "Invalid JSON on line X"
The JSONL file is corrupted. Regenerate with:
```bash
python ga4_generator.py
```

### Error: "Permission denied" during upload
The service account needs `roles/bigquery.admin` role.

### dlt not installed
Install with:
```bash
pip install dlt[bigquery]
```

---

## Customization

### Change Output Directory
In `ga4_generator.py`, modify:
```python
OUTPUT_DIR = "./outputs"  # Change this path
```

### Change Anomaly Windows
In `ga4_generator.py`, modify the date ranges:
```python
ANOMALY_A_PII_START   = datetime(2024, 10, 22)
ANOMALY_A_PII_END     = datetime(2024, 10, 27)
# ... etc
```

### Change Write Disposition
In `.env`:
```bash
BQ_WRITE_DISPOSITION=WRITE_APPEND    # Add to existing data
BQ_WRITE_DISPOSITION=WRITE_EMPTY     # Only write if table is empty
```


## Experiments

This generator can emit `experience_impression` events for experiments (A/B or multi-variant). Key points:

- **Event name:** `experience_impression`
- **Important event_param:** `exp_variant_string` — format: `<tool_id>-<experience_id>-<variant>` (example: `EXP-BF2025-01`).
- **When it fires:** On product detail page loads (PDPs). The generator emits impressions both for entrance page_views and subsequent product page_views.
- **Deterministic assignment:** Variants are assigned deterministically by hashing `user_pseudo_id + experience_id` and taking modulo `n_variants`, ensuring stable assignment across sessions.

Configuration lives in `ga4_data_generator.py` as the `EXPERIMENTS` mapping. Example:

```python
EXPERIMENTS = {
  "BF2025": {
    "tool_id": "EXP",
    "experience_id": "BF2025",
    "n_variants": 2,
    "start": datetime(2025, 11, 1),
    "end": datetime(2025, 11, 28),
    "pages": ["/products/"],  # prefix match for PDPs
    "sample_rate": 1.0,        # apply to all eligible users
  }
}
```

- **`pages`** accepts path prefixes — any page path that starts with a configured prefix is eligible.
- **`sample_rate`** (0.0–1.0) throttles how many eligible users receive the experiment.

The generator prints an impressions summary after running (`Experiment impressions:`) and includes per-date, per-variant counts. Use the `exp_variant_string` field to build audiences, segments, or to filter impressions in BigQuery.

---

## Anomalies Injected

| Anomaly | Type | Window | Description |
|---------|------|--------|-------------|
| **A** | PII Leakage | 2024-10-22 → 2024-10-27 | Email/phone/name leaked into query parameters |
| **B** | Cross-Domain Failure | 2024-11-05 → 2024-11-30 | Payment gateway referral loses session context |
| **C** | Missing session_start | 2024-11-14 → 2024-11-21 | GTM misconfiguration suppresses session_start events |
| **D** | Missing Attribution | 2024-12-03 → 2024-12-18 | CMP blocking analytics_storage before consent |

Details in `outputs/anomaly_manifest.csv`.

---

## Resources

- **dlt Documentation:** https://dlthub.com/docs
- **dlt BigQuery Destination:** https://dlthub.com/docs/dlt-ecosystem/destinations/bigquery
- **GA4 Export Schema:** https://support.google.com/analytics/answer/7029846

