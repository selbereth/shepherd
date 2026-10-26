# Shepherd

Self-hosted child filter. Clients (Chrome/Brave extension now, Android app later) report
pages to your server; the server scores them, stores everything, and pushes a domain ban list back.

- `server/` – FastAPI + SQLite. Rule-based page scoring, device keys, ban list, event log.
- `extension/` – MV3 extension: sends page text for scoring, blocks banned domains via declarativeNetRequest.

## Run the server
    echo "SHEPHERD_ADMIN_KEY=$(openssl rand -hex 24)" > .env
    docker compose up -d --build

## Register a device
    curl -X POST localhost:8080/admin/devices -H "X-Admin-Key: $KEY" \
         -H 'Content-Type: application/json' -d '{"name":"kid-pc"}'
Load `extension/` unpacked, open its options page, enter the server URL and the returned key.

## Admin
- `POST /admin/banned {"domain": "..."}` / `DELETE /admin/banned/{domain}`
- `GET /admin/events?verdict=block`
- `SHEPHERD_AUTO_BAN=true` bans a domain automatically when a page scores as block.
