# Solar_P1 — Solar Proposal / Energy Report App

FastAPI backend + vanilla-JS SPA. User enters PV system params → backend fetches
site irradiance from PVGIS and runs a deterministic calculation engine → SPA
renders a report (Chart.js + MapLibre 3D site view) → ReportLab generates a
downloadable PDF proposal. Used by a solar business: the PDFs go to paying customers.

Roadmap: `~/.claude/plans/what-is-the-scope-unified-cosmos.md`. Phases 0 (unblock),
1 (PVGIS) and 2 (financials) are done; next is Phase 3 (UX: edit/delete, validation,
mobile, PDF redesign).

## Commands

```bash
source .venv/bin/activate          # Python 3.11, matches the Docker image
pip install -r requirements.txt
dot_clean -m migrations            # REQUIRED on this exFAT volume before alembic, see Sharp edges
alembic upgrade head               # creates solar_reports.db
uvicorn app.main:app --reload      # serves API + frontend on :8000
pytest tests/ -v                   # fully offline, never hits PVGIS
docker build -t solar-p1 . && docker run --env-file .env -p 8000:8000 solar-p1
```
Windows: `start.bat` / `stop.bat` (port 8000, needs `.venv`).

## Layout

| Path | Role |
|---|---|
| `app/main.py` | App factory, CORS, lifespan (temp_pdfs mkdir + purge), static mounts, `/` → index.html |
| `app/config.py` | `Settings` (pydantic-settings), `get_settings()` is `lru_cache`d |
| `app/database/session.py` | Engine, `SessionLocal`, `Base`, `get_db` dependency |
| `app/models/solar_project.py` | `solar_projects` — inputs, orientation, loss params, calc results, irradiance source, one row |
| `app/models/irradiance_cache.py` | `irradiance_cache` — PVGIS results per ~1 km cell + orientation |
| `app/schemas/solar_project.py` | `ProjectBase/Create/Update/Response`; range validation lives here |
| `app/services/project_service.py` | CRUD + async `calculate_project` (row → dict → irradiance → engine → row) |
| `app/services/irradiance.py` | PVGIS client, cache, fallback. The only network I/O in the calc path |
| `app/calculations/solar.py` | **Pure functions, no DB/IO.** The only place physics lives |
| `app/calculations/financial.py` | **Pure functions, no DB/IO.** Subsidy, cashflow, payback, IRR, NPV, LCOE, CO₂ |
| `app/api/routes/projects.py` | `/api/projects` CRUD, `POST /{id}/calculate` (async), `GET /{id}/report/pdf` |
| `app/api/routes/geospatial.py` | `GET /api/geospatial/building` — Overpass/OSM footprint lookup, falls back to a synthetic box |
| `app/utils/pdf_generator.py` | ReportLab proposal (financial page when costed) + `format_inr`; returns bool, never raises |
| `frontend/js/api.js` | fetch wrappers + shared helpers `esc()`, `formatInr()` |
| `frontend/js/app.js` | View switching, form submit (create → calculate → render), report rendering |
| `frontend/js/charts.js` | Chart.js monthly bars + cumulative cashflow line; honours reduced motion |
| `frontend/js/3d-model.js` | `mapManager` — MapLibre map, OSM footprint, CSS-3D panel array, sun-position solver, season/time sliders |
| `migrations/env.py` | Reads `DATABASE_URL` env first, else `alembic.ini`. New models must be imported here |
| `tests/fixtures/pvgis_gurugram.json` | Real PVGIS v5_3 response for the reference cell |

Frontend is plain globals (`api`, `app`, `chartManager`, `mapManager`, `esc`) wired
via inline `onclick` in `index.html`. No bundler, no framework, no npm. Chart.js
and maplibre-gl load from CDN.

## Calculation engine

```
annual_kwh = capacity_kwp × H(i)_y × irradiance_calibration × PR/100
```

