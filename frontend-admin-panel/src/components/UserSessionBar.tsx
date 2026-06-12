import React from 'react';
import { AppBar, Toolbar, Typography, Button } from '@mui/material';

interface UserSessionBarProps {
  username?: string;
  onLogout?: () => void;
  authEnabled: boolean;
}

export default function UserSessionBar({ username, onLogout, authEnabled }: UserSessionBarProps) {
  return (
    <AppBar position="static" color="primary">
      <Toolbar>
        <Typography variant="h6" sx={{ flexGrow: 1, fontWeight: 'bold' }}>
          Admin Panel Dashboard{authEnabled ? '' : ' (Local)'}
        </Typography>
        <Typography variant="body1" sx={{ mr: 3 }}>
          User: <strong>{username || 'unknown'}</strong>
        </Typography>
        {authEnabled && (
          <Button variant="contained" color="error" onClick={onLogout}>
            Logout
          </Button>
        )}
      </Toolbar>
    </AppBar>
  );
}
