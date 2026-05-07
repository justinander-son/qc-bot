# QC Pipeline — Claude Context

## What This Project Is

Production video QC pipeline for **59 Studio** animation dailies. Processes MP4 videos and JPG/PNG image sequences through two phases: (1) filename regex + FFprobe technical metadata, (2) FFmpeg black frame + frozen frame detection. Built initially with Gemini AI assistance (Phase 1 complete). Phase 2 is underway.

**UI stays Streamlit. No FastAPI. No React. Everything runs locally.**

---

## Phase 1 — Current State (Complete)

| File | Purpose |
|------|---------|
| `config.py` | Central config: paths, filename regex, allowed specs, routing logic |
| `main.py` | ThreadPoolExecutor parallel processing engine, generates `QC_Report.txt` |
| `database.py` | Thread-safe JSON flat-file DB (`qc_database.json`) |
| `dashboard.py` | Streamlit web UI — stats, filtering, manual override/unroute |
| `checkers/metadata.py` | Phase 1: FFprobe technical metadata + filename regex validation |
| `checkers/content.py` | Phase 2: FFmpeg `blackdetect` + `freezedetect` filters |

**Pipeline flow:** `rglob('*')` scan → skip excluded dirs → skip already-passed → Phase 1 metadata QC → Phase 2 content QC → write to `qc_database.json` → copy passed files to `APPROVED_DIR`

---

## Phase 2 — Architecture (In Progress)

### The Core Paradigm Shift

Phase 2 moves from **filesystem-scanning** to **record-driven processing**.

**Phase 1:** Pipeline scans a directory tree, decides what to process, results live in a local JSON file.

**Phase 2:** Airtable records define what needs QC. The pipeline reads "pending" records, locates the referenced files, runs QC, and writes results back to those same records. Airtable is both the job queue and the authoritative result store.

- `rglob('*')` scan → replaced by Airtable API query for pending records
- Files to process → explicitly declared by records, not discovered
- QC results → written back to the originating Airtable record
- `qc_database.json` → replaced by SQLite (Airtable is authoritative; SQLite is local audit/resilience layer)
- Pipeline trigger → record state (`qc_status == "pending"`) rather than a button

### Airtable Integration Model

```
Airtable Record
    ├─ file path or resolvable filename
    ├─ qc_status: "pending"  ← triggers processing
    ▼
Pipeline: reads record → locates file → runs checkers
    ▼
Writes back:
    ├─ qc_status: "pass" | "fail" | "error"
    ├─ qc_errors: [list]
    ├─ qc_checked_at: timestamp
    └─ qc_pipeline_version: version tag
```

Two required Airtable client methods:
1. `get_pending_records(base_id, table_id)` → records where `qc_status == "pending"`
2. `write_qc_result(record_id, result: QCResult)` → patch record with outcome

Field names, base IDs, table IDs are project-specific → live in `projects/matisse.yaml`, NOT hardcoded.

### Guiding Principles

1. **Record-driven** — Airtable defines the work. Pipeline is a consumer of declared jobs.
2. **Portable** — No hardcoded absolute paths. Env vars (`.env`) for credentials, YAML for per-show config.
3. **Fail-safe integrations** — Airtable API errors must never crash a QC run. `airtable_synced` flag in local DB enables retry.
4. **Checkers as plugins** — `BaseChecker` ABC. Each checker is independently testable.
5. **Auditable** — Every run tagged with pipeline version. Results mirrored locally before Airtable write.
6. **Local + Streamlit** — No cloud deployment, no FastAPI, no React. Streamlit dashboard stays.

### Target Directory Structure

