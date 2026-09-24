# Solar_P1 — Solar Proposal / Energy Report App

FastAPI backend + vanilla-JS SPA. User enters PV system params → backend fetches
site irradiance from PVGIS and runs a deterministic calculation engine → SPA
renders a report (Chart.js + MapLibre 3D site view) → ReportLab generates a
downloadable PDF proposal. Used by a solar business: the PDFs go to paying customers.

Roadmap: `~/.claude/plans/what-is-the-scope-unified-cosmos.md`. Part One (Phases 0–4)
is done: unblock, PVGIS irradiance, financials, UX, geometry-derived shading. Part Two
is under way — **Phases 5 (multi-tenancy), 6 (component catalog + ALMM/DCR compliance)
7 (P90, site temperature loss, shaded monthly split) and 8 (consumption, slab tariffs,
sizing) are done**; next is Phase 9 (roof geometry and panel layout — start with the
Bhuvan imagery spike). The app is becoming a multi-tenant SaaS sold to other EPCs.

## Commands

```bash
source .venv/bin/activate          # Python 3.11, matches the Docker image
pip install -r requirements.txt
dot_clean -m migrations            # REQUIRED on this exFAT volume before alembic, see Sharp edges
alembic upgrade head               # creates solar_reports.db
python scripts/create_user.py --email you@firm.com --org "Your Firm"   # first account
python scripts/load_components.py  # shared panel/inverter catalog, idempotent
uvicorn app.main:app --reload      # serves API + frontend on :8000
pytest tests/ -v                   # fully offline, never hits PVGIS
docker build -t solar-p1 . && docker run --env-file .env -p 8000:8000 solar-p1
```
Windows: `start.bat` / `stop.bat` (port 8000, needs `.venv`).

## Layout

| Path | Role |
|---|---|
| `app/main.py` | App factory, CORS, lifespan (temp_pdfs mkdir + purge), static mounts, `/` → index.html |
| `app/config.py` | `Settings` (pydantic-settings), `lru_cache`d; refuses to boot in production on the default SECRET_KEY |
| `app/models/{organisation,user}.py` | `organisations`, `users` — one firm, its people |
| `app/services/auth.py` | bcrypt hashing, `authenticate()` with constant-time-ish lookup |
| `app/api/deps.py` | `current_user` dependency; every data route depends on it |
| `app/api/routes/auth.py` | `POST /api/auth/login`, `/logout`, `GET /me` |
| `scripts/create_user.py` | Creates the first organisation and user; password from a prompt |
| `app/database/session.py` | Engine, `SessionLocal`, `Base`, `get_db` dependency |
| `app/models/solar_project.py` | `solar_projects` — inputs, orientation, loss params, calc results, irradiance source, one row |
| `app/models/irradiance_cache.py` | `irradiance_cache` — PVGIS results per ~1 km cell + orientation |
| `app/schemas/solar_project.py` | `ProjectBase/Create/Update/Response`; range validation lives here |
| `app/services/project_service.py` | CRUD + async `calculate_project` (row → dict → irradiance → engine → row) |
| `app/services/irradiance.py` | PVGIS client, cache, fallback. The only network I/O in the calc path |
| `app/calculations/solar.py` | **Pure functions, no DB/IO.** The only place physics lives |
| `app/calculations/financial.py` | **Pure functions, no DB/IO.** Subsidy, cashflow, payback, IRR, NPV, LCOE, CO₂ |
| `app/calculations/compliance.py` | **Pure.** ALMM List-I and DCR rules; decides whether a subsidy may be claimed |
| `app/calculations/tariff.py` | **Pure.** Telescopic slab billing and net-metering settlement with banking |
| `app/calculations/sizing.py` | **Pure.** Capacity ceilings from consumption, roof and budget |
| `app/models/tariff_plan.py` | `tariff_plans` — DISCOM rate cards, same shared/own pattern as the catalog |
| `app/models/components.py` | `panel_models`, `inverter_models`; `org_id` NULL = shared seed row |
| `app/services/catalog.py` | Component visibility in one place: shared rows plus the firm's own |
| `app/api/routes/catalog.py` | `/api/catalog/panels`, `/inverters` — list, create, update |
| `seeds/components.json` + `scripts/load_components.py` | Shared catalog, loaded idempotently |
| `app/calculations/solar_position.py` | **Pure.** Sun elevation/azimuth, ported from `3d-model.js` |
| `app/calculations/shading.py` | **Pure.** Horizon profile from footprints, year sweep, shading loss |
| `app/services/buildings.py` | Overpass client, cache, no-geometry fallback. Only runs when `shading_auto` |
| `app/models/building_cache.py` | `building_cache` — OSM footprints per ~11 m cell |
| `app/api/routes/projects.py` | `/api/projects` CRUD, `POST /{id}/calculate` (async), `GET /{id}/report/pdf` |
| `app/api/routes/geospatial.py` | `GET /api/geospatial/building` — Overpass/OSM footprint lookup, falls back to a synthetic box |
| `app/utils/pdf_generator.py` | ReportLab proposal: cover, energy, monthly, financial (when costed); page footers; `format_inr` |
| `frontend/js/api.js` | fetch wrappers + shared helpers `esc()`, `formatInr()` |
| `frontend/js/app.js` | `FORM_FIELDS` table, create/edit/delete, search, report rendering |
| `frontend/js/charts.js` | Chart.js monthly bars + cumulative cashflow line; honours reduced motion |
| `frontend/js/3d-model.js` | `mapManager` — MapLibre map, OSM footprint, CSS-3D panel array, sun-position solver, season/time sliders |
| `migrations/env.py` | Reads `DATABASE_URL` env first, else `alembic.ini`. New models must be imported here |
| `tests/fixtures/pvgis_gurugram.json` | Real PVGIS v5_3 response for the reference cell |
| `tests/fixtures/overpass_gurugram.json` | Real Overpass response (175 buildings) for the reference cell |

