import { useState, useEffect, useCallback } from 'react';
import { authenticatedFetch, logger } from '../utils/apiFetch';

export interface CSVFileRecord {
  id: number;
  filename: string;
  s3_key: string;
  file_size_bytes: number;
  mime_type: string;
  status?: string;
  verified?: boolean;
  created_at: string;
  updated_at: string;
  delete_requested_at?: string | null;
  delete_attempts?: number | null;
  delete_last_error?: string | null;
  delete_completed_at?: string | null;
}

export function useCSVData() {
  const [fileList, setFileList] = useState<CSVFileRecord[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [uploading, setUploading] = useState<boolean>(false);
  const [uploadProgress, setUploadProgress] = useState<number>(0);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const fetchDatabaseRecords = useCallback(async () => {
    setLoading(true);
    setErrorMessage(null);
    logger.info('Fetching CSV file records');
    try {
      const response = await authenticatedFetch('/files');
      if (!response.ok) throw new Error(`Backend returned ${response.status}`);
      const data: CSVFileRecord[] = await response.json();
      setFileList(data);
    } catch (err: any) {
      logger.error({ err }, 'Failed to fetch file records');
      setErrorMessage('Failed to load database records.');
    } finally {
      setLoading(false);
    }
  }, []);

  const handleFileUpload = async (file: File | undefined) => {
    if (!file) return;
    setUploading(true);
    setErrorMessage(null);

    if (!file.name.toLowerCase().endsWith('.csv')) {
      setErrorMessage('Only .csv files are allowed.');
      setUploading(false);
      return;
    }

    try {
      const urlResponse = await authenticatedFetch('/files/upload-url', {
        method: 'POST',
        body: JSON.stringify({ filename: file.name, file_size_bytes: file.size, mime_type: file.type || 'text/csv' }),
      });

      let urlBody: any = null;
      try { urlBody = await urlResponse.json(); } catch (e) { urlBody = null; }
      if (!urlResponse.ok) {
        const msg = (urlBody && (urlBody.detail?.message || urlBody.message)) || urlBody || `Backend returned ${urlResponse.status}`;
        throw new Error(msg);
      }

      const { upload_url, s3_key } = urlBody;

      // Upload first (keep progress updates via XHR), then create DB record on success.
      const uploadPromise = new Promise<void>((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        try {
          xhr.open('PUT', upload_url);
          try { xhr.setRequestHeader('Content-Type', file.type || 'text/csv'); } catch (e) { }
          xhr.upload.onprogress = (event) => {
            if (event.lengthComputable) setUploadProgress(Math.round((event.loaded / event.total) * 100));
          };

          xhr.onload = () => {
            if (xhr.status >= 200 && xhr.status < 300) {
              resolve();
            } else {
              reject(new Error('Upload failed'));
            }
          };

          xhr.onerror = () => reject(new Error('Upload failed'));

          xhr.send(file);
        } catch (err) {
          reject(err);
        }
      });

      try {
        await uploadPromise;
      } catch (err) {
        setErrorMessage('Upload failed.');
        setUploadProgress(0);
        return;
      }

      // Only create DB record after upload succeeds
      const confirmResponse = await authenticatedFetch('/files', {
        method: 'POST',
        body: JSON.stringify({ filename: file.name, file_size_bytes: file.size, mime_type: file.type || 'text/csv', s3_key }),
      });

      if (!confirmResponse.ok) {
        let b: any = null;
        try { b = await confirmResponse.json(); } catch (e) { try { b = await confirmResponse.text(); } catch (e2) { b = null } }
        throw new Error((b && (b.detail?.message || b.message)) || b || `DB returned ${confirmResponse.status}`);
      }

      await confirmResponse.json();
      await fetchDatabaseRecords();
      setUploadProgress(0);

    } catch (err: any) {
      logger.error({ err }, 'File upload failed');
      setErrorMessage(err?.message || 'Upload error');
    } finally {
      setUploading(false);
    }
  };

  const handleDeleteFile = async (id: number, deleteS3 = false) => {
    try {
      const resp = await authenticatedFetch(`/files/${id}?delete_s3=${deleteS3}`, { method: 'DELETE' });
      if (resp.status === 202) {
        setFileList(prev => prev.map(f => f.id === id ? { ...f, status: 'deleting' } : f));
        return;
      }
      if (resp.status === 404) {
        setFileList(prev => prev.filter(f => f.id !== id));
        return;
      }
      if (!resp.ok) throw new Error(await resp.text());
      setFileList(prev => prev.filter(f => f.id !== id));
    } catch (err) {
      logger.error({ err, id }, 'Delete failed');
      throw err;
    }
  };

  useEffect(() => { fetchDatabaseRecords(); }, [fetchDatabaseRecords]);

  useEffect(() => {
    const hasTransientRows = fileList.some((f) => f.status === 'pending' || f.status === 'deleting');
    if (!hasTransientRows) return;

    const timer = setInterval(() => {
      fetchDatabaseRecords();
    }, 5000);

    return () => clearInterval(timer);
  }, [fileList, fetchDatabaseRecords]);

  useEffect(() => {
    if (!errorMessage) return;
    const t = setTimeout(() => setErrorMessage(null), 5000);
    return () => clearTimeout(t);
  }, [errorMessage]);

  return { fileList, loading, uploading, uploadProgress, errorMessage, handleFileUpload, handleDeleteFile, refresh: fetchDatabaseRecords };
}