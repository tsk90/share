"""Relay for Render: the PC agent pushes video over a WebSocket, browsers watch over WebSockets.

Protocol (binary frames, first byte = type):
  agent -> relay -> viewers:  0 = init segment, 1 = keyframe fragment, 2 = delta fragment
  relay -> viewers:           3 = stream reset (new init follows), text "live"/"offline" = agent status
  viewer -> relay (text JSON): {"scale":..,"fps":..,"bitrate":..}  forwarded to the agent
  relay -> agent (text JSON):  {"viewers": n, "cfg": {...}}
Set the PASSWORD environment variable; agent and viewers must present it.
"""
import asyncio, hmac, json, os
from pathlib import Path
from aiohttp import web, WSMsgType

PASSWORD = os.environ.get("PASSWORD", "")
STATIC = Path(__file__).parent / "static"
QUEUE_MAX = 90


class State:
    agent = None
    init = None          # cached init segment (type byte included)
    viewers = set()
    cfg = {"scale": 0, "fps": 60, "bitrate": 8}


S = State()


class Viewer:
    def __init__(self, ws):
        self.ws, self.q, self.need_key = ws, asyncio.Queue(QUEUE_MAX), True


def authed(given):
    return bool(PASSWORD) and hmac.compare_digest(given.encode(), PASSWORD.encode())


async def reject_slowly(request, label):
    await asyncio.sleep(1.5)  # blunt brute-force slowdown
    return web.Response(status=401, text="unauthorized")


async def notify_agent():
    if S.agent is not None and not S.agent.closed:
        await S.agent.send_str(json.dumps({"viewers": len(S.viewers), "cfg": S.cfg}))


async def broadcast(data):
    kind = data[0]
    for v in list(S.viewers):
        if v.need_key and kind != 1:
            continue
        if kind == 1:
            v.need_key = False
        if v.q.full():  # viewer too slow: drop backlog, resume at next keyframe
            while not v.q.empty():
                v.q.get_nowait()
            v.need_key = True
            continue
        v.q.put_nowait(data)


async def agent_ws(request):
    if not authed(request.query.get("pw", "")):
        return await reject_slowly(request, "agent")
    ws = web.WebSocketResponse(max_msg_size=8 * 1024 * 1024, heartbeat=20)
    await ws.prepare(request)
    S.agent, S.init = ws, None
    for v in S.viewers:
        v.need_key = True
        v.q.put_nowait(b"\x03")
        v.q.put_nowait("live")
    await notify_agent()
    try:
        async for msg in ws:
            if msg.type == WSMsgType.BINARY and msg.data:
                if msg.data[0] == 0:
                    S.init = msg.data
                    for v in S.viewers:
                        v.need_key = True
                        v.q.put_nowait(b"\x03")
                        v.q.put_nowait(S.init)
                else:
                    await broadcast(msg.data)
    finally:
        if S.agent is ws:
            S.agent, S.init = None, None
            for v in S.viewers:
                v.q.put_nowait("offline")
    return ws


async def viewer_ws(request):
    if not authed(request.query.get("pw", "")):
        return await reject_slowly(request, "viewer")
    ws = web.WebSocketResponse(max_msg_size=64 * 1024, heartbeat=20)
    await ws.prepare(request)
    v = Viewer(ws)
    S.viewers.add(v)
    await ws.send_str("live" if S.agent else "offline")
    if S.init:
        await ws.send_bytes(S.init)
    await notify_agent()

    async def sender():
        while True:
            item = await v.q.get()
            await (ws.send_str(item) if isinstance(item, str) else ws.send_bytes(item))

    task = asyncio.create_task(sender())
    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                try:
                    c = json.loads(msg.data)
                    new = {"scale": min(max(int(c["scale"]), 0), 7680), "fps": min(max(int(c["fps"]), 5), 60),
                           "bitrate": min(max(int(c["bitrate"]), 1), 50)}
                except (ValueError, KeyError, TypeError):
                    continue
                if new != S.cfg:
                    S.cfg = new
                    await notify_agent()
    finally:
        task.cancel()
        S.viewers.discard(v)
        await notify_agent()
    return ws


async def index(request):
    return web.FileResponse(STATIC / "index.html")


def make_app():
    app = web.Application()
    app.add_routes([web.get("/", index), web.get("/ws/agent", agent_ws), web.get("/ws/view", viewer_ws),
                    web.get("/healthz", lambda r: web.Response(text="ok"))])
    return app


if __name__ == "__main__":
    if not PASSWORD:
        raise SystemExit("Set the PASSWORD environment variable.")
    web.run_app(make_app(), port=int(os.environ.get("PORT", 10000)))
