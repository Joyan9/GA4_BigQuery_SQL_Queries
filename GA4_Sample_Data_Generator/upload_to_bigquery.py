import os
import json
from dotenv import load_dotenv
from google.cloud import bigquery
from google.oauth2 import service_account

# Load environment variables from .env file
load_dotenv()

# --- CONFIGURATION ---
DIRECTORY_PATH = './outputs'
SCHEMA_PATH = './outputs/ga4_schema.json'

def get_required_env(name):
    """Return required environment variable value or raise a clear error."""
    value = os.getenv(name)
    if value is None or not value.strip():
        raise ValueError(f"Missing required environment variable: {name}")
    return value.strip()

def load_schema(schema_path):
    """Loads a standard BigQuery JSON schema file."""
    with open(schema_path, 'r') as f:
        schema_data = json.load(f)
    
    # Map the JSON list to BigQuery SchemaField objects
    return [bigquery.SchemaField.from_api_repr(field) for field in schema_data]

def upload_jsonl_to_bigquery():
    project_id = get_required_env("GOOGLE_CLOUD_PROJECT")
    dataset_id = get_required_env("BIGQUERY_DATASET_ID")

    # 1. Authenticate using the inline JSON from .env
    service_account_info = json.loads(get_required_env("GOOGLE_SERVICE_ACCOUNT_JSON"))
    credentials = service_account.Credentials.from_service_account_info(service_account_info)
    
    client = bigquery.Client(project=project_id, credentials=credentials)
    dataset_ref = client.dataset(dataset_id)

    # 2. Load your custom schema
    table_schema = load_schema(SCHEMA_PATH)

    # 3. Configure the load job
    job_config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        schema=table_schema,
        autodetect=False,  # We use your explicit schema instead
        time_partitioning=bigquery.TimePartitioning(
            type_=bigquery.TimePartitioningType.DAY
        ),
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )

    # Loop through the directory
    for filename in os.listdir(DIRECTORY_PATH):
        if filename.endswith(".jsonl"):
            file_path = os.path.join(DIRECTORY_PATH, filename)
            table_name = os.path.splitext(filename)[0]
            table_ref = dataset_ref.table(table_name)

            print(f"Uploading {filename}...")

            with open(file_path, "rb") as source_file:
                load_job = client.load_table_from_file(
                    source_file, table_ref, job_config=job_config
                )

            load_job.result()  # Wait for completion
            print(f"Done. Loaded {load_job.output_rows} rows into {table_name}.")

if __name__ == "__main__":
    upload_jsonl_to_bigquery()