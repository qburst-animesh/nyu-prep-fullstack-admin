from sqlalchemy import Column, Integer, String, DateTime, BigInteger, Boolean
from datetime import datetime
from .database import Base

class CSVFile(Base):
    __tablename__ = "csv_files"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String, nullable=False)
    s3_key = Column(String, unique=True, nullable=False)
    file_size_bytes = Column(BigInteger, nullable=False)
    mime_type = Column(String, default="text/csv")
    uploaded_by = Column(String, nullable=True) # Matches Cognito User Sub
    status = Column(String, default="pending")
    verified = Column(Boolean, nullable=True)
    verification_attempts = Column(Integer, default=0)
    # Async delete tracking
    delete_requested_at = Column(DateTime, nullable=True)
    delete_attempts = Column(Integer, default=0)
    delete_last_error = Column(String, nullable=True)
    delete_completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