Frontend is plain globals (`api`, `app`, `chartManager`, `mapManager`, `esc`) wired
via inline `onclick` in `index.html`. No bundler, no framework, no npm. Chart.js
and maplibre-gl load from CDN.

## Auth and tenancy

Multi-tenant. Every project belongs to an organisation; a user belongs to one
organisation and sees only its projects.

- **Scoping happens in `project_service.get_project(db, project_id, org_id)`.** Every
  other service function goes through it, so a route cannot forget to scope. Routes
  pass `user.org_id` from the `current_user` dependency, never a client-supplied value.
- A project belonging to another firm returns **404, not 403** — Org B must not learn
  that a project exists.
- **The caches stay global on purpose.** `irradiance_cache` and `building_cache` hold
  public facts about places, not tenant data; a cross-tenant cache hit is the feature.
  Never add `org_id` to them.
- Sessions: signed cookie via Starlette `SessionMiddleware`, `HttpOnly`, `SameSite=Lax`,
  `Secure` in production, 14 days. No JWT — same-origin SPA, and a cookie is revocable.
- Passwords: bcrypt directly, not passlib (passlib 1.7.4 breaks against bcrypt 4.x).
  bcrypt truncates past 72 bytes, so `MAX_PASSWORD_BYTES` is enforced at the schema
  rather than silently accepting a weaker password.
- Login returns one message for unknown email and wrong password alike, and hashes a
  dummy password when the email is unknown, so neither wording nor timing confirms
  which addresses have accounts.
- **No default account ships.** The migration creates a "Default Organisation" and
  adopts pre-tenancy projects into it, but creates no user — run
  `scripts/create_user.py` once.
- Tests sign in once per session and replay the signed cookie (`_org_a_cookies`);
  bcrypt is deliberately slow and logging in per test cost ~30 s.

## Calculation engine

```
annual_kwh = capacity_kwp × H(i)_y × irradiance_calibration × PR/100
```

- `H(i)_y`: in-plane annual irradiation (kWh/m²/yr) from PVGIS `PVcalc` for the
  site's lat/lon, `tilt_deg`, and `azimuth_deg` (PVGIS convention: 0 = south,
  −90 = east, +90 = west). Requested with `loss=0` — our own 7-way loss stack
  supplies the losses; letting PVGIS apply them too would double-count.
- Monthly generation is split by each month's `H(i)_m` **less that month's shading**,
  so a shaded December loses share to an unshaded June. The annual total is unchanged:
  shading is already in the performance ratio, this only reshapes the year. The
  "Monsoon" tag on Jun–Sep is a chart label only.
- **P90** (`annual_gen_p90_kwh`) = P50 × (1 − 1.282 × relative SD), from PVGIS's
  interannual `SD_y`. This is **weather variability only** — a bank's P90 also carries
  model and degradation uncertainty and will be lower. The report and PDF both say so;
  never present it as bankable. None when the dataset gave no SD, e.g. the fallback.
- **Temperature loss** can come from the site. `temp_loss_auto` (off by default, like
  `shading_auto`) replaces `temp_loss_pct` with PVGIS's `l_tg` for this location *and
  mounting*. `temp_loss_computed_pct` is always reported so the operator can see what
  the site suggests even when not applying it.
