"""LAN screen share to any web browser: GPU capture (DXGI) + hardware H.264 -> fragmented MP4 over HTTP -> MSE.

  python lanshare.py [--port 8080] [--fps 60] [--bitrate 8] [--scale 1920] [--monitor 0]
Open  http://<this-pc-ip>:<port>  in a browser. ffmpeg runs only while someone is watching.
"""
import argparse, hashlib, hmac, os, shutil, socket, subprocess, sys
import time
from http.cookies import SimpleCookie
from urllib.parse import parse_qs, urlparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # no console flash when run from the tray

ENCODERS = [  # first one the machine supports wins
    ("h264_nvenc", ["-preset", "p1", "-tune", "ll", "-rc", "cbr", "-zerolatency", "1"]),
    ("h264_amf", ["-usage", "ultralowlatency", "-quality", "speed", "-rc", "cbr"]),
    ("h264_qsv", ["-preset", "veryfast", "-low_power", "1"]),
    ("libx264", ["-preset", "ultrafast", "-tune", "zerolatency"]),
]

PAGE = b"""<!doctype html><meta charset=utf-8><title>Screen Share</title>
<style>html,body{margin:0;height:100%;background:#000;overflow:hidden}video{width:100%;height:100%;object-fit:contain}
#bar{position:fixed;top:8px;right:8px;font:13px sans-serif;color:#fff;background:#000b;padding:6px 10px;border-radius:6px;
display:flex;gap:10px;align-items:center;transition:opacity .3s}#bar.hide{opacity:0;pointer-events:none}
select,button{background:#222;color:#fff;border:1px solid #555;border-radius:4px;padding:3px 6px;font:inherit}
#m{position:fixed;top:8px;left:8px;color:#fff;font:13px sans-serif;background:#000b;padding:4px 8px;border-radius:4px}</style>
<video id=v autoplay muted playsinline></video><div id=m>connecting...</div>
<div id=bar>
 <label>Resolution <select id=scale><option value=0>Native<option value=1920>1080p<option value=1280>720p<option value=854>480p</select></label>
 <label>FPS <select id=fps><option>15<option>30<option>60</select></label>
 <label>Bitrate <select id=bitrate><option value=2>2 Mbps<option value=4>4 Mbps<option value=8>8 Mbps<option value=15>15 Mbps<option value=25>25 Mbps</select></label>
 <button id=fs>Fullscreen</button></div>
<script>
const $=id=>document.getElementById(id),v=$('v'),m=$('m'),bar=$('bar');
const saved=JSON.parse(localStorage.ss||'{}'),cfg=Object.assign({scale:0,fps:60,bitrate:8},saved);
for(const k in cfg)$(k).value=cfg[k];
let gen=0,ctrl=null;
for(const k in cfg)$(k).onchange=()=>{cfg[k]=$(k).value;localStorage.ss=JSON.stringify(cfg);gen++;ctrl&&ctrl.abort()};
$('fs').onclick=()=>document.fullscreenElement?document.exitFullscreen():document.documentElement.requestFullscreen();
let t;const wake=()=>{bar.classList.remove('hide');clearTimeout(t);t=setTimeout(()=>bar.classList.add('hide'),3000)};
onmousemove=wake;wake();
const CODEC='video/mp4; codecs="avc1.640033"';
async function start(my){
  const ms=new MediaSource();v.src=URL.createObjectURL(ms);
  await new Promise(r=>ms.addEventListener('sourceopen',r,{once:true}));
  const sb=ms.addSourceBuffer(CODEC);const q=[];
  const pump=()=>{if(sb.updating||!q.length)return;try{sb.appendBuffer(q.shift())}catch(e){q.length=0}};
  sb.onupdateend=()=>{
    if(v.buffered.length){const end=v.buffered.end(v.buffered.length-1),beg=v.buffered.start(0);
      if(end-v.currentTime>0.25)v.currentTime=end-0.05;
      if(v.currentTime-beg>5&&!sb.updating){sb.remove(beg,v.currentTime-2);return}}
    pump()};
  ctrl=new AbortController();
  const res=await fetch('/stream?'+new URLSearchParams(cfg),{signal:ctrl.signal});const rd=res.body.getReader();m.style.display='none';
  for(;;){const{done,value}=await rd.read();if(done||my!==gen)break;q.push(value);pump()}
}
(async function loop(){const my=gen;try{await start(my)}catch(e){}m.style.display='';m.textContent=my!==gen?'applying settings...':'disconnected, retrying...';setTimeout(loop,my!==gen?50:1500)})();
</script>"""


