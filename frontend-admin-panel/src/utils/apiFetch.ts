import pino from 'pino';
import { fetchAuthSession, signOut as amplifySignOut } from 'aws-amplify/auth';

export const logger = pino({
  browser: { asObject: true },
  level: (import.meta.env.VITE_LOG_LEVEL as string) || 'info',
  redact: ['headers.Authorization', 'token'],
});

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL as string | undefined;
const DEFAULT_API_BASE = 'http://localhost:8000/api/v1';
const RESOLVED_API_BASE = API_BASE_URL ?? DEFAULT_API_BASE;
if (!API_BASE_URL) {
  logger.warn(`VITE_API_BASE_URL not defined — defaulting to ${DEFAULT_API_BASE}`);
}

const AUTH_ENABLED = Boolean(import.meta.env.VITE_COGNITO_USER_POOL_ID && import.meta.env.VITE_COGNITO_CLIENT_ID);
export const AUTH_SESSION_EXPIRED_EVENT = 'auth:session-expired';

let signOutInProgress = false;

async function forceLogoutOnSessionExpiry(path: string, reason: string) {
  if (!AUTH_ENABLED || signOutInProgress) return;
  signOutInProgress = true;
  try {
    logger.warn({ path, reason }, 'Session expired/invalid. Signing out user.');
    await amplifySignOut();
  } catch (error) {
    logger.warn({ error, path, reason }, 'Auto sign-out failed after session expiry.');
  } finally {
    if (typeof window !== 'undefined') {
      window.dispatchEvent(new CustomEvent(AUTH_SESSION_EXPIRED_EVENT, { detail: { path, reason } }));
    }
    signOutInProgress = false;
  }
}

export async function authenticatedFetch(path: string, options: RequestInit = {}): Promise<Response> {
  const targetUrl = `${RESOLVED_API_BASE}${path.startsWith('/') ? '' : '/'}${path}`;

  // Set default core headers upfront to keep execution DRY
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string>),
  };

  if (AUTH_ENABLED) {
    try {
      let session: any = await fetchAuthSession();

      // resilient token extraction for different Amplify shapes
      let token: string | undefined;
      if (session) {
        // Backend validates audience against Cognito app client id, so require ID token.
        token = session?.tokens?.idToken?.toString?.();
        if (!token && typeof session?.getIdToken === 'function') {
          try {
            const it = session.getIdToken();
            token = it && (it.getJwtToken ? it.getJwtToken() : it.jwtToken);
          } catch (e) {
            token = undefined;
          }
        }
      }

      // Try one forced refresh before giving up to avoid stale-session 401s.
      if (!token) {
        try {
          session = await fetchAuthSession({ forceRefresh: true });
          token = session?.tokens?.idToken?.toString?.();
          if (!token && typeof session?.getIdToken === 'function') {
            const it = session.getIdToken();
            token = it && (it.getJwtToken ? it.getJwtToken() : it.jwtToken);
          }
        } catch (_) {}
      }

      if (token) {
        headers['Authorization'] = `Bearer ${token}`;
        logger.debug({ path }, 'Appended Cognito bearer token to request assets.');
      } else {
        logger.warn({ path }, 'Authenticated request attempted without Cognito ID token.');
        await forceLogoutOnSessionExpiry(path, 'missing_id_token');
        return new Response(JSON.stringify({ detail: 'Not authenticated' }), {
          status: 401,
          headers: { 'Content-Type': 'application/json' },
        });
      }
    } catch (error) {
      logger.warn({ error, path }, 'Cognito session token unavailable.');
      await forceLogoutOnSessionExpiry(path, 'session_fetch_failed');
      return new Response(JSON.stringify({ detail: 'Not authenticated' }), {
        status: 401,
        headers: { 'Content-Type': 'application/json' },
      });
    }
  }

  const response = await fetch(targetUrl, { ...options, headers });
  if (AUTH_ENABLED && response.status === 401) {
    await forceLogoutOnSessionExpiry(path, 'backend_401');
  }
  return response;
}