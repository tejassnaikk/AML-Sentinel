"""Ingest: copy source CSV -> Bronze, stamping ingestion_timestamp metadata."""
import datetime
import os
import boto3

s3 = boto3.client("s3")

def lambda_handler(event, context):
    src_bucket = os.environ["SOURCE_BUCKET"]
    src_key = os.environ["SOURCE_KEY"]
    dst_bucket = os.environ["BRONZE_BUCKET"]
    ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
    dst_key = f"raw_tx/ingest_date={ts[:10]}/HI-Small_Trans.csv"

    s3.copy_object(
        Bucket=dst_bucket,
        Key=dst_key,
        CopySource={"Bucket": src_bucket, "Key": src_key},
        Metadata={"ingestion_timestamp": ts},
        MetadataDirective="REPLACE",
    )
    head = s3.head_object(Bucket=dst_bucket, Key=dst_key)
    return {
        "status": "ok",
        "bronze_key": dst_key,
        "ingestion_timestamp": ts,
        "size_bytes": head["ContentLength"],
    }
