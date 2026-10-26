"""System-tray launcher for lanshare.py (no console window). Run with pythonw.exe, or use tray.vbs."""
import json, os, re, secrets, shutil, subprocess, sys, threading, webbrowser
import pystray
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lanshare

PORT = 8080
STARTUP_VBS = os.path.join(os.environ["APPDATA"], r"Microsoft\Windows\Start Menu\Programs\Startup", "LANScreenShare.vbs")
proc = None
tunnel = None
public_url = None

CONFIG = os.path.join(os.environ["APPDATA"], "LANScreenShare", "config.json")


def load_password():
    """Password is generated once and kept in %APPDATA%; the same one protects LAN and public access."""
    try:
        with open(CONFIG) as f:
            return json.load(f)["password"]
    except (OSError, ValueError, KeyError):
        pw = secrets.token_urlsafe(9)
        os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
        with open(CONFIG, "w") as f:
            json.dump({"password": pw}, f)
        return pw


PASSWORD = load_password()


def cloudflared_exe():
    return shutil.which("cloudflared") or next((p for p in (r"C:\Program Files (x86)\cloudflared\cloudflared.exe",
                                                           r"C:\Program Files\cloudflared\cloudflared.exe") if os.path.exists(p)), None)


def url():
    return f"http://{lanshare.lan_ip()}:{PORT}"


def icon_image(on):
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((4, 8, 60, 44), 5, fill=(40, 120, 220) if on else (120, 120, 120))
    d.rectangle((9, 13, 55, 39), fill=(15, 25, 40))
    d.rectangle((26, 44, 38, 52), fill=(200, 200, 200))
    d.rectangle((18, 52, 46, 56), fill=(200, 200, 200))
    d.ellipse((44, 2, 62, 20), fill=(60, 200, 90) if on else (200, 60, 60))
    return img


def running():
    return proc is not None and proc.poll() is None


def start(icon=None, item=None):
    global proc
    if not running():
        proc = subprocess.Popen([sys.executable, os.path.join(HERE, "lanshare.py"), "--port", str(PORT)],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=lanshare.NOWIN,
                                env={**os.environ, "SS_PASSWORD": PASSWORD})
    refresh(icon)


def tunnel_running():
    return tunnel is not None and tunnel.poll() is None


def start_tunnel(icon, item=None):
    global tunnel, public_url
    exe = cloudflared_exe()
    if not exe:
        return icon.notify("cloudflared not found. Install: winget install Cloudflare.cloudflared")
    if not running():
        start(icon)
    public_url = None
    tunnel = subprocess.Popen([exe, "tunnel", "--url", f"http://localhost:{PORT}", "--no-autoupdate"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, creationflags=lanshare.NOWIN)

    def watch():
        global public_url
        for line in tunnel.stderr:  # cloudflared logs the assigned URL here
            m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", line)
            if m and not public_url:
                public_url = m.group(0)
                subprocess.run(["clip"], input=public_url.encode(), creationflags=lanshare.NOWIN)
                icon.notify(f"Public link copied: {public_url}  |  Password: {PASSWORD}")
                refresh(icon)
    threading.Thread(target=watch, daemon=True).start()
    refresh(icon)


def stop_tunnel(icon=None, item=None):
    global tunnel, public_url
    if tunnel_running():
        tunnel.terminate()
    tunnel, public_url = None, None
    refresh(icon)


def copy(icon, text, label):
    subprocess.run(["clip"], input=text.encode(), creationflags=lanshare.NOWIN)
    icon.notify(f"Copied {label}")


def stop(icon=None, item=None):
    global proc
    stop_tunnel()
    if running():
        proc.terminate()
        proc.wait()
    refresh(icon)


def refresh(icon):
    if icon:
        icon.icon = icon_image(running())
        icon.title = f"Screen Share: sharing at {url()}" if running() else "Screen Share: stopped"
        icon.update_menu()


def copy_url(icon, item):
    subprocess.run(["clip"], input=url().encode(), creationflags=lanshare.NOWIN)
    icon.notify(f"Copied {url()}")


def autostart_on(item=None):
    return os.path.exists(STARTUP_VBS)


def toggle_autostart(icon, item):
    if autostart_on():
        os.remove(STARTUP_VBS)
    else:
        with open(STARTUP_VBS, "w") as f:
            f.write(f'CreateObject("WScript.Shell").Run """{sys.executable.replace("python.exe", "pythonw.exe")}"" ""{os.path.join(HERE, "tray.py")}""", 0, False\n')


def quit_app(icon, item):
    stop()
    icon.stop()


menu = pystray.Menu(
    pystray.MenuItem(lambda i: f"Sharing: {url()}" if running() else "Stopped", None, enabled=False),
    pystray.MenuItem("Open in browser", lambda i, m: webbrowser.open(f"http://localhost:{PORT}"), default=True),
    pystray.MenuItem("Copy link", copy_url),
    pystray.MenuItem(lambda i: f"Public: {public_url}" if public_url else "Public link: starting..." if tunnel_running() else "Public link: off",
                     None, enabled=False),
    pystray.MenuItem("Start public link (Cloudflare)", start_tunnel, visible=lambda i: not tunnel_running()),
    pystray.MenuItem("Copy public link", lambda i, m: copy(i, public_url, "public link"), visible=lambda i: bool(public_url)),
    pystray.MenuItem("Stop public link", stop_tunnel, visible=lambda i: tunnel_running()),
    pystray.MenuItem("Copy password", lambda i, m: copy(i, PASSWORD, "password")),
    pystray.Menu.SEPARATOR,
    pystray.MenuItem("Start sharing", start, visible=lambda i: not running()),
    pystray.MenuItem("Stop sharing", stop, visible=lambda i: running()),
    pystray.MenuItem("Start with Windows", toggle_autostart, checked=autostart_on),
    pystray.MenuItem("Quit", quit_app),
)

icon = pystray.Icon("lanshare", icon_image(False), "Screen Share", menu)


def setup(icon):
    icon.visible = True
    start(icon)
    icon.notify(f"Sharing at {url()}")


icon.run(setup)
