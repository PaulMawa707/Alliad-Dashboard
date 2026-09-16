"""Alliad Fleet Health Dashboard — Flask application (VSS · MiX · Track3)."""

from __future__ import annotations

import logging
import os

import neon_meta_store
import operation_log
from flask import Flask, jsonify, redirect, render_template, request, send_from_directory, session, url_for

from env_file import load_project_env

APP_BUILD = "flask-alliad-2026-09"
DEFAULT_PORT = 8060

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("alliad-flask")

load_project_env()

import brand  # noqa: E402

from data import (  # noqa: E402
    bust_cache_for_refresh,
    cache_freshness,
    cache_get,
    cache_latest_data_iso,
    cache_needs_hydration,
    hydrate_cache_from_neon,
    hydrate_missing_snapshots_from_neon,
    last_bust_cache_iso,
    last_saved_refresh_display,
    mix_integration_enabled,
    snapshot_counts_from_cache,
)
from vss_client import (  # noqa: E402
    active_base_url,
    last_vss_error,
    last_vss_profile,
    last_vss_token_source,
)
from web.auth import cron_request_authorized, login_required, verify_login  # noqa: E402
from web.prewarm import (  # noqa: E402
    REFRESH_STEPS,
    auto_refresh_realtime,
    auto_refresh_track3,
    prewarm_cache_sync,
    realtime_auto_refresh_seconds,
    realtime_data_age_seconds,
    refresh_step,
    start_background_workers,
)
try:
    from web.vss_proxy import register_vss_proxy  # noqa: E402
except ImportError:  # Camera proxy is optional; dashboard still runs without it.
    def register_vss_proxy(app, login_required):  # noqa: ARG001
        return None
from web.views import (  # noqa: E402
    alarms_context,
    behaviour_context,
    device_context,
    logs_context,
    mix_context,
    nav_items,
    overview_context,
    parse_online_age_hours,
    realtime_context,
    track3_context,
)

if os.environ.get("DHL_DASH_ACCESS_LOG", "0").strip().lower() not in ("1", "true", "yes", "on"):
    logging.getLogger("werkzeug").setLevel(logging.WARNING)

app = Flask(__name__, static_folder="assets", template_folder="templates")
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "alliad-dev-change-me-in-production")

register_vss_proxy(app, login_required)


@app.before_request
def hydrate_dashboard_cache():
    if not session.get("logged_in"):
        return None
    path = request.path or ""
    if not path.startswith("/dashboard") and not path.startswith("/api/"):
        return None
    if path.startswith("/api/logs") or path.startswith("/api/cron/") or path in ("/api/logout", "/api/refresh"):
        return None
    if cache_needs_hydration():
        try:
            hydrate_cache_from_neon()
        except Exception as exc:  # noqa: BLE001
            log.warning("hydrate from Neon failed: %s", exc)
    return None


def _mix_enabled() -> bool:
    return mix_integration_enabled()


def _track3_enabled() -> bool:
    from track3_client import track3_enabled

    return track3_enabled()


def _realtime_age_for_ui() -> int | None:
    age = realtime_data_age_seconds()
    return int(age) if age is not None else None


def _layout_context(*, active: str, **extra):
    ctx = {
        "active_tab": active,
        "nav_items": nav_items(
            active=active, mix_enabled=_mix_enabled(), track3_enabled=_track3_enabled()
        ),
        "mix_enabled": _mix_enabled(),
        "track3_enabled": _track3_enabled(),
        "brand_name": brand.brand_name(),
        "brand_tagline": brand.brand_tagline(),
        "brand_subtitle": brand.brand_subtitle(),
        "brand_logo": brand.logo_file(),
        "brand_mark": brand.mark_file(),
        "app_build": APP_BUILD,
        "username": session.get("username", ""),
        "ui_poll_ms": max(250, int(os.environ.get("DHL_UI_POLL_MS", "5000") or "5000")),
        "vss_error": last_vss_error() if cache_get("realtime_status") is None else None,
        "vss_profile": last_vss_profile(),
        "vss_base_url": active_base_url(),
        "awaiting_vss": cache_get("realtime_status") is None,
        "last_refresh_display": last_saved_refresh_display(),
        "last_auto_refresh_display": neon_meta_store.last_auto_refresh_display(),
        "realtime_auto_refresh_seconds": realtime_auto_refresh_seconds(),
        "realtime_age_seconds": _realtime_age_for_ui(),
    }
    ctx.update(extra)
    return ctx


