import React, { useEffect, useState } from 'react';
import { AppBar, Toolbar, Typography, Button, Container, Box, CircularProgress, Alert } from '@mui/material';
import CSVTable from './components/CSVTable';

const customFormFields = {
  signUp: {
    email: {
      order: 1,
      isRequired: true,
      label: 'Email Address',
      placeholder: 'Enter your email',
      name: 'email'
    },
    username: { order: 2 },
    password: { order: 3 },
    confirm_password: { order: 4 }
  }
};

interface AuthChildrenProps {
  signOut?: () => void;
  user?: Record<string, any>;
}

export default function App({ authEnabled = true }: { authEnabled?: boolean }) {
  const [AuthenticatorComp, setAuthenticatorComp] = useState<any | null>(null);
  const [authLoadError, setAuthLoadError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    if (!authEnabled) return;

    (async () => {
      try {
        const mod = await import('@aws-amplify/ui-react');
        if (!mounted) return;
        setAuthenticatorComp(() => mod.Authenticator);
        // try load styles optionally (non-fatal)
        try {
          await import('@aws-amplify/ui-react/styles.css');
        } catch (_) {}
      } catch (err: any) {
        if (!mounted) return;
        setAuthLoadError(err?.message || String(err));
        setAuthenticatorComp(null);
      }
    })();

    return () => {
      mounted = false;
    };
  }, [authEnabled]);

  if (!authEnabled) {
    // Render a simple unauthenticated layout for local development
    return (
      <Box sx={{ bgcolor: '#f4f6f8', minHeight: '100vh' }}>
        <AppBar position="static" color="primary">
          <Toolbar>
            <Typography variant="h6" sx={{ flexGrow: 1, fontWeight: 'bold' }}>
              Admin Panel Dashboard (Local)
            </Typography>
            <Typography variant="body1" sx={{ mr: 3 }}>
              User: <strong>local-dev</strong>
            </Typography>
          </Toolbar>
        </AppBar>
        <Container maxWidth="lg" sx={{ mt: 6 }}>
          <CSVTable />
        </Container>
      </Box>
    );
  }

  if (authLoadError) {
    // If the auth UI package failed to load, show a warning and fall back
    return (
      <Box sx={{ bgcolor: '#f4f6f8', minHeight: '100vh' }}>
        <AppBar position="static" color="primary">
          <Toolbar>
            <Typography variant="h6" sx={{ flexGrow: 1, fontWeight: 'bold' }}>
              Admin Panel Dashboard
            </Typography>
            <Typography variant="body1" sx={{ mr: 3 }}>
              User: <strong>auth-unavailable</strong>
            </Typography>
          </Toolbar>
        </AppBar>
        <Container maxWidth="lg" sx={{ mt: 6 }}>
          <Alert severity="warning" sx={{ mb: 2 }}>
            Authentication UI failed to load; running without hosted sign-in. ({authLoadError})
          </Alert>
          <CSVTable />
        </Container>
      </Box>
    );
  }

  if (!AuthenticatorComp) {
    // Still loading the auth UI
    return (
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '60vh' }}>
        <CircularProgress />
      </Box>
    );
  }

  const Authenticator = AuthenticatorComp;
  return (
    <Authenticator formFields={customFormFields}>
      {({ signOut, user }: AuthChildrenProps) => (
        <Box sx={{ bgcolor: '#f4f6f8', minHeight: '100vh' }}>
          <AppBar position="static" color="primary">
            <Toolbar>
              <Typography variant="h6" sx={{ flexGrow: 1, fontWeight: 'bold' }}>
                Admin Panel Dashboard
              </Typography>
              <Typography variant="body1" sx={{ mr: 3 }}>
                User: <strong>{user?.username}</strong>
              </Typography>
              <Button variant="contained" color="error" onClick={signOut}>
                Sign Out
              </Button>
            </Toolbar>
          </AppBar>
          <Container maxWidth="lg" sx={{ mt: 6 }}>
            <CSVTable />
          </Container>
        </Box>
      )}
    </Authenticator>
  );
}