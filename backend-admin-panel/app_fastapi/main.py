from fastapi import FastAPI, Depends, HTTPException, status, Request
import json
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import List
import uuid
import os
import time
import asyncio
from datetime import datetime, timezone
from fastapi.security import HTTPBearer
import hmac
from fastapi.security import HTTPAuthorizationCredentials
import posixpath as pp
import logging

from .database import engine, Base, get_db
from . import models, schemas
from .s3_service import S3Service
from .auth import verify_token
import boto3
from botocore.exceptions import ClientError
from starlette.responses import StreamingResponse
from fastapi import Response
 

# Initialize Database tables
Base.metadata.create_all(bind=engine)

app = FastAPI(title="CSV Cloud Infrastructure Backend", version="1.0.0")
s3 = S3Service()
lambda_client = boto3.client('lambda', region_name=os.getenv('AWS_DEFAULT_REGION'))
SUMMARY_BUCKET_NAME = os.getenv('SUMMARY_BUCKET_NAME')
# Lambda invocation tuning (can be overridden via env)
DELETE_LAMBDA_INVOKE_RETRIES = int(os.getenv('DELETE_LAMBDA_INVOKE_RETRIES', '3'))
DELETE_LAMBDA_BACKOFF_BASE_SEC = float(os.getenv('DELETE_LAMBDA_BACKOFF_BASE_SEC', '0.5'))

# Logger for backend operations
logger = logging.getLogger('csv_backend')

security = HTTPBearer()


def _expected_verify_secret() -> str | None:
    # Backward-compatible lookup: old local setup used LAMBDA_VERIFY_SECRET.
    return os.getenv('VERIFY_SECRET') or os.getenv('LAMBDA_VERIFY_SECRET')


