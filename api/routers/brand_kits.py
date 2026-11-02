"""
API router — brand kits
GET    /api/brand-kits        List brand kits
POST   /api/brand-kits        Create brand kit
PATCH  /api/brand-kits/{id}   Update brand kit
DELETE /api/brand-kits/{id}   Delete brand kit
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status, File, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db import get_db
from api.models import BrandKit
from api.schemas import BrandKitCreate, BrandKitRead
from api.storage import upload_bytes
from api.config import get_settings

router = APIRouter(prefix="/api/brand-kits", tags=["brand-kits"])
_settings = get_settings()


@router.get("", response_model=list[BrandKitRead])
async def list_brand_kits(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(BrandKit).order_by(BrandKit.name))
    return result.scalars().all()


@router.post("", response_model=BrandKitRead, status_code=status.HTTP_201_CREATED)
async def create_brand_kit(body: BrandKitCreate, db: AsyncSession = Depends(get_db)):
    kit = BrandKit(**body.model_dump())
    db.add(kit)
    await db.flush()
    return kit


@router.patch("/{kit_id}", response_model=BrandKitRead)
async def update_brand_kit(
    kit_id: uuid.UUID,
    body: BrandKitCreate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(BrandKit).where(BrandKit.id == kit_id))
    kit = result.scalar_one_or_none()
    if not kit:
        raise HTTPException(status_code=404, detail="Brand kit not found")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(kit, field, value)
    return kit


@router.delete("/{kit_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_brand_kit(kit_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(BrandKit).where(BrandKit.id == kit_id))
    kit = result.scalar_one_or_none()
    if not kit:
        raise HTTPException(status_code=404, detail="Brand kit not found")
    await db.delete(kit)


@router.post("/{kit_id}/logo", response_model=BrandKitRead)
async def upload_brand_logo(
    kit_id: uuid.UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Upload a PNG or JPEG logo for a brand kit."""
    result = await db.execute(select(BrandKit).where(BrandKit.id == kit_id))
    kit = result.scalar_one_or_none()
    if not kit:
        raise HTTPException(status_code=404, detail="Brand kit not found")

    content = await file.read()
    ext = file.filename.split(".")[-1] if file.filename and "." in file.filename else "png"
    storage_key = f"brand_kits/{kit_id}/logo.{ext}"
    upload_bytes(
        _settings.bucket_originals,
        storage_key,
        content,
        content_type=file.content_type or "image/png",
    )

    kit.logo_key = storage_key
    return kit
