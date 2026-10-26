"""System-tray launcher for lanshare.py (no console window). Run with pythonw.exe, or use tray.vbs."""
import os, subprocess, sys, webbrowser
import pystray
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lanshare

PORT = 8080
STARTUP_VBS = os.path.join(os.environ["APPDATA"], r"Microsoft\Windows\Start Menu\Programs\Startup", "LANScreenShare.vbs")
proc = None


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
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=lanshare.NOWIN)
    refresh(icon)


def stop(icon=None, item=None):
    global proc
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
