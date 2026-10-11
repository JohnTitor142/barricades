import json
import time

from fastapi.testclient import TestClient

from app import main
from app.game import PROTOCOL_VERSION, Settings, World


def recv_until(ws, pred, limit=300):
    for _ in range(limit):
        msg = json.loads(ws.receive_text())
        if pred(msg):
            return msg
    raise AssertionError("message attendu jamais reçu")


def fresh_client(**kw):
    main.world = World(Settings(**kw), seed=7)
    main.connections.clear()
    return TestClient(main.app)


def join(ws, name):
    ws.send_text(json.dumps({"t": "join", "name": name}))
    return json.loads(ws.receive_text())


def test_health(monkeypatch):
    monkeypatch.setenv("SOURCE_COMMIT", "abc123")
    with fresh_client() as c:
        h = c.get("/health").json()
        assert h["ok"] is True and h["commit"] == "abc123"


def test_welcome_contains_map_and_state_follows():
    with fresh_client() as c, c.websocket_connect("/ws") as ws:
        w = join(ws, "Alice")
        assert w["t"] == "welcome" and len(w["walls"]) >= 10 and len(w["props"]) >= 70
        assert len(w["pos"]) == len(w["props"]) and w["names"][str(w["id"])] == "Alice"
        assert len(w["ps"]) == len(w["props"]) and all(pct == 100 for _, pct in w["ps"])
        assert w["map"] and len(w["areas"]) >= 6 and w["v"] == PROTOCOL_VERSION
        assert all(len(wl) == 6 for wl in w["walls"])          # x1, y1, x2, y2, épaisseur, style
        assert "wp" in w                                        # armes au sol dès l'arrivée
        s = recv_until(ws, lambda m: m["t"] == "s")
        assert s["ph"] == "wait" and "me" in s and any(p[0] == w["id"] for p in s["p"])
        assert len(s["me"]) == 6     # [munitions, recharge, arme, cap vers l'humain, recharge dash, recharge sort]


def test_input_moves_player():
    with fresh_client() as c, c.websocket_connect("/ws") as ws:
        pid = join(ws, "A")["id"]
        main.world._teleport(main.world.players[pid], (500, 400))
        ws.send_text(json.dumps({"t": "input", "dx": 1, "dy": 0, "a": 0}))
        recv_until(ws, lambda m: m["t"] == "s" and any(p[0] == pid and p[1] > 520 for p in m["p"]))


def test_two_players_start_a_round_and_hit_event_is_broadcast():
    with fresh_client(intermission_seconds=0.3, freeze_seconds=0) as c, \
            c.websocket_connect("/ws") as a, c.websocket_connect("/ws") as b:
        join(a, "A")
        join(b, "B")
        recv_until(a, lambda m: m["t"] == "s" and m["ph"] == "play")
        b.send_text(json.dumps({"t": "act", "k": "hit"}))
        recv_until(a, lambda m: m["t"] == "s" and any(e["k"] == "hit" for e in m["ev"]))


def test_garbage_is_ignored():
    with fresh_client() as c, c.websocket_connect("/ws") as ws:
        ws.send_text("pas du json")
        ws.send_text(json.dumps({"t": "input", "dx": 1, "dy": 0, "a": 0}))      # avant join
        ws.send_text(json.dumps({"t": "input", "dx": 1e999, "dy": 0, "a": 0}))  # inf
        ws.send_text(json.dumps({"t": "act", "k": "fly"}))
        assert join(ws, "A")["t"] == "welcome"
        assert main.world.players


def test_full_room_refuses_and_disconnect_cleans_up():
    with fresh_client(max_players=1) as c:
        with c.websocket_connect("/ws") as a:
            pid = join(a, "A")["id"]
            with c.websocket_connect("/ws") as b:
                b.send_text(json.dumps({"t": "join", "name": "B"}))
                try:
                    b.receive_text()
                    refused = False
                except Exception:  # noqa: BLE001
                    refused = True
                assert refused
        for _ in range(60):
            if pid not in main.world.players:
                break
            time.sleep(0.05)
        assert pid not in main.world.players
