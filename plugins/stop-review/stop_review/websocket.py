"""WebSocket framing over the existing Codex daemon proxy's byte streams."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from websockets.client import ClientProtocol
from websockets.frames import Frame, Opcode
from websockets.http11 import Response
from websockets.protocol import OPEN
from websockets.uri import parse_uri


class ProxyWebSocket:
    """Delegate Upgrade, masking, and control frames to websockets."""

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.reader = reader
        self.writer = writer
        self.protocol = ClientProtocol(parse_uri("ws://localhost/rpc"), max_size=16 * 1024 * 1024)
        self.events = self._events()

    async def _flush(self) -> None:
        """Write queued frames, including automatic Ping and Close replies."""
        for data in self.protocol.data_to_send():
            if data:
                self.writer.write(data)
        await self.writer.drain()

    async def open(self) -> None:
        """Perform the native /rpc WebSocket Upgrade through the proxy."""
        self.protocol.send_request(self.protocol.connect())
        await self._flush()
        event = await anext(self.events)
        if not isinstance(event, Response) or self.protocol.state is not OPEN:
            raise ValueError("Codex proxy rejected the WebSocket Upgrade")

    async def send(self, text: str) -> None:
        """Send one JSON-RPC envelope as a Text frame."""
        self.protocol.send_text(text.encode("utf-8"))
        await self._flush()

    async def _events(self) -> AsyncIterator[Response | Frame]:
        """Preserve all decoded events across reads and EOF."""
        while True:
            data = await self.reader.read(65536)
            if data:
                self.protocol.receive_data(data)
            else:
                self.protocol.receive_eof()
            await self._flush()
            for event in self.protocol.events_received():
                yield event
            if not data:
                return

    async def messages(self) -> AsyncIterator[str]:
        """Reassemble fragmented messages; reject non-text application data."""
        fragments = []
        async for event in self.events:
            if not isinstance(event, Frame):
                raise ValueError("Unexpected proxy WebSocket event")
            if event.opcode in (Opcode.TEXT, Opcode.CONT):
                fragments.append(event.data)
                if event.fin:
                    yield b"".join(fragments).decode("utf-8")
                    fragments.clear()
            elif event.opcode is Opcode.CLOSE:
                return
            elif event.opcode not in (Opcode.PING, Opcode.PONG):
                raise ValueError("Unexpected proxy WebSocket frame")
