from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from .game import TICK_RATE, Settings, World
from .models import ActMsg, InputMsg, JoinMsg, client_msg

log = logging.getLogger("barricade")

MAX_MSGS_PER_SEC = 150
SEND_TIMEOUT = 0.5


def settings_from_env() -> Settings:
    env = os.environ.get
    return Settings(
        round_seconds=float(env("ROUND_SECONDS", 300)),
        freeze_seconds=float(env("FREEZE_SECONDS", 10)),
        intermission_seconds=float(env("INTERMISSION_SECONDS", 8)),
        min_players=int(env("MIN_PLAYERS", 2)),
        max_players=int(env("MAX_PLAYERS", 24)),
        fill_to=int(env("FILL_TO", 0)),
        map=env("MAP", "entrepot"),
    )


world = World(settings_from_env())
connections: dict[int, WebSocket] = {}


def dumps(obj: dict) -> str:
    return json.dumps(obj, separators=(",", ":"))


async def _send(ws: WebSocket, payload: str) -> None:
    try:
        await asyncio.wait_for(ws.send_text(payload), SEND_TIMEOUT)
    except Exception:
        log.debug("envoi impossible", exc_info=True)  # le handler du websocket fera le ménage


async def broadcast() -> None:
    base = dumps(world.snapshot())
    sends = []
    for pid, ws in list(connections.items()):
        ammo, reloading = world.me(pid)
        sends.append(_send(ws, f'{base[:-1]},"me":[{ammo},{reloading}]}}'))  # seul "me" diffère par client
    if sends:
        await asyncio.gather(*sends)


async def game_loop() -> None:
    dt = 1.0 / TICK_RATE
    next_t = time.perf_counter()
    while True:
        if not connections:
            await asyncio.sleep(0.1)  # personne : on ne simule pas
            next_t = time.perf_counter()
            continue
        next_t += dt
        world.step(dt)
        await broadcast()
        delay = next_t - time.perf_counter()
        if delay > 0:
            await asyncio.sleep(delay)
        else:
            next_t = time.perf_counter()  # retard : on ne rattrape pas


@asynccontextmanager
async def lifespan(_: FastAPI):
    task = asyncio.create_task(game_loop())
    yield
    task.cancel()


app = FastAPI(lifespan=lifespan)


@app.get("/health")
def health() -> dict:
    return {"ok": True, "players": world.real_count, "total": len(world.players),
            "phase": world.phase, "tick": world.tick}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    pid: int | None = None
    window_start, count = time.monotonic(), 0
    try:
        while True:
            raw = await ws.receive_text()

            now = time.monotonic()
            if now - window_start >= 1.0:
                window_start, count = now, 0
            count += 1
            if count > MAX_MSGS_PER_SEC:
                await ws.close(code=1008)
                return

            try:
                msg = client_msg.validate_json(raw)
            except ValidationError:
                continue

            if isinstance(msg, JoinMsg):
                if pid is not None:
                    continue
                if not world.can_join():
                    await ws.close(code=1013)  # salon plein
                    return
                player = world.add_player(msg.name)
                pid = player.id
                connections[pid] = ws
                await ws.send_text(dumps({"t": "welcome", "id": pid, **world.static_info()}))
            elif pid is None:
                continue
            elif isinstance(msg, InputMsg):
                world.set_input(pid, msg.dx, msg.dy, msg.a)
            elif isinstance(msg, ActMsg):
                world.act(pid, msg.k)
    except (WebSocketDisconnect, RuntimeError, KeyError):
        pass
    finally:
        if pid is not None:
            connections.pop(pid, None)
            world.remove_player(pid)