def _get_user_id(current_user: dict) -> str:
    """Extract user identifier from Cognito claims."""
    return current_user.get('sub') or current_user.get('username') or 'unknown'


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Dependency to validate Cognito JWTs on incoming requests.
    Uses the `verify_token` helper which fetches and validates JWKS.
    """
    # Allow disabling authentication in local development by setting DISABLE_AUTH
    if os.getenv('DISABLE_AUTH', '').lower() in ('1', 'true', 'yes'):
        return { 'username': 'local-dev' }

    if not credentials or not credentials.credentials:
        raise HTTPException(status_code=401, detail="Missing authentication token")

    token = credentials.credentials
    try:
        claims = verify_token(token)
        return claims
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
# CORS configuration targeting your MUI React Admin Framework
# Allow common local dev ports by default (CRA:3000, Vite:5173)
origins_str = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173,http://localhost:8000")
origins = [origin.strip() for origin in origins_str.split(",") if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/api/v1/files/upload-url", response_model=dict)
def request_upload_url(file_info: schemas.CSVFileBase, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """
    Step 1: Frontend asks for an S3 storage token layout slot.
    Returns a unique tracking key and direct network destination path.
    """
    # Enforce maximum file size limit
    max_size = int(os.getenv('MAX_FILE_SIZE_BYTES', 100 * 1024 * 1024))  # 100MB default
    if file_info.file_size_bytes > max_size:
        raise HTTPException(status_code=400, detail={"message": f"File size exceeds maximum allowed size of {max_size} bytes"})

    # Ensure only CSV files are requested for upload
    allowed_mimetypes = {"text/csv", "application/vnd.ms-excel", "application/csv"}
    if not file_info.filename.lower().endswith('.csv'):
        raise HTTPException(status_code=400, detail={"message": "Only .csv files are allowed for upload."})
    if file_info.mime_type and file_info.mime_type not in allowed_mimetypes:
        raise HTTPException(status_code=400, detail={"message": "Invalid MIME type; only CSV uploads are permitted."})

    # Prevent duplicate allocations for identical filename + size pairs
    existing = db.query(models.CSVFile).filter(
        models.CSVFile.filename == file_info.filename,
        models.CSVFile.file_size_bytes == file_info.file_size_bytes
    ).first()

    if existing:
        raise HTTPException(status_code=409, detail={
            "message": "A file with the same name and size already exists.",
            "file": {
                "id": existing.id,
                "filename": existing.filename,
                "s3_key": existing.s3_key,
                "file_size_bytes": existing.file_size_bytes,
            }
        })

    unique_key = f"csv_uploads/{uuid.uuid4()}_{file_info.filename}"
    upload_url = s3.generate_presigned_upload_url(unique_key, content_type=file_info.mime_type)
    
    if not upload_url:
        raise HTTPException(status_code=500, detail="Unable to prepare upload. Please try again.")
        
    return {"upload_url": upload_url, "s3_key": unique_key}

@app.post("/api/v1/files", response_model=schemas.CSVFileResponse, status_code=status.HTTP_201_CREATED)
def record_file_metadata(payload: schemas.CSVFileCreate, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """
    Step 2: Frontend calls this after successful S3 streaming upload.
    Saves the operational records to PostgreSQL.
    """
    # Ensure only CSV metadata is stored
    if not payload.filename.lower().endswith('.csv'):
        raise HTTPException(status_code=400, detail={"message": "Only .csv files are allowed."})
    allowed_mimetypes = {"text/csv", "application/vnd.ms-excel", "application/csv"}
    if payload.mime_type and payload.mime_type not in allowed_mimetypes:
        raise HTTPException(status_code=400, detail={"message": "Invalid MIME type; only CSV uploads are permitted."})

    # Prevent storing duplicate logical files (same name + size)
    duplicate = db.query(models.CSVFile).filter(
        models.CSVFile.filename == payload.filename,
        models.CSVFile.file_size_bytes == payload.file_size_bytes
    ).first()
    if duplicate:
        raise HTTPException(status_code=409, detail={
            "message": "A file with the same name and size already exists.",
            "file": {
                "id": duplicate.id,
                "filename": duplicate.filename,
                "s3_key": duplicate.s3_key,
                "file_size_bytes": duplicate.file_size_bytes,
            }
        })

    db_file = models.CSVFile(**payload.model_dump())
    db_file.uploaded_by = current_user.get('sub') or current_user.get('username')
    db.add(db_file)
    db.commit()
    db.refresh(db_file)
    return db_file


@app.patch("/api/v1/files/{file_id}/status", response_model=schemas.CSVFileResponse)
async def update_file_status(file_id: int, payload: schemas.CSVFileStatusUpdate, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Allows the client to mark a previously-registered record as uploaded/failed.
    When marking as 'uploaded' the backend will validate the object exists in S3.
    """
    user_id = _get_user_id(current_user)
    file_record = db.query(models.CSVFile).filter(
        models.CSVFile.id == file_id,
        models.CSVFile.uploaded_by == user_id
    ).first()
    if not file_record:
        raise HTTPException(status_code=404, detail="Target record not found")

    new_status = payload.status
    # If claiming the asset is uploaded, attempt to verify S3 content exists.
    verified = None
    if new_status == 'uploaded':
        # Retry head_object a few times to account for eventual consistency or short propagation delays
        meta = None
        attempts = 5
        for attempt in range(attempts):
            meta = s3.head_object(file_record.s3_key)
            if meta:
                break
            # non-blocking small backoff
            await asyncio.sleep(0.5)

        if meta:
            verified = True
            # Optional: basic size check (log but do not fail)
            try:
                content_length = int(meta.get('ContentLength', -1))
                if content_length != file_record.file_size_bytes:
                    # Size mismatch detected; keep verified True but log for ops
                    pass
            except Exception:
                pass
        else:
            # Could not confirm object presence. Accept the status change but mark as not verified.
            verified = False

    # Persist verification state when appropriate
    if new_status == 'uploaded':
        # initialize verification_attempts if None
        try:
            current_attempts = int(file_record.verification_attempts or 0)
        except Exception:
            current_attempts = 0

        if verified is True:
            file_record.verified = True
        elif verified is False:
            file_record.verified = False
            file_record.verification_attempts = current_attempts + 1

    file_record.status = new_status
    db.commit()
    db.refresh(file_record)
    return file_record

