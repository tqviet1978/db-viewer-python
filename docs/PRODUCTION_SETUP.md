# Production Setup Guide

This guide covers deploying dbviewer as a persistent systemd service and exposing it publicly via a Cloudflare Tunnel with a custom domain.

## Overview

```
Browser → https://db-viewer.vietml.com
              ↓
        Cloudflare Tunnel (cloudflared)
              ↓
        localhost:9876
              ↓
        dbviewer (systemd service)
```

## Requirements

- dbviewer installed via `install.sh` (see [DEV_SETUP.md](DEV_SETUP.md))
- `sudo` access on the server
- A Cloudflare account with your domain added

---

## Part 1 — Run dbviewer as a systemd Service

### 1.1 Create the service file

```bash
sudo nano /etc/systemd/system/dbviewer.service
```

Paste the following content — replace `youruser` with your actual username:

```ini
[Unit]
Description=DB Viewer
After=network.target

[Service]
Type=simple
User=youruser
ExecStart=/home/youruser/.dbviewer/bin/dbviewer --port 9876
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Save and exit: `Ctrl+O` → `Enter` → `Ctrl+X`

### 1.2 Enable and start the service

```bash
# Reload systemd to pick up the new service file
sudo systemctl daemon-reload

# Enable the service to start automatically on boot
sudo systemctl enable dbviewer

# Start the service now
sudo systemctl start dbviewer
```

### 1.3 Verify the service is running

```bash
sudo systemctl status dbviewer
```

Expected output:

```
● dbviewer.service - DB Viewer
     Loaded: loaded (/etc/systemd/system/dbviewer.service; enabled)
     Active: active (running) since ...
   Main PID: 12345 (dbviewer)
```

Verify it is listening on the correct port:

```bash
ss -tlnp | grep 9876
```

Expected output:

```
LISTEN  0  128  0.0.0.0:9876  0.0.0.0:*  users:(("python",pid=12345,...))
```

Do a quick local test:

```bash
curl -s http://localhost:9876/ | head -5
```

### 1.4 Useful service management commands

```bash
# View live logs
journalctl -u dbviewer -f

# View last 50 log lines
journalctl -u dbviewer -n 50

# Restart after config changes
sudo systemctl restart dbviewer

# Stop the service
sudo systemctl stop dbviewer

# Disable autostart on boot
sudo systemctl disable dbviewer
```

---

## Part 2 — Expose via Cloudflare Tunnel

### 2.1 Install cloudflared

Check if it is already installed:

```bash
cloudflared --version
```

If not installed, run the following for Debian/Ubuntu:

```bash
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb \
  -o cloudflared.deb
sudo dpkg -i cloudflared.deb
rm cloudflared.deb

# Confirm installation
cloudflared --version
```

### 2.2 Authenticate with Cloudflare

```bash
cloudflared tunnel login
```

This opens a browser window. Select your domain to grant access. A credentials file will be saved to `~/.cloudflared/cert.pem`.

### 2.3 Create the tunnel

```bash
cloudflared tunnel create dbviewer
```

The output will include a **Tunnel ID** — save it, you will need it in the next step:

```
Created tunnel dbviewer with id xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

### 2.4 Create the tunnel config file

```bash
mkdir -p ~/.cloudflared
nano ~/.cloudflared/config.yml
```

Paste the following — replace `<TUNNEL_ID>` with the ID from the previous step, and adjust the hostname and username:

```yaml
tunnel: <TUNNEL_ID>
credentials-file: /home/youruser/.cloudflared/<TUNNEL_ID>.json

ingress:
  - hostname: db-viewer.yourdomain.com
    service: http://localhost:9876
  - service: http_status:404
```

Save and exit: `Ctrl+O` → `Enter` → `Ctrl+X`

### 2.5 Create the DNS record

```bash
cloudflared tunnel route dns dbviewer db-viewer.yourdomain.com
```

This automatically creates a `CNAME` record in Cloudflare DNS pointing `db-viewer.yourdomain.com` to your tunnel.

Verify the record was created by logging into the Cloudflare dashboard → DNS → check for a `CNAME` entry for `db-viewer`.

### 2.6 Run cloudflared as a systemd service

```bash
# Install cloudflared as a system service
sudo cloudflared service install

# Enable autostart on boot
sudo systemctl enable cloudflared

# Start the service now
sudo systemctl start cloudflared

# Verify it is running
sudo systemctl status cloudflared
```

Expected output:

```
● cloudflared.service - cloudflared
     Active: active (running) since ...
```

---

## Part 3 — Verify the Full Stack

Run all checks in sequence:

```bash
# 1. Both services are running
sudo systemctl status dbviewer cloudflared

# 2. dbviewer is listening on port 9876
ss -tlnp | grep 9876

# 3. Local connectivity
curl -s http://localhost:9876/ | head -3

# 4. Public URL (allow up to 30s for DNS to propagate after first setup)
curl -s https://db-viewer.yourdomain.com/ | head -3
```

Then open https://db-viewer.yourdomain.com in a browser — the login dialog should appear.

Log in with the default credentials:

```
Username: admin
Password: admin123
```

---

## Part 4 — Change the Default Password

Since the app is publicly accessible, **change the default password immediately**:

```bash
~/.dbviewer/bin/dbviewer --change-password
```

Follow the interactive prompts. Then restart the service to apply:

```bash
sudo systemctl restart dbviewer
```

---

## Part 5 — Security Considerations

When exposing dbviewer to the public internet, keep these points in mind:

1. **Change the default password** — this is critical. Use a strong password.
2. **Restrict database permissions** — the database user configured in `connections.json` should have only the permissions needed. Consider using read-only users for production databases.
3. **Review connection configs** — ensure `connections.json` does not contain credentials for databases you don't want exposed.
4. **Use Cloudflare Access (optional)** — for additional security, set up a Cloudflare Access policy that requires authentication before reaching the tunnel.
5. **Monitor logs** — check `journalctl -u dbviewer -f` periodically for unexpected access patterns.
6. **Keep updated** — run `dbviewer --update` regularly to get security fixes.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `systemctl status dbviewer` shows `failed` | Wrong `ExecStart` path or permission issue | Check path with `which dbviewer` or `ls ~/.dbviewer/bin/`; verify `User=` is correct |
| Port 9876 not in `ss -tlnp` output | Service not started or crashed | Run `journalctl -u dbviewer -n 50` to see the error |
| `curl localhost:9876` works but public URL returns 502 | cloudflared not running or wrong port in config | Check `sudo systemctl status cloudflared` and verify port in `~/.cloudflared/config.yml` |
| Public URL returns a Cloudflare 1033 error | Tunnel is down | Run `sudo systemctl restart cloudflared` |
| DNS not resolving yet | DNS propagation delay | Wait 1–2 minutes after first setup; check with `dig db-viewer.yourdomain.com` |
| `cloudflared service install` fails | Missing `sudo` or credentials not found | Ensure you ran `cloudflared tunnel login` first and `~/.cloudflared/cert.pem` exists |
| Database connections fail after reboot | Database service not started yet | Ensure your database starts before dbviewer: add `After=mysql.service` (or equivalent) to the service file |
