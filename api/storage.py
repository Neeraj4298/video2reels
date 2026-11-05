"""
MinIO / S3-compatible storage client helper.
Wraps minio-py for upload, download, and presigned URL generation.
"""
from __future__ import annotations
import io
import shutil
import socket
import uuid
from pathlib import Path

from minio import Minio
from minio.error import S3Error

from api.config import get_settings

_settings = get_settings()
_LOCAL_STORAGE_ROOT = Path(__file__).resolve().parent.parent / "work" / "local_storage"


def _local_object_path(bucket: str, key: str) -> Path:
    p = _LOCAL_STORAGE_ROOT / bucket / key
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _is_minio_reachable() -> bool:
    try:
        ep = _settings.minio_endpoint
        host, port_s = (ep.split(":", 1) if ":" in ep else (ep, "9000"))
        sock = socket.socket()
        sock.settimeout(0.3)
        ok = sock.connect_ex((host, int(port_s))) == 0
        sock.close()
        return ok
    except Exception:
        return False


def get_client() -> Minio:
    """Return a MinIO client for internal API/worker storage operations."""
    return Minio(
        _settings.minio_endpoint,
        access_key=_settings.minio_access_key,
        secret_key=_settings.minio_secret_key,
        secure=_settings.minio_secure,
    )


def _get_presign_client() -> Minio:
    """
    Return a MinIO client configured with the browser-reachable endpoint
    (localhost:9000 instead of internal Docker hostname minio:9000) and
    explicit region='us-east-1' so presigning works offline without a network call.
    """
    public_endpoint = _settings.minio_endpoint.replace("minio:9000", "localhost:9000")
    return Minio(
        public_endpoint,
        access_key=_settings.minio_access_key,
        secret_key=_settings.minio_secret_key,
        secure=_settings.minio_secure,
        region="us-east-1",
    )


def upload_file(bucket: str, key: str, path: Path | str) -> str:
    """Upload a local file to object storage (falls back to local disk if MinIO is offline)."""
    path = Path(path)
    try:
        client = get_client()
        client.fput_object(bucket, key, str(path))
    except Exception:
        dest = _local_object_path(bucket, key)
        shutil.copy2(str(path), str(dest))
    return key


def upload_bytes(bucket: str, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
    """Upload in-memory bytes to object storage (falls back to local disk if MinIO is offline)."""
    try:
        client = get_client()
        bio = io.BytesIO(data)
        client.put_object(bucket, key, bio, length=len(data), content_type=content_type)
    except Exception:
        dest = _local_object_path(bucket, key)
        dest.write_bytes(data)
    return key


def download_file(bucket: str, key: str, dest: Path | str) -> Path:
    """Download an object from storage to a local path."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        client = get_client()
        client.fget_object(bucket, key, str(dest))
    except Exception:
        local_src = _local_object_path(bucket, key)
        if local_src.exists():
            shutil.copy2(str(local_src), str(dest))
        else:
            raise
    return dest


def download_bytes(bucket: str, key: str) -> bytes:
    """Download an object from storage as bytes."""
    try:
        client = get_client()
        response = client.get_object(bucket, key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()
    except Exception:
        local_src = _local_object_path(bucket, key)
        if local_src.exists():
            return local_src.read_bytes()
        raise


def presigned_get_url(bucket: str, key: str, ttl_seconds: int = 3600) -> str:
    """Generate a presigned GET URL (or local API streaming URL when MinIO is offline)."""
    if not _is_minio_reachable() and _local_object_path(bucket, key).exists():
        return f"http://localhost:8000/api/clips/storage/{bucket}/{key}"
    from datetime import timedelta
    client = _get_presign_client()
    return client.presigned_get_object(bucket, key, expires=timedelta(seconds=ttl_seconds))


def presigned_put_url(bucket: str, key: str, ttl_seconds: int = 3600) -> str:
    """Generate a presigned PUT URL (for direct browser uploads)."""
    if not _is_minio_reachable():
        return f"http://localhost:8000/api/clips/storage/{bucket}/{key}"
    from datetime import timedelta
    client = _get_presign_client()
    return client.presigned_put_object(bucket, key, expires=timedelta(seconds=ttl_seconds))


def object_exists(bucket: str, key: str) -> bool:
    """Check if an object exists in storage."""
    if _local_object_path(bucket, key).exists():
        return True
    client = get_client()
    try:
        client.stat_object(bucket, key)
        return True
    except S3Error:
        return False
    except Exception:
        return _local_object_path(bucket, key).exists()


def delete_object(bucket: str, key: str) -> None:
    """Delete an object from storage."""
    local_p = _local_object_path(bucket, key)
    if local_p.exists():
        local_p.unlink(missing_ok=True)
    client = get_client()
    try:
        client.remove_object(bucket, key)
    except Exception:
        pass


def delete_prefix(bucket: str, prefix: str) -> None:
    """Delete all objects under a given prefix in a bucket."""
    local_dir = _LOCAL_STORAGE_ROOT / bucket / prefix
    if local_dir.exists():
        shutil.rmtree(local_dir, ignore_errors=True)
    client = get_client()
    try:
        objects = client.list_objects(bucket, prefix=prefix, recursive=True)
        for obj in objects:
            client.remove_object(bucket, obj.object_name)
    except Exception:
        pass