- `H(i)_y`: in-plane annual irradiation (kWh/m²/yr) from PVGIS `PVcalc` for the
  site's lat/lon, `tilt_deg`, and `azimuth_deg` (PVGIS convention: 0 = south,
  −90 = east, +90 = west). Requested with `loss=0` — our own 7-way loss stack
  supplies the losses; letting PVGIS apply them too would double-count.
- Monthly generation is split by the site's real monthly `H(i)_m` share. The
  "Monsoon" tag on Jun–Sep is a chart label only.
- `PR = 100 − sum(losses)`. Additive, not multiplicative — matches the
  reference PDF, not PVsyst.
- 25-yr compounded degradation, unchanged.

**Calibration — read before touching the numbers.** For India PVGIS uses **ERA5**
reanalysis, not satellite data, and ERA5 overestimates irradiance under heavy
aerosol haze. Raw PVGIS promises ~1687 kWh/kWp at Gurugram, about 20% above what
Delhi NCR rooftops deliver. `DEFAULT_IRRADIANCE_CALIBRATION = 0.8305` anchors the
absolute level to the one known-good point — the reference proposal's 1401 kWh/kWp
at Gurugram, PR 78.5% — while PVGIS supplies everything site-relative. The owner
chose this deliberately to avoid over-promising to customers. It is one national
factor, so it under-promises somewhat in the south (Chennai: 1281). Operators can
override it per project, bounded 0.5–1.5.

Tests pin Gurugram to 1401 via the fixture. If that assertion fails, the model or
the calibration changed — find out which before updating the number.

## Financial model (app/calculations/financial.py)

Runs only when `system_cost_inr` is set; otherwise every financial field is None
and the report/PDF hide the section. Never substitute a benchmark cost — an
invented price in a customer proposal is worse than a missing section.

- **Subsidy**: PM Surya Ghar residential, marginal bands in `PM_SURYA_GHAR_SLABS`
  (₹30k/kW to 2 kW, ₹18k for the 3rd kW, nothing above, so max ₹78k). Verified
  against 2026 scheme guides. `subsidy_inr` overrides it: blank/None = auto,
  0 = commercial or ineligible. Clamped to system cost.
- **Cashflow**, 25 rows, same degradation curve as the energy model
  (`solar.generation_by_year`). Self-consumed share valued at the grid tariff,
  escalating yearly; `export_ratio_pct` is the *annual net-metering surplus*,
  paid at a flat export tariff. O&M is flat, as % of system cost.
- **Metrics** from unrounded values; rounding only for storage. Simple and
  discounted payback (interpolated in the payback year), IRR by bisection on
  [−99%, 1000%], NPV, 25-year net savings (after investment), customer LCOE,
  CO₂ at the CEA v21.0 FY 2024-25 weighted average, 0.710 t/MWh (more
  conservative than the 0.736 combined margin).
- Pinned reference: 9.525 kWp at ₹55,000/kWp, auto subsidy, ₹8/kWh → **5.2-year
  payback, 20.0% IRR**. The plan's sanity band is 4–6 years; outside it means a
  sign error. IRR was cross-checked against Newton's method and a brute-force scan.
- Money is `float`, rounded to whole rupees. These are projections, not a ledger.

## Irradiance service behaviour

| PVGIS outcome | Result |
|---|---|
| Cache hit | Cached value, `source="pvgis"`, no network (~4 ms) |
| 200 OK | Parsed, cached, `source="pvgis"` (~0.8 s p50) |
| 400 (e.g. "Location over the sea") | `InvalidLocationError` → route returns **422** with PVGIS's message |
| Timeout, network error, 5xx, 429, malformed | Fallback profile, `source="fallback"`, **not cached** |

- The fallback reproduces the reference Gurugram yield. It is not site-specific,
  and the report shows an amber warning plus a PDF note saying so.
