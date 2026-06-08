import { fetchAuthSession } from 'aws-amplify/auth';
import pino from 'pino';

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

export async function authenticatedFetch(path: string, options: RequestInit = {}): Promise<Response> {
  const targetUrl = `${RESOLVED_API_BASE}${path.startsWith('/') ? '' : '/'}${path}`;

  // Set default core headers upfront to keep execution DRY
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string>),
  };

  try {
    const session = await fetchAuthSession();
    const token = session?.tokens?.accessToken?.toString?.();

    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
      logger.debug({ path }, 'Appended Cognito bearer token to request assets.');
    }
  } catch (error) {
    logger.warn({ error, path }, 'Cognito session token unavailable; fallback to unauthenticated dispatch.');
  }

  return await fetch(targetUrl, { ...options, headers });
}