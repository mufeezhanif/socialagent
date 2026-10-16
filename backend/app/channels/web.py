from pathlib import Path


class WebChannel:
    """Messages are stored by the outbox; the browser polls /api/chat/messages."""

    name = "web"

    async def send_text(self, chat_ref: str, text: str) -> str | None:
        return None

    async def send_video(self, chat_ref: str, path: Path, caption: str) -> str | None:
        return None

    async def typing(self, chat_ref: str) -> None:
        return None
