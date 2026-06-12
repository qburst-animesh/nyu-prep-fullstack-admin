import os
import json
import time
import csv
import io
import urllib.request
import urllib.parse
from typing import Optional

import boto3
from botocore.exceptions import ClientError
import posixpath as pp

# Environment configuration
BACKEND_VERIFY_URL = os.getenv('BACKEND_VERIFY_URL')
VERIFY_SECRET = os.getenv('VERIFY_SECRET')
SUMMARY_BUCKET_NAME = os.getenv('SUMMARY_BUCKET_NAME')
MAX_ROWS_TO_VALIDATE = int(os.getenv('MAX_ROWS_TO_VALIDATE', '1000'))
VALIDATE_FULL_FILE = os.getenv('VALIDATE_FULL_FILE', 'false').lower() in ('1', 'true', 'yes')
FAILED_PREFIX = os.getenv('FAILED_PREFIX', 'failed/')
COPY_ON_FAILURE = os.getenv('COPY_ON_FAILURE', 'true').lower() in ('1', 'true', 'yes')
S3_READ_RETRIES = int(os.getenv('S3_READ_RETRIES', '3'))
SAMPLE_ROWS = int(os.getenv('SAMPLE_ROWS', '5'))

s3_client = boto3.client('s3')


def should_skip_key(key: str) -> bool:
    # Prevent recursive processing of generated artifacts and failed copies.
    return key.endswith('.summary.json') or key.startswith(FAILED_PREFIX)


def summary_key_for_csv(key: str) -> str:
    """Return the summary JSON key: just the CSV filename with .summary.json extension.
    This is stored in the dedicated SUMMARY_BUCKET_NAME.

    Examples:
      - "uploads/2026-06-10/file.csv" -> "file.csv.summary.json"
      - "file.csv" -> "file.csv.summary.json"
    """
    basename = pp.basename(key)
    return f"{basename}.summary.json"


def derive_backend_base(verify_url: Optional[str]) -> str:
    if not verify_url:
        return ''
    # Prefer to trim off the /files/... portion so we end up with the API base (e.g. https://host/api/v1)
    try:
        idx = verify_url.find('/files')
        if idx != -1:
            return verify_url[:idx]
    except Exception:
        pass
    p = urllib.parse.urlparse(verify_url)
    path = p.path or ''
    if path.endswith('/verify'):
        path = path[: path.rfind('/verify')]
    return urllib.parse.urlunparse((p.scheme, p.netloc, path, '', '', ''))


BACKEND_BASE_URL = os.getenv('BACKEND_BASE_URL') or derive_backend_base(BACKEND_VERIFY_URL)


