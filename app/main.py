"""
Backend extrator de streams - Playerflix + Supabase
"""

import os
import re
import time
import requests
from flask import Flask, jsonify, request, Response
from flask_cors import CORS

from app import supabase_client as sb

app = Flask(__name__)
CORS(app)

# ============ CONFIG ============
USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 14; TECNO KI5k) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/153.0.8010.36 Mobile Safari/537.36"
)

BASE_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept-Language": "pt-BR,pt;q=0.9",
}

CACHE_TTL = 600  # 10 minutos


# ============ HELPERS ============

def http_get(url, extra_headers=None, timeout=15):
    headers = BASE_HEADERS.copy()
    if extra_headers:
        headers.update(extra_headers)
    r = requests.get(url, headers=headers, timeout=timeout)
    r.raise_for_status()
    return r


# ============ LOGICA DE EXTRACAO ============

def buscar_servidores(tipo, id_, season=None, episode=None):
    """Chama Ajax.php do playerflix e retorna data com options."""
    playerflix = sb.get_provider_url("playerflix")

    if tipo == "movie":
        path = f"filme/{id_}"
    else:
        path = f"serie/{id_}"

    season_param = season if season is not None else "null"
    episode_param = episode if episode is not None else "null"

    api_url = (
        f"{playerflix}/inc/Ajax.php"
        f"?type={tipo}&id={id_}"
        f"&season={season_param}&episode={episode_param}"
    )

    r = http_get(api_url, {
        "Referer": f"{playerflix}/{path}",
        "Origin": playerflix,
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
    })

    data = r.json()
    if not data.get("status"):
        raise Exception("API playerflix retornou status=false")

    return data["data"]


def extrair_m3u8(embed_url):
    """Baixa HTML do embed e extrai a URL do M3U8 + tempo de expiracao.
    Retorna: (m3u8_url, expires_timestamp)
    """
    playerflix = sb.get_provider_url("playerflix")

    r = http_get(embed_url, {
        "Referer": f"{playerflix}/",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })

    match = re.search(r'url:\s*["\']([^"\']+\.m3u8[^"\']*)["\']', r.text)
    if not match:
        raise Exception("M3U8 nao encontrado no HTML do embed")

    m3u8 = match.group(1).replace("\\/", "/")

    # Extrai o "expires" da URL (segundos Unix)
    expires_match = re.search(r'expires=(\d+)', m3u8)
    expires_at = int(expires_match.group(1)) if expires_match else None

    return m3u8, expires_at


# ============ ROTAS ============

@app.route("/")
def home():
    return jsonify({
        "status": "online",
        "servico": "Extrator de Streams",
        "endpoints": [
            "GET /api/stream/movie/<id>                 -> filme (auto)",
            "GET /api/stream/tv/<id>/<s>/<e>            -> serie (auto)",
            "GET /api/servers/movie/<id>                -> lista servidores filme",
            "GET /api/servers/tv/<id>/<s>/<e>           -> lista servidores serie",
            "GET /api/proxy?url=...                      -> proxy de segmentos",
        ]
    })


@app.route("/api/servers/movie/<id_>")
def servers_movie(id_):
    return _listar_servidores("movie", id_)


@app.route("/api/servers/tv/<id_>/<season>/<episode>")
def servers_tv(id_, season, episode):
    return _listar_servidores("tv", id_, season, episode)


def _listar_servidores(tipo, id_, season=None, episode=None):
    """Retorna a lista de servidores disponiveis (sem extrair M3U8)."""
    try:
        data = buscar_servidores(tipo, id_, season, episode)
        options = data.get("options", [])
        return jsonify({
            "status": True,
            "titulo": data.get("title"),
            "id": id_,
            "tipo": tipo,
            "temporada": season,
            "episodio": episode,
            "servidores": [
                {
                    "label": o.get("label"),
                    "budget": o.get("budget"),
                    "embed": o.get("embed"),
                }
                for o in options
            ],
        })
    except Exception as e:
        return jsonify({"erro": str(e)}), 500


@app.route("/api/stream/movie/<id_>")
def stream_movie(id_):
    return _extrair_stream("movie", id_)


@app.route("/api/stream/tv/<id_>/<season>/<episode>")
def stream_tv(id_, season, episode):
    return _extrair_stream("tv", id_, season, episode)


