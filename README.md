# Shepherd

Self-hosted child filter. Clients (Chrome/Brave extension now, Android app later) report
pages to your server; the server scores them, stores everything, and pushes a domain ban list back.

- `server/` – FastAPI + SQLite. Rule-based page scoring, device keys, ban list, event log.
- `extension/` – MV3 extension: sends page text for scoring, blocks banned domains via declarativeNetRequest.

## Run the server
Create a `docker-compose.yml` (this repo's file builds from source; this one uses the published image):

```yaml
services:
  shepherd:
    image: ghcr.io/selbereth/shepherd-server:main
    container_name: shepherd
    restart: unless-stopped
    ports:
      - "8080:8080"
    environment:
      PUID: 1000                     # run as this user id (match your host user: `id -u`)
      PGID: 1000                     # run as this group id (`id -g`)
      SHEPHERD_ADMIN_KEY: change-me  # long random string, e.g. `openssl rand -hex 24`
      SHEPHERD_AUTO_BAN: "false"     # ban a domain automatically when a page scores as block
      SHEPHERD_WARN_SCORE: "5"
      SHEPHERD_BLOCK_SCORE: "10"
    volumes:
      - ./data:/data                 # SQLite database lives here
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request as u; u.urlopen('http://localhost:8080/docs')"]
      interval: 30s
```

Then `docker compose up -d`. The container starts as root only to fix ownership of `/data`,
then drops to `PUID:PGID`, so files in `./data` belong to your user.

To build from source instead, put `SHEPHERD_ADMIN_KEY`, `PUID` and `PGID` in a `.env` file and run
`docker compose up -d --build` with the compose file in this repo.

## Register a device
    curl -X POST localhost:8080/admin/devices -H "X-Admin-Key: $KEY" \
         -H 'Content-Type: application/json' -d '{"name":"kid-pc"}'
Load `extension/` unpacked, open its options page, enter the server URL and the returned key.

## Admin
- `POST /admin/banned {"domain": "..."}` / `DELETE /admin/banned/{domain}`
- `GET /admin/events?verdict=block`
- `SHEPHERD_AUTO_BAN=true` bans a domain automatically when a page scores as block.
