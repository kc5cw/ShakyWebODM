import hashlib

from webodm import settings


def external_provider_key():
    endpoint = settings.EXTERNAL_AUTH_ENDPOINT
    if not endpoint:
        raise ValueError('External authentication is disabled')
    return hashlib.sha256(endpoint.encode('utf-8')).hexdigest()


def normalize_external_user_id(value):
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError('External user ID must be a positive integer')
    text = str(value)
    if not text or len(text) > 255 or not text.isascii() or not text.isdecimal():
        raise ValueError('External user ID must be a positive integer')
    number = int(text)
    if number <= 0:
        raise ValueError('External user ID must be a positive integer')
    return str(number)
