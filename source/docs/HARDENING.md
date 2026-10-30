# Hardening checklist for the owner

Nothing here is applied by the repository: every step is for the owner to run on the Pi, with the machine free where it says so.

## Users: switch on the roles (A-01)

Default (kept on purpose, for compatibility): while no person exists, everybody who can reach DWC is an administrator
(`identity.COMPAT_USER`, the API operations of `workshop_api.VIA_OPEN`). The service page shows an amber bar at the top of
the page ("There are no people yet" / "Users disabled") with a button that opens the Users section while this is the case.
The risk grows with the reach of the LAN: anybody on it can send G-code.

Steps (from a browser on the LAN, no sudo):
1. Service page, section Users: press "Create the first person", choose a name, a role `admin` and a PIN of 4 to 12 digits.
   From that moment the roles apply to every call (the first person turns users on; nothing else needs a restart).
2. Create the other people with the lowest role that is enough (viewer / operator / technician); the PIN is theirs.
3. Check: open DWC in a private window: the PIN dialog must appear before any action.
4. Keep `/opt/dsf/conf/workshop-users.json` out of backups that leave the house in clear (it holds scrypt hashes, mode 600).
   If you lock yourself out, delete that file by hand on the Pi to start again (the service then is in open mode again).

Restrict the LAN (the other half of the same risk):
1. Put the machine on its own network or VLAN, or give the router a rule that only the known devices (.14 kiosk, .16 PC,
   the phones of the people) reach the Pi on ports 80, 8090, 8095 and 23.
2. Set DWC's own password (Settings, General) as well: the camera relay on :8090 asks for the day key only when DWC has a password.
3. Apply `tools/proxy/workshop-nginx.conf` (below) for headers and compression.

## Reverse proxy: compression and security headers (A-02)

Evidence (DuetWebServer, DSF 3.7 source, `src/DuetWebServer/Program.cs`): the web server is Kestrel with `UseFileServer` only; there is
no response compression and it does not look for the `.gz` file next to a bundle (`DuetFileProvider` only resolves symlinks), so
every asset goes out uncompressed whatever the `.gz` files in the plugin zips say. It reads `/opt/dsf/conf/http.json` (Kestrel
endpoint, default port 80) and sends `Cache-Control: public,max-age=3600` (the `MaxAge` setting) for everything but `index.html`. There are no security
headers. That is why the QA saw app.js 3.8 MB, monaco 5.1 MB, babylon 2.4 MB and the plugin bundles with encoded size == decoded size.
Our plugin packaging is not the cause (the .gz files are in the zips but nobody serves them).

Install (all **[SUDO]**, **[FREE MACHINE]**: DWC is unreachable for a minute):
1. `sudo apt install nginx` (and, for brotli, `libnginx-mod-http-brotli-filter` then uncomment the two brotli lines).
2. Back up: `sudo cp /opt/dsf/conf/http.json /opt/dsf/conf/http.json.bak`.
3. Move DuetWebServer to the loopback: in `/opt/dsf/conf/http.json` set the Kestrel endpoint `"Url": "http://127.0.0.1:5000"` (it was `http://0.0.0.0:80`).
4. `sudo cp tools/proxy/workshop-nginx.conf /etc/nginx/conf.d/workshop.conf`, remove the default site
   (`sudo rm /etc/nginx/sites-enabled/default`), `sudo nginx -t`.
5. `sudo systemctl restart duetwebserver` (or `duetcontrolserver` if your image runs them together), then `sudo systemctl enable --now nginx`.
6. Check from the PC: `curl -sI -H 'Accept-Encoding: gzip' http://192.168.1.10/ | grep -i "content-encoding\|x-frame"`, open DWC, the
   console of every page must show no Content-Security-Policy-Report-Only violation for a week; then rename that header to
   `Content-Security-Policy` in the file and reload nginx.
7. Rollback: restore `http.json.bak`, `sudo systemctl stop nginx`, restart DuetWebServer. The service itself is not touched.

Unchanged by the proxy: the camera relay (:8090), Vision (:8095) and the G-code bridge (:23) are separate ports and stay as they are.
TLS: see the comment at the end of the file; a certificate for a LAN name is self-signed or from a private CA (browser warning),
so enable it only if the network is not trusted. WebSocket and uploads were kept in mind (Upgrade headers, no body limit).

