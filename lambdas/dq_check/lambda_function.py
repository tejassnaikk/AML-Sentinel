"""Cloud DQ gate: validate the Bronze object the ingest step just wrote."""
import datetime
import os
import boto3

s3 = boto3.client("s3")
MIN_BYTES = 100_000_000  # raw CSV should be ~475MB; anything under 100MB is a broken load
MAX_AGE_HOURS = 48

def lambda_handler(event, context):
    bucket = os.environ["BRONZE_BUCKET"]
    key = event["bronze_key"]  # passed from the ingest step's output
    head = s3.head_object(Bucket=bucket, Key=key)

    failures = []
    size = head["ContentLength"]
    if size < MIN_BYTES:
        failures.append(f"size {size} < {MIN_BYTES}")

    ts_raw = head.get("Metadata", {}).get("ingestion_timestamp")
    if not ts_raw:
        failures.append("missing ingestion_timestamp metadata")
    else:
        age = datetime.datetime.now(datetime.timezone.utc) - datetime.datetime.fromisoformat(ts_raw)
        if age.total_seconds() > MAX_AGE_HOURS * 3600:
            failures.append(f"stale: ingested {age} ago (max {MAX_AGE_HOURS}h)")

    if failures:
        # raising makes Step Functions route to the failure/alert branch
        raise Exception("DQ FAIL: " + "; ".join(failures))

    return {"dq": "pass", "bronze_key": key, "size_bytes": size, "ingestion_timestamp": ts_raw}
