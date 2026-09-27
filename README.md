# Meu Player - Backend Extrator

API que extrai streams M3U8 de provedores de video.

## Endpoints

- GET / - Status da API
- GET /api/stream/movie/550 - Extrai M3U8 do filme ID 550
- GET /api/proxy?url=<m3u8>&referer=<referer> - Proxy de stream

## Rodar localmente

    pip install -r requirements.txt
    python -m app.main

## Deploy

Hospedado no Render (plano Free) + UptimeRobot para keep-alive.
