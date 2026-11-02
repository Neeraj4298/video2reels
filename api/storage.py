"""
MinIO / S3-compatible storage client helper.
Wraps minio-py for upload, download, and presigned URL generation.
"""
from __future__ import annotations
import io
import uuid
from pathlib import Path

from minio import Minio
from minio.error import S3Error

from api.config import get_settings

_settings = get_settings()


def get_client() -> Minio:
    """Return a cached MinIO client."""
    return Minio(
        _settings.minio_endpoint,
        access_key=_settings.minio_access_key,
        secret_key=_settings.minio_secret_key,
        secure=_settings.minio_secure,
    )


def upload_file(bucket: str, key: str, path: Path | str) -> str:
    """Upload a local file to object storage. Returns the storage key."""
    client = get_client()
    path = Path(path)
    client.fput_object(bucket, key, str(path))
    return key


def upload_bytes(bucket: str, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
    """Upload in-memory bytes to object storage. Returns the storage key."""
    client = get_client()
    bio = io.BytesIO(data)
    client.put_object(bucket, key, bio, length=len(data), content_type=content_type)
    return key


def download_file(bucket: str, key: str, dest: Path | str) -> Path:
    """Download an object from storage to a local path."""
    client = get_client()
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    client.fget_object(bucket, key, str(dest))
    return dest


def download_bytes(bucket: str, key: str) -> bytes:
    """Download an object from storage as bytes."""
    client = get_client()
    response = client.get_object(bucket, key)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()


def presigned_get_url(bucket: str, key: str, ttl_seconds: int = 3600) -> str:
    """Generate a presigned GET URL (for downloading renders)."""
    from datetime import timedelta
    client = get_client()
    return client.presigned_get_object(bucket, key, expires=timedelta(seconds=ttl_seconds))


def presigned_put_url(bucket: str, key: str, ttl_seconds: int = 3600) -> str:
    """Generate a presigned PUT URL (for direct browser uploads)."""
    from datetime import timedelta
    client = get_client()
    return client.presigned_put_object(bucket, key, expires=timedelta(seconds=ttl_seconds))


def object_exists(bucket: str, key: str) -> bool:
    """Check if an object exists in storage."""
    client = get_client()
    try:
        client.stat_object(bucket, key)
        return True
    except S3Error:
        return False


def delete_object(bucket: str, key: str) -> None:
    """Delete an object from storage."""
    client = get_client()
    try:
        client.remove_object(bucket, key)
    except S3Error:
        pass


def delete_prefix(bucket: str, prefix: str) -> None:
    """Delete all objects under a given prefix in a bucket."""
    client = get_client()
    try:
        objects = client.list_objects(bucket, prefix=prefix, recursive=True)
        for obj in objects:
            client.remove_object(bucket, obj.object_name)
    except Exception:
        pass

