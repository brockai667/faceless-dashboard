# Progress Log — FacelessDashboard hardening

This file tracks the autonomous work done across three phases: tests, bug
fixes/error handling, and UI polish. Each entry records what was done and,
for non-obvious calls, the rationale.

## Understanding of the codebase (read before any changes)

- `server.py` — stdlib-only HTTP server (no Flask). Serves `app.html` at `/`,
  `data.json`, `history.json`, and JSON APIs for IG comments
  (`/api/comments`, `/api/all_comments`, `/api/reply`, `/api/hide`,
  `/api/comment_done`) plus `/api/refresh` which shells out to `generate.py`.
  Cloud mode (Render) is detected via `PORT` env var; secrets arrive as
  `SETTINGS_JSON` / `IG_TOKENS_JSON` / `TIKTOK_TOKENS_JSON` env vars and are
  written to local files by `bootstrap_secrets()`.
- `generate.py` — the real data pipeline. For each of the 10 "factories" it
  reads Buffer GraphQL (queue status), YouTube Data API v3 (channel stats +
  recent video stats), `tiktok.fetch_all()` and `instagram.fetch_all()`, then
  aggregates everything into `data.json` (current snapshot + `totals`) and
  appends one row/day to `history.json` (trend data). It also renders a
  legacy standalone `dashboard.html` via `build_html()` — this file is
  git-ignored/generated and NOT served by `server.py` (only `app.html` is
  served). `app.html` is the real, tracked frontend.
- `instagram.py` — Instagram Graph API client. Reads `ig_tokens.json`,
  auto-refreshes long-lived tokens under 10 days to expiry, fetches
  `me` (stats) + `me/media` (last 15 posts) + per-video `insights` (views).
- `tiktok.py` — TikTok Open API client. Reads `tiktok_tokens.json` +
  `settings.json` (client key/secret for refresh), fetches `user/info` and
  `video/list`, auto-refreshes on 401/403 via refresh_token.
- `tiktok_auth.py` — one-time interactive OAuth CLI, not used at runtime.
- `store.py` — optional GitHub-Gist-backed persistence for `history.json`,
  `prev.json` (last totals, for "since last refresh" deltas) and
  `done_comments.json` (dismissed comment IDs). No-op locally unless
  `GH_TOKEN`/`GIST_ID` env vars are set — falls back to local files.
- `app.html` — single-page dashboard (vanilla JS). Fetches `/data.json` and
  `/history.json`, renders Overview/Growth/Platforms/Winners/Factories/
  Comments tabs. All formatting (`fmt()`, `dur()`) and delta/growth math
  (`delta()`, `dchip()`, `dayDelta()`) live inline in `<script>`.

## Decisions & rationale

1. **Never commit or write real credential files.** `.gitignore` already
   excludes `settings.json`, `ig_tokens.json`, `tiktok_tokens.json`,
   `data.json`, `history.json`, `ig_cache.json`, `dashboard.html` — this is
   respected as-is. Tests use **synthetic** JSON fixtures with the same
   shape as the real caches (built from reading the real files' structure
   only, never their secret values) so nothing sensitive ends up in
   `tests/`. Confirmed the local token files contain live-looking IG/TikTok
   access tokens, reinforcing that these must stay untouched/uncommitted.
2. **pytest chosen** as the test framework (industry standard, easy mocking
   via `monkeypatch`/`unittest.mock`, good fixture support). Added
   `requirements-dev.txt` rather than polluting `requirements.txt` (which
   intentionally documents that the app itself has zero runtime deps —
   stdlib only, per its own comment) with a test-only dependency.
3. Tests avoid any real network access — all `urllib.request.urlopen` calls
   are monkeypatched.
