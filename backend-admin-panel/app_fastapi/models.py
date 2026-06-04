from sqlalchemy import Column, Integer, String, DateTime, BigInteger
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
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
