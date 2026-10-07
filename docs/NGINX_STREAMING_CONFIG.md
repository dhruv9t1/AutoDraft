# nginx Configuration for SSE Streaming

Reference config for the production server (`word-addin.duckdns.org`) to support the SSE streaming endpoint `/api/documents/identify-variables-stream`.

Companion to [`STREAMING_VERIFICATION.md`](./STREAMING_VERIFICATION.md) — Phase 4.

---

## Full `/etc/nginx/sites-available/wordaddin`

```nginx
server {
    server_name word-addin.duckdns.org;

    # SSE streaming endpoint — must bypass nginx buffering
    location = /api/documents/identify-variables-stream {
        proxy_pass http://127.0.0.1:3001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # SSE essentials
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_buffering off;
        proxy_cache off;
        chunked_transfer_encoding on;
        gzip off;                       # gzip buffers the response — kills streaming

        # Long-lived stream timeouts
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
        proxy_connect_timeout 60s;
    }

    location / {
        proxy_pass http://127.0.0.1:3001;
        proxy_set_header Host $host;
        proxy_read_timeout 600s;
        proxy_connect_timeout 60s;
        proxy_send_timeout 600s;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    listen 443 ssl; # managed by Certbot
    ssl_certificate /etc/letsencrypt/live/word-addin.duckdns.org/fullchain.pem; # managed by Certbot
    ssl_certificate_key /etc/letsencrypt/live/word-addin.duckdns.org/privkey.pem; # managed by Certbot
    include /etc/letsencrypt/options-ssl-nginx.conf; # managed by Certbot
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem; # managed by Certbot
}

server {
    if ($host = word-addin.duckdns.org) {
        return 301 https://$host$request_uri;
    } # managed by Certbot

    listen 80;
    server_name word-addin.duckdns.org;
    return 404; # managed by Certbot
}
```

---

## Why each directive

| Directive | Purpose |
|-----------|---------|
| `proxy_buffering off` | nginx default buffers upstream response; with SSE that holds frames until the buffer fills or the stream ends. |
| `proxy_cache off` | Prevents any cache layer from collecting frames before flushing. |
| `proxy_http_version 1.1` + `Connection ""` | Required for chunked transfer / keep-alive to upstream; HTTP/1.0 closes per-request. |
| `chunked_transfer_encoding on` | Explicit, in case a parent context disables it. |
| `gzip off` | If gzip is enabled at `http {}` level it buffers the body to compress; SSE then arrives in one lump. |
| `proxy_read_timeout 300s` / `proxy_send_timeout 300s` | Long-lived stream tolerance. Backend sends `:` heartbeats every ~15s. |
| `location =` (exact match) | Slightly faster lookup, avoids accidentally catching other paths. |

---

## Apply

```bash
sudo nano /etc/nginx/sites-available/wordaddin   # paste the new block
sudo nginx -t
sudo systemctl reload nginx
```

---

## Verify

```bash
curl -N -X POST https://word-addin.duckdns.org/api/documents/identify-variables-stream \
  -H "Content-Type: application/json" \
  -d '{"documentContent":"Cheque No. 123456 dated 03/03/2023, drawn on STATE BANK OF INDIA for Rs. 3,94,033."}'
```

Expect `event: chunk_done` arriving incrementally with visible delay between frames — **not** all at once at the end.

If frames still batch:
- Check `/etc/nginx/nginx.conf` `http {}` block for `gzip on` — the per-location `gzip off` above should override it, but other modules (`ngx_http_sub_module`, `ngx_http_gunzip_module`) can also buffer.
- Check for any reverse proxy / CDN in front of nginx (Cloudflare, etc.) — they have their own buffering settings.

---

## Rollback

The streaming `location` block is additive — removing it reverts streaming requests to the catch-all `location /` (which buffers, breaking SSE but not the rest of the API). To fully disable streaming, the frontend has its own toggle described in `STREAMING_VERIFICATION.md` → Rollback plan.
