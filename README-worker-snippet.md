## Headless monitor (alerts zonder UI open)
Wil je dat alerts blijven werken terwijl niemand de webpagina open heeft? Draai een **tweede container** met dezelfde image als worker.

### Portainer (losse container)
- Image: `adsb-alert:latest`
- Command override: `python -m app.worker`
- Volumes: `/opt/adsb-alert/data:/app/data:rw`
- Env: `TZ=Europe/Amsterdam`
- Restart policy: unless-stopped

### Stack (docker-compose) voorbeeld
```yaml
version: "3.8"
services:
  adsb-alert-ui:
    image: adsb-alert:latest
    container_name: adsb-alert-ui
    ports: ["8000:8000"]
    volumes: ["/opt/adsb-alert/data:/app/data:rw"]
    environment: ["TZ=Europe/Amsterdam"]
    restart: unless-stopped

  adsb-alert-worker:
    image: adsb-alert:latest
    container_name: adsb-alert-worker
    command: ["python", "-m", "app.worker"]
    volumes: ["/opt/adsb-alert/data:/app/data:rw"]
    environment: ["TZ=Europe/Amsterdam"]
    restart: unless-stopped
```

- De worker leest periodiek `config.json` (watchlist, radius, telegram) en verstuurt alerts met dezelfde cooldownlogica.
- Interval instellen via `monitor_interval_seconds` in `data/config.json` (default: `refresh_seconds`, min 5s).