@app.route("/")
def index():
    if session.get("logged_in"):
        return redirect(url_for("dashboard_overview"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if verify_login(username, password):
            session["logged_in"] = True
            session["username"] = username.strip()
            log_sid = operation_log.start_session("login", username=username.strip())
            session["log_session_id"] = log_sid
            operation_log.end_session(log_sid, "ok", message="Signed in")
            nxt = request.args.get("next") or url_for("dashboard_overview")
            return redirect(nxt)
        error = "Invalid username or password."

    return render_template(
        "login.html",
        error=error,
        logo_exists=True,
        hero_exists=True,
        brand_name=brand.brand_name(),
        brand_tagline=brand.brand_tagline(),
        brand_logo=brand.logo_file(),
        brand_mark=brand.mark_file(),
    )


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/api/logout", methods=["POST"])
def api_logout():
    session.clear()
    return jsonify({"ok": True, "redirect": url_for("login")})


@app.route("/dashboard")
@login_required
def dashboard_overview():
    ctx = overview_context(age_hours=parse_online_age_hours(request.args.get("age_hours")))
    return render_template("pages/overview.html", **_layout_context(active="overview", **ctx))


@app.route("/dashboard/realtime")
@login_required
def dashboard_realtime():
    ctx = realtime_context(
        age_hours=parse_online_age_hours(request.args.get("age_hours")),
        fleets=request.args.getlist("fleet"),
        statuses=request.args.getlist("status"),
        ignitions=request.args.getlist("ignition"),
        ch_filter=request.args.get("ch_filter", "all"),
        chart=request.args.get("chart", "online_pie"),
    )
    return render_template("pages/realtime.html", **_layout_context(active="realtime", **ctx))


@app.route("/dashboard/alarms")
@login_required
def dashboard_alarms():
    ctx = alarms_context(
        fleets=request.args.getlist("fleet"),
        alarm_types=request.args.getlist("alarm_type"),
        severity=request.args.get("severity", "all"),
        chart=request.args.get("chart", "high_critical"),
    )
    return render_template("pages/alarms.html", **_layout_context(active="alarms", **ctx))


@app.route("/dashboard/device")
@login_required
def dashboard_device():
    device_id = request.args.get("device_id", "").strip() or None
    ctx = device_context(device_id=device_id)
    return render_template("pages/device.html", **_layout_context(active="device", **ctx))


@app.route("/dashboard/mix")
@login_required
def dashboard_mix():
    if not _mix_enabled():
        return redirect(url_for("dashboard_overview"))
    ctx = mix_context(issues=request.args.getlist("issue"))
    return render_template("pages/mix.html", **_layout_context(active="mix", **ctx))


@app.route("/dashboard/behaviour")
@login_required
def dashboard_behaviour():
    ctx = behaviour_context(
        behaviours=request.args.getlist("behaviour"),
        sources=request.args.getlist("source"),
        chart=request.args.get("chart", "per_asset"),
    )
    return render_template("pages/behaviour.html", **_layout_context(active="behaviour", **ctx))


@app.route("/dashboard/track3")
@login_required
def dashboard_track3():
    if not _track3_enabled():
        return redirect(url_for("dashboard_overview"))
    ctx = track3_context(statuses=request.args.getlist("status"))
    return render_template("pages/track3.html", **_layout_context(active="track3", **ctx))


@app.route("/dashboard/logs")
@login_required
def dashboard_logs():
    ctx = logs_context()
    return render_template("pages/logs.html", **_layout_context(active="logs", **ctx))


@app.route("/api/logs")
@login_required
def api_logs():
    since = request.args.get("since", "0")
    try:
        since_id = max(0, int(since))
    except ValueError:
        since_id = 0
    limit = request.args.get("limit", "100")
    try:
        limit_n = max(1, min(500, int(limit)))
    except ValueError:
        limit_n = 100
    events = operation_log.fetch_events(since_id=since_id, limit=limit_n)
    return jsonify({
        "events": events,
        "latest_id": operation_log.latest_event_id(),
        "sessions": operation_log.fetch_sessions(limit=15),
    })


@app.route("/api/logs/sessions")
@login_required
def api_logs_sessions():
    return jsonify({"sessions": operation_log.fetch_sessions(limit=20)})


@app.route("/api/cache/status")
@login_required
def api_cache_status():
    def _count(key: str) -> int | None:
        value = cache_get(key)
        try:
            return int(len(value)) if value is not None else None
        except TypeError:
            return None

    return jsonify(
        {
            "freshness": cache_freshness(),
            "counts": {
                "dhl_devices": _count("dhl_devices"),
                "realtime_status": _count("realtime_status"),
                "alarms_24h": _count("alarms_24h"),
                "mix_health": _count("mix_health"),
                "track3_units": _count("track3_units"),
                "behaviour_events": _count("behaviour_events"),
            },
            "latest_data": cache_latest_data_iso(),
            "last_refresh": last_saved_refresh_display(),
            "last_auto_refresh": neon_meta_store.last_auto_refresh_display(),
            "last_bust": last_bust_cache_iso(),
            "vss_token_source": last_vss_token_source(),
            "vss_profile": last_vss_profile(),
            "vss_base_url": active_base_url(),
            "vss_error": last_vss_error(),
            "realtime_age_seconds": _realtime_age_for_ui(),
            "realtime_auto_refresh_seconds": realtime_auto_refresh_seconds(),
        }
    )


@app.route("/api/cron/realtime", methods=["GET", "POST"])
def api_cron_realtime():
    """Vercel Cron (and local timer) entrypoint: refresh realtime on a 30-minute schedule."""
    if not cron_request_authorized():
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    log_sid = operation_log.start_session("refresh", username="cron")
    operation_log.set_current_session(log_sid)
    try:
        from data import hydrate_missing_snapshots_from_neon

        hydrate_missing_snapshots_from_neon()
        interval = realtime_auto_refresh_seconds()
        age = realtime_data_age_seconds()
        # Vercel + GitHub both tick every 15 min; only pull VSS when the 30-min window elapsed.
        if age is not None and interval and age < interval:
            result = {"refreshed": False, "reason": "fresh", "age_seconds": int(age)}
        else:
            result = auto_refresh_realtime(force=True)
        result.setdefault("age_seconds", _realtime_age_for_ui())
        result["interval_seconds"] = realtime_auto_refresh_seconds()
        result["last_auto_refresh"] = neon_meta_store.last_auto_refresh_display()
        result["ok"] = True
        result["source"] = "cron"
        # Track3 and the behaviour events are cheap next to the VSS pull, so the
        # same tick keeps the driver-behaviour page current.
        try:
            result["track3"] = auto_refresh_track3().get("track3")
        except Exception as exc:  # noqa: BLE001
            log.warning("cron: Track3 refresh failed: %s", exc)
            result["track3_error"] = str(exc)
        status = "ok" if result.get("refreshed") or result.get("reason") in ("fresh", "disabled") else "error"
        reason = result.get("reason") or "unknown"
        extra = result.get("message") or ""
        if status == "error" and reason in ("token-unusable", "token-expired"):
            extra = extra or "Stored VSS token expired. The 12h token job must refresh Neon."
        operation_log.end_session(
            log_sid,
            status,
            message=f"Cron realtime refresh: refreshed={result.get('refreshed')} reason={reason}"
            + (f" ({extra})" if extra else ""),
        )
        return jsonify(result)
    except Exception as exc:  # noqa: BLE001
        operation_log.end_session(log_sid, "error", message=f"Cron realtime refresh failed: {exc}")
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/refresh/realtime", methods=["POST"])
@login_required
def api_refresh_realtime():
    """Auto-refresh hook: re-pull realtime status using the stored VSS token."""
    result = auto_refresh_realtime()
    result.setdefault("age_seconds", _realtime_age_for_ui())
    result["interval_seconds"] = realtime_auto_refresh_seconds()
    result["last_auto_refresh"] = neon_meta_store.last_auto_refresh_display()
    return jsonify(result)


@app.route("/api/refresh", methods=["POST"])
@login_required
def api_refresh():
    payload = request.get_json(silent=True) or {}
    step = str(payload.get("step") or request.args.get("step") or "").strip()
    if step:
        return _api_refresh_step(step)

    bust_cache_for_refresh(keep_devices=False)
    username = session.get("username", "")
    log_sid = operation_log.start_session("refresh", username=username)
    session["log_session_id"] = log_sid
    operation_log.set_current_session(log_sid)
    try:
        prewarm_cache_sync(stale_while_revalidate=False)
        from data import last_mix_error

        mix_err = last_mix_error()
        counts = snapshot_counts_from_cache()
        vss_loaded = bool(counts.get("dhl_devices") or counts.get("realtime_status"))
        if not vss_loaded:
            log.warning("VSS refresh empty — restoring Neon snapshots")
            hydrate_cache_from_neon()
            counts = snapshot_counts_from_cache()
        exclude_neon = {"mix_health"} if mix_err else set()
        missing_neon = hydrate_missing_snapshots_from_neon(exclude_keys=exclude_neon)
        counts = {**missing_neon, **counts}
        if not counts:
            counts = hydrate_cache_from_neon()
        neon_meta_store.record_last_refresh(
            counts=counts,
            username=username,
            session_id=log_sid,
        )
        end_msg = f"Refresh complete — {counts}"
        end_status = "ok"
        has_vss = bool(counts.get("dhl_devices") or counts.get("realtime_status"))
        vss_err = last_vss_error() if not has_vss else None
        if vss_err:
            end_msg = f"Refresh failed for VSS: {vss_err[:180]}"
            end_status = "error"
        elif not vss_loaded and has_vss:
            end_msg = f"Restored saved VSS data — live refresh failed: {(last_vss_error() or 'unknown')[:120]}"
        if mix_err:
            if vss_loaded or counts.get("dhl_devices"):
                end_msg = f"VSS data saved. MiX failed: {mix_err[:180]}"
            else:
                end_msg = f"{end_msg}. MiX failed: {mix_err[:120]}"
        operation_log.end_session(log_sid, end_status, message=end_msg)
        return jsonify({
            "ok": end_status == "ok",
            "message": end_msg,
            "counts": counts,
            "last_refresh": neon_meta_store.last_refresh_display(),
            "session_id": log_sid,
            "mix_error": mix_err or None,
            "vss_error": vss_err or None,
        })
    except Exception as exc:  # noqa: BLE001
        try:
            hydrate_cache_from_neon()
        except Exception:  # noqa: BLE001
            pass
        operation_log.end_session(log_sid, "error", message=f"Refresh failed: {exc}")
        return jsonify({"ok": False, "error": str(exc), "session_id": log_sid}), 500
    finally:
        operation_log.set_current_session(None)


def _api_refresh_step(step: str):
    """One stage of a manual refresh — a full pull exceeds the serverless time limit."""
    username = session.get("username", "")

    if step == "start":
        bust_cache_for_refresh(keep_devices=False)
        log_sid = operation_log.start_session("refresh", username=username)
        session["log_session_id"] = log_sid
        session["refresh_errors"] = {}
        return jsonify({"ok": True, "session_id": log_sid, "steps": list(REFRESH_STEPS)})

    log_sid = session.get("log_session_id") or ""
    errors = dict(session.get("refresh_errors") or {})

    if step == "finish":
        counts = snapshot_counts_from_cache()
        if not counts:
            counts = hydrate_cache_from_neon()
        vss_err = errors.get("vss")
        mix_err = errors.get("mix")
        track3_err = errors.get("track3")
        has_vss = bool(counts.get("dhl_devices") or counts.get("realtime_status"))
        has_track3 = bool(counts.get("track3_units") or counts.get("behaviour_events"))
        if has_vss or has_track3:
            neon_meta_store.record_last_refresh(counts=counts, username=username, session_id=log_sid)
        if vss_err and not has_vss:
            end_msg, end_status = f"Refresh failed for VSS: {vss_err[:180]}", "error"
        elif track3_err and not has_track3:
            end_msg, end_status = f"Refresh failed for Track3: {track3_err[:180]}", "error"
        elif mix_err:
            end_msg, end_status = f"VSS and Track3 data saved. MiX failed: {mix_err[:180]}", "ok"
        elif track3_err:
            end_msg, end_status = f"Data saved. Track3 partly failed: {track3_err[:180]}", "ok"
        else:
            end_msg, end_status = f"Refresh complete — {counts}", "ok"
        if log_sid:
            operation_log.end_session(log_sid, end_status, message=end_msg)
        session["refresh_errors"] = {}
        return jsonify({
            "ok": end_status == "ok",
            "message": end_msg,
            "counts": counts,
            "last_refresh": neon_meta_store.last_refresh_display(),
            "session_id": log_sid,
            "mix_error": mix_err or None,
            "vss_error": vss_err or None,
            "track3_error": track3_err or None,
        })

    if step not in REFRESH_STEPS:
        return jsonify({"ok": False, "error": f"Unknown refresh step: {step}"}), 400

    if log_sid:
        operation_log.set_current_session(log_sid)
    try:
        ok, err = refresh_step(step)
    finally:
        operation_log.set_current_session(None)

    if not ok and err:
        if step == "mix":
            bucket = "mix"
        elif step.startswith("track3") or step == "behaviour":
            bucket = "track3"
        else:
            bucket = "vss"
        errors[bucket] = err[:200]
        session["refresh_errors"] = errors

    return jsonify({
        "ok": ok,
        "step": step,
        "error": err,
        "counts": snapshot_counts_from_cache(),
    })


start_background_workers()


if __name__ == "__main__":
    host = os.environ.get("DHL_DASH_HOST", "127.0.0.1")
    port = int(os.environ.get("DHL_DASH_PORT", str(DEFAULT_PORT)))
    debug = os.environ.get("DHL_DASH_DEBUG", "0") == "1"
    log.info("%s (Flask) — http://%s:%s/login", brand.page_title_suffix(), host, port)
    app.run(host=host, port=port, debug=debug, threaded=True)
