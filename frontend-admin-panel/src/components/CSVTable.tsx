import React from 'react';
import { Box, Typography, Button, IconButton, CircularProgress, Alert } from '@mui/material';
import { DataGrid, GridColDef, GridRenderCellParams } from '@mui/x-data-grid';
import DeleteIcon from '@mui/icons-material/Delete';
import CloudUploadIcon from '@mui/icons-material/CloudUpload';
import { useCSVData, CSVFileRecord} from '../hooks/useCSVData';

function CSVTable() {
  const { fileList, loading, uploading, errorMessage, handleFileUpload, handleDeleteFile } = useCSVData();

  const onFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    handleFileUpload(file);
  };

  const tableColumns: GridColDef<CSVFileRecord>[] = [
    { field: 'id', headerName: 'ID', width: 70 },
    { field: 'filename', headerName: 'File Name', width: 230 },
    {
      field: 'file_size_bytes',
      headerName: 'Size',
      width: 130,
      valueFormatter: (value?: number) => {
        if (!value) return '0 KB';
        return `${(value / 1024).toFixed(2)} KB`;
      }
    },
    { field: 'mime_type', headerName: 'MIME Classification', width: 160 },
    {
      field: 'created_at',
      headerName: 'Registration Timestamp',
      width: 200,
      valueFormatter: (value?: string) => value ? new Date(value).toLocaleString() : ''
    },
    {
      field: 'actions',
      headerName: 'Actions',
      width: 100,
      sortable: false,
      renderCell: (params: GridRenderCellParams<CSVFileRecord>) => (
        <IconButton color="error" onClick={() => handleDeleteFile(params.row.id)}>
          <DeleteIcon />
        </IconButton>
      )
    }
  ];

  return (
    <Box sx={{ p: 4, bgcolor: 'white', borderRadius: 2, boxShadow: 2 }}>
      {errorMessage && (
        <Alert severity="error" sx={{ mb: 3 }}>{errorMessage}</Alert>
      )}

      <Box sx={{ display: 'flex', flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
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
          <input type="file" accept=".csv" hidden onChange={onFileChange} />
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

export default CSVTable;