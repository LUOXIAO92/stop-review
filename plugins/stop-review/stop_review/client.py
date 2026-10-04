"""The small app-server surface needed for one native context review."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from .websocket import ProxyWebSocket

RPC_TIMEOUT = 30

class RPCError(RuntimeError):
    """Preserve the host's typed error for narrowly scoped capability checks."""

    def __init__(self, method: str, error: dict) -> None:
        self.code = error.get("code")
        self.message = error.get("message")
        super().__init__(f"Codex {method}: {error}")


class Client:
    """Connect only to an existing daemon; never launch a replacement server."""

    def __init__(self, home: Path, cwd: Path, *, close_timeout: float = 2) -> None:
        self.home, self.cwd = home, cwd
        self.close_timeout = close_timeout
        self.process = None
        self.reader_task = None
        self.stderr_task = None
        self.sequence = 0
        self.pending = {}
        self.events = asyncio.Queue()
        self.stderr = b""
        self.failure = None
        self.closed = False

    async def __aenter__(self) -> Client:
        """Initialize a WebSocket session on the existing host's proxy."""
        self.process = await asyncio.create_subprocess_exec(
            "codex", "app-server", "proxy", cwd=self.cwd,
            env={**os.environ, "CODEX_HOME": str(self.home)},
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self.stderr_task = asyncio.create_task(self._stderr())
        self.socket = ProxyWebSocket(self.process.stdout, self.process.stdin)
        try:
            await asyncio.wait_for(self.socket.open(), RPC_TIMEOUT)
            self.reader_task = asyncio.create_task(self._read())
            await self.call("initialize", {
                "clientInfo": {"name": "stop-review", "version": "0.1.0"},
                "capabilities": {"experimentalApi": True},
            })
            await self.socket.send(json.dumps({"method": "initialized", "params": {}}))
        except BaseException:
            await self.close()
            raise
        return self

    async def __aexit__(self, *args: object) -> None:
        """Close only this proxy process, leaving the owning daemon untouched."""
        await self.close()

    async def close(self) -> None:
        """Reap the proxy and its readers within a bounded time."""
        self.closed = True
        if self.process is None:
            return
        self.process.stdin.close()
        try:
            await asyncio.wait_for(self.process.wait(), self.close_timeout)
        except TimeoutError:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), self.close_timeout)
            except TimeoutError:
                self.process.kill()
                await self.process.wait()
        for task in (self.reader_task, self.stderr_task):
            if task is not None:
                task.cancel()
        await asyncio.gather(
            *(task for task in (self.reader_task, self.stderr_task) if task is not None),
            return_exceptions=True,
        )

    async def _stderr(self) -> None:
        """Drain diagnostic output without retaining an unbounded transcript."""
        while data := await self.process.stderr.read(4096):
            self.stderr = (self.stderr + data)[-8192:]

    async def _read(self) -> None:
        """Route responses and notifications; refuse client-side tool/approval requests."""
        try:
            async for raw in self.socket.messages():
                message = json.loads(raw)
                if not isinstance(message, dict):
                    raise ValueError("Invalid app-server envelope")
                if "method" in message:
                    if "id" in message:
                        await self.socket.send(json.dumps({
                            "id": message["id"], "error": {
                                "code": -32601,
                                "message": "The completion reviewer cannot use client tools or approve actions.",
                            },
                        }))
                    else:
                        await self.events.put(message)
                else:
                    future = self.pending.get(message.get("id"))
                    if future is not None and not future.done():
                        future.set_result(message)
            raise ConnectionError("Codex proxy closed")
        except Exception as error:
            self.failure = error
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(error)
            await self.events.put(error)

    async def call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Correlate a request while the reader consumes interleaved events."""
        if self.failure:
            raise self.failure
        self.sequence += 1
        request_id = self.sequence
        future = asyncio.get_running_loop().create_future()
        self.pending[request_id] = future
        try:
            await self.socket.send(json.dumps({"id": request_id, "method": method, "params": params}))
            reply = await asyncio.wait_for(asyncio.shield(future), RPC_TIMEOUT)
        finally:
            self.pending.pop(request_id, None)
            if not future.done():
                future.cancel()
        if "error" in reply:
            raise RPCError(method, reply["error"])
        if not isinstance(reply.get("result"), dict):
            raise ValueError(f"Invalid Codex {method} response")
        return reply["result"]

    async def read_thread(self, thread_id: str) -> dict[str, Any]:
        """Read identity and live state, never private conversation files."""
        result = await self.call("thread/read", {"threadId": thread_id, "includeTurns": False})
        thread = result.get("thread")
        if not isinstance(thread, dict) or thread.get("id") != thread_id:
            raise ValueError("Codex returned a different thread")
        return thread

    async def current_turn(self, binding: dict, turn_id: str) -> bool:
        """Attest the exact active Main turn, including its shared session identity."""
        thread = await self.read_thread(binding["thread_id"])
        if thread.get("sessionId") != binding["session_id"]:
            raise ValueError("The owning session identity changed")
        if thread.get("status", {}).get("type") != "active":
            return False
        result = await self.call("thread/turns/list", {
            "threadId": binding["thread_id"], "limit": 1,
            "itemsView": "notLoaded", "sortDirection": "desc",
        })
        turns = result.get("data")
        if not isinstance(turns, list) or not turns or not isinstance(turns[0], dict):
            raise ValueError("The live Main turn could not be verified")
        return turns[0].get("id") == turn_id and turns[0].get("status") == "inProgress"

    async def wait(self, thread_id: str, turn: dict) -> dict:
        """Collect only the requested review turn's terminal output and observed usage."""
        text, usage = None, None
        for item in turn.get("items", []):
            if item.get("type") == "agentMessage":
                text = item.get("text")
        if turn.get("status") != "inProgress":
            return {"status": turn.get("status"), "output": text, "usage": usage}
        while True:
            event = await self.events.get()
            if isinstance(event, Exception):
                raise event
            params = event.get("params", {})
            if params.get("threadId") != thread_id:
                continue
            method = event.get("method")
            if method == "thread/tokenUsage/updated":
                usage = params.get("tokenUsage")
            elif method == "item/completed" and params.get("turnId") == turn["id"]:
                item = params.get("item", {})
                if item.get("type") == "agentMessage":
                    text = item.get("text")
            elif method == "turn/completed" and params.get("turn", {}).get("id") == turn["id"]:
                terminal = params["turn"]
                for item in terminal.get("items", []):
                    if item.get("type") == "agentMessage":
                        text = item.get("text")
                return {"status": terminal.get("status"), "output": text, "usage": usage}
