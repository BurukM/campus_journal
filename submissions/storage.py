"""
Supabase Storage integration for Campus Journal submissions.

Manages the lifecycle of project files uploaded directly to Supabase Storage:
1. Creating short-lived signed upload URLs/tokens for direct client-side uploads.
2. Server-side verification of uploaded storage objects.
3. Generating short-lived signed download URLs for authorized users.
4. In-memory downloading of storage objects for Technical Design Brief compilation.
5. Isolated local development fallback when Supabase credentials are not configured.
"""

import logging
import os
import urllib.parse
from pathlib import Path
from typing import Any, Optional, Tuple

from django.conf import settings
from django.urls import reverse

logger = logging.getLogger(__name__)


class StorageServiceError(Exception):
    """Raised when an operation with the storage backend fails."""
    pass


def is_supabase_configured() -> bool:
    """Returns True if Supabase URL and Secret Key are both configured."""
    url = getattr(settings, 'SUPABASE_URL', '')
    key = getattr(settings, 'SUPABASE_SECRET_KEY', '')
    return bool(url and key and url.strip() and key.strip())


def get_storage_bucket_name() -> str:
    """Returns the configured Supabase Storage bucket name."""
    return getattr(settings, 'SUPABASE_STORAGE_BUCKET', 'submission-files')


def get_supabase_client():
    """
    Creates and returns a Supabase client configured with the server-side secret key.
    Returns None if Supabase credentials are not configured.
    """
    if not is_supabase_configured():
        return None
    try:
        from supabase import create_client
        return create_client(settings.SUPABASE_URL.strip(), settings.SUPABASE_SECRET_KEY.strip())
    except Exception as exc:
        logger.error(f"Failed to initialize Supabase client: {exc}")
        return None


def create_signed_upload_url(path: str, request=None) -> dict:
    """
    Asks Supabase for a temporary signed upload URL and token for the specified path.
    The client will upload the file directly to this URL using HTTP PUT.

    Returns:
        dict: {
            'upload_url': str,
            'token': str,
            'storage_path': str,
            'bucket': str,
            'provider': 'supabase' | 'local',
        }
    """
    path = path.strip('/')
    bucket = get_storage_bucket_name()
    client = get_supabase_client()

    if client:
        try:
            res = client.storage.from_(bucket).create_signed_upload_url(path)
            # res is a dict: {'signed_url': ..., 'signedUrl': ..., 'token': ..., 'path': ...}
            url = res.get('signed_url') or res.get('signedUrl')
            token = res.get('token', '')
            if not url:
                raise StorageServiceError("Supabase did not return a valid signed upload URL.")
            return {
                'upload_url': url,
                'token': token,
                'storage_path': path,
                'bucket': bucket,
                'provider': 'supabase',
            }
        except Exception as exc:
            logger.error(f"Error creating Supabase signed upload URL for path '{path}': {exc}")
            raise StorageServiceError(f"Could not generate signed upload URL from Supabase: {exc}")

    # Local fallback when Supabase credentials are not configured
    from django.urls import reverse
    local_endpoint = reverse('submissions:local_upload') + f'?path={urllib.parse.quote(path)}'
    if request:
        local_endpoint = request.build_absolute_uri(local_endpoint)
    return {
        'upload_url': local_endpoint,
        'token': 'local-dev-token',
        'storage_path': path,
        'bucket': 'local',
        'provider': 'local',
    }


def verify_storage_object(path: str, max_size_bytes: Optional[int] = None) -> Tuple[bool, dict]:
    """
    Verifies that the object was uploaded and exists in storage, and checks size limits.

    Returns:
        tuple (is_valid, metadata_or_error_dict)
    """
    path = path.strip('/')
    bucket = get_storage_bucket_name()
    client = get_supabase_client()

    if client:
        try:
            exists = client.storage.from_(bucket).exists(path)
            if not exists:
                return False, {'error': f"Object '{path}' was not found in Supabase bucket '{bucket}'."}

            size = 0
            content_type = ''

            # Try info() first
            try:
                info_data = client.storage.from_(bucket).info(path)
                size = info_data.get('size') or info_data.get('metadata', {}).get('size', 0)
                content_type = info_data.get('mimetype') or info_data.get('metadata', {}).get('mimetype', '')
            except Exception:
                # Fall back to list()
                folder = os.path.dirname(path)
                filename = os.path.basename(path)
                items = client.storage.from_(bucket).list(folder)
                for item in items:
                    if item.get('name') == filename:
                        meta = item.get('metadata') or {}
                        size = meta.get('size', 0)
                        content_type = meta.get('mimetype', '')
                        break

            if max_size_bytes and size and size > max_size_bytes:
                max_mb = max_size_bytes / (1024 * 1024)
                return False, {
                    'error': f"Uploaded file size ({size / (1024*1024):.1f} MB) exceeds maximum allowed size ({max_mb:.0f} MB)."
                }

            return True, {
                'size': size,
                'content_type': content_type,
                'storage_path': path,
                'provider': 'supabase',
            }

        except Exception as exc:
            logger.error(f"Error verifying storage object '{path}': {exc}")
            return False, {'error': f"Verification error with storage provider: {exc}"}

    if getattr(settings, 'DEBUG', False):
        full_path = Path(settings.MEDIA_ROOT) / path
        if not full_path.exists():
            return False, {'error': f"Local file not found at '{path}'."}
        size = full_path.stat().st_size
        if max_size_bytes and size > max_size_bytes:
            max_mb = max_size_bytes / (1024 * 1024)
            return False, {
                'error': f"Uploaded file size ({size / (1024*1024):.1f} MB) exceeds maximum allowed size ({max_mb:.0f} MB)."
            }
        return True, {
            'size': size,
            'content_type': '',
            'storage_path': path,
            'provider': 'local',
        }

    return False, {'error': "Storage backend is not configured."}


def create_signed_download_url(path: str, expires_in: int = 60) -> str:
    """
    Generates a temporary signed download URL for private files in Supabase Storage.
    The URL expires after `expires_in` seconds (default 60s).
    """
    path = path.strip('/')
    bucket = get_storage_bucket_name()
    client = get_supabase_client()

    if client:
        try:
            res = client.storage.from_(bucket).create_signed_url(path, expires_in=expires_in)
            url = res.get('signedURL') or res.get('signedUrl')
            if url:
                return url
            raise StorageServiceError("Supabase did not return a valid signed download URL.")
        except Exception as exc:
            logger.error(f"Error generating signed download URL for '{path}': {exc}")
            raise StorageServiceError(f"Could not generate download URL: {exc}")

    # Local development / test fallback
    return f"{settings.MEDIA_URL}{path}"


def download_storage_object(path: str) -> bytes:
    """
    Downloads file bytes directly into memory from Supabase Storage or local fallback.
    Never writes to the filesystem.
    """
    path = path.strip('/')
    bucket = get_storage_bucket_name()
    client = get_supabase_client()

    if client:
        try:
            return client.storage.from_(bucket).download(path)
        except Exception as exc:
            logger.error(f"Error downloading object '{path}' from Supabase: {exc}")
            raise StorageServiceError(f"Could not download object from Supabase Storage: {exc}")

    # Local development / test fallback
    full_path = Path(settings.MEDIA_ROOT) / path
    if full_path.exists():
        with open(full_path, 'rb') as f:
            return f.read()

    raise StorageServiceError(f"Storage object '{path}' could not be retrieved.")
