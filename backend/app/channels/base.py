from pathlib import Path
from typing import Protocol


class Channel(Protocol):
    name: str

    async def send_text(self, chat_ref: str, text: str) -> str | None: ...

    async def send_video(self, chat_ref: str, path: Path, caption: str) -> str | None: ...

    async def typing(self, chat_ref: str) -> None: ...
