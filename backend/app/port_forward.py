"""Also answer on container port 80 (some hosts route their public port to 80); bytes are piped to the API on PORT."""

import asyncio
import os

TARGET = int(os.environ.get("PORT", "8000"))


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
        if writer.can_write_eof():
            writer.write_eof()
    except OSError:
        pass


async def _handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        up_reader, up_writer = await asyncio.open_connection("127.0.0.1", TARGET)
    except OSError:
        writer.close()
        return
    try:
        await asyncio.gather(_pipe(reader, up_writer), _pipe(up_reader, writer))
    finally:
        writer.close()
        up_writer.close()


async def main() -> None:
    server = await asyncio.start_server(_handle, "0.0.0.0", 80)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    if TARGET != 80:
        asyncio.run(main())
