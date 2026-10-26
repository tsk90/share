"""Screen Share Agent: tray app. Connects this PC to your relay server; viewers open the server link + password.
Packaged as a single .exe (ffmpeg bundled) by build_exe.bat."""
import asyncio, json, os, sys, threading, tkinter as tk, webbrowser
from tkinter import simpledialog, messagebox

BASE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
os.environ["PATH"] = BASE + os.pathsep + os.environ["PATH"]  # bundled ffmpeg.exe lives next to the unpacked files
sys.path.insert(0, os.path.join(BASE, ".."))

import pystray
from PIL import Image, ImageDraw
import agent
from lanshare import NOWIN  # noqa: F401  (ensures lanshare is bundled)

APPDIR = os.path.join(os.environ["APPDATA"], "ScreenShareAgent")
CONFIG = os.path.join(APPDIR, "config.json")
STARTUP = os.path.join(os.environ["APPDATA"], r"Microsoft\Windows\Start Menu\Programs\Startup", "ScreenShareAgent.vbs")
state = {"status": "Not configured", "loop": None, "task": None}


def load():
    try:
        with open(CONFIG) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save(cfg):
    os.makedirs(APPDIR, exist_ok=True)
    with open(CONFIG, "w") as f:
        json.dump(cfg, f)


def ask_config(current):
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    url = simpledialog.askstring("Screen Share", "Server link (e.g. https://my-app.onrender.com):",
                                 initialvalue=current.get("url", ""), parent=root)
    if not url:
        root.destroy()
        return None
    pw = simpledialog.askstring("Screen Share", "Password:", show="*", parent=root)
    root.destroy()
    if not pw:
        return None
    cfg = {"url": url.strip().rstrip("/"), "password": pw}
    if not cfg["url"].startswith("http"):
        cfg["url"] = "https://" + cfg["url"]
    save(cfg)
    return cfg


def icon_image(ok):
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((4, 8, 60, 44), 5, fill=(40, 120, 220))
    d.rectangle((9, 13, 55, 39), fill=(15, 25, 40))
    d.rectangle((26, 44, 38, 52), fill=(200, 200, 200))
    d.rectangle((18, 52, 46, 56), fill=(200, 200, 200))
    d.ellipse((44, 2, 62, 20), fill=(60, 200, 90) if ok else (200, 60, 60))
    return img


def set_status(text):
    state["status"] = text
    ic = state.get("icon")
    if ic:
        ic.icon = icon_image(text.startswith(("Connected", "Streaming")))
        ic.title = f"Screen Share: {text}"
        ic.update_menu()


def start_agent(cfg):
    class A:
        url, password, monitor = cfg["url"], cfg["password"], 0

    def runner():
        loop = asyncio.new_event_loop()
        state["loop"] = loop
        state["task"] = loop.create_task(agent.run(A, set_status))
        try:
            loop.run_until_complete(state["task"])
        except asyncio.CancelledError:
            pass

    threading.Thread(target=runner, daemon=True).start()


def stop_agent():
    loop, task = state.get("loop"), state.get("task")
    if loop and task:
        loop.call_soon_threadsafe(task.cancel)
    state["loop"] = state["task"] = None


def change_settings(icon, item):
    cfg = ask_config(load())
    if cfg:
        stop_agent()
        start_agent(cfg)


def open_viewer(icon, item):
    cfg = load()
    if cfg.get("url"):
        webbrowser.open(cfg["url"])


def autostart_on(item=None):
    return os.path.exists(STARTUP)


def toggle_autostart(icon, item):
    if autostart_on():
        os.remove(STARTUP)
    else:
        exe = sys.executable if getattr(sys, "frozen", False) else f'pythonw "{os.path.abspath(__file__)}"'
        cmd = f'"{exe}"' if getattr(sys, "frozen", False) else exe
        with open(STARTUP, "w") as f:
            f.write('CreateObject("WScript.Shell").Run "' + cmd.replace('"', '""') + '", 0, False\n')


def quit_app(icon, item):
    stop_agent()
    icon.stop()


menu = pystray.Menu(
    pystray.MenuItem(lambda i: state["status"], None, enabled=False),
    pystray.MenuItem("Open viewer page", open_viewer, default=True),
    pystray.MenuItem("Change server / password", change_settings),
    pystray.MenuItem("Start with Windows", toggle_autostart, checked=autostart_on),
    pystray.MenuItem("Quit", quit_app),
)
icon = pystray.Icon("ssagent", icon_image(False), "Screen Share", menu)
state["icon"] = icon


def setup(ic):
    ic.visible = True
    cfg = load()
    if not (cfg.get("url") and cfg.get("password")):
        cfg = ask_config({})
    if cfg:
        start_agent(cfg)
    else:
        set_status("Not configured - use 'Change server / password'")


icon.run(setup)