4. `dashboard.html` (legacy generated file, gitignored, unused by
   `server.py`) is left alone for UI polish — only `app.html` (the real
   served frontend) is polished, since editing generated/ignored output
   would be pointless (next `generate.py` run overwrites it anyway, and its
   `build_html()` Python f-string generator is a separate code path from
   `app.html`'s JS). Decided NOT to touch `build_html()`'s inline HTML/CSS
   in generate.py for the "UI polish" phase, to keep the diff focused on the
   file that actually matters to users.

## Phase 1 — data-layer tests (done)

Added `tests/` (pytest, `conftest.py` blocks any real `urlopen` call via an
autouse fixture so nothing ever hits the network or real token files):

- `test_generate.py` (28 tests) — `fmt()`/`ago()` formatting, `_iso_dur()`,
  `_recent()`, `profile_link()`, `yt_stats()`/`yt_videos()` (YouTube API
  aggregation incl. 404/error handling), `render_ranking()` (leaderboard
  sort, empty-state copy, HTML-escaping of video titles).
- `test_instagram.py` (9 tests) — token loading/refresh, `fetch_all()`
  aggregation of profile+media+view-insights, and graceful degradation when
  `me`/`me/media`/insights calls fail.
- `test_tiktok.py` (8 tests) — token loading, 401/403 auto-refresh flow
  (success + failure), and graceful degradation on API errors.
- `test_store.py` (10 tests) — Gist-backed persistence, local-file fallback
  when `GH_TOKEN`/`GIST_ID` unset, tolerant handling of Gist API errors.

65 tests, all passing (`python -m pytest tests/`).

## Phase 2 — bug fixes & error handling (done)

Real bugs found & fixed (a single corrupted/missing JSON file used to crash a
much bigger scope than just itself):

1. `generate.py:80` `load_settings()` and the `channels_cache.json` load in
   `main()` used bare `json.load(open(...))` — a corrupt file crashed the
   entire run before any factory was processed. Fixed via new
   `_load_json_safe(path, default)` helper (warns + falls back).
2. `generate.py` per-factory `cfg = json.load(open(cfg_path))` — a corrupt
   `config.json` for **one** factory used to crash the loop for **all 10**
   factories. Now uses `_load_json_safe`, so a bad config only degrades that
   one factory (same as the existing "no token" path).
3. `server.py` `ig_tokens()` / `_settings()` had the same bare-`json.load`
   problem — a corrupt `ig_tokens.json` would raise all the way out of
   `fetch_all_comments()` (which iterates `ig_tokens().keys()` with **no**
   try/except) and `reply_comment`/`hide_comment`, breaking those endpoints
   entirely instead of just that request. Fixed with a matching
   `_load_json_safe` helper in server.py.
4. `server.py` `fetch_comments()` called `ig_get("me/media", ...)` with no
   error handling at all — an expired/blocked IG token or a network blip
   raised straight out of the `/api/comments` handler. Now caught and
   returned as `{"error": ...}`, matching the pattern already used elsewhere
   in the file.
5. `server.py` `do_POST` parsed the request body with a bare `json.loads` —
   a malformed JSON body (e.g. a stray client bug or manual curl test) raised
   uncaught. Now returns `400 {"error": "neplatny JSON telo"}`.
6. Added a top-level try/except around GET/POST routing (`_route_get`/
   `_route_post`) so *any* unexpected exception becomes a `500` JSON error
   response instead of a broken/reset connection with a traceback only on
   stderr — the dashboard JS can now always parse a response.
7. `/data.json` on a brand-new install (no `generate.py` run yet) now returns
   a valid empty-shape JSON (`{"projects":[],"totals":{},...}`) instead of a
   404 `{"error":"not found"}`, so the frontend's normal empty-state handling
   kicks in instead of a fetch failure.

12 new regression tests added (`tests/test_server_data.py` + 3 in
`test_generate.py`) covering each of the above. 77 tests total, all passing.

## Phase 3 — UI polish in app.html (done)

- **Consistent date formatting**: added `fmtDate()`/`fmtDateShort()` JS
  helpers (`YYYY-MM-DD` → `DD.MM.YYYY`, matching the Slovak-style `gen_at`
  timestamp already produced by `generate.py`) and applied them everywhere a
  raw ISO date was previously shown as-is: factory "naposledy" (last
  published) line, the Docs table's published-date column, and the growth
  chart's x-axis labels (previously an inconsistent `MM-DD` slice).
- **Loading state**: the page previously rendered a blank `<section>` until
  the first `fetch()` resolved. Added a static "Načítavam dáta…" spinner in
  the initial HTML and set `#updated`'s initial text to "Načítavam…" instead
  of an em-dash.
- **Empty states**: `load()` now normalizes `DATA` (`normalizeData()`) so a
  first-run/empty `data.json` (all-zero totals, no projects) can't produce
  `NaN` anywhere; if there are zero factories it shows an explicit "spusti
  generate.py" empty-state instead of a broken-looking all-zero dashboard.
- **No-crash data fetch**: `load()` is now wrapped in try/catch — a
  server-down or network failure shows a retry button instead of leaving the
  page permanently blank with an unhandled promise rejection.
- **Accessibility**: tabs now use `role="tablist"/"tab"/"tabpanel"` with
  `aria-selected`/`aria-controls`/`aria-labelledby` kept in sync in `show()`;
  the decorative status dot is `aria-hidden`; the comment-reply `<input>` has
  an `aria-label` (it only had a placeholder before); `#updated` is
  `role="status"` so screen readers announce load state changes; all
  `target="_blank"` links now include `rel="noopener noreferrer"` (tab-nabbing
  hardening, previously missing on all 5 external links).

Verified: extracted `<script>` still parses (`node -e "new Function(...)"`),
full pytest suite still green after the `generate.py`/`server.py` changes.

## Final status

- 77 pytest tests, all passing.
- 3 commits pushed to `origin/main`: data-layer tests, bug fixes/error
  handling, UI polish.

(Further entries appended as work proceeds.)
