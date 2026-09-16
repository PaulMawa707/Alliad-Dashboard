"""Reverse-proxy VSS under /vss/ so HTTPS dashboard can embed live video (no mixed content)."""

from __future__ import annotations

import logging
import os
import re
from typing import Iterable
from urllib.parse import urlparse

import requests
from flask import Flask, Response, request, stream_with_context

from vss_client import _ssl_verify_for_url, active_base_url

log = logging.getLogger("dhl-flask")

_HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}

_REALVIDEO_FLV_URL = re.compile(
    r"_mediaPara\.url \+= gParaServerIp \+ \":\" \+ gParaServerPort;\s*"
    r"_mediaPara\.url \+= \"/flvRouter\.php\?live\?\";",
    re.MULTILINE,
)

# CanvasPlayer sends live video over wss://<stream-host>:36301/stream — not via the dashboard host.
_PLAYER_WS_HOST_PROXY = re.compile(
    r"if \(_serverIp != window\.location\.hostname\)[^\n]*\n"
    r"\s*_wsurl = \"wss://\" \+ window\.location\.hostname \+ \":\" \+ g_cnfServerSSLPort"
    r" \+ \"/\" \+ streamServerType \+ \"\?ipaddr=\" \+ _serverIp;",
    re.MULTILINE,
)


def vss_embed_proxy_enabled() -> bool:
    return os.environ.get("DHL_VSS_EMBED_PROXY", "1").strip().lower() in ("1", "true", "yes", "on")


def _stream_port() -> int:
    raw = os.environ.get("VSS_STREAM_PORT", "33122").strip()
    try:
        return int(raw)
    except ValueError:
        return 33122


def _stream_ws_port() -> int:
    raw = os.environ.get("VSS_STREAM_WS_PORT", "36301").strip()
    try:
        return int(raw)
    except ValueError:
        return 36301


def _default_stream_host() -> str:
    parsed = urlparse(active_base_url())
    return parsed.hostname or "40.76.130.233"


def _stream_wss_hostname() -> str:
    """TLS hostname for wss:// (cert matches domain, not raw IP)."""
    return os.environ.get("VSS_STREAM_WSS_HOST", "vss.controltech-ea.com").strip() or "vss.controltech-ea.com"


def _parse_device_from_flv_query(query_string: str) -> str | None:
    if not query_string:
        return None
    payload = query_string.split("?", 1)[-1]
    parts = payload.split("_")
    if len(parts) >= 2:
        return parts[1]
    return None


def _fetch_stream_host(device_id: str | None) -> str:
    if not device_id:
        return _default_stream_host()
    try:
        base = active_base_url().rstrip("/")
        upstream = requests.post(
            f"{base}/vss/vehicle/queryGtOfDevice.action",
            json={"deviceNo": device_id},
            timeout=15,
            verify=_ssl_verify_for_url(base),
        )
        payload = upstream.json()
        data = payload.get("data") or {}
        node_id = str(data.get("nodeID") or "0")
        gt_address = str(data.get("gtAddress") or "").strip()
        if node_id != "0" and gt_address:
            return gt_address.split(":")[0]
    except Exception as exc:  # noqa: BLE001
        log.warning("VSS stream host lookup failed for %s: %s", device_id, exc)
    return _default_stream_host()


def _rewrite_realvideo_html(text: str, *, stream_host: str, stream_port: int) -> str:
    """Point wasm/CanvasPlayer at the VSS media node (URL is parsed for WebSocket host)."""
    text = _REALVIDEO_FLV_URL.sub(
        f'_mediaPara.url += "{stream_host}:{stream_port}/flvRouter.php?live?";',
        text,
        count=1,
    )
    return text


def _rewrite_player_js(text: str, *, wss_host: str) -> str:
    """Route wss through the VSS domain (valid TLS cert) with ipaddr to the media node."""
    text = _PLAYER_WS_HOST_PROXY.sub(
        "if (false && (_serverIp != window.location.hostname)) "
        '_wsurl = "wss://" + window.location.hostname + ":" + g_cnfServerSSLPort'
        ' + "/" + streamServerType + "?ipaddr=" + _serverIp;',
        text,
        count=1,
    )
    old = (
        '_wsurl = "wss://" + _serverIp + ":" + g_cnfServerSSLPort + "/" + streamServerType + "?ipaddr=127.0.0.1";'
    )
    new = (
        f'_wsurl = "wss://{wss_host}:" + g_cnfServerSSLPort + "/" + streamServerType + "?ipaddr=" + '
        f'(_serverIp === "{wss_host}" ? "127.0.0.1" : _serverIp);'
    )
    return text.replace(old, new, 1)