```
QC/
├── core/
│   ├── config.py          # Env-var + YAML config loader (replaces hardcoded config.py)
│   ├── database.py        # SQLAlchemy models, SQLite (Postgres-forward schema)
│   ├── pipeline.py        # Orchestration: pull records → locate files → run checkers → write back
│   └── registry.py        # Checker plugin registry
├── checkers/
│   ├── base.py            # BaseChecker ABC
│   ├── filename.py        # Filename convention (ported from metadata.py)
│   ├── metadata.py        # FFprobe technical metadata
│   ├── content.py         # Black/freeze/silence detection
│   ├── loudness.py        # NEW: EBU R128 via ebur128 filter
│   ├── colorspace.py      # NEW: HDR/color space validation
│   └── integrity.py       # NEW: File size, PTS discontinuities
├── integrations/
│   ├── base.py            # BaseIntegration ABC
│   ├── airtable.py        # Airtable API client
│   └── notifications.py   # Optional: Slack/email job summaries (fail-safe)
├── dashboard/
│   └── app.py             # Refactored Streamlit (no subprocess hack, reads from SQLite)
├── tests/
│   ├── fixtures/          # Synthetic test media (ffmpeg -f lavfi generated)
│   ├── test_checkers.py
│   ├── test_pipeline.py
│   └── test_airtable.py   # Mocked Airtable API tests
├── projects/
│   └── matisse.yaml       # Per-show config: base_id, table_id, field mappings, allowed specs
├── .env.example
└── CLAUDE.md              # This file
```

### Local Audit DB Schema (SQLite)

```sql
CREATE TABLE results (
    id                 TEXT PRIMARY KEY,
    airtable_record_id TEXT,
    filename           TEXT NOT NULL,
    rel_path           TEXT NOT NULL,        -- NOT filename — avoids collision bug
    status             TEXT,                 -- pass|fail|error|skipped
    pipeline_version   TEXT,
    checked_at         DATETIME,
    meta               JSON,
    airtable_synced    BOOLEAN DEFAULT FALSE -- FALSE = retry needed
);

CREATE TABLE checks (
    id          TEXT PRIMARY KEY,
    result_id   TEXT REFERENCES results(id),
    checker     TEXT NOT NULL,
    passed      BOOLEAN,
    severity    TEXT,                        -- error|warning|info
    message     TEXT,
    details     JSON
);
```

---

## Multi-Agent Team

Five specialised agents, each owning a domain. When working in parallel, brief each agent with this file as context.

| Agent | Role | Owns |
|-------|------|------|
| **Alpha** | The Architect | `core/config.py`, `core/database.py`, `.env`, `projects/*.yaml`, migration scripts |
| **Beta** | The QC Engineer | `checkers/`, `core/registry.py`, `core/pipeline.py` |
| **Gamma** | The Integration Lead | `integrations/airtable.py`, `integrations/base.py`, `QCResult` dataclass |
| **Delta** | The Dashboard Lead | `dashboard/app.py`, reporting, export |
| **Epsilon** | The QA Lead | `tests/`, CI config |

**Implementation order:**
1. Alpha: portable config + SQLite schema + migration from `qc_database.json`
2. Gamma: Airtable client + `QCResult` dataclass + `BaseIntegration` ABC
3. Beta: `BaseChecker` ABC, port existing checkers, add `loudness.py`
4. Alpha + Gamma: `core/pipeline.py` — wire record fetch → file locate → checkers → write-back
5. Delta: refactor Streamlit dashboard (drop subprocess hack, read from SQLite)
6. Epsilon: test fixtures + full test suite

---

## Known Tech Debt (Phase 1 — prioritised)

### Architecture (fix first)
1. Hardcoded absolute paths in `config.py` — `SOURCE_DIR`, `APPROVED_DIR` are machine-specific
2. 50+ hardcoded excluded date dirs in `EXCLUDED_DIRS` — should be config-driven
3. JSON flat-file `qc_database.json` — no transactions, no queries, threading lock is a bandaid
4. **Latent bug:** filename used as DB primary key — same filename in different dirs silently overwrites
5. `subprocess.Popen` + `>> PROGRESS: X` stdout hack — brittle IPC, no error propagation
6. No pipeline versioning — can't tell which DB results came from which version of checks

