# Lix-API - Backend Extrator de Streams

API que extrai streams M3U8 de provedores de video, com cache persistente no Supabase.

## Endpoints

| Metodo | Rota | Descricao |
|--------|------|-----------|
| GET | / | Status da API |
| GET | /api/stream/movie/<id> | Extrai M3U8 de filme (auto) |
| GET | /api/stream/tv/<id>/<s>/<e> | Extrai M3U8 de serie |
| GET | /api/servers/movie/<id> | Lista servidores disponiveis |
| GET | /api/servers/tv/<id>/<s>/<e> | Lista servidores de serie |
| GET | /api/proxy?url=... | Proxy para contornar CORS do CDN |

## Parametros opcionais

- ?servidor=NOME - Forca um servidor especifico (ex: ?servidor=VIP Player)

## Exemplos

    # Filme
    curl https://SEU-BACKEND.onrender.com/api/stream/movie/550

    # Serie (temporada 1, episodio 1)
    curl https://SEU-BACKEND.onrender.com/api/stream/tv/1396/1/1

    # Escolher servidor especifico
    curl "https://SEU-BACKEND.onrender.com/api/stream/movie/550?servidor=VIP Player"

## Rodar localmente

    pip install -r requirements.txt
    export $(cat .env | grep -v '^#' | xargs)
    python -m app.main

## Deploy

- Backend: Render (plano Free) + UptimeRobot para keep-alive
- Banco: Supabase (stream_providers + stream_cache)

## Variaveis de ambiente

- SUPABASE_URL - URL do projeto Supabase
- SUPABASE_SERVICE_KEY - Secret Key do Supabase
