# Alliad Fleet Health Dashboard

Flask web dashboard that pulls **live** data for the Alliad fleet from three
platforms: the VSS API (Howen cameras), MiX Telematics, and Track3 (Wialon
Hosting).

Pages:

- **Overview** — KPIs, online vs offline pie, status breakdown, top fleets by faults, alarm types.
- **Driver Behaviour** — over speeding, harsh acceleration, harsh braking, harsh cornering from Track3 and MiX side by side.
- **Track3 Fleet** — the 78-unit Alliad group on Track3: reporting status, last-message age, live speed.
- **Real-Time Status** — per-device live state, module health, camera-channel health, voltages, signal.
- **Alarms (24h)** — alarm-type pie, per-hour trend, top devices, fleet-by-type heatmap, locations on a map.
- **Device Drilldown** — pick one device to see its current state and last 24h alarm history.
- **MiX Health** — MiX telematics asset health when `MIX_ENABLED=1`.

## Quick start

1. Create a virtualenv and install requirements:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

2. Copy `.env.example` to `.env` and set credentials:

   | Variable | Purpose |
   |----------|---------|
   | `FLEET_BRAND_NAME`, `FLEET_VSS_CONTAINS` | Customer name shown in the UI, and the keyword that selects their VSS fleets |
   | `VSS_BASE_URL`, `VSS_USERNAME`, `VSS_PASSWORD` | Primary VSS server login |
   | `VSS_BASE_URL_N`, `VSS_USERNAME_N`, `VSS_PASSWORD_N` | Secondary profile (tried if primary fails) |
   | `MIX_ENABLED`, `MIX_GROUP_IDS`, `MIX_ORGANISATION_ID` | MiX site scope (Alliad site = `2751326493625476525`) |
   | `TRACK3_TOKEN`, `TRACK3_GROUP_ID`, `TRACK3_RESOURCE_ID` | Track3 (Wialon) API token and the Alliad unit group |
   | `DHL_DASH_USERNAME`, `DHL_DASH_PASSWORD` | Dashboard sign-in (variable names are historical) |
   | `FLASK_SECRET_KEY` | Session secret (required in production) |

   The app auto-discovers which VSS profile works (same pattern as `howen_vss_api.ipynb`) and stores the token for 22 hours.

   For shared deployments, set `NEON_DB_URL`. The app creates the `vss_tokens` table automatically on startup, or you can run `scripts/neon_vss_tokens.sql` once in Neon. The active VSS token/PID is stored in Neon; local JSON token fallback is disabled when `NEON_DB_URL` is configured. Give each customer deployment its own snapshot/meta/log tables (`NEON_SNAPSHOT_TABLE` and friends) but leave the VSS token row shared, so two dashboards do not trip VSS error `10082` (login too frequently).

3. Run:

   ```powershell
   python flask_app.py
   ```

   Open **http://127.0.0.1:8060/login**

## Deployment

The repository is [PaulMawa707/Alliad-Dashboard](https://github.com/PaulMawa707/Alliad-Dashboard), deployed on Vercel under the `data-science-geeks` team. The Vercel CLI is blocked by Application Control policy on the build machine, so project setup goes through the REST API:

```powershell
$env:VERCEL_TOKEN = "<token from https://vercel.com/account/tokens>"
python scripts/setup_vercel_project.py --name alliad-fleet --team data-science-geeks --repo PaulMawa707/Alliad-Dashboard
```

That creates the project, writes `.vercel/project.json`, and pushes every variable listed in `scripts/push_env_vercel.py` to production. Deploy with:

```powershell
python scripts/deploy_vercel.py            # uploads the git-tracked tree, waits for the build
python scripts/vercel_logs.py              # build logs for the latest production deployment
```

`--repo` only works once the Vercel account has a GitHub login connection; until then the API file upload above is the deployment path. After connecting GitHub in the Vercel dashboard, pushes to `main` deploy on their own and `deploy_vercel.py` becomes a manual fallback.

To refresh only the environment later:

```powershell
python scripts/push_env_vercel.py --dry-run   # review
python scripts/push_env_vercel.py             # apply
```

`vercel.json` runs `/api/cron/realtime` every 15 minutes, and `.github/workflows/realtime-cron.yml` pings the same endpoint as a backstop. Both need `CRON_SECRET` to match. There is deliberately no VSS token-refresh job here — the DHL deployment owns that schedule and both dashboards read the same `vss_tokens` row.

## Data sources

| Source | Auth | What the dashboard reads |
|--------|------|--------------------------|
| VSS (Howen) | username/password → token + pid, cached 22h | Device list, real-time status, alarms, live camera feeds |
| MiX Telematics | OAuth password grant → bearer token | Asset health, positions, driver-behaviour events |
| Track3 (Wialon) | long-lived API token → short-lived session `eid` | Unit list with last-message age, eco-driving violations |

Driver-behaviour event names differ per platform ("Over Speeding" on Track3,
"Pre-Warning Over Speeding at 75km/hr" on MiX), so `behaviour.py` maps every raw
event onto one of four canonical behaviours before the page renders.

## VSS token caching

- Successful VSS login writes the active `token`, `pid`, `issued_at`, `base_url`, and `profile` to Neon when `NEON_DB_URL` is configured.
- Reused for all API calls until **22 hours** (`VSS_TOKEN_TTL_HOURS`) or session expiry.
- On dashboard login/startup, if the stored token is older than the TTL, the app generates a fresh VSS token, overwrites the Neon row, and uses that token for data loading.
- Optional without Neon only: set `VSS_TOKEN` / `VSS_PID` in `.env` to skip `apiLogin`.
- HTTPS controltech hosts use `verify=False` by default (set `VSS_SSL_VERIFY=1` to enable certificate verification).

## Project layout

```
ALLIAD-DASHBOARD/
  flask_app.py          # Flask app (main entry)
  brand.py              # Customer name, tagline, VSS fleet keyword, accent colours
  vss_client.py         # Multi-profile VSS client + token store
  mix_client.py         # MiX OAuth + asset/position/event APIs
  mix_behaviour.py      # MiX driver-behaviour events -> canonical rows
  track3_client.py      # Wialon session, Alliad unit group, live status
  track3_events.py      # Wialon eco-driving report -> canonical rows
  behaviour.py          # Shared driver-behaviour vocabulary for both platforms
  data.py               # Cached DataFrame loaders
  components.py         # Plotly figure builders
  web/                  # Auth, views, background prewarm
  templates/            # Login + dashboard pages
  assets/               # Branding + flask-theme.css
  scripts/test_sources.py, scripts/verify_pages.py
```
