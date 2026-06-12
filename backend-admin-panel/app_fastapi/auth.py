from jose import jwt
import requests
import os


def _get_cognito_config():
    region = os.getenv('COGNITO_REGION')
    user_pool = os.getenv('COGNITO_USER_POOL_ID')
    client_id = os.getenv('COGNITO_CLIENT_ID')
    if not (region and user_pool and client_id):
        raise RuntimeError('Cognito environment variables not configured')
    return region, user_pool, client_id


def _fetch_jwks(region: str, user_pool: str):
    jwks_url = f"https://cognito-idp.{region}.amazonaws.com/{user_pool}/.well-known/jwks.json"
    resp = requests.get(jwks_url, timeout=10)
    resp.raise_for_status()
    return resp.json()


def verify_token(token: str):
    region, user_pool, client_id = _get_cognito_config()
    jwks = _fetch_jwks(region, user_pool)

    header = jwt.get_unverified_header(token)
    key = next((k for k in jwks.get('keys', []) if k.get('kid') == header.get('kid')), None)
    if not key:
        raise Exception('Unable to find JWKS key')

    issuer = f"https://cognito-idp.{region}.amazonaws.com/{user_pool}"
    return jwt.decode(token, key, algorithms=['RS256'], audience=client_id, issuer=issuer)