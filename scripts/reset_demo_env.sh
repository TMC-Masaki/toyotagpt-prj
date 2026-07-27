#!/usr/bin/env bash
set -euo pipefail

API_BASE="${API_BASE:-http://127.0.0.1:8000}"
EVENT_ROOT="${EVENT_ROOT:-/mnt/vlm_data/logs/events}"
S3_BUCKET="${S3_BUCKET:-toyotagpt-masaki}"
S3_PREFIX_BASE="${S3_PREFIX_BASE:-events}"
DDB_TABLE="${DDB_TABLE:-toyotagpt-eventdb}"
AWS_REGION="${AWS_REGION:-ap-northeast-1}"
SKIP_AWS="${SKIP_AWS:-0}"

echo "### capture current states"
UPLOAD_ENABLED="$(curl -sS "${API_BASE}/config" | python3 -c 'import sys,json; print("true" if json.load(sys.stdin).get("upload",{}).get("enabled") else "false")')"
SCHED_RUNNING="$(curl -sS "${API_BASE}/scheduler/status" | python3 -c 'import sys,json; print("true" if json.load(sys.stdin).get("running") else "false")')"
echo "upload_enabled=${UPLOAD_ENABLED}"
echo "scheduler_running=${SCHED_RUNNING}"

echo
echo "### stop upload + scheduler"
curl -sS -X POST "${API_BASE}/config" \
  -H 'Content-Type: application/json' \
  -d '{"upload_enabled": false}' >/dev/null || true
curl -sS -X POST "${API_BASE}/scheduler/stop" >/dev/null || true
sleep 2

echo
echo "### reset local event dirs"
sudo mkdir -p "${EVENT_ROOT}"

# remove state dirs
for d in pending approved uploaded failed rejected sessions; do
  sudo rm -rf "${EVENT_ROOT:?}/${d}"
done

# remove legacy flat event dirs directly under EVENT_ROOT
sudo find "${EVENT_ROOT}" -maxdepth 1 -mindepth 1 -type d \
  ! -name pending \
  ! -name approved \
  ! -name uploaded \
  ! -name failed \
  ! -name rejected \
  ! -name sessions \
  -exec rm -rf {} +

# recreate canonical dirs
for d in pending approved uploaded failed rejected sessions; do
  sudo mkdir -p "${EVENT_ROOT}/${d}"
done

# permissions: keep local demo dirs operable from host side too
sudo chown -R "$(id -u)":"$(id -g)" "${EVENT_ROOT}" || true

echo
echo "### verify local dirs"
find "${EVENT_ROOT}" -maxdepth 1 -mindepth 1 -type d | sort

if [ "${SKIP_AWS}" != "1" ]; then
  echo
  echo "### clear S3 + DynamoDB"
  sudo docker exec \
    -e RESET_BUCKET="${S3_BUCKET}" \
    -e RESET_PREFIX="${S3_PREFIX_BASE}" \
    -e RESET_TABLE="${DDB_TABLE}" \
    -e AWS_DEFAULT_REGION="${AWS_REGION}" \
    vlm_platform sh -lc '
python3 - <<'"'"'PY'"'"'
import os
import boto3

bucket = os.environ["RESET_BUCKET"]
prefix = os.environ["RESET_PREFIX"].strip("/")
table_name = os.environ["RESET_TABLE"]
region = os.environ.get("AWS_DEFAULT_REGION", "ap-northeast-1")

session = boto3.session.Session(region_name=region)
s3 = session.client("s3")
ddb = session.resource("dynamodb")
table = ddb.Table(table_name)

# S3 delete
paginator = s3.get_paginator("list_objects_v2")
deleted_s3 = 0
for page in paginator.paginate(Bucket=bucket, Prefix=prefix + "/"):
    objs = [{"Key": x["Key"]} for x in page.get("Contents", [])]
    for i in range(0, len(objs), 1000):
        chunk = objs[i:i+1000]
        if chunk:
            s3.delete_objects(Bucket=bucket, Delete={"Objects": chunk})
            deleted_s3 += len(chunk)

# DynamoDB delete all
deleted_ddb = 0
scan_kwargs = {
    "ProjectionExpression": "#pk",
    "ExpressionAttributeNames": {"#pk": "event-id"},
}
last = None
with table.batch_writer() as batch:
    while True:
        if last:
            scan_kwargs["ExclusiveStartKey"] = last
        resp = table.scan(**scan_kwargs)
        items = resp.get("Items", [])
        for item in items:
            pk = item.get("event-id")
            if pk is not None:
                batch.delete_item(Key={"event-id": pk})
                deleted_ddb += 1
        last = resp.get("LastEvaluatedKey")
        if not last:
            break

print(f"S3 deleted: {deleted_s3}")
print(f"DynamoDB deleted: {deleted_ddb}")
PY
'
else
  echo
  echo "### SKIP_AWS=1: skip S3/DynamoDB clear"
fi

echo
echo "### restore previous states"
if [ "${SCHED_RUNNING}" = "true" ]; then
  curl -sS -X POST "${API_BASE}/scheduler/start" >/dev/null || true
fi

if [ "${UPLOAD_ENABLED}" = "true" ]; then
  curl -sS -X POST "${API_BASE}/config" \
    -H 'Content-Type: application/json' \
    -d '{"upload_enabled": true}' >/dev/null || true
else
  curl -sS -X POST "${API_BASE}/config" \
    -H 'Content-Type: application/json' \
    -d '{"upload_enabled": false}' >/dev/null || true
fi

echo
echo "### final check"
curl -sS "${API_BASE}/config" | jq '.upload'
curl -sS "${API_BASE}/scheduler/status" | jq .
echo -n "pending   = "; find "${EVENT_ROOT}/pending"  -maxdepth 1 -mindepth 1 -type d | wc -l
echo -n "approved  = "; find "${EVENT_ROOT}/approved" -maxdepth 1 -mindepth 1 -type d | wc -l
echo -n "uploaded  = "; find "${EVENT_ROOT}/uploaded" -maxdepth 1 -mindepth 1 -type d | wc -l
echo -n "failed    = "; find "${EVENT_ROOT}/failed"   -maxdepth 1 -mindepth 1 -type d | wc -l
echo -n "rejected  = "; find "${EVENT_ROOT}/rejected" -maxdepth 1 -mindepth 1 -type d | wc -l