- **`mounting_type`** is an input, not an assumption: `free` = elevated racking with
  airflow, `building` = flush mounted. It does not change irradiation at all, only
  module temperature — at the reference site 10.98% vs 14.71%, which is 12.8 MWh
  against 13.4. Picking one silently would be wrong for half of all installs.
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
- **Inverter replacement**: one mid-life capex, `inverter_replacement_year`
  (default 12, 0 disables) costing `INVERTER_COST_SHARE` = 12% of system cost
  unless `inverter_replacement_cost_inr` overrides it. Unlike `shading_auto` this
  defaults **on**: omitting a cost the customer will certainly pay overstates
  lifetime savings. It feeds payback, IRR, NPV and LCOE, and both the report and
  the PDF name the amount and year. Held flat in nominal terms, like O&M.
- **Metrics** from unrounded values; rounding only for storage. Simple and
  discounted payback (interpolated in the payback year), IRR by bisection on
  [−99%, 1000%], NPV, 25-year net savings (after investment), customer LCOE,
  CO₂ at the CEA v21.0 FY 2024-25 weighted average, 0.710 t/MWh (more
  conservative than the 0.736 combined margin).
- Pinned reference: 9.525 kWp at ₹55,000/kWp, auto subsidy, ₹8/kWh, replacement in
  year 12 → **5.2-year payback, 19.7% IRR, LCOE ₹3.91**. (Without the replacement:
  20.0% and ₹3.73.) The plan's sanity band is 4–6 years; outside it means a
  sign error. IRR was cross-checked against Newton's method and a brute-force scan.
- Money is `float`, rounded to whole rupees. These are projections, not a ledger.
- Consumption is held flat across the 25 years: no load growth is modelled. Fixed
  DISCOM charges are excluded from savings because they do not change when solar is
  added, so they cancel out of the difference.

## Consumption, tariffs and sizing

Savings come from the customer's own bill when both a 12-month `consumption_json` and a
`tariff_plan_id` are present. Missing either falls back to the older estimate — a flat
tariff with a guessed `export_ratio_pct` — and `savings_basis` records which was used so
the report and PDF can say so. Projects created before this phase are untouched.

Two things make Indian billing different from a flat rate, and both change what solar
is worth:

- **Telescopic slabs.** Each band is charged at its own rate, so solar removes units
  from the *top* of the bill. Savings are `bill(consumption) − bill(imports)`, never
  `units × average tariff`.
- **Banking.** A surplus month is not paid out; the units bank as credit and offset a
  later month. Only the balance left at the end of the settlement year is bought out at
  the export rate. `settle_net_metering` conserves generation: self-consumed plus banked
  surplus equals what was generated.

This matters more than any other number in the app. Same 9.5 kWp system, same
generation, on a slab tariff of ₹3 / ₹6.50 / ₹9.50:

| Customer | Effective value | Payback |
|---|---|---|
| Flat estimate (the old guess) | ₹6.50/kWh | 5.2 yr |
| 2,000 units a month | ₹9.50/kWh | 3.6 yr |
| 900 units a month | ₹7.14/kWh | 4.7 yr |
| 250 units a month | ₹3.47/kWh | **10.6 yr** |

The flat estimate told that last customer 5.2 years. **No tariff rates ship with the
app** — they vary by DISCOM, category and revision, and a stale rate in a proposal is a
commercial problem. Operators create their own plans, and `tariff_check_json` compares
the modelled annual bill against the one on the customer's bills so a wrong plan shows
up rather than quietly skewing every saving.

`recommend_capacity` answers the question customers ask first. Three ceilings —
consumption, roof, budget — and the smallest wins, with `limited_by` naming it.
**The roof ceiling is approximate**: `PACKING_FACTOR` in `sizing.py` is a stand-in for
row spacing and setbacks until Phase 9 lays the array out for real.

## Shading model (app/calculations/shading.py)

Opt-in per project via `shading_auto`, **off by default** — switching it on changes
the numbers, so no existing proposal moves on its own. When off, nothing is fetched
and the operator's `shading_loss_pct` stands.

Method: collapse the surrounding OSM footprints into a **horizon profile** (highest
obstruction elevation per degree of azimuth), then sweep the sun path for a year,
weighting each sample by the beam irradiance it would put on the tilted plane. About
30 ms, so it sits on the request path happily. The computed figure is written to
`shading_computed_pct` and, while `shading_auto` is on, replaces `shading_loss_pct`
in the loss stack.

