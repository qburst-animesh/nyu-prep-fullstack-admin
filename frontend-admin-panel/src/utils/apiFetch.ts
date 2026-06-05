import { fetchAuthSession } from 'aws-amplify/auth';
import pino from 'pino';

export const logger = pino({
  browser: { asObject: true },
  level: process.env.REACT_APP_LOG_LEVEL || 'info',
  redact: ['headers.Authorization', 'token'],
});

const API_BASE_URL = process.env.REACT_APP_API_BASE_URL;
if (!API_BASE_URL) {
  logger.error('CRITICAL: REACT_APP_API_BASE_URL environment variable is not defined.');
}

export async function authenticatedFetch(path: string, options: RequestInit = {}): Promise<Response> {
  const targetUrl = `${API_BASE_URL}${path}`;
  
  // Set default core headers upfront to keep execution DRY
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string>),
  };

  try {
    const session = await fetchAuthSession();
    const token = session.tokens?.accessToken?.toString();

    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
      logger.debug({ path }, 'Appended Cognito bearer token to request assets.');
    }
  } catch (error) {
    logger.warn({ error, path }, 'Cognito session token unavailable; fallback to unauthenticated dispatch.');
  }

  return await fetch(targetUrl, { ...options, headers });
}