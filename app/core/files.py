"""Fayl yuklashni xavfsiz qabul qilish.

Ilgari kengaytma to'g'ridan-to'g'ri klient yuborgan fayl nomidan olinardi va
hajm/tur umuman tekshirilmasdi — `/uploads` statik tarqatilgani uchun bu
zararli fayl hosting va saqlangan XSS imkonini berardi.
"""

import os
import uuid
from typing import Optional, Set

from fastapi import HTTPException, UploadFile, status

from app.core import config

_CHUNK = 64 * 1024


def _extension_for(upload: UploadFile, allowed_ext: Set[str], allowed_mime: Set[str]) -> str:
    content_type = (upload.content_type or "").split(";")[0].strip().lower()
    if content_type not in allowed_mime:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Bu fayl turi qo'llab-quvvatlanmaydi: {content_type or 'noma’lum'}",
        )

    ext = os.path.splitext(upload.filename or "")[1].lower()
    if ext not in allowed_ext:
        # Kengaytma ishonchsiz bo'lsa MIME turidan tiklaymiz.
        ext = {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/webp": ".webp",
            "image/gif": ".gif",
            "application/pdf": ".pdf",
        }.get(content_type, "")
    if not ext:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Fayl kengaytmasini aniqlab bo'lmadi",
        )
    return ext


async def save_upload(
    upload: UploadFile,
    prefix: str = "",
    *,
    allow_documents: bool = False,
) -> str:
    """Faylni `uploads/` ga saqlaydi va `/uploads/<nom>` URL yo'lini qaytaradi.

    Fayl nomi har doim server tomonda generatsiya qilinadi (UUID), shuning
    uchun path traversal yoki nom orqali qayta yozish mumkin emas.
    """
    allowed_ext = set(config.ALLOWED_IMAGE_EXTENSIONS)
    allowed_mime = set(config.ALLOWED_IMAGE_MIME)
    if allow_documents:
        allowed_ext |= config.ALLOWED_DOCUMENT_EXTENSIONS
        allowed_mime |= config.ALLOWED_DOCUMENT_MIME

    ext = _extension_for(upload, allowed_ext, allowed_mime)

    os.makedirs(config.UPLOAD_DIR, exist_ok=True)
    filename = f"{prefix}{uuid.uuid4().hex}{ext}"
    destination = os.path.join(config.UPLOAD_DIR, filename)

    written = 0
    try:
        with open(destination, "wb") as buffer:
            while True:
                chunk = await upload.read(_CHUNK)
                if not chunk:
                    break
                written += len(chunk)
                if written > config.MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=(
                            "Fayl juda katta. Maksimal hajm: "
                            f"{config.MAX_UPLOAD_BYTES // (1024 * 1024)} MB"
                        ),
                    )
                buffer.write(chunk)
    except HTTPException:
        _silent_remove(destination)
        raise
    except OSError as exc:
        _silent_remove(destination)
        raise HTTPException(status_code=500, detail=f"Faylni saqlashda xatolik: {exc}")

    if written == 0:
        _silent_remove(destination)
        raise HTTPException(status_code=400, detail="Bo'sh fayl yuborildi")

    return f"/uploads/{filename}"


def _silent_remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def delete_upload(url_path: Optional[str]) -> None:
    """`/uploads/<nom>` yo'li bo'yicha faylni o'chiradi (xatoni yutadi)."""
    if not url_path:
        return
    filename = os.path.basename(url_path)
    if not filename:
        return
    _silent_remove(os.path.join(config.UPLOAD_DIR, filename))
