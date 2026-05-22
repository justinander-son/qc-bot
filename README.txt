DAILIES QC PIPELINE - SETUP & USAGE GUIDE
==========================================

Modular QC pipeline for animation/VFX dailies. Uses FFmpeg for technical
analysis and Streamlit for a web-based management dashboard. Airtable records
drive what gets processed — set a record to a pending status, run the pipeline,
results write back automatically.

---
1. INSTALLATION
---
1. Ensure you have Python 3.9+ and FFmpeg/FFprobe installed on your system.
2. Navigate to the project folder and create a virtual environment:
   python3 -m venv .venv
3. Activate the environment:
   source .venv/bin/activate  (Mac/Linux)
   .venv\Scripts\activate     (Windows)
4. Install dependencies:
   pip install -r requirements.txt

---
2. ENVIRONMENT SETUP
---
Copy .env.example to .env and fill in the required values:

   QC_PROJECT=matisse             # matches a file in projects/<name>.yaml
   SOURCE_DIR=/path/to/dailies    # root directory where media files live
   APPROVED_DIR=/path/to/approved # destination for passed files
   AIRTABLE_API_KEY=patXXX...     # Airtable personal access token
   AIRTABLE_BASE_ID=appXXX...     # your Airtable base ID
   AIRTABLE_TABLE_ID=tblXXX...    # your Airtable table ID

---
3. PORTING TO A NEW SHOW
---
1. Copy projects/matisse.yaml to projects/<show>.yaml.
2. Update filename_regex to match the new show's naming convention.
3. Update allowed_resolutions, allowed_codecs, and target_fps.
4. Update the airtable.fields block to match your Airtable column names exactly.
5. Update airtable.pending_values and status_values to match your workflow.
6. Set QC_PROJECT=<show> in .env.

---
4. USAGE
---
A) THE DASHBOARD (Recommended)
   streamlit run dashboard/app.py

   From here you can:
   - Run the QC pipeline against all pending Airtable records.
   - View detailed PASS/FAIL logs per file and per checker.
   - Manually override failures and route files.
   - Browse run history and technical metadata.

B) PIPELINE TRIGGER (Airtable-driven)
   The pipeline picks up any record where the QC Status field matches a value
   in pending_values (e.g. "Pending Review"). It locates the file on disk using
   the file_path field, runs all checkers, then writes the result back to the
   same record.

---
5. PROJECT STRUCTURE
---
core/
  config.py      — Loads .env + projects/<show>.yaml into typed config objects
  database.py    — SQLite schema and session management (SQLAlchemy)
  pipeline.py    — Orchestration: fetch records → locate files → run checkers → write back
  models.py      — Shared dataclasses (QCResult, JobSummary)
  registry.py    — Checker plugin registry

checkers/
  base.py        — BaseChecker ABC all checkers implement
  metadata.py    — Filename regex + FFprobe technical metadata
  content.py     — Black frame and frozen frame detection (FFmpeg)
  loudness.py    — EBU R128 loudness (FFmpeg ebur128 filter)
  colorspace.py  — HDR / color space validation
  integrity.py   — File size and PTS discontinuity checks

integrations/
  airtable.py    — Airtable API client (get pending records, write results)
  notifications.py — Optional Slack/email job summaries

dashboard/
  app.py         — Streamlit web interface

projects/
  matisse.yaml   — Per-show config: field names, specs, Airtable IDs

tests/           — Full pytest suite, no external services required

---
6. DATABASE RESET
---
The local SQLite audit database (qc.db) mirrors every result before it is
written to Airtable. To re-process files from scratch:
- Delete qc.db, OR
- Use the "Reset Database" button in the dashboard.

Airtable remains the authoritative record store. Resetting the local DB does
not change Airtable records — set those back to a pending_value manually if
you want the pipeline to re-run them.