LOGIN = b"""<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>Screen Share</title>
<style>body{margin:0;height:100vh;display:flex;align-items:center;justify-content:center;background:#000;color:#fff;font:15px sans-serif}
form{display:flex;gap:8px}input,button{background:#222;color:#fff;border:1px solid #555;border-radius:4px;padding:8px 12px;font:inherit}.e{color:#f66;position:fixed;top:40%%}</style>
<form method=post action=/login><input name=pw type=password placeholder=Password autofocus><button>Watch</button></form>%s"""


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def encoder_works(name, opts):
    cmd = ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=640x360:d=0.2",
           "-pix_fmt", "yuv420p", "-c:v", name, *opts, "-f", "null", "-"]
    return subprocess.run(cmd, capture_output=True, creationflags=NOWIN).returncode == 0


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--fps", type=int, default=60)
    p.add_argument("--bitrate", type=int, default=8, help="Mbps")
    p.add_argument("--scale", type=int, default=0, help="output width, 0 = native")
    p.add_argument("--monitor", type=int, default=0)
    p.add_argument("--password", default=os.environ.get("SS_PASSWORD", ""), help="require this password (recommended when public)")
    a = p.parse_args()
    token = hmac.new(a.password.encode(), b"lanshare-session", hashlib.sha256).hexdigest() if a.password else ""
    if not shutil.which("ffmpeg"):  # PATH may predate the ffmpeg install; re-read it from the registry
        import winreg
        for root, sub in ((winreg.HKEY_CURRENT_USER, "Environment"),
                          (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment")):
            try:
                with winreg.OpenKey(root, sub) as k:
                    os.environ["PATH"] += ";" + os.path.expandvars(winreg.QueryValueEx(k, "Path")[0])
            except OSError:
                pass
    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg not found. Install: winget install Gyan.FFmpeg (then reopen the terminal)")

    name, opts = next(((n, o) for n, o in ENCODERS if encoder_works(n, o)), ENCODERS[-1])
    def build_cmd(fps, bitrate, scale):
        vf = f"ddagrab={a.monitor}:framerate={fps}:draw_mouse=1,hwdownload,format=bgra"
        if scale:
            vf += f",scale={scale}:-2:flags=fast_bilinear"
        vf += ",format=yuv420p"
        rate = f"{bitrate}M"
        return ["ffmpeg", "-v", "warning", "-fflags", "nobuffer", "-flags", "low_delay",
                "-filter_complex", vf, "-c:v", name, *opts, "-profile:v", "high", "-level", "5.1",
                "-bf", "0", "-b:v", rate, "-maxrate", rate, "-bufsize", f"{max(bitrate // 2, 1)}M",
                "-g", str(fps), "-flush_packets", "1",
                "-movflags", "empty_moov+default_base_moof+frag_every_frame", "-f", "mp4", "pipe:1"]

    def num(q, key, default, lo, hi):
        try:
            return min(max(int(q.get(key, [default])[0]), lo), hi)
        except ValueError:
            return default

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def authed(self):
            if not a.password:
                return True
            c = SimpleCookie(self.headers.get("Cookie", ""))
            return "ss" in c and hmac.compare_digest(c["ss"].value, token)

        def send_login(self, error=False):
            body = LOGIN % (b"<div class=e>Wrong password</div>" if error else b"")
            self.send_response(401 if error else 200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            if urlparse(self.path).path != "/login" or not a.password:
                return self.send_error(404)
            n = min(int(self.headers.get("Content-Length", 0) or 0), 1024)
            given = parse_qs(self.rfile.read(n).decode(errors="ignore")).get("pw", [""])[0]
            if hmac.compare_digest(given.encode(), a.password.encode()):
                secure = "; Secure" if self.headers.get("X-Forwarded-Proto") == "https" else ""
                self.send_response(303)
                self.send_header("Set-Cookie", f"ss={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=2592000{secure}")
                self.send_header("Location", "/")
                self.end_headers()
            else:
                time.sleep(1.5)  # slow down guessing
                self.send_login(error=True)

        def do_GET(self):
            url = urlparse(self.path)
            if not self.authed():
                if url.path == "/stream":
                    return self.send_error(401)
                return self.send_login()
            if url.path == "/stream":
                self.stream(parse_qs(url.query))
            elif url.path in ("/", "/index.html"):
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(PAGE)))
                self.end_headers()
                self.wfile.write(PAGE)
            else:
                self.send_error(404)

        def stream(self, q):
            cmd = build_cmd(num(q, "fps", a.fps, 5, 120), num(q, "bitrate", a.bitrate, 1, 100),
                            num(q, "scale", a.scale, 0, 7680))
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0, creationflags=NOWIN)
            print(f"viewer connected: {self.client_address[0]}")
            try:
                self.send_response(200)
                self.send_header("Content-Type", "video/mp4")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                while chunk := proc.stdout.read(65536):
                    self.wfile.write(chunk)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionError, OSError):
                pass
            finally:
                proc.kill()
                print(f"viewer left: {self.client_address[0]}")

    ThreadingHTTPServer.daemon_threads = True
    srv = ThreadingHTTPServer(("0.0.0.0", a.port), Handler)
    print(f"Encoder: {name}\nOpen in a browser:  http://{lan_ip()}:{a.port}\nCtrl+C to stop.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
