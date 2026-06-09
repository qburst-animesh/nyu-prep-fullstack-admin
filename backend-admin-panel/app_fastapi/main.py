from fastapi import FastAPI, Depends, HTTPException, status, Request
import json
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from typing import List
import uuid
import os
import time
from datetime import datetime

from .database import engine, Base, get_db
from . import models, schemas
from .s3_service import S3Service
import boto3
from botocore.exceptions import ClientError
from starlette.responses import StreamingResponse
from fastapi import Response
from fastapi.middleware.cors import CORSMiddleware

# Initialize Database tables
Base.metadata.create_all(bind=engine)

app = FastAPI(title="CSV Cloud Infrastructure Backend", version="1.0.0")
s3 = S3Service()

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
def request_upload_url(file_info: schemas.CSVFileBase, db: Session = Depends(get_db)):
    """
    Step 1: Frontend asks for an S3 storage token layout slot.
    Returns a unique tracking key and direct network destination path.
    """
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
def record_file_metadata(payload: schemas.CSVFileCreate, db: Session = Depends(get_db)):
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
    db.add(db_file)
    db.commit()
    db.refresh(db_file)
    return db_file


@app.patch("/api/v1/files/{file_id}/status", response_model=schemas.CSVFileResponse)
def update_file_status(file_id: int, payload: schemas.CSVFileStatusUpdate, db: Session = Depends(get_db)):
    """Allows the client to mark a previously-registered record as uploaded/failed.
    When marking as 'uploaded' the backend will validate the object exists in S3.
    """
    file_record = db.query(models.CSVFile).filter(models.CSVFile.id == file_id).first()
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
            # small backoff
            time.sleep(0.5)

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

    # Build a response dict including the optional verification flag (friendly, non-technical)
    response = {
        "id": file_record.id,
        "filename": file_record.filename,
        "s3_key": file_record.s3_key,
        "file_size_bytes": file_record.file_size_bytes,
        "mime_type": file_record.mime_type,
        "uploaded_by": file_record.uploaded_by,
        "status": file_record.status,
        "created_at": file_record.created_at,
        "updated_at": file_record.updated_at,
        "verified": verified,
    }

    return response