def _forward_headers() -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in request.headers:
        lk = key.lower()
        if lk in _HOP_BY_HOP or lk == "host":
            continue
        out[key] = value
    return out


def _response_headers(upstream: requests.Response) -> Iterable[tuple[str, str]]:
    """Forward upstream headers; drop encoding/length — ``requests`` may have decoded the body."""
    for key, value in upstream.headers.items():
        lk = key.lower()
        if lk in _HOP_BY_HOP:
            continue
        if lk in (
            "x-frame-options",
            "content-security-policy",
            "content-encoding",
            "content-length",
        ):
            continue
        yield key, value


def _stream_response(upstream: requests.Response) -> Response:
    def _generate():
        try:
            for chunk in upstream.iter_content(chunk_size=65536):
                if chunk:
                    yield chunk
        finally:
            upstream.close()

    headers = list(_response_headers(upstream))
    headers.append(("X-Accel-Buffering", "no"))
    return Response(
        stream_with_context(_generate()),
        status=upstream.status_code,
        headers=headers,
    )


def register_vss_proxy(app: Flask, login_required) -> None:
    """Mount ``/vss/<path>`` → upstream ``{VSS_BASE_URL}/vss/<path>``."""

    @app.route("/vss-flv/flvRouter.php", methods=["GET", "HEAD", "OPTIONS"])
    @login_required
    def vss_flv_stream_proxy():
        if request.method == "OPTIONS":
            return Response(status=204)

        qs = request.query_string.decode("latin-1", errors="replace")
        device_id = _parse_device_from_flv_query(qs)
        host = _fetch_stream_host(device_id)
        port = _stream_port()
        target = f"http://{host}:{port}/flvRouter.php"
        if qs:
            target = f"{target}?{qs}"

        try:
            upstream = requests.request(
                method=request.method,
                url=target,
                headers={"Accept": request.headers.get("Accept", "*/*")},
                allow_redirects=False,
                stream=True,
                timeout=120,
            )
        except requests.RequestException as exc:
            log.warning("VSS FLV proxy failed %s: %s", target, exc)
            return Response(f"VSS FLV proxy error: {exc}", status=502, mimetype="text/plain")

        if request.method == "HEAD":
            return Response(status=upstream.status_code, headers=list(_response_headers(upstream)))
        return _stream_response(upstream)

    @app.route("/vss/<path:subpath>", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD"])
    @login_required
    def vss_reverse_proxy(subpath: str):
        base = active_base_url().rstrip("/")
        qs = request.query_string.decode("latin-1", errors="replace")
        target = f"{base}/vss/{subpath}"
        if qs:
            target = f"{target}?{qs}"

        if request.method == "OPTIONS":
            return Response(status=204)

        try:
            upstream = requests.request(
                method=request.method,
                url=target,
                headers=_forward_headers(),
                data=request.get_data(),
                cookies=None,
                allow_redirects=False,
                stream=True,
                timeout=120,
                verify=_ssl_verify_for_url(base),
            )
        except requests.RequestException as exc:
            log.warning("VSS proxy failed %s: %s", target, exc)
            return Response(f"VSS proxy error: {exc}", status=502, mimetype="text/plain")

        if request.method == "HEAD":
            return Response(status=upstream.status_code, headers=list(_response_headers(upstream)))

        content_type = (upstream.headers.get("Content-Type") or "").lower()
        device_id = request.args.get("deviceId") or request.args.get("deviceID")
        stream_host = _fetch_stream_host(str(device_id) if device_id else None)
        wss_host = _stream_wss_hostname()

        rewrite_html = (
            vss_embed_proxy_enabled()
            and subpath.endswith("RealVideo.html")
            and "text/html" in content_type
        )
        rewrite_player = (
            vss_embed_proxy_enabled()
            and subpath.endswith("dist/player/player.js")
            and "javascript" in content_type
        )

        if rewrite_html or rewrite_player:
            body = upstream.content
            status = upstream.status_code
            headers = list(_response_headers(upstream))
            upstream.close()
            text = body.decode("utf-8", errors="replace")
            if rewrite_html:
                text = _rewrite_realvideo_html(
                    text,
                    stream_host=stream_host,
                    stream_port=_stream_port(),
                )
            if rewrite_player:
                text = _rewrite_player_js(text, wss_host=wss_host)
            return Response(text, status=status, headers=headers)

        return _stream_response(upstream)
