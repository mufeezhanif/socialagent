import mimetypes

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.security import verify_media_token

router = APIRouter(tags=["media"])


@router.get("/media/{token}")
async def media(token: str):
    path = verify_media_token(token)
    if path is None:
        raise HTTPException(404, "Not found or link expired")
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(path, media_type=media_type, headers={"Cache-Control": "private, max-age=3600"})