@app.get("/api/v1/files", response_model=List[schemas.CSVFileResponse])
def list_uploaded_files(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    """Fetches full index mapping for the React Admin DataGrid view component"""
    files = db.query(models.CSVFile).offset(skip).limit(limit).all()
    return files

@app.get("/api/v1/files/{file_id}/download")
def get_file_download_link(file_id: int, db: Session = Depends(get_db)):
    """Generates direct retrieval string dynamically on access request"""
    file_record = db.query(models.CSVFile).filter(models.CSVFile.id == file_id).first()
    if not file_record:
        raise HTTPException(status_code=404, detail="File not found")
    # Include a filename so browsers download with a sensible name
    download_url = s3.generate_presigned_download_url(file_record.s3_key, filename=file_record.filename)
    if not download_url:
        raise HTTPException(status_code=500, detail="Could not generate download URL")
    return {"download_url": download_url}


@app.get("/api/v1/files/{file_id}/download-stream")
def download_file_stream(file_id: int, db: Session = Depends(get_db)):
    """Stream the S3 object through the backend to the client with proper
    Content-Disposition so browsers download the file. This avoids relying on
    presigned URLs when they fail due to credential/region issues in dev.
    """
    file_record = db.query(models.CSVFile).filter(models.CSVFile.id == file_id).first()
    if not file_record:
        raise HTTPException(status_code=404, detail="File not found")

    try:
        obj = s3.s3_client.get_object(Bucket=s3.bucket_name, Key=file_record.s3_key)
    except ClientError as e:
        raise HTTPException(status_code=404, detail=f"S3 object not found: {e}")

    body = obj.get('Body')
    if body is None:
        raise HTTPException(status_code=500, detail="S3 returned no body for object")

    content_type = obj.get('ContentType') or file_record.mime_type or 'application/octet-stream'
    headers = {
        'Content-Disposition': f'attachment; filename="{file_record.filename}"'
    }
    content_length = obj.get('ContentLength')
    if content_length is not None:
        headers['Content-Length'] = str(content_length)

    return StreamingResponse(body.iter_chunks(chunk_size=8192), media_type=content_type, headers=headers)


@app.head("/api/v1/files/{file_id}/download-stream")
def download_file_stream_head(file_id: int, db: Session = Depends(get_db)):
    """HEAD probe for the streaming endpoint. Returns 200 when the S3 object
    is accessible to the backend (so the frontend can decide whether to
    open the streaming URL or fallback to presigned URLs).
    """
    file_record = db.query(models.CSVFile).filter(models.CSVFile.id == file_id).first()
    if not file_record:
        raise HTTPException(status_code=404, detail="File not found")

    meta = s3.head_object(file_record.s3_key)
    if not meta:
        raise HTTPException(status_code=404, detail="S3 object not found or inaccessible")

    headers = {}
    if meta.get('ContentLength') is not None:
        headers['Content-Length'] = str(meta.get('ContentLength'))
    if meta.get('ContentType'):
        headers['Content-Type'] = meta.get('ContentType')
    return Response(status_code=200, headers=headers)


@app.get("/api/v1/files/{file_id}/summary")
def get_file_summary(file_id: int, db: Session = Depends(get_db)):
    """Return whether a summary JSON exists for the file and a presigned URL if it does."""
    file_record = db.query(models.CSVFile).filter(models.CSVFile.id == file_id).first()
    if not file_record:
        raise HTTPException(status_code=404, detail="File not found")

    summary_key = f"{file_record.s3_key}.summary.json"
    meta = s3.head_object(summary_key)
    if not meta:
        return {"exists": False}

    url = s3.generate_presigned_download_url(summary_key)
    return {"exists": True, "summary_url": url}


@app.post("/api/v1/files/{file_id}/trigger-parse")
def trigger_file_parse(file_id: int, db: Session = Depends(get_db)):
    """Trigger the processing Lambda asynchronously to re-parse a file.
    Requires `LAMBDA_FUNCTION_NAME` environment variable to be set on the backend.
    """
    file_record = db.query(models.CSVFile).filter(models.CSVFile.id == file_id).first()
    if not file_record:
        raise HTTPException(status_code=404, detail="File not found")

    lambda_name = os.getenv('LAMBDA_FUNCTION_NAME')
    if not lambda_name:
        # Server is not configured to invoke the parser Lambda. Return a
        # friendly response instead of a hard 4xx so the frontend can handle
        # this condition gracefully during local development.
        return {"invoked": False, "reason": "Parser lambda not configured on server. Set LAMBDA_FUNCTION_NAME to enable remote parsing via Lambda."}

    # Build a minimal S3 event-like payload the lambda expects
    payload = {
        "Records": [
            {
                "s3": {
                    "bucket": {"name": s3.bucket_name},
                    "object": {"key": file_record.s3_key}
                }
            }
        ]
    }

    try:
        lambda_client = boto3.client('lambda', region_name=os.getenv('AWS_DEFAULT_REGION'))
        lambda_client.invoke(FunctionName=lambda_name, InvocationType='Event', Payload=json.dumps(payload).encode('utf-8'))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to invoke parser: {e}")

    return {"invoked": True}


@app.post("/api/v1/files/{file_id}/retry-delete")
def retry_delete(file_id: int, db: Session = Depends(get_db)):
    """Retry an asynchronous delete. If `DELETE_LAMBDA_FUNCTION` is configured
    the backend will invoke it asynchronously and return 202 Accepted. If no
    lambda is configured the backend will attempt a synchronous delete.
    """
    file_record = db.query(models.CSVFile).filter(models.CSVFile.id == file_id).first()
    if not file_record:
        raise HTTPException(status_code=404, detail="File not found")

    delete_lambda = os.getenv('DELETE_LAMBDA_FUNCTION')
    if delete_lambda:
        # mark the record and invoke the lambda asynchronously
        file_record.status = 'deleting'
        file_record.delete_requested_at = datetime.utcnow()
        try:
            file_record.delete_attempts = (file_record.delete_attempts or 0) + 1
        except Exception:
            file_record.delete_attempts = 1
        file_record.delete_last_error = None
        db.add(file_record)
        db.commit()

        payload = {"file_id": file_id, "s3_key": file_record.s3_key}
        try:
            lambda_client = boto3.client('lambda', region_name=os.getenv('AWS_DEFAULT_REGION'))
            lambda_client.invoke(FunctionName=delete_lambda, InvocationType='Event', Payload=json.dumps(payload).encode('utf-8'))
        except Exception as e:
            file_record.delete_last_error = str(e)
            file_record.delete_attempts = (file_record.delete_attempts or 0) + 1
            file_record.status = 'delete_failed'
            db.add(file_record)
            db.commit()
            raise HTTPException(status_code=500, detail=f"Failed to invoke delete lambda: {e}")

        return Response(status_code=202)

    # No lambda configured: attempt synchronous delete
    deleted = s3.delete_s3_object(file_record.s3_key)
    if deleted:
        file_record.delete_completed_at = datetime.utcnow()
        db.add(file_record)
        db.commit()
        # remove DB record
        db.delete(file_record)
        db.commit()
        return {"deleted": True}
    else:
        try:
            file_record.delete_attempts = (file_record.delete_attempts or 0) + 1
        except Exception:
            file_record.delete_attempts = 1
        file_record.delete_last_error = 'Synchronous delete failed'
        file_record.status = 'delete_failed'
        db.add(file_record)
        db.commit()
        raise HTTPException(status_code=500, detail='Synchronous delete failed')

@app.post("/api/v1/files/verify")
def verify_file(payload: dict, request: Request, db: Session = Depends(get_db)):
    """Endpoint intended for trusted callers (e.g. an S3-triggered Lambda).
    Caller must provide a matching `X-Verify-Token` header. The payload must
    include `s3_key`.
    """
    verify_token = request.headers.get("X-Verify-Token")
    expected = os.getenv("VERIFY_SECRET")
    if not expected or verify_token != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")

    s3_key = payload.get('s3_key')
    if not s3_key:
        raise HTTPException(status_code=400, detail="Missing s3_key in payload")

    file_record = db.query(models.CSVFile).filter(models.CSVFile.s3_key == s3_key).first()
    if not file_record:
        raise HTTPException(status_code=404, detail="File not found")

    # Verify presence in S3
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


@app.delete("/api/v1/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_file_record(file_id: int, delete_s3: bool = False, db: Session = Depends(get_db)):
    """Deletes the DB record; optionally deletes the S3 object when `delete_s3=true`."""
    file_record = db.query(models.CSVFile).filter(models.CSVFile.id == file_id).first()
    if not file_record:
        raise HTTPException(status_code=404, detail="File not found")

    if delete_s3:
        # If a delete lambda is configured, invoke it asynchronously and
        # mark the DB record as 'deleting'. The lambda will call back to
        # `/api/v1/files/{id}/delete-complete` to finalize removal.
        delete_lambda = os.getenv('DELETE_LAMBDA_FUNCTION')
        if delete_lambda:
            file_record.status = 'deleting'
            file_record.delete_requested_at = datetime.utcnow()
            file_record.delete_attempts = 0
            file_record.delete_last_error = None
            db.add(file_record)
            db.commit()
            payload = {"file_id": file_id, "s3_key": file_record.s3_key}
            try:
                lambda_client = boto3.client('lambda', region_name=os.getenv('AWS_DEFAULT_REGION'))
                lambda_client.invoke(FunctionName=delete_lambda, InvocationType='Event', Payload=json.dumps(payload).encode('utf-8'))
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Failed to invoke delete lambda: {e}")
            return Response(status_code=202)

        # No lambda configured: perform synchronous deletion and fail if it doesn't work
        deleted = s3.delete_s3_object(file_record.s3_key)
        if not deleted:
            # If we couldn't remove the S3 asset, do not remove the DB record
            # so operators can retry or investigate; surface an error to client.
            raise HTTPException(status_code=500, detail="Failed to delete object from S3")

    db.delete(file_record)
    db.commit()
    return None


@app.post("/api/v1/files/{file_id}/delete-complete")
def delete_complete(file_id: int, payload: dict, request: Request, db: Session = Depends(get_db)):
    """Callback endpoint for the delete Lambda to notify the backend of the
    result. This endpoint is protected by the `VERIFY_SECRET` header.
    Payload should be: {"deleted": true|false, "message": "..."}
    """
    verify_token = request.headers.get('X-Verify-Token')
    expected = os.getenv('VERIFY_SECRET')
    if expected and verify_token != expected:
        raise HTTPException(status_code=401, detail='Unauthorized')

    file_record = db.query(models.CSVFile).filter(models.CSVFile.id == file_id).first()
    if not file_record:
        raise HTTPException(status_code=404, detail='File not found')

    deleted_flag = bool(payload.get('deleted'))
    message = payload.get('message')

    if deleted_flag:
        # Record completion timestamp for audit before removing
        file_record.delete_completed_at = datetime.utcnow()
        db.add(file_record)
        db.commit()
        # Now remove the DB record
        db.delete(file_record)
        db.commit()
        return {"deleted": True}
    else:
        file_record.status = 'delete_failed'
        # store the callback message for operator diagnostics
        try:
            file_record.delete_last_error = str(message) if message is not None else None
        except Exception:
            file_record.delete_last_error = None
        # increment attempts counter
        try:
            file_record.delete_attempts = (file_record.delete_attempts or 0) + 1
        except Exception:
            file_record.delete_attempts = 1
        db.add(file_record)
        db.commit()
        return {"deleted": False, "message": message}
