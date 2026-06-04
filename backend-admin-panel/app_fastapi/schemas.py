from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class CSVFileBase(BaseModel):
    filename: str
    file_size_bytes: int
    mime_type: Optional[str] = "text/csv"

class CSVFileCreate(CSVFileBase):
    s3_key: str
    uploaded_by: Optional[str] = None

class CSVFileResponse(CSVFileBase):
    id: int
    s3_key: str
    uploaded_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
