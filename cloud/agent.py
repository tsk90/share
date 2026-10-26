"""PC agent: captures this screen with ffmpeg (GPU) and pushes fragmented MP4 to the relay over WebSocket.
Encodes only while at least one viewer is connected.

  python cloud/agent.py --url https://your-app.onrender.com --password SECRET
(or set RELAY_URL / RELAY_PASSWORD environment variables)
"""
import argparse, asyncio, json, os, shutil, struct, subprocess, sys
from urllib.parse import quote

import aiohttp

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from lanshare import ENCODERS, NOWIN, encoder_works  # reuse encoder detection


def split_boxes(buf):
    """Yield complete top-level MP4 boxes from a bytearray, removing them from it."""
    while len(buf) >= 8:
        size, typ = struct.unpack(">I4s", buf[:8])
        if size == 1 and len(buf) >= 16:
            size = struct.unpack(">Q", buf[8:16])[0]
        if size < 8 or len(buf) < size:
            return
        yield bytes(typ), bytes(buf[:size])
        del buf[:size]


def is_keyframe(moof):
    """True if the first sample of this fragment is a sync sample (reads the trun box)."""
    i = moof.find(b"trun")
    if i < 0:
        return False
    flags = struct.unpack(">I", b"\0" + moof[i + 4 + 1:i + 4 + 4])[0]
    p = i + 4 + 4 + 4  # skip type, version/flags, sample_count
    if flags & 0x1:
        p += 4
    if flags & 0x4:
        return not (struct.unpack(">I", moof[p:p + 4])[0] & 0x10000)
    if flags & 0x400:
        p += 4 * bool(flags & 0x100) + 4 * bool(flags & 0x200)
        return not (struct.unpack(">I", moof[p:p + 4])[0] & 0x10000)
    j = moof.find(b"tfhd")  # no per-sample flags: fall back to the track fragment default
    if j >= 0:
        tf = struct.unpack(">I", b"\0" + moof[j + 5:j + 8])[0]
        if tf & 0x20:
            q = j + 4 + 4 + 4 + 8 * bool(tf & 0x1) + 4 * bool(tf & 0x2) + 4 * bool(tf & 0x8) + 4 * bool(tf & 0x10)
            return not (struct.unpack(">I", moof[q:q + 4])[0] & 0x10000)
    return True


def build_cmd(name, opts, monitor, cfg):
    fps, bitrate, scale = cfg["fps"], cfg["bitrate"], cfg["scale"]
    vf = f"ddagrab={monitor}:framerate={fps}:draw_mouse=1,hwdownload,format=bgra"
    if scale:
        vf += f",scale={scale}:-2:flags=fast_bilinear"
    vf += ",format=yuv420p"
    rate = f"{bitrate}M"
    return ["ffmpeg", "-v", "warning", "-fflags", "nobuffer", "-flags", "low_delay", "-filter_complex", vf,
            "-c:v", name, *opts, "-profile:v", "high", "-level", "5.1", "-bf", "0", "-b:v", rate, "-maxrate", rate,
            "-bufsize", f"{max(bitrate // 2, 1)}M", "-g", str(fps), "-flush_packets", "1",
            "-movflags", "empty_moov+default_base_moof+frag_every_frame", "-f", "mp4", "pipe:1"]


async def pump_ffmpeg(ws, cmd):
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.DEVNULL, creationflags=NOWIN)
    buf, pending = bytearray(), None
    try:
        while data := await proc.stdout.read(65536):
            buf += data
            for typ, box in split_boxes(buf):
                if typ in (b"ftyp", b"moov"):
                    pending = (pending or b"") + box
                    if typ == b"moov":
                        await ws.send_bytes(b"\x00" + pending)
                        pending = None
                elif typ == b"moof":
                    pending = box
                elif typ == b"mdat" and pending:
                    await ws.send_bytes((b"\x01" if is_keyframe(pending) else b"\x02") + pending + box)
                    pending = None
    finally:
        if proc.returncode is None:
            proc.kill()


async def run(a, status=print):
    name, opts = next(((n, o) for n, o in ENCODERS if encoder_works(n, o)), ENCODERS[-1])
    status(f"Encoder: {name}")
    ws_url = a.url.replace("https://", "wss://").replace("http://", "ws://").rstrip("/") + "/ws/agent?pw=" + quote(a.password)
    while True:
        try:
            async with aiohttp.ClientSession() as sess, sess.ws_connect(ws_url, heartbeat=20, max_msg_size=0) as ws:
                status("Connected - waiting for viewers")
                task, want = None, None
                async for msg in ws:
                    if msg.type != aiohttp.WSMsgType.TEXT:
                        continue
                    st = json.loads(msg.data)
                    new = (st["viewers"] > 0, json.dumps(st["cfg"], sort_keys=True))
                    if new == want:
                        continue
                    want = new
                    if task:
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)
                        task = None
                    if new[0]:
                        status(f"Streaming to {st['viewers']} viewer(s)")
                        task = asyncio.create_task(pump_ffmpeg(ws, build_cmd(name, opts, a.monitor, st["cfg"])))
                    else:
                        status("Connected - idle (no viewers)")
                if task:
                    task.cancel()
        except aiohttp.WSServerHandshakeError as e:
            status("Wrong password" if e.status == 401 else f"Server error {e.status}")
        except (aiohttp.ClientError, OSError) as e:
            status("Cannot reach server - retrying")
        await asyncio.sleep(3)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--url", default=os.environ.get("RELAY_URL"))
    p.add_argument("--password", default=os.environ.get("RELAY_PASSWORD"))
    p.add_argument("--monitor", type=int, default=0)
    a = p.parse_args()
    if not (a.url and a.password):
        sys.exit("Need --url and --password (or RELAY_URL / RELAY_PASSWORD).")
    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg not found. Install: winget install Gyan.FFmpeg")
    try:
        asyncio.run(run(a))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
