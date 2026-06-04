from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from typing import List
import uuid

from .database import engine, Base, get_db
from . import models, schemas
from .s3_service import S3Service
from fastapi.middleware.cors import CORSMiddleware

# Initialize Database tables
Base.metadata.create_all(bind=engine)

app = FastAPI(title="CSV Cloud Infrastructure Backend", version="1.0.0")
s3 = S3Service()

# CORS configuration targeting your MUI React Admin Framework
origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/api/v1/files/upload-url", response_model=dict)
def request_upload_url(file_info: schemas.CSVFileBase):
    """
    Step 1: Frontend asks for an S3 storage token layout slot.
    Returns a unique tracking key and direct network destination path.
    """
    unique_key = f"csv_uploads/{uuid.uuid4()}_{file_info.filename}"
    upload_url = s3.generate_presigned_upload_url(unique_key)
    
    if not upload_url:
        raise HTTPException(status_code=500, detail="Cloud storage URL generation failed")
        
    return {"upload_url": upload_url, "s3_key": unique_key}

@app.post("/api/v1/files", response_model=schemas.CSVFileResponse, status_code=status.HTTP_201_CREATED)
def record_file_metadata(payload: schemas.CSVFileCreate, db: Session = Depends(get_db)):
    """
    Step 2: Frontend calls this after successful S3 streaming upload.
    Saves the operational records to PostgreSQL.
    """
    db_file = models.CSVFile(**payload.model_dump())
    db.add(db_file)
    db.commit()
    db.refresh(db_file)
    return db_file

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
        raise HTTPException(status_code=404, detail="Requested record not found in system storage index")
    
    download_url = s3.generate_presigned_download_url(file_record.s3_key)
    return {"download_url": download_url}

@app.delete("/api/v1/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_file_record(file_id: int, db: Session = Depends(get_db)):
    """Executes distributed cleanup actions across both Database and S3 boundaries"""
    file_record = db.query(models.CSVFile).filter(models.CSVFile.id == file_id).first()
    if not file_record:
        raise HTTPException(status_code=404, detail="Target asset metadata not found")

    # Clear cloud asset and data ledger steps
    s3.delete_s3_object(file_record.s3_key)
    db.delete(file_record)
    db.commit()
    return None
