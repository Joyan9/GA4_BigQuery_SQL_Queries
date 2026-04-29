"""
GA4 Events Uploader using dlt (Data Load Tool)
==============================================
Uploads GA4 JSONL events to BigQuery using dlt library.

Key features:
  - Uses dlt to manage data pipeline
  - NO UNNESTING — data records remain nested as-is
  - Configurable via .env file
  - Supports incremental loading

Environment variables required:
  BIGQUERY_DATASET_ID      — BigQuery dataset name
  BIGQUERY_TABLE_ID        — BigQuery table name (default: ga4_events)
  GOOGLE_APPLICATION_CREDENTIALS or GOOGLE_SERVICE_ACCOUNT_JSON
  GOOGLE_CLOUD_PROJECT     — GCP project ID
"""

import os
import json
import sys
from pathlib import Path
from typing import Optional

import dlt


def load_env_file(env_path: str = ".env") -> None:
    """Load a local .env file without adding an extra dependency."""
    path = Path(env_path)
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def validate_config() -> dict:
    """Validate required BigQuery configuration."""
    config = {
        "dataset_id": os.environ.get("BIGQUERY_DATASET_ID", "").strip(),
        "table_id": os.environ.get("BIGQUERY_TABLE_ID", "ga4_events").strip() or "ga4_events",
        "project_id": os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip(),
    }

    if not config["dataset_id"]:
        raise RuntimeError(
            "BIGQUERY_DATASET_ID not set. Please add it to .env or set as environment variable."
        )

    if not config["project_id"]:
        raise RuntimeError(
            "GOOGLE_CLOUD_PROJECT not set. Please add it to .env or set as environment variable."
        )

    return config


