# GA4 Data Generator & dlt BigQuery Uploader

This project has been separated into two independent scripts:

## 1. **ga4_generator.py** — Data Generation
Generates 90 days of realistic GA4 e-commerce event data with injected anomalies.

**Outputs:**
- `outputs/ga4_events.jsonl` — BigQuery-ready NDJSON (one event per line)
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
- Configurable via `.env` file
- Progress logging and error handling
- Supports `WRITE_TRUNCATE`, `WRITE_APPEND`, `WRITE_EMPTY` dispositions

**Run:**
```bash
python ga4_uploader_dlt.py [path_to_jsonl]

# Default (uses ./outputs/ga4_events.jsonl):
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

Writing 412,857 events to ./outputs/ga4_events.jsonl ...
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

Loading events from ./outputs/ga4_events.jsonl ...
  Loaded 412,857 events

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
├── ga4_generator.py              # Data generation script
├── ga4_uploader_dlt.py           # dlt-based uploader
├── requirements.txt              # Python dependencies
├── .env                          # Configuration (create this)
├── outputs/
│   ├── ga4_events.jsonl          # Generated events (NDJSON)
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