### Missing QC Checks
7. No EBU R128 / LUFS loudness check (most important missing check — `ebur128` filter, zero new deps)
8. No pixel format validation (`pix_fmt` from ffprobe unused)
9. No color space / HDR metadata validation (`color_transfer`, `color_primaries` unused)
10. No bit depth check
11. No audio channel count / sample rate check
12. No PTS discontinuity / dropped frame detection (`-show_frames` not used)
13. No silence detection (`silencedetect` filter unused)
14. No file size anomaly detection
15. `BLACK_PIXEL_THRESHOLD = 0.00` too strict — misses near-black frames, should be `0.10`

### Code Quality
16. Zero test coverage
17. No logging framework — `print()` everywhere
18. No retry logic for transient ffprobe/ffmpeg failures
19. `requirements.txt` doesn't document `ffmpeg`/`ffprobe` system dependency

---

## FFmpeg / FFprobe Reference

### FFprobe — currently underutilised
Current usage: `-show_format -show_streams -print_format json` only.

Untapped for Phase 2:
- `-show_frames`: per-frame PTS/DTS/picture-type → dropped frame detection
- `-select_streams v:0`: target first video stream (faster)
- `side_data_list` in stream JSON: HDR10, Dolby Vision, HDR10+ metadata
- `color_transfer`: `smpte2084` = HDR10 PQ, `arib-std-b67` = HLG
- `color_primaries`: `bt2020` = wide gamut
- `pix_fmt`: pixel format (e.g., `yuv420p`, `yuv422p10le`)

### FFmpeg Filters Available (no new dependencies)
- `ebur128`: EBU R128 loudness → stderr, regex-parseable. Broadcast: -23 LUFS ±1 LU. Streaming: -16 LUFS
- `silencedetect`: audio silence (complement to `freezedetect`)
- `cropdetect`: auto-detect crop boundaries

### Python Wrappers
- `ffmpeg-python`: unmaintained since ~2019 — project correctly avoids it, keep using subprocess
- `python-ffmpeg`: maintained alternative if subprocess complexity grows
- `pyairtable`: Airtable API client (to be added to requirements)

### EBU R128
- Broadcast target: -23 LUFS ±1 LU integrated, max true peak -1 dBTP
- Streaming (R128s2): -16 LUFS
- FFmpeg: `ffmpeg -i input.mp4 -af ebur128 -f null -` (output to stderr)

---

## Project Config (matisse.yaml — target format)

```yaml
project: matisse
source_dir: ${SOURCE_DIR}           # from .env
approved_dir: ${APPROVED_DIR}       # from .env

airtable:
  base_id: ${AIRTABLE_BASE_ID}      # from .env
  table_id: ${AIRTABLE_TABLE_ID}    # from .env
  fields:
    file_path: "File Path"          # field name in Airtable
    qc_status: "QC Status"
    qc_errors: "QC Errors"
    qc_checked_at: "QC Checked At"
    qc_version: "QC Version"
  pending_value: "Pending"

filename_regex: '^(\d{3})_([A-Za-z0-9]+)_(T|All Walls|Brick|Floor|WallA|WallB|WallC|WallD)_(FullRes|HalfRes|QRes)_(v\d{6}[a-z]?)(?:_(\d+))?\.(mp4|jpg|png)$'

allowed_resolutions:
  - "13584x1712"
  - "6792x2260"
  - "13584x4518"
  - "8192x4320"
  - "2318x1632"
  - "4636x3264"
  - "7972x3424"
  - "5612x3424"

allowed_codecs: [h264, prores, mjpeg, png]
target_fps: "30/1"

qc:
  content_fade_margin: 0.5
  black_sensitivity_duration: 0.03
  black_pixel_threshold: 0.10      # was 0.00 — too strict
  black_picture_threshold: 0.98
  freeze_sensitivity_duration: 0.03
  freeze_noise_floor: "-60dB"
  loudness_target_lufs: -23.0
  loudness_tolerance_lu: 1.0
```
