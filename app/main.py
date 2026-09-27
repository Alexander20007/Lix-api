"""
Backend extrator de streams - Playerflix
Rotas:
  GET /                       -> status da API
  GET /api/stream/<tipo>/<id> -> retorna M3U8 do filme/serie
  GET /api/proxy?url=...      -> proxy para contornar CORS do CDN
"""

import os
import re
import time
import requests
from flask import Flask, jsonify, request, Response
from flask_cors import CORS

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

# Cache em memoria
CACHE = {}
CACHE_TTL = 600  # 10 minutos

# ============ HELPERS ============

def http_get(url, extra_headers=None, timeout=15):
    headers = BASE_HEADERS.copy()
    if extra_headers:
        headers.update(extra_headers)
    r = requests.get(url, headers=headers, timeout=timeout)
    r.raise_for_status()
    return r


def cache_get(key):
    if key in CACHE:
        valor, expira_em = CACHE[key]
        if time.time() < expira_em:
            return valor
        del CACHE[key]
    return None


def cache_set(key, valor):
    CACHE[key] = (valor, time.time() + CACHE_TTL)


# ============ LOGICA DE EXTRACAO ============

def buscar_servidores(tipo, id_):
    """Chama Ajax.php e retorna data com options."""
    if tipo == "movie":
        path = f"filme/{id_}"
    else:
        path = f"serie/{id_}"

    api_url = (
        f"https://playerflix.ink/inc/Ajax.php"
        f"?type={tipo}&id={id_}&season=null&episode=null"
    )

    r = http_get(api_url, {
        "Referer": f"https://playerflix.ink/{path}",
        "Origin": "https://playerflix.ink",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
    })

    data = r.json()
    if not data.get("status"):
        raise Exception("API playerflix retornou status=false")

    return data["data"]


def extrair_m3u8(embed_url):
    """Baixa HTML do embed e extrai a URL do M3U8."""
    r = http_get(embed_url, {
        "Referer": "https://playerflix.ink/",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })

    match = re.search(
        r'url:\s*["\']([^"\']+\.m3u8[^"\']*)["\']',
        r.text
    )
    if not match:
        raise Exception("M3U8 nao encontrado no HTML do embed")

    return match.group(1).replace("\\/", "/")


# ============ ROTAS ============

@app.route("/")
def home():
    return jsonify({
        "status": "online",
        "servico": "Extrator de Streams",
        "endpoints": [
            "/api/stream/<tipo>/<id>  -> tipo=movie ou tv",
            "/api/proxy?url=...       -> proxy de segmentos"
        ]
    })


@app.route("/api/stream/<tipo>/<id_>")
def stream(tipo, id_):
    try:
        cache_key = f"stream:{tipo}:{id_}"
        cached = cache_get(cache_key)
        if cached:
            cached["cache"] = True
            return jsonify(cached)

        data = buscar_servidores(tipo, id_)

        options = data.get("options", [])
        if not options:
            return jsonify({"erro": "Nenhum servidor disponivel"}), 404

        escolhido = next(
            (o for o in options if o.get("budget") == "success"),
            options[0]
        )

        m3u8 = extrair_m3u8(escolhido["embed"])

        resultado = {
            "status": True,
            "titulo": data.get("title"),
            "id": id_,
            "tipo": tipo,
            "servidor": escolhido.get("label"),
            "embed": escolhido.get("embed"),
            "m3u8": m3u8,
            "servidores_disponiveis": [
                {"label": o.get("label"), "budget": o.get("budget")}
                for o in options
            ],
        }

        cache_set(cache_key, resultado)
        return jsonify(resultado)

    except Exception as e:
        return jsonify({"erro": str(e), "tipo": tipo, "id": id_}), 500


@app.route("/api/proxy")
def proxy():
    """Proxy que repassa requisicoes pro CDN com o Referer correto."""
    url = request.args.get("url")
    referer = request.args.get("referer", "https://v2.watchplay.shop/")

    if not url:
        return "Faltando parametro ?url=", 400

    try:
        is_m3u8 = ".m3u8" in url

        r = http_get(url, {"Referer": referer}, timeout=30)
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
                    proxy_seg = (
                        f"/api/proxy?url={seg_url}"
                        f"&referer={referer}"
                    )
                    linhas.append(proxy_seg)
                else:
                    linhas.append(linha)

            return Response(
                "\n".join(linhas),
                content_type="application/vnd.apple.mpegurl",
            )

        return Response(r.content, content_type=content_type)

    except Exception as e:
        return jsonify({"erro": str(e)}), 500


# ============ START ============

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
