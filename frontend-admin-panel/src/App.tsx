import React, { useEffect, useState } from 'react';
import { Container, Box, Alert } from '@mui/material';
import CSVTable from './components/CSVTable';
import AuthGate from './components/AuthGate';
import UserSessionBar from './components/UserSessionBar';
import { AUTH_SESSION_EXPIRED_EVENT } from './utils/apiFetch';


function AuthenticatedLayout({ signOut, user, sessionExpiredNotice, onSessionExpired, authEnabled }: { signOut?: () => void; user?: any; sessionExpiredNotice: string | null; onSessionExpired: (notice: string) => void; authEnabled: boolean }) {
  useEffect(() => {
    const onExpired = () => {
      onSessionExpired('Your session expired. Please sign in again.');
      try {
        if (typeof signOut === 'function') signOut();
      } catch (e) {
        // ignore
      }
    };
    window.addEventListener(AUTH_SESSION_EXPIRED_EVENT, onExpired as EventListener);
    return () => window.removeEventListener(AUTH_SESSION_EXPIRED_EVENT, onExpired as EventListener);
  }, [signOut, onSessionExpired]);

  return (
    <Box sx={{ bgcolor: '#f4f6f8', minHeight: '100vh' }}>
      {sessionExpiredNotice && authEnabled && (
        <Container maxWidth="lg" sx={{ pt: 2 }}>
          <Alert severity="warning" onClose={() => onSessionExpired('')} sx={{ mb: 2 }}>
            {sessionExpiredNotice}
          </Alert>
        </Container>
      )}
      {!authEnabled && (
        <Container maxWidth="lg" sx={{ pt: 2 }}>
          <Alert severity="warning" sx={{ mb: 2 }}>
            Authentication is disabled because Cognito environment variables are not configured.
          </Alert>
        </Container>
      )}
      <UserSessionBar
        username={user?.username}
        onLogout={signOut}
        authEnabled={authEnabled}
      />
      <Container maxWidth="lg" sx={{ mt: 6 }}>
        <CSVTable />
      </Container>
    </Box>
  );
}

export default function App({ authEnabled = true }: { authEnabled?: boolean }) {
  const [sessionExpiredNotice, setSessionExpiredNotice] = useState<string | null>(null);

  return (
    <AuthGate authEnabled={authEnabled}>
      {({ signOut, user }) => <AuthenticatedLayout signOut={signOut} user={user} sessionExpiredNotice={sessionExpiredNotice} onSessionExpired={setSessionExpiredNotice} authEnabled={authEnabled} />}
    </AuthGate>
  );
}