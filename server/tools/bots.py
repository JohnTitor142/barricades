"""Bots de charge réseau : N vrais clients WebSocket qui se baladent, frappent et tirent.

Usage : python tools/bots.py --url ws://localhost:8000/ws --n 24 --seconds 30
Mesure le débit descendant par client. (Ne pas confondre avec les bots *serveur* FILL_TO,
qui sont des joueurs simulés dans le jeu pour tester seul.)
"""
import argparse
import asyncio
import json
import math
import random
import time

import websockets


async def bot(url: str, idx: int, stats: dict, stop: float) -> None:
    async with websockets.connect(url) as ws:
        await ws.send(json.dumps({"t": "join", "name": f"net{idx}"}))
        angle = random.uniform(0, math.tau)

        async def sender() -> None:
            nonlocal angle
            while time.time() < stop:
                angle += random.uniform(-0.4, 0.4)
                await ws.send(json.dumps({"t": "input", "dx": math.cos(angle), "dy": math.sin(angle), "a": angle}))
                r = random.random()
                if r < 0.05:
                    await ws.send('{"t":"act","k":"hit"}')
                elif r < 0.08:
                    await ws.send('{"t":"act","k":"shoot"}')
                await asyncio.sleep(1 / 30)

        send_task = asyncio.create_task(sender())
        try:
            while time.time() < stop:
                raw = await asyncio.wait_for(ws.recv(), 2)
                stats["msgs"] += 1
                stats["bytes"] += len(raw)
        finally:
            send_task.cancel()


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="ws://localhost:8000/ws")
    ap.add_argument("--n", type=int, default=24)
    ap.add_argument("--seconds", type=int, default=20)
    a = ap.parse_args()
    stats = {"msgs": 0, "bytes": 0}
    stop = time.time() + a.seconds
    res = await asyncio.gather(*(bot(a.url, i, stats, stop) for i in range(a.n)), return_exceptions=True)
    errors = [r for r in res if isinstance(r, Exception)]
    print(f"{a.n} clients, {a.seconds}s : {stats['msgs'] / a.seconds / a.n:.1f} msg/s/client, "
          f"{stats['bytes'] / a.seconds / a.n / 1024:.1f} Ko/s/client, {len(errors)} erreurs")
    for e in errors[:3]:
        print("  erreur :", repr(e))


asyncio.run(main())