def http_post_json(url: str, data: dict, headers: Optional[dict] = None, timeout: int = 10, method: str = 'POST'):
    body = json.dumps(data).encode('utf-8')
    req_headers = {'Content-Type': 'application/json', **(headers or {})}
    # urllib.request.Request supports a 'method' kwarg on recent Python versions
    req = urllib.request.Request(url, data=body, headers=req_headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        resp_body = resp.read().decode('utf-8')
        try:
            return resp.getcode(), json.loads(resp_body)
        except Exception:
            return resp.getcode(), resp_body


def call_backend_verify(s3_key: str, file_size_bytes: int | None = None, bucket: str | None = None):
    """Call backend verify endpoint with helpful metadata to aid matching.

    Sends `s3_key` plus optional `file_size_bytes` and `bucket` so the
    backend can robustly match existing DB records when keys differ.
    """
    # Determine the verify URL. Support either a full verify URL or a base URL.
    verify_url = None
    if BACKEND_VERIFY_URL:
        if '/api/v1/files' in BACKEND_VERIFY_URL:
            verify_url = BACKEND_VERIFY_URL
        else:
            verify_url = BACKEND_VERIFY_URL.rstrip('/') + '/api/v1/files/verify'
    elif BACKEND_BASE_URL:
        verify_url = BACKEND_BASE_URL.rstrip('/') + '/api/v1/files/verify'

    if not verify_url or not VERIFY_SECRET:
        print('Backend verify URL or VERIFY_SECRET not set; skipping backend verify call', 'verify_url=', verify_url, 'VERIFY_SECRET_set=', bool(VERIFY_SECRET))
        return None

    payload = {'s3_key': s3_key}
    if file_size_bytes is not None:
        payload['file_size_bytes'] = int(file_size_bytes)
    if bucket:
        payload['bucket'] = bucket

    try:
        status, body = http_post_json(verify_url, payload, headers={'X-Verify-Token': VERIFY_SECRET})
        print('verify response', status, body)
        return body
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode('utf-8')
        except Exception:
            body = None
        print('verify http error', e.code, body)
        return None
    except Exception as e:
        print('verify call failed', e)
        return None


def patch_status_by_id(backend_base: str, file_id: int, status: str):
    url = f"{backend_base.rstrip('/')}/files/{file_id}/status"
    try:
        status_code, body = http_post_json(url, {'status': status}, method='PATCH')
        print('patched status', file_id, status_code, body)
        return True
    except Exception as e:
        print('patch status failed', e)
        return False


def get_object_stream(bucket: str, key: str):
    # Attempt to get the object with retries
    last_exc = None
    for attempt in range(1, S3_READ_RETRIES + 1):
        try:
            resp = s3_client.get_object(Bucket=bucket, Key=key)
            return resp
        except ClientError as e:
            last_exc = e
            code = e.response.get('Error', {}).get('Code')
            print(f'get_object attempt {attempt} failed: {code}')
            time.sleep(0.5 * attempt)
    raise last_exc


def copy_to_failed(bucket: str, key: str, reason: str):
    if not COPY_ON_FAILURE:
        print('COPY_ON_FAILURE disabled; not copying to failed prefix')
        return
    dest_key = FAILED_PREFIX + key
    try:
        s3_client.copy_object(Bucket=bucket, CopySource={'Bucket': bucket, 'Key': key}, Key=dest_key, Metadata={'failure-reason': reason}, MetadataDirective='REPLACE')
        print(f'Copied {key} to {dest_key}')
    except Exception as e:
        print('Failed to copy to failed prefix', e)


def validate_csv_stream(stream_body, max_rows=1000, validate_full=False):
    # stream_body is a StreamingBody from boto3 get_object
    text_stream = io.TextIOWrapper(stream_body, encoding='utf-8', errors='replace', newline='')
    reader = csv.reader(text_stream)
    try:
        header = next(reader)
    except StopIteration:
        raise ValueError('empty')
    except csv.Error as e:
        raise

    num_cols = len(header)
    rows_checked = 0
    sample_rows = []
    truncated = False
    for row in reader:
        rows_checked += 1
        if len(row) != num_cols:
            raise csv.Error(f'Row {rows_checked + 1} has {len(row)} columns, expected {num_cols}')
        if len(sample_rows) < SAMPLE_ROWS:
            sample_rows.append(row)
        if not validate_full and rows_checked >= max_rows:
            truncated = True
            break

    summary = {
        'header': header,
        'num_columns': num_cols,
        'num_rows': rows_checked,
        'sample_rows': sample_rows,
        'truncated': truncated,
    }
    return summary


def handle_record(bucket: str, key: str):
    print(f'Handling s3://{bucket}/{key}')
    # 1. Check object existence and size
    try:
        head = s3_client.head_object(Bucket=bucket, Key=key)
    except ClientError as e:
        print('head_object failed', e)
        # notify backend if possible
        call_backend_verify(key, None, bucket)
        return

    size = head.get('ContentLength', 0)
    if size == 0:
        print('Empty file detected')
        # Call backend verify to mark record; if exists, patch to failed
        resp = call_backend_verify(key, size, bucket)
        if resp and isinstance(resp, dict) and resp.get('id'):
            try:
                patch_status_by_id(BACKEND_BASE_URL, resp['id'], 'failed')
            except Exception:
                pass
        return

    # 2. Stream, validate and summarize CSV
    try:
        obj = get_object_stream(bucket, key)
        body = obj['Body']
        summary = validate_csv_stream(body, max_rows=MAX_ROWS_TO_VALIDATE, validate_full=VALIDATE_FULL_FILE)
        # attach some metadata
        summary['s3_key'] = key
        summary['bucket'] = bucket
        summary['file_size'] = size
        summary['processed_at'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        # write summary JSON into a `summaries/` subfolder next to the CSV
        summary_key = summary_key_for_csv(key)
        # Allow storing summaries in a separate bucket when configured.
        target_summary_bucket = SUMMARY_BUCKET_NAME or bucket
        try:
            s3_client.put_object(Bucket=target_summary_bucket, Key=summary_key, Body=json.dumps(summary), ContentType='application/json')
            print('Wrote summary to', f's3://{target_summary_bucket}/{summary_key}')
        except Exception as e:
            print('Failed to write summary', e)
    except Exception as e:
        # Distinguish empty vs malformed vs s3 errors
        reason = 'malformed' if isinstance(e, csv.Error) else str(e)
        print('Validation failed:', reason)
        if COPY_ON_FAILURE:
            try:
                copy_to_failed(bucket, key, reason)
            except Exception as ex:
                print('copy_to_failed error', ex)

        # Call backend verify to ensure a DB record exists, then mark as failed
        resp = call_backend_verify(key, size, bucket)
        if resp and isinstance(resp, dict) and resp.get('id'):
            try:
                patch_status_by_id(BACKEND_BASE_URL, resp['id'], 'failed')
            except Exception as ex:
                print('patch failed', ex)
        return

    # 3. If validation passes, call backend verify to mark verified
    resp = call_backend_verify(key, size, bucket)
    print('Processing complete for', key, 'verify response', resp)


def lambda_handler(event, context):
    print('Received event:', json.dumps(event))
    records = event.get('Records', [])
    for r in records:
        try:
            # Support both direct S3 event (when Lambda is invoked by S3)
            # and SQS-wrapped S3 event (when S3 posts to SQS and Lambda polls SQS).
            bucket = None
            key = None
            if 'body' in r and isinstance(r['body'], str):
                try:
                    inner = json.loads(r['body'])
                    # inner is typically an S3 event with its own Records array
                    inner_rec = inner.get('Records', [None])[0]
                    if inner_rec:
                        s3 = inner_rec.get('s3', {})
                        bucket = s3.get('bucket', {}).get('name')
                        key = s3.get('object', {}).get('key')
                except Exception:
                    pass
            # Fallback: direct S3 event structure
            if not key or not bucket:
                s3 = r.get('s3', {})
                bucket = s3.get('bucket', {}).get('name')
                key = s3.get('object', {}).get('key')
            if not key or not bucket:
                continue
            key = urllib.parse.unquote_plus(key)
            if should_skip_key(key):
                print('Skipping generated/failed artifact key:', key)
                continue
            handle_record(bucket, key)
        except Exception as e:
            print('Error processing record', e)

    return {'status': 'ok'}