- The horizon uses **exact ray-to-wall intersection per azimuth bin**. An earlier
  version sampled points along each wall and left gaps the sun shone through, which
  under-reported shading by ~10x. If you touch `horizon_profile`, keep
  `test_horizon_angle_matches_trigonometry`: it pins one wall to `atan(rise/distance)`
  and checks the filled bins are contiguous.
- The array is one point at roof height (host building's OSM height, else 3 m). No
  row-to-row self-shading, no variation across a big roof.
- All irradiance is treated as beam, so the figure **overstates** the real loss:
  diffuse light still arrives when the sun is blocked. That errs towards
  under-promising, matching the Phase 1 calibration decision.
- Reference site: 9.11% annual, December 30% vs June 0.7%. That takes PR from 78.5%
  to 69.4% and payback from 5.2 to 5.9 years — this feature moves real money.

**Height data is the weak link.** In the reference Gurugram neighbourhood *all 175*
buildings lack a height tag, so every one falls back to `ASSUMED_HEIGHT_M = 6.0`
(two storeys). The result is therefore driven by that assumption, not by survey data.
`shading_heights_assumed` carries the count, and the report and PDF both print it.
Never present the number without that caveat.

## Component catalog and compliance

The catalog is the keystone of Part Two: stringing, the SLD, layout dimensions and
compliance all read from it.

- **`org_id` NULL is the shared seed catalog; a value is that firm's own addition.**
  One table, no per-tenant duplication. Shared rows are read-only (403 on edit), so one
  firm cannot change a model another is quoting.
- **Compliance flags are tri-state.** `almm_listed` and `dcr` are `True`, `False`, or
  NULL for "not recorded". **NULL never reads as compliant** — an unrecorded module
  blocks the subsidy exactly as a non-compliant one does, because a subsidy you cannot
  evidence is one the customer will not receive.
- Two rules are asserted, both sourced: **ALMM List-I** for net-metered and PM Surya
  Ghar projects, and **DCR** for subsidy-linked projects. No inverter rule is asserted —
  nothing inverter-side was verified against a primary source, so `bis_certified` is
  information only.
- The List-II exemption (ends 2026-12-31) is a dated **warning**, never an error: what
  replaces it is unpublished, and hard-blocking on a guess about a future rule would be
  worse than flagging it.
- **A blocked subsidy is removed from the financials, not just hidden on the PDF.**
  Payback, IRR and NPV would otherwise rest on money that never arrives. Live check:
  the same 15-panel system pays back in 6.2 years on a DCR module and 7.0 on a
  non-DCR one.
- The seed ships only what a model designation reveals — manufacturer, model, watts.
  Voc, Isc and temperature coefficients are absent because they feed Phase 10 string
  sizing, where a wrong number oversizes a string and damages an inverter. A human
  copies them from the datasheet and sets `datasheet_verified`.
- Once a catalog panel is chosen it is the source of truth: `panel_wattage` is derived
  from `wp`, and the form makes the typed fields read-only.
- A project with no `panel_model_id` asserts nothing and keeps its subsidy, so rows
  created before the catalog are untouched.

## Irradiance service behaviour

| PVGIS outcome | Result |
|---|---|
| Cache hit | Cached value, `source="pvgis"`, no network (~4 ms) |
| 200 OK | Parsed, cached, `source="pvgis"` (~0.8 s p50) |
| 400 (e.g. "Location over the sea") | `InvalidLocationError` → route returns **422** with PVGIS's message |
| Timeout, network error, 5xx, 429, malformed | Fallback profile, `source="fallback"`, **not cached** |

- The fallback reproduces the reference Gurugram yield. It is not site-specific,
  and the report shows an amber warning plus a PDF note saying so.
- Cache keys are **integers plus mounting**: `round(lat×100)`, `round(lon×100)`,
  whole-degree tilt/azimuth, and `free`/`building`. Never key on floats. PVGIS is
  queried at the cell's own coordinates, so a cached value doesn't depend on which
  project fetched it. Mounting is in the key because the same cell has two different
  temperature losses.
- `parse_pvgis` also lifts `E_y`, `SD_y` (for P90) and `l_tg` (site temperature loss).
  All three are optional, so a row cached before Phase 7 still works. **Never trust the
  JSON types**: PVGIS returns `l_spec` as a string while its siblings are numbers, so
  everything goes through `_as_float`.
- Known omission: PVGIS also quantifies angle-of-incidence and spectral losses
  (≈2.9% combined at the reference site) that the loss stack ignores, so the model is
  mildly optimistic by that much.
- `get_irradiance` commits the session when it writes a cache row. Call it before
  modifying other objects in that session (see `calculate_project`).
- PVGIS v5_3, no API key, 10 s timeout.

Overpass (`buildings.py`) follows the same shape: integer cache keys on a finer
~11 m grid, queried at the cell centre, any failure returning None so the caller
falls back to the operator's value instead of inventing a skyline. It retries once
(15 s timeout, ~31 s worst case) because the public instance returns 504 under load
often enough that a single attempt usually fails.

## Conventions

- Routes stay thin: validate → call `project_service` → map None to 404. No DB
  queries in route bodies.
- **`PUT` is a full replace**, not a partial update: every required field must be
  sent and an omitted optional field is cleared. The edit form always submits the
  whole form. If a partial update is ever needed, add a `PATCH`.
- Form fields live in one place: `FORM_FIELDS` in `app.js`, whose ids match both
  the `<input id>` and the `ProjectBase` field name. Adding an input means adding
  a row there, or it silently never reaches the API.
- Prefer the browser: `required`/`min`/`max` for validation, `<details>` for
  collapsible sections, `form.reset()` for defaults, `confirm()` for destructive
  actions. `app.init()` only adds what the platform lacks — opening a `<details>`
  that holds an invalid field, since native validation cannot focus a hidden input.
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
- The sun solver exists twice on purpose: Python for the engine, JavaScript in
  `3d-model.js` so dragging the time slider stays local.
  `test_python_and_javascript_solvers_agree` runs both through node and pins them to
  1e-6, so they cannot drift. Change one, change the other.
- Anything reachable without a session is a decision, not an accident. Today that is
  `/api/health` (Render's check) and the static frontend. Everything else depends on
  `current_user`, including `/api/geospatial/building`, which spends our Overpass quota.
- **Tests never touch the network.** The autouse `offline_pvgis` fixture in
  `conftest.py` replaces `fetch_pvgis`, and `offline_overpass` replaces
  `fetch_buildings`; both return the list of calls made. To test the real HTTP
  client, route it through `httpx.MockTransport` (see `test_irradiance.py`). The conftest points `DATABASE_URL` at a temp file with
  hard assignment, because the schema fixture drops tables.
- **New models are imported in `app/models/__init__.py`.** SQLAlchemy resolves a
  ForeignKey by table name at mapper-configuration time, so importing one model without
  its referents fails with `NoReferencedTableError` — which the test suite hides,
  because `conftest.py` imports everything. Scripts and `migrations/env.py` import the
  package, not individual modules.
- Migrations use `op.batch_alter_table` so they run on both SQLite and Postgres.
  Verify with `alembic upgrade head && alembic downgrade -1 && alembic upgrade head`
  and `alembic check` (no drift).

## Sharp edges

- The tenant isolation test in `tests/test_auth.py` is load-bearing. If it is ever
  weakened, every firm's proposals are one bug away from each other.

- **The repo is on an exFAT volume.** macOS writes a `._<name>` AppleDouble twin
  for files here. Alembic loads every `*.py` in `migrations/versions/`, so
  `._*.py` crashes it with `SyntaxError: source code string cannot contain null
  bytes`. Run `dot_clean -m migrations` before any alembic command. New files
  regenerate them. `.gitignore` and `.dockerignore` exclude them; Render builds
  from a clean git checkout and is unaffected. pip's `Ignoring invalid
  distribution -xyz` warnings are the same cause, and harmless.
- The `/calculate` route is async but uses the sync SQLAlchemy `Session`, so DB
  calls run on the event loop. Fine for sub-ms queries; move to an async engine
  if calculation volume grows.
- `geospatial.py` is a **second, older Overpass caller** for the 3D view: sync
  `httpx.post` with a 20 s timeout inside a sync route, so it blocks a threadpool
  worker, and it has no cache. `services/buildings.py` is the good one; the route
  should eventually be moved onto it.
- Overpass is flaky: expect 504s, and expect the shading estimate to be absent
  sometimes. Recalculating is the fix, and a success is cached permanently.
- The form is still create-then-calculate, but a failed calculation no longer
  duplicates: `handleFormSubmit` keeps the new id in `editingId`, so a retry
  updates that project.
- `search` uses a leading-wildcard `ILIKE`, which cannot use the name indexes.
  Fine at proposal volumes; needs a trigram index if the dashboard slows down.
- The PDF has no logo or brand colours: there is no logo asset in the repo, and
  inventing branding for a real business would be wrong. `_page_decorations`
  in `pdf_generator.py` is where one would go.
