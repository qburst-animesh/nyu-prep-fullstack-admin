import React, { useState, useEffect } from 'react';
import { fetchAuthSession } from 'aws-amplify/auth';
import { Box, Typography, Button, IconButton, CircularProgress } from '@mui/material';
import { DataGrid } from '@mui/x-data-grid';
import DeleteIcon from '@mui/icons-material/Delete';
import CloudUploadIcon from '@mui/icons-material/CloudUpload';

const API_BASE_URL = 'http://localhost:8000/api/v1';

// Custom wrapper replacing Axios interceptor logic using native browser fetch
async function authenticatedFetch(path, options = {}) {
  try {
    const session = await fetchAuthSession();
    const token = session.tokens?.accessToken?.toString();

    const headers = {
      'Content-Type': 'application/json',
      ...options.headers,
    };

    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    return fetch(`${API_BASE_URL}${path}`, { ...options, headers });
  } catch (error) {
    console.warn('Cognito session token unavailable, proceeding with default fetch headers.', error);
    const headers = {
      'Content-Type': 'application/json',
      ...options.headers,
    };
    return fetch(`${API_BASE_URL}${path}`, { ...options, headers });
  }
}

export default function CSVTable() {
  const [fileList, setFileList] = useState([]);
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);

  useEffect(() => {
    fetchDatabaseRecords();
  }, []);

  // CRUD - READ (Fetch records from database via FastAPI)
  const fetchDatabaseRecords = async () => {
    setLoading(true);
    try {
      const response = await authenticatedFetch('/files');
      if (!response.ok) throw new Error('Network error fetching catalog data.');
      const data = await response.json();
      setFileList(data);
    } catch (err) {
      console.error('Failed to load database ledger:', err);
    } finally {
      setLoading(false);
    }
  };

  // CRUD - CREATE (Presigned Lifecycle Upload Flow)
  const handleFileUpload = async (event) => {
    const file = event.target.files[0];
    if (!file) return;

    setUploading(true);
    try {
      // Step A: Request AWS Presigned Slot allocation from backend
      const urlResponse = await authenticatedFetch('/files/upload-url', {
        method: 'POST',
        body: JSON.stringify({
          filename: file.name,
          file_size_bytes: file.size,
          mime_type: file.type || 'text/csv'
        })
      });

      if (!urlResponse.ok) throw new Error('Could not secure presigned allocation pointer.');
      const { upload_url, s3_key } = await urlResponse.json();

      // Step B: Direct Binary Stream to AWS S3 Bucket (Bypass API gateway load limits)
      // Standard native fetch is intentionally used here to omit bearer authorization strings intended only for our app backend
      const s3PutResponse = await fetch(upload_url, {
        method: 'PUT',
        body: file,
        headers: { 'Content-Type': file.type || 'text/csv' }
      });

      if (!s3PutResponse.ok) throw new Error('S3 direct file stream transmission rejected.');

      // Step C: Commit File Meta Records into PostgreSQL Database Ledger
      const confirmResponse = await authenticatedFetch('/files', {
        method: 'POST',
        body: JSON.stringify({
          filename: file.name,
          file_size_bytes: file.size,
          mime_type: file.type || 'text/csv',
          s3_key: s3_key
        })
      });

      if (!confirmResponse.ok) throw new Error('Database registry acknowledgment failed.');

      fetchDatabaseRecords(); // Synchronize UI state layout engine views
    } catch (err) {
      console.error('Asynchronous upload execution broken:', err);
    } finally {
      setUploading(false);
    }
  };

  // CRUD - DELETE (Removes object row from Database ledger registry index)
  const handleDeleteFile = async (idToDelete) => {
    try {
      const response = await authenticatedFetch(`/files/${idToDelete}`, {
        method: 'DELETE'
      });
      if (!response.ok) throw new Error('Delete transaction rejected by API server engine.');
      setFileList(prev => prev.filter(file => file.id !== idToDelete));
    } catch (err) {
      console.error('Failed to purge selected database asset record:', err);
    }
  };

  // Columns definition mapping data attributes to DataGrid
  const tableColumns = [
    { field: 'id', headerName: 'ID', width: 70 },
    { field: 'filename', headerName: 'File Name', width: 230 },
    { 
      field: 'file_size_bytes', 
      headerName: 'Size', 
      width: 130,
      valueFormatter: (value) => {
        if (!value) return '0 KB';
        return `${(value / 1024).toFixed(2)} KB`;
      }
    },
    { field: 'mime_type', headerName: 'MIME Classification', width: 160 },
    { 
      field: 'created_at', 
      headerName: 'Registration Timestamp', 
      width: 200,
      valueFormatter: (value) => value ? new Date(value).toLocaleString() : ''
    },
    {
      field: 'actions',
      headerName: 'Actions',
      width: 100,
      sortable: false,
      renderCell: (cellData) => (
        <IconButton color="error" onClick={() => handleDeleteFile(cellData.row.id)}>
          <DeleteIcon />
        </IconButton>
      )
    }
  ];

  return (
    <Box sx={{ p: 4, bgcolor: 'white', borderRadius: 2, boxShadow: 2 }}>
      {/* FIXED: Swapped Stack for Box with an sx block to prevent native DOM property leakage */}
      <Box 
        sx={{ 
          display: 'flex', 
          flexDirection: 'row', 
          justifyContent: 'space-between', 
          alignItems: 'center', 
          mb: 3 
        }}
      >
        <Typography variant="h5" sx={{ fontWeight: 'bold', color: '#1976d2' }}>
          Database CSV Records
        </Typography>
        <Button 
          variant="contained" 
          component="label"
          startIcon={uploading ? <CircularProgress size={20} color="inherit" /> : <CloudUploadIcon />} 
          disabled={uploading}
        >
          {uploading ? 'Uploading...' : 'Upload CSV'}
          <input type="file" accept=".csv" hidden onChange={handleFileUpload} />
        </Button>
      </Box>

      <Box sx={{ height: 400, width: '100%' }}>
        <DataGrid 
          rows={fileList} 
          columns={tableColumns} 
          loading={loading}
          pageSizeOptions={[]}
          initialState={{ pagination: { paginationModel: { page: 0, pageSize: 5 } } }}
        />
      </Box>
    </Box>
  );
}
