"""
Custom storage backends for Campus Journal.

Provides SupabaseMediaStorage for persisting user-uploaded media (such as
news article featured images) directly to Supabase Storage when configured,
with a safe fallback to local FileSystemStorage (using /tmp/media in serverless
environments such as Vercel) for local development and test suites.
"""

import logging
import mimetypes
import os
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage

logger = logging.getLogger(__name__)


def is_supabase_configured() -> bool:
    """Returns True if Supabase URL and Secret Key are both configured."""
    url = getattr(settings, 'SUPABASE_URL', '')
    key = getattr(settings, 'SUPABASE_SECRET_KEY', '')
    return bool(url and key and str(url).strip() and str(key).strip())


def get_storage_bucket_name() -> str:
    """Returns the configured Supabase Storage bucket name."""
    return getattr(settings, 'SUPABASE_STORAGE_BUCKET', 'submission-files')


def get_supabase_client():
    """Returns an authenticated Supabase client, or None."""
    if not is_supabase_configured():
        return None
    try:
        from supabase import create_client
        return create_client(settings.SUPABASE_URL.strip(), settings.SUPABASE_SECRET_KEY.strip())
    except Exception as exc:
        logger.error(f"Failed to initialize Supabase client for media storage: {exc}")
        return None


class SupabaseMediaStorage(FileSystemStorage):
    """
    Storage backend for user uploads (such as news featured images).
    When Supabase credentials are configured, persists files directly to Supabase Storage.
    Falls back gracefully to local FileSystemStorage (or /tmp/media in serverless environments)
    when Supabase is unconfigured or during local test execution.
    """

    def __init__(self, *args, **kwargs):
        location = kwargs.pop('location', None) or str(settings.MEDIA_ROOT)
        base_url = kwargs.pop('base_url', None) or settings.MEDIA_URL
        super().__init__(location=location, base_url=base_url, *args, **kwargs)

    def _save(self, name, content):
        normalized_name = str(name).replace('\\', '/').lstrip('/')
        if is_supabase_configured():
            try:
                client = get_supabase_client()
                if client:
                    bucket = get_storage_bucket_name()
                    content.seek(0)
                    file_bytes = content.read()
                    content_type, _ = mimetypes.guess_type(normalized_name)
                    content_type = content_type or 'application/octet-stream'

                    file_options = {
                        'content-type': content_type,
                        'upsert': 'true',
                    }
                    client.storage.from_(bucket).upload(normalized_name, file_bytes, file_options)
                    return normalized_name
            except Exception as exc:
                logger.warning(
                    f"Supabase media upload failed for '{normalized_name}': {exc}. Falling back to local storage."
                )

        try:
            return super()._save(name, content)
        except OSError as exc:
            logger.error(f"Local storage save failed for '{name}': {exc}")
            return normalized_name

    def url(self, name):
        if not name:
            return ''
        normalized_name = str(name).replace('\\', '/').lstrip('/')
        if is_supabase_configured():
            try:
                client = get_supabase_client()
                if client:
                    bucket = get_storage_bucket_name()
                    try:
                        res = client.storage.from_(bucket).create_signed_url(normalized_name, expires_in=86400)
                        signed_url = (
                            res.get('signedURL') or res.get('signedUrl')
                            if isinstance(res, dict)
                            else getattr(res, 'signed_url', None) or getattr(res, 'signedURL', None)
                        )
                        if signed_url:
                            return signed_url
                    except Exception:
                        pass
                    public_url = client.storage.from_(bucket).get_public_url(normalized_name)
                    if public_url:
                        return public_url
            except Exception as exc:
                logger.warning(f"Failed to generate Supabase URL for '{normalized_name}': {exc}")

        return super().url(name)

    def exists(self, name):
        normalized_name = str(name).replace('\\', '/').lstrip('/')
        if is_supabase_configured():
            try:
                client = get_supabase_client()
                if client:
                    bucket = get_storage_bucket_name()
                    return client.storage.from_(bucket).exists(normalized_name)
            except Exception:
                pass
        return super().exists(name)

    def delete(self, name):
        normalized_name = str(name).replace('\\', '/').lstrip('/')
        if is_supabase_configured():
            try:
                client = get_supabase_client()
                if client:
                    bucket = get_storage_bucket_name()
                    client.storage.from_(bucket).remove([normalized_name])
            except Exception:
                pass
        try:
            super().delete(name)
        except Exception:
            pass

    def _open(self, name, mode='rb'):
        normalized_name = str(name).replace('\\', '/').lstrip('/')
        if is_supabase_configured():
            try:
                client = get_supabase_client()
                if client:
                    bucket = get_storage_bucket_name()
                    data = client.storage.from_(bucket).download(normalized_name)
                    return ContentFile(data, name=name)
            except Exception:
                pass
        return super()._open(name, mode=mode)