@app.get("/api/v1/files", response_model=List[schemas.CSVFileResponse])
def list_uploaded_files(skip: int = 0, limit: int = 100, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Fetches full index mapping for the React Admin DataGrid view component"""
    user_id = _get_user_id(current_user)
    files = db.query(models.CSVFile).filter(models.CSVFile.uploaded_by == user_id).offset(skip).limit(limit).all()
    return files

@app.get("/api/v1/files/{file_id}/download")
def get_file_download_link(file_id: int, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Generates direct retrieval string dynamically on access request"""
    user_id = _get_user_id(current_user)
    file_record = db.query(models.CSVFile).filter(
        models.CSVFile.id == file_id,
        models.CSVFile.uploaded_by == user_id
    ).first()
    if not file_record:
        raise HTTPException(status_code=404, detail="File not found")
    # Include a filename so browsers download with a sensible name
    download_url = s3.generate_presigned_download_url(file_record.s3_key, filename=file_record.filename)
    if not download_url:
        raise HTTPException(status_code=500, detail="Could not generate download URL")
    return {"download_url": download_url}


# Streaming download endpoints removed — use /api/v1/files/{file_id}/download
# which returns a presigned URL that clients can use to fetch the object directly from S3.


@app.get("/api/v1/files/{file_id}/summary")
def get_file_summary(file_id: int, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Return whether a summary JSON exists for the file and a presigned URL if it does."""
    user_id = _get_user_id(current_user)
    file_record = db.query(models.CSVFile).filter(
        models.CSVFile.id == file_id,
        models.CSVFile.uploaded_by == user_id
    ).first()
    if not file_record:
        raise HTTPException(status_code=404, detail="File not found")

    if not SUMMARY_BUCKET_NAME:
        return {"exists": False}

    # Use simple key format: just the filename.summary.json in the dedicated summary bucket
    basename = pp.basename(file_record.s3_key)
    summary_key = f"{basename}.summary.json"

    meta = s3.head_object(summary_key, bucket_name=SUMMARY_BUCKET_NAME)
    if meta:
        url = s3.generate_presigned_download_url(summary_key, bucket_name=SUMMARY_BUCKET_NAME)
        return {"exists": True, "summary_url": url}

    return {"exists": False}


@app.get('/api/v1/health')
def health_check(db: Session = Depends(get_db)):
    """Basic health endpoint checking DB connectivity and S3 access."""
    status_dict = {'ok': True}
    # Check DB connectivity with a light query
    try:
        db.execute(text('SELECT 1'))
        status_dict['db'] = 'ok'
    except Exception as e:
        logger.exception('DB health check failed')
        status_dict['db'] = f'error: {str(e)}'
        status_dict['ok'] = False

    # Check S3 bucket access (best-effort)
    try:
        s3.s3_client.head_bucket(Bucket=s3.bucket_name)
        status_dict['s3_bucket'] = 'ok'
    except Exception:
        # Do not fail overall health for S3 issues, just report
        status_dict['s3_bucket'] = f'unavailable: {s3.bucket_name}'

    return status_dict



# Retry-delete endpoint intentionally commented out for now. Implementation
# exists in previous commits and can be re-enabled if asynchronous delete
# orchestration via `DELETE_LAMBDA_FUNCTION` is required.


@app.delete("/api/v1/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_file_record(file_id: int, delete_s3: bool = False, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Deletes the DB record; optionally deletes the S3 object when `delete_s3=true`."""
    user_id = _get_user_id(current_user)
    file_record = db.query(models.CSVFile).filter(
        models.CSVFile.id == file_id,
        models.CSVFile.uploaded_by == user_id
    ).first()
    if not file_record:
        raise HTTPException(status_code=404, detail="File not found")

    if delete_s3:
        # If a delete lambda is configured, invoke it asynchronously and
        # mark the DB record as 'deleting'. The lambda will call back to
        # `/api/v1/files/{id}/delete-complete` to finalize removal.
        delete_lambda = os.getenv('DELETE_LAMBDA_FUNCTION')
        if delete_lambda:
            file_record.status = 'deleting'
            file_record.delete_requested_at = datetime.now(timezone.utc)
            file_record.delete_attempts = 0
            file_record.delete_last_error = None
            db.add(file_record)
            db.commit()
            payload = {
                "file_id": file_id,
                "s3_key": file_record.s3_key,
                # Send the backend's active bucket so delete lambda targets the right bucket.
                "bucket_name": s3.bucket_name,
                # Inform delete lambda of the summary bucket (may be None)
                "summary_bucket": SUMMARY_BUCKET_NAME,
            }
            # Attempt asynchronous invocation with retry/backoff and logging
            invoked = False
            last_exc = None
            for attempt in range(1, DELETE_LAMBDA_INVOKE_RETRIES + 1):
                try:
                    logger.info("Invoking delete-lambda %s for file_id=%s (attempt %d)", delete_lambda, file_id, attempt)
                    lambda_client.invoke(FunctionName=delete_lambda, InvocationType='Event', Payload=json.dumps(payload).encode('utf-8'))
                    invoked = True
                    logger.info("Successfully invoked delete-lambda %s for file_id=%s", delete_lambda, file_id)
                    break
                except Exception as e:
                    last_exc = e
                    logger.warning("Failed to invoke delete-lambda %s on attempt %d: %s", delete_lambda, attempt, str(e))
                    # exponential backoff
                    sleep_sec = DELETE_LAMBDA_BACKOFF_BASE_SEC * (2 ** (attempt - 1))
                    await asyncio.sleep(sleep_sec)

            if not invoked:
                err_msg = f"Failed to invoke delete lambda after {DELETE_LAMBDA_INVOKE_RETRIES} attempts: {last_exc}"
                logger.error(err_msg)
                raise HTTPException(status_code=500, detail=err_msg)

            return Response(status_code=202)

        # No lambda configured: perform synchronous deletion and fail if it doesn't work
        deleted = s3.delete_s3_object(file_record.s3_key)
        if not deleted:
            # If we couldn't remove the S3 asset, do not remove the DB record
            # so operators can retry or investigate; surface an error to client.
            raise HTTPException(status_code=500, detail="Failed to delete object from S3")

        # Attempt to remove associated summary JSON
        try:
            basename = pp.basename(file_record.s3_key)
            summary_key = f"{basename}.summary.json"
            if SUMMARY_BUCKET_NAME:
                s3.delete_s3_object(summary_key, bucket_name=SUMMARY_BUCKET_NAME)
        except Exception:
            pass

    db.delete(file_record)
    db.commit()
    return None


@app.post("/api/v1/files/verify")
def verify_file(payload: schemas.VerifyPayload, request: Request, db: Session = Depends(get_db)):
    """Trusted callback endpoint used by the processor Lambda to confirm S3
    objects. Requests must include a matching `X-Verify-Token` header."""
    verify_token_header = request.headers.get('X-Verify-Token')
    expected = _expected_verify_secret()
    # Fail-closed: if no secret configured, reject the call.
    if not expected or not hmac.compare_digest(str(verify_token_header or ''), str(expected)):
        raise HTTPException(status_code=401, detail='Unauthorized')

    s3_key = payload.s3_key
    if not s3_key:
        raise HTTPException(status_code=400, detail='Missing s3_key in payload')

    # Try exact match first
    file_record = db.query(models.CSVFile).filter(models.CSVFile.s3_key == s3_key).first()

    # If not found, attempt heuristics: match by filename + size, then by s3_key suffix
    if not file_record:
        basename = pp.basename(s3_key)
        if getattr(payload, 'file_size_bytes', None) is not None:
            try:
                file_record = db.query(models.CSVFile).filter(
                    models.CSVFile.file_size_bytes == int(payload.file_size_bytes),
                    models.CSVFile.filename == basename
                ).first()
            except Exception:
                file_record = None

        if not file_record:
            # fallback: any record whose s3_key ends with the basename
            try:
                file_record = db.query(models.CSVFile).filter(models.CSVFile.s3_key.endswith(basename)).first()
            except Exception:
                file_record = None

        # If we found a candidate, update its s3_key to the canonical value reported by the processor
        if file_record:
            file_record.s3_key = s3_key
            db.add(file_record)
            db.commit()
            db.refresh(file_record)
        else:
            raise HTTPException(status_code=404, detail='File not found')

    # Verify presence in S3 (allow processor to inform which bucket to check)
    bucket_to_check = getattr(payload, 'bucket', None)
    if bucket_to_check:
        meta = s3.head_object(s3_key, bucket_name=bucket_to_check)
    else:
        meta = s3.head_object(s3_key)

    if meta:
        file_record.status = 'uploaded'
        file_record.verified = True
    else:
        file_record.verified = False
        file_record.verification_attempts = (file_record.verification_attempts or 0) + 1

    db.add(file_record)
    db.commit()
    db.refresh(file_record)
    return {"id": file_record.id, "verified": bool(file_record.verified)}


@app.post("/api/v1/files/{file_id}/delete-complete")
def delete_complete(file_id: int, payload: schemas.DeleteCompletePayload, request: Request, db: Session = Depends(get_db)):
    """Callback endpoint for the delete Lambda to notify the backend of the
    result. Protected by `VERIFY_SECRET` and uses timing-safe compare."""
    verify_token_header = request.headers.get('X-Verify-Token')
    expected = _expected_verify_secret()
    # Fail-closed: require the VERIFY_SECRET to be configured and match
    if not expected or not hmac.compare_digest(str(verify_token_header or ''), str(expected)):
        raise HTTPException(status_code=401, detail='Unauthorized')

    file_record = db.query(models.CSVFile).filter(models.CSVFile.id == file_id).first()
    if not file_record:
        raise HTTPException(status_code=404, detail='File not found')

    if payload.deleted:
        # Record completion timestamp for audit before removing
        file_record.delete_completed_at = datetime.now(timezone.utc)
        db.add(file_record)
        db.commit()
        # Now remove the DB record
        db.delete(file_record)
        db.commit()
        return {"deleted": True}
    else:
        file_record.status = 'delete_failed'
        try:
            file_record.delete_last_error = str(payload.message) if payload.message is not None else None
        except Exception:
            file_record.delete_last_error = None
        try:
            file_record.delete_attempts = (file_record.delete_attempts or 0) + 1
        except Exception:
            file_record.delete_attempts = 1
        db.add(file_record)
        db.commit()
        return {"deleted": False, "message": payload.message}


@app.post("/api/v1/files/{file_id}/trigger-parse")
async def trigger_parse(file_id: int, db: Session = Depends(get_db), current_user: dict = Depends(get_current_user)):
    """Trigger the parser Lambda to process a CSV file."""
    user_id = _get_user_id(current_user)
    file_record = db.query(models.CSVFile).filter(
        models.CSVFile.id == file_id,
        models.CSVFile.uploaded_by == user_id
    ).first()
    if not file_record:
        raise HTTPException(status_code=404, detail="File not found")

    parser_lambda = os.getenv('LAMBDA_FUNCTION_NAME')
    if not parser_lambda:
        return {"invoked": False, "reason": "Server is not configured to parse files automatically"}

    try:
        payload = {
            "file_id": file_id,
            "s3_key": file_record.s3_key,
            "bucket_name": s3.bucket_name,
            "summary_bucket": SUMMARY_BUCKET_NAME,
        }
        lambda_client.invoke(
            FunctionName=parser_lambda,
            InvocationType='Event',
            Payload=json.dumps(payload).encode('utf-8')
        )
        logger.info("Invoked parser lambda for file_id=%s", file_id)
        return {"invoked": True}
    except Exception as e:
        logger.error("Failed to invoke parser lambda for file_id=%s: %s", file_id, str(e))
        raise HTTPException(status_code=500, detail=f"Failed to invoke parser: {str(e)}")