Camera relay with users on (`dsf/camera_access.py`, tested in `test_camera_access.py`): once a person exists, every route needs a role
(reads: operator and above, or a viewer with the camera flag; writes by role; a route not in the table is admin; a failing user store
answers 503 `service_unreachable`, never lets through). An `<img>`/`<video>` cannot send headers, so GET reads without a session token
accept the day key (`?t=` or the cookie `workshop_camera`), which the page gets from the API `camera.token` (operator or a viewer
with the camera). Without users, or from the Pi itself, the stream is open as before. Residual: the stream is open to the whole LAN
until the first person is created.

## G-code bridge (A-10, A-11)

- The unit `workshop-gcode-bridge` runs as the normal login user (`bridge/workshop-gcode-bridge.service`: `User=__USER__`,
  `NoNewPrivileges=yes`, `CapabilityBoundingSet=CAP_NET_BIND_SERVICE` for port 23); `install.sh` refuses to install it for root.
  It is NOT a root service.
- Password: new passwords are stored as `scrypt$<hex>` (salted). A bridge that already has an old sha256 password keeps working
  (the old format is still verified); to move it to scrypt set the password again from the Services page.
- Port 23 listens on every interface (`0.0.0.0`) and, with no `allowed` list, accepts every private address (10.x, 172.16-31.x,
  192.168.x). The default was NOT changed (the cutting PC .16 sends live jobs through it and an upgrade must not cut it). The bridge
  now logs a security event `open_to_lan` and the state file says `security.exposed: true` while there is no allow-list and no password.
  Owner step (no sudo; edit `0:/sys/workshop/config/bridge.json`, or the Services page): set
  `"allowed": ["192.168.1.16"]` (the PC) and, if the program can send it, a password; keep `trusted` for the PC if it cannot
  send `BRIDGE KEY`. Loopback is always allowed. The change is picked up without a restart (settings reload when the file changes).
- `0:/sys/workshop/data/.api-token` (the local key of the system programs, mode 640, group dsf): it lives on the SD, and the SD is
  what DuetWebServer serves as `0:/` through `/machine/file/...`. So anybody who can read files through DWC can read the key; with
  DWC without password that is the whole LAN, with a DWC password any session. The key opens every operation except `admin` as
  "the system" (VIA_TOKEN), without a PIN. Confirmed by reading `workshop_api.py`; it is a real escalation once people exist.
  Fixed in the code (2026-10-26), applied on the machine only when you install the new service: the key lives in
  `/opt/dsf/conf/workshop-api-token` (outside the SD, never served by DWC). Mode 640 and group dsf, not 600: the service, Vision and RS485
  run as dsf, but the G-code bridge runs as the login user (member of dsf) and must read it too. On its first start the new service
  moves the old file (same key, so programs that hold it keep working), removes the SD copy and logs one line
  "api: the local key moved out of the SD card". Install steps:
  1. Update Vision and RS485 FIRST (their readers: see fix-service-report.md, they read the new path and fall back to the old one), or accept
     that they answer 401 to the service until you do.
  2. `sudo -u dsf ls -l /opt/dsf/conf` must show the folder writable by dsf (workshop-secrets.json already lives there).
  3. Install the service (tools/install.sh), then check: `ls -l /opt/dsf/conf/workshop-api-token` is `-rw-r----- dsf dsf`, and
     `ls /opt/dsf/sd/sys/workshop/data/.api-token` no longer exists. Restart the bridge: `sudo systemctl restart workshop-gcode-bridge`
     (it reads the new path and falls back to the old file until then).
  4. Rollback: copy the contents of the new file back to the old SD path; the old service reads it and does not delete it.


## Phone notices topic (A-24)

On ntfy.sh the topic is the only secret: whoever knows it reads and sends the notices. A NEW installation now gets
`workshop-` plus 160 random bits (it was `taller-<host>-` plus 40 bits). An existing topic is never replaced. To get a strong one on a
machine that has the old kind: call the API operation `notifications.new_topic` (new random topic) and subscribe again on the phones (the old topic
stops working), or use your own long random value. Never publish the topic (it is masked in logs and exports).
