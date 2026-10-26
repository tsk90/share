# Screen Share

Low-CPU screen sharing to any web browser. The GPU does the capture (DXGI) and H.264 encoding via ffmpeg, so CPU and RAM stay low. Windows host only; viewers need just a browser.

## LAN mode (no internet, lowest latency)
- `tray.vbs` – runs in the system tray (right-click for menu), or `host.bat` for a console.
- Open `http://<host-ip>:8080` in a browser on the same network. Resolution / FPS / bitrate are chosen in the viewer.
- Needs: Windows, `winget install Gyan.FFmpeg`, Python 3, `pip install pystray pillow`.
- Allow inbound TCP 8080 in Windows Firewall (admin PowerShell):
  `New-NetFirewallRule -DisplayName "LAN Screen Share Web" -Direction Inbound -Protocol TCP -LocalPort 8080 -Action Allow`

## Cloud mode (Render)
A relay on Render serves the viewer page; an agent on your PC pushes the video to it over an outbound WebSocket (no port forwarding).

1. Deploy: Render -> New -> Blueprint -> pick this repo (`render.yaml`). Copy the generated `PASSWORD` from the service's Environment tab.
2. On the PC: `pip install aiohttp`, then
   `python cloud/agent.py --url https://<your-service>.onrender.com --password <PASSWORD>`
3. Open the Render URL, enter the password. The agent only encodes while someone is watching.

Notes: Render has no UDP, so this is WebSocket/TCP (expect ~150-500 ms). Free instances sleep when idle, so use a paid instance for real-time use. Stream traffic counts against your upload and Render's bandwidth (~8 Mbps at the default 8M bitrate; viewers pick lower).

View-only: no remote control or audio.