def load_jsonl_file(jsonl_path: str) -> list:
    """Load JSONL file and return list of dicts."""
    path = Path(jsonl_path)
    if not path.exists():
        raise FileNotFoundError(f"JSONL file not found: {path}")

    events = []
    with open(path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
                events.append(event)
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON on line {line_num}: {e}")

    return events


def parse_service_account_json() -> dict:
    """Parse service account JSON from environment."""
    service_account_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    service_account_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()

    credentials = None

    if service_account_json:
        try:
            credentials = json.loads(service_account_json)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Invalid JSON in GOOGLE_SERVICE_ACCOUNT_JSON: {e}")
    elif service_account_path:
        path = Path(service_account_path)
        if not path.exists():
            raise FileNotFoundError(f"Service account file not found: {service_account_path}")
        try:
            credentials = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Invalid JSON in service account file {service_account_path}: {e}")
    else:
        raise RuntimeError(
            "No BigQuery credentials found. Set either:\n"
            "  - GOOGLE_APPLICATION_CREDENTIALS (path to service account JSON)\n"
            "  - GOOGLE_SERVICE_ACCOUNT_JSON (service account JSON content)\n"
            "In your .env file or environment."
        )

    # Extract required fields for dlt
    required_fields = ["project_id", "private_key", "client_email"]
    missing_fields = [f for f in required_fields if f not in credentials]

    if missing_fields:
        raise RuntimeError(
            f"Service account JSON missing required fields: {missing_fields}.\n"
            f"Valid fields found: {list(credentials.keys())}"
        )

    return {
        "project_id": credentials["project_id"],
        "private_key": credentials["private_key"],
        "client_email": credentials["client_email"],
    }


def setup_dlt_env_vars(credentials: dict) -> None:
    """Set environment variables in the format dlt expects for BigQuery."""
    # dlt looks for credentials in format: DESTINATION__BIGQUERY__CREDENTIALS__*
    os.environ["DESTINATION__BIGQUERY__CREDENTIALS__PROJECT_ID"] = credentials["project_id"]
    os.environ["DESTINATION__BIGQUERY__CREDENTIALS__PRIVATE_KEY"] = credentials["private_key"]
    os.environ["DESTINATION__BIGQUERY__CREDENTIALS__CLIENT_EMAIL"] = credentials["client_email"]
    
    # Disable strict schema inference to handle None values and mixed types
    os.environ["DATA__SCHEMA_CONTRACT"] = "ignore"
    os.environ["DATA__WARN_INCONSISTENT_COLUMNS"] = "false"


def upload_with_dlt(jsonl_path: str, table_name: Optional[str] = None) -> None:
    """Upload JSONL events to BigQuery using dlt with NO UNNESTING."""
    print("=" * 70)
    print("GA4 Events BigQuery Uploader (dlt)")
    print("=" * 70)

    # Load configuration
    load_env_file()
    config = validate_config()

    print(f"\nConfiguration:")
    print(f"  Dataset ID: {config['dataset_id']}")
    print(f"  Table ID:   {config['table_id']}")
    print(f"  Project ID: {config['project_id']}")

    # Parse service account credentials
    creds = parse_service_account_json()
    
    # Set up environment variables for dlt
    setup_dlt_env_vars(creds)

    # Load events from JSONL
    print(f"\nLoading events from {jsonl_path} ...")
    events = load_jsonl_file(jsonl_path)
    print(f"  Loaded {len(events):,} events")

    # Set table name
    table_name = table_name or config["table_id"]
    
    print(f"\nSetting up dlt pipeline...")
    print(f"  Destination: BigQuery")
    print(f"  Table: {config['dataset_id']}.{table_name}")
    print(f"  Data flattening depth: 0 (NO UNNESTING - preserves nested structures)")

    try:
        # Create a dlt resource with NO UNNESTING (max_table_nesting=0)
        @dlt.resource(
            name=table_name,
            write_disposition="replace",  # Replace all existing data
            max_table_nesting=0,  # CRITICAL: Prevents unnesting - keeps nested data as JSON
        )
        def ga4_events():
            """Yield GA4 events from loaded data."""
            for event in events:
                yield event

        # Create pipeline
        pipeline = dlt.pipeline(
            pipeline_name="ga4_loader",
            destination="bigquery",
            dataset_name=config["dataset_id"],
        )

        # Drop any leftover state/pending packages from previous runs
        pipeline.drop()

        # Load the data
        print(f"\nUploading {len(events):,} events to BigQuery ...")
        load_info = pipeline.run(ga4_events())

        # Print load summary
        print("\n" + "=" * 70)
        print("Upload Complete!")
        print("=" * 70)
        print(f"  Events loaded: {len(events):,}")
        print(f"  Status: Success")
        
        # Print the result
        if hasattr(load_info, 'loads_ids') and load_info.loads_ids:
            print(f"  Load IDs: {', '.join(load_info.loads_ids)}")
        
        print(f"\n[SUCCESS] All {len(events):,} events successfully uploaded to BigQuery!")
        print("=" * 70)

    except Exception as e:
        print(f"\n[ERROR] Error during upload: {e}")
        print("\nDebugging tips:")
        print("  1. Verify GOOGLE_APPLICATION_CREDENTIALS or GOOGLE_SERVICE_ACCOUNT_JSON")
        print("  2. Check that BIGQUERY_DATASET_ID exists in your BigQuery project")
        print("  3. Verify service account has bigquery.admin role")
        print("  4. Ensure max_table_nesting=0 is set to prevent unnesting")
        raise


def main():
    """Entry point for the uploader script."""
    # Get JSONL path from command line or default
    if len(sys.argv) > 1:
        jsonl_path = sys.argv[1]
    else:
        # Default path
        jsonl_path = "./outputs/ga4_events.jsonl"

    # Check if file exists
    if not Path(jsonl_path).exists():
        print(f"Error: JSONL file not found: {jsonl_path}")
        print(f"\nUsage: python ga4_uploader_dlt.py [path_to_jsonl]")
        print(f"\nExample:")
        print(f"  python ga4_uploader_dlt.py ./outputs/ga4_events.jsonl")
        sys.exit(1)

    # Upload
    upload_with_dlt(jsonl_path)


if __name__ == "__main__":
    main()