- Cache keys are **integers**: `round(lat×100)`, `round(lon×100)`, whole-degree
  tilt/azimuth. Never key on floats. PVGIS is queried at the cell's own
  coordinates, so a cached value doesn't depend on which project fetched it.
- `get_irradiance` commits the session when it writes a cache row. Call it before
  modifying other objects in that session (see `calculate_project`).
- PVGIS v5_3, no API key, 10 s timeout.

## Conventions

- Routes stay thin: validate → call `project_service` → map None to 404. No DB
  queries in route bodies.
- Calculation functions stay pure and independently testable; the service layer
  owns the dict ⇄ ORM translation and all I/O.
- Loss/degradation params are percentages (11.5 means 11.5%), stored as floats.
- `monthly_gen_json` is a JSON **string** column, parsed client-side.
- `is_calculated` is reset to False on update; the PDF route 400s if it's False.
- Defaults live in three places for each param (model column default, schema
  default, HTML input `value`). Change all three together. New input columns
  also need a `server_default` so existing rows are backfilled.
- Any operator-entered string going into `innerHTML` goes through `esc()`.
  Numbers don't need it. Prefer `textContent`.
- **Bump the `?v=N` cache-buster** on a `<script>` tag in `index.html` whenever
  that JS file changes. A browser mixing a cached old `api.js` with a new
  `app.js` breaks with `ReferenceError`s on the shared helpers.
- Currency: `₹` + `formatInr()` in the browser; `format_inr()` → `Rs. 4,45,875`
  in the PDF, because the built-in Helvetica has no ₹ glyph.
- **Tests never touch the network.** The autouse `offline_pvgis` fixture in
  `conftest.py` replaces `fetch_pvgis` and returns the list of calls made. To
  test the real HTTP client, route it through `httpx.MockTransport` (see
  `test_irradiance.py`). The conftest points `DATABASE_URL` at a temp file with
  hard assignment, because the schema fixture drops tables.
- Migrations use `op.batch_alter_table` so they run on both SQLite and Postgres.
  Verify with `alembic upgrade head && alembic downgrade -1 && alembic upgrade head`
  and `alembic check` (no drift).

## Sharp edges

- **The repo is on an exFAT volume.** macOS writes a `._<name>` AppleDouble twin
  for files here. Alembic loads every `*.py` in `migrations/versions/`, so
  `._*.py` crashes it with `SyntaxError: source code string cannot contain null
  bytes`. Run `dot_clean -m migrations` before any alembic command. New files
  regenerate them. `.gitignore` and `.dockerignore` exclude them; Render builds
  from a clean git checkout and is unaffected. pip's `Ignoring invalid
  distribution -xyz` warnings are the same cause, and harmless.
- `main.py` sets `allow_origins=["*"]` with `allow_credentials=True`; browsers
  reject that combination, and it's wide open regardless. Frontend is
  same-origin, so CORS isn't actually needed.
- The `/calculate` route is async but uses the sync SQLAlchemy `Session`, so DB
  calls run on the event loop. Fine for sub-ms queries; move to an async engine
  if calculation volume grows.
- `geospatial.py` uses **sync** `httpx.post` with a 20s timeout inside a sync
  route — blocks a threadpool worker for up to 20s per request. No caching, no
  rate-limit handling against the public Overpass instance.
- PUT has hybrid semantics. `ProjectUpdate` inherits `ProjectBase`, so required
  fields must always be sent; `update_project`'s `exclude_unset=True` then leaves
  **omitted** defaulted fields unchanged. Clearing an optional field (e.g.
  `system_cost_inr`) needs an explicit `null`. (Phase 3: make it a real partial update.)
- The form flow is create-then-calculate. If calculate fails (e.g. 422 on bad
  coordinates), the project already exists uncalculated, and there's no edit UI
  yet — resubmitting creates a duplicate. (Phase 3.)
- `createProject` in `api.js` shows `[object Object]` for Pydantic 422s, because
  `detail` is an array there. (Phase 3 validation.)
