# Deployment Guide

## Production Server

- **Host:** ubuntu@161.118.177.172
- **SSH:** `ssh -i ssh-key-2026-03-15.key ubuntu@161.118.177.172`
- **OS:** Ubuntu (systemd)
- **Domain:** word-addin.duckdns.org (HTTPS via Let's Encrypt + nginx)

## Backend Runtime

- **Path:** `/home/ubuntu/word-addin/backend`
- **Build:** `cd /home/ubuntu/word-addin/backend && python -m venv .venv && .venv/bin/pip install -r requirements.txt`
- **Start:** `/home/ubuntu/word-addin/backend/.venv/bin/python /home/ubuntu/word-addin/backend/run.py`
- **Port:** 3001 (default)

## Systemd Service

- **Service file:** `/etc/systemd/system/word-addin.service`

### Service File Template

```ini
[Unit]
Description=Word Add-in Backend

[Service]
Environment=DATABASE_URL=postgresql://autodraft_app:RUNTIME_PASSWORD@db.PROJECT.supabase.co:5432/postgres
Environment=MIGRATION_DATABASE_URL=postgresql://SCHEMA_OWNER:MIGRATION_PASSWORD@db.PROJECT.supabase.co:5432/postgres
Environment=ALLOW_UNSAFE_DATABASE_ROLE=false
ExecStart=/home/ubuntu/word-addin/backend/.venv/bin/python /home/ubuntu/word-addin/backend/run.py
Restart=always

[Install]
WantedBy=multi-user.target
```

### Environment Variables

| Variable | Default | Required? |
|---|---|---|
| `DATABASE_URL` | `postgresql://autodraft_app:...@localhost:5432/wordaddin` | **Yes** — dedicated non-owner, non-superuser, NOBYPASSRLS runtime role |
| `MIGRATION_DATABASE_URL` | empty | Recommended for startup migrations; use schema-owner/migrator credentials, never the runtime role |
| `ALLOW_UNSAFE_DATABASE_ROLE` | `false` | Keep `false` in production |
| `HOST` | `127.0.0.1` | No |
| `PORT` | `3001` | No |
| `OLLAMA_API_URL` | `http://localhost:11434` | Base URL of AI service |
| `OLLAMA_API_PATH` | `/api/chat` | Set to `/v1/chat/completions` for cloud/OpenAI-compatible APIs |
| `OLLAMA_API_KEY` | empty | Required for cloud APIs (Bearer token) |
| `OLLAMA_MODEL` | `qwen3:4b` | Default local model; override only when the deployment intentionally uses another validated model |

**Important:** Production must not use `postgres`/schema-owner credentials in `DATABASE_URL`. The backend now rejects a runtime role that is superuser, `BYPASSRLS`, or owner of tenant tables. Apply migrations through `MIGRATION_DATABASE_URL` or before starting the service.

## Systemd Commands

```bash
# Start/stop/restart
sudo systemctl start word-addin
sudo systemctl stop word-addin
sudo systemctl restart word-addin

# Enable on boot
sudo systemctl enable word-addin

# Check status
sudo systemctl status word-addin

# View logs
sudo journalctl -u word-addin -f        # follow real-time
sudo journalctl -u word-addin -n 100    # last 100 lines
sudo journalctl -u word-addin --since today

# After editing the service file
sudo systemctl daemon-reload
sudo systemctl restart word-addin
```

## Nginx

- **Config:** `/etc/nginx/sites-enabled/`
- Proxies `https://word-addin.duckdns.org` → `http://127.0.0.1:3001`
- SSL managed by Certbot (Let's Encrypt)
- HTTP (port 80) redirects to HTTPS (port 443)

## Troubleshooting

### 502 Bad Gateway
1. Check if backend is running: `sudo systemctl status word-addin`
2. Check logs: `sudo journalctl -u word-addin -n 50`
3. Check if port 3001 is listening: `sudo lsof -i :3001`
4. If stuck at "Connecting to database..." → `DATABASE_URL` is wrong or missing
5. Verify nginx config: `cat /etc/nginx/sites-enabled/*`

### Service won't start
- Python/venv path not found → check `ExecStart` points to the deployed backend virtualenv and `run.py`
- Service file must be in `/etc/systemd/system/` (NOT `/etc/systemd/`)
- After any service file change: `sudo systemctl daemon-reload && sudo systemctl restart word-addin`
