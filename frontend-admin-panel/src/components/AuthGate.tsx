import React, { useEffect, useState } from 'react';
import { Box, CircularProgress, Alert } from '@mui/material';

export interface AuthRenderProps {
  signOut?: () => void;
  user?: Record<string, any>;
}

interface AuthGateProps {
  authEnabled: boolean;
  children: (props: AuthRenderProps) => React.ReactNode;
}

export default function AuthGate({ authEnabled, children }: AuthGateProps) {
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
    return <>{children({ user: { username: 'local-dev' } })}</>;
  }

  if (authLoadError) {
    return (
      <Box sx={{ p: 3 }}>
        <Alert severity="error">
          Authentication UI failed to load: {authLoadError}
        </Alert>
      </Box>
    );
  }

  if (!AuthenticatorComp) {
    return (
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '60vh' }}>
        <CircularProgress />
      </Box>
    );
  }

  const Authenticator = AuthenticatorComp;
  return <Authenticator>{(props: AuthRenderProps) => children(props)}</Authenticator>;
}