def _extrair_stream(tipo, id_, season=None, episode=None):
    """Extracao completa com fallback entre servidores."""
    try:
        servidor_escolhido = request.args.get("servidor")

        cache_key = f"stream:{tipo}:{id_}:{season}:{episode}:{servidor_escolhido or 'auto'}"

        # Tenta cache
        cached = sb.cache_get(cache_key)
        if cached:
            cached["cache"] = True
            return jsonify(cached)

        # Busca servidores
        data = buscar_servidores(tipo, id_, season, episode)
        options = data.get("options", [])
        if not options:
            return jsonify({"erro": "Nenhum servidor disponivel"}), 404

        # Monta lista de candidatos a tentar
        candidatos = []

        if servidor_escolhido:
            escolhido = next(
                (o for o in options if o.get("label") == servidor_escolhido),
                None
            )
            if not escolhido:
                return jsonify({
                    "erro": f"Servidor '{servidor_escolhido}' nao encontrado",
                    "disponiveis": [o.get("label") for o in options],
                }), 404
            candidatos.append(escolhido)
            for o in options:
                if o.get("label") != servidor_escolhido and o.get("budget") == "success":
                    candidatos.append(o)
        else:
            candidatos = [o for o in options if o.get("budget") == "success"]
            if not candidatos:
                candidatos = options

        # Tenta extrair de cada candidato ate conseguir
        escolhido = None
        m3u8 = None
        expires_at = None
        ultimo_erro = None
        tentados = []

        for cand in candidatos:
            label = cand.get("label")
            tentados.append(label)
            try:
                m3u8, expires_at = extrair_m3u8(cand["embed"])
                escolhido = cand
                break
            except Exception as e:
                ultimo_erro = str(e)
                print(f"[WARN] Falha ao extrair de {label}: {e}")
                continue

        if not escolhido or not m3u8:
            return jsonify({
                "erro": "Nao foi possivel extrair M3U8 de nenhum servidor",
                "ultimo_erro": ultimo_erro,
                "servidores_tentados": tentados,
            }), 500

        resultado = {
            "status": True,
            "titulo": data.get("title"),
            "id": id_,
            "tipo": tipo,
            "servidor": escolhido.get("label"),
            "embed": escolhido.get("embed"),
            "m3u8": m3u8,
            "expires_at": expires_at,
            "servidores_disponiveis": [
                {"label": o.get("label"), "budget": o.get("budget")}
                for o in options
            ],
            "servidores_tentados": tentados,
        }

        if tipo == "tv":
            resultado["temporada"] = season
            resultado["episodio"] = episode
            ne = data.get("next_episode")
            if ne:
                resultado["proximo_episodio"] = {
                    "season": ne.get("season_number"),
                    "episode": ne.get("episode_number"),
                    "title": ne.get("title"),
                }

        # Calcula TTL do cache baseado no expires do M3U8
        ttl_final = CACHE_TTL
        if expires_at:
            segundos_restantes = expires_at - int(time.time())
            # Margem de seguranca: 60s antes de expirar
            ttl_final = max(60, min(CACHE_TTL, segundos_restantes - 60))
            print(f"[INFO] TTL ajustado: {ttl_final}s (expira em {segundos_restantes}s)")

        # Salva no cache Supabase
        try:
            sb.cache_set(cache_key, resultado, ttl_seconds=ttl_final)
        except Exception as cache_err:
            print(f"[WARN] Falha ao salvar cache: {cache_err}")

        return jsonify(resultado)

    except Exception as e:
        return jsonify({"erro": str(e), "tipo": tipo, "id": id_}), 500


@app.route("/api/proxy")
def proxy():
    url = request.args.get("url")
    referer = request.args.get("referer", "https://v2.watchplay.shop/")
    if not url:
        return "Faltando parametro ?url=", 400

    try:
        is_m3u8 = ".m3u8" in url

        # Headers extras pra enganar o CDN
        extra_headers = {
            "Referer": referer,
            "Origin": referer.rsplit("/", 1)[0] if referer else "https://v2.watchplay.shop",
            "Accept": "*/*",
            "Accept-Language": "pt-BR,pt;q=0.9",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "cross-site",
        }

        r = http_get(url, extra_headers, timeout=30)
        content_type = r.headers.get("Content-Type", "application/octet-stream")

        if is_m3u8:
            base = url.rsplit("/", 1)[0]
            linhas = []
            for linha in r.text.splitlines():
                linha = linha.strip()
                if linha and not linha.startswith("#"):
                    if linha.startswith("http"):
                        seg_url = linha
                    else:
                        seg_url = f"{base}/{linha}"
                    linhas.append(f"/api/proxy?url={seg_url}&referer={referer}")
                else:
                    linhas.append(linha)
            return Response(
                "\n".join(linhas),
                content_type="application/vnd.apple.mpegurl"
            )

        return Response(r.content, content_type=content_type)

    except Exception as e:
        return jsonify({"erro": str(e)}), 500


# ============ START ============

if __name__ == "__main__":
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
