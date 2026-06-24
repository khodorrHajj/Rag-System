from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any
from uuid import UUID

from fastapi import WebSocket
from fastapi.encoders import jsonable_encoder

logger = logging.getLogger(__name__)

class ChatRealtimeBroker:
    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None

    def attach_current_loop(self) -> None:
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            return

    async def connect(self, user_id: UUID, websocket: WebSocket) -> None:
        self.attach_current_loop()
        await websocket.accept()
        async with self._lock:
            self._connections[str(user_id)].add(websocket)

    async def disconnect(self, user_id: UUID, websocket: WebSocket) -> None:
        async with self._lock:
            user_connections = self._connections.get(str(user_id))
            if not user_connections:
                return

            user_connections.discard(websocket)
            if not user_connections:
                self._connections.pop(str(user_id), None)

    def publish_to_user(self, user_id: UUID, event: dict[str, Any]) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return

        try:
            asyncio.run_coroutine_threadsafe(
                self._broadcast(str(user_id), jsonable_encoder(event)),
                loop,
            )
        except RuntimeError:
            logger.debug("Skipping chat event publish because the event loop is unavailable.")

    async def _broadcast(self, user_id: str, event: dict[str, Any]) -> None:
        async with self._lock:
            connections = list(self._connections.get(user_id, set()))

        if not connections:
            return

        stale_connections: list[WebSocket] = []
        for connection in connections:
            try:
                await connection.send_json(event)
            except Exception:
                stale_connections.append(connection)

        if not stale_connections:
            return

        async with self._lock:
            user_connections = self._connections.get(user_id)
            if not user_connections:
                return

            for connection in stale_connections:
                user_connections.discard(connection)

            if not user_connections:
                self._connections.pop(user_id, None)

chat_realtime_broker = ChatRealtimeBroker()

