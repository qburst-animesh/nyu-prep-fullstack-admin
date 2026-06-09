import os
import json
import boto3
import urllib.request
import urllib.error

BUCKET = os.getenv('BUCKET_NAME')
BACKEND_BASE = os.getenv('BACKEND_BASE_URL')  # e.g. https://api.example.com
VERIFY_SECRET = os.getenv('VERIFY_SECRET')

s3 = boto3.client('s3')


def _post_callback(file_id: int, deleted: bool, message: str = None):
    if not BACKEND_BASE:
        print('No BACKEND_BASE_URL configured; cannot call callback')
        return None

    url = f"{BACKEND_BASE.rstrip('/')}/api/v1/files/{file_id}/delete-complete"
    payload = {'deleted': deleted}
    if message:
        payload['message'] = message
    data = json.dumps(payload).encode('utf-8')
    headers = {'Content-Type': 'application/json'}
    if VERIFY_SECRET:
        headers['X-Verify-Token'] = VERIFY_SECRET

    req = urllib.request.Request(url, data=data, headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode('utf-8')
            print('Callback response:', resp.status, body)
            return resp.status, body
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode('utf-8')
        except Exception:
            body = ''
        print('Callback HTTPError:', e.code, body)
        return e.code, body
    except Exception as e:
        print('Callback failed:', e)
        return None


def lambda_handler(event, context):
    """Lambda to delete an S3 object and notify the backend to remove the DB record.

    Expected invocation payload: {"file_id": 123, "s3_key": "csv_uploads/.."}
    """
    print('Event:', event)
    file_id = None
    s3_key = None

    # support both direct invocation payload and wrapped Records if provided
    if isinstance(event, dict):
        file_id = event.get('file_id')
        s3_key = event.get('s3_key')
        # fallback: if Records provided, try to extract key
        if not s3_key and 'Records' in event and len(event['Records']) > 0:
            try:
                s3_key = event['Records'][0]['s3']['object']['key']
            except Exception:
                pass

    if not file_id or not s3_key:
        msg = 'Missing file_id or s3_key in event'
        print(msg)
        return {'status': 'error', 'message': msg}

    try:
        print(f'Deleting s3://{BUCKET}/{s3_key}')
        resp = s3.delete_object(Bucket=BUCKET, Key=s3_key)
        print('S3 delete response:', resp)
        _post_callback(file_id, True)
        return {'status': 'deleted', 's3_response': resp}
    except Exception as e:
        print('S3 delete failed:', e)
        try:
            _post_callback(file_id, False, str(e))
        except Exception:
            pass
        return {'status': 'error', 'message': str(e)}
