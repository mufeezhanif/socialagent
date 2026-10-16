from app.channels.base import Channel
from app.channels.web import WebChannel
from app.channels.whatsapp import WhatsAppChannel

_CHANNELS: dict[str, Channel] = {"whatsapp": WhatsAppChannel(), "web": WebChannel()}


def get_channel(name: str) -> Channel:
    return _CHANNELS.get(name, _CHANNELS["web"])
