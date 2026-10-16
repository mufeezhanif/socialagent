from pathlib import Path

from app.integrations import gateway


class WhatsAppChannel:
    name = "whatsapp"

    async def send_text(self, chat_ref: str, text: str) -> str | None:
        return await gateway.send_text(chat_ref, text)

    async def send_video(self, chat_ref: str, path: Path, caption: str) -> str | None:
        return await gateway.send_video(chat_ref, str(Path(path).resolve()), caption)

    async def typing(self, chat_ref: str) -> None:
        await gateway.typing(chat_ref)
