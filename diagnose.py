"""
Quick Airtable + config diagnostic.
Run from the project root: python diagnose.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv()

print("── Environment ──────────────────────────────────────")
api_key = os.environ.get("AIRTABLE_API_KEY", "")
print(f"  AIRTABLE_API_KEY : {'SET (' + api_key[:6] + '...)' if api_key else 'NOT SET ← problem'}")
print(f"  AIRTABLE_BASE_ID : {os.environ.get('AIRTABLE_BASE_ID', 'NOT SET ← problem')}")
print(f"  AIRTABLE_TABLE_ID: {os.environ.get('AIRTABLE_TABLE_ID', 'NOT SET ← problem')}")
print(f"  SOURCE_DIR       : {os.environ.get('SOURCE_DIR', 'NOT SET ← problem')}")

print("\n── Config loading ───────────────────────────────────")
try:
    from core.config import load_config
    config = load_config()
    print(f"  project          : {config.project_name}")
    print(f"  source_dir       : {config.source_dir}")
    print(f"  source_dir exists: {config.source_dir.exists()}")
    print(f"  airtable         : {'configured' if config.airtable else 'NOT configured ← will use scan mode'}")
    if config.airtable:
        print(f"  base_id          : {config.airtable.base_id}")
        print(f"  table_id         : {config.airtable.table_id}")
        print(f"  pending_value    : {config.airtable.pending_value!r}")
        print(f"  fields           : {config.airtable.fields}")
        print(f"  status_values    : {config.airtable.status_values}")
except Exception as e:
    print(f"  ERROR: {e}")
    sys.exit(1)

if not config.airtable:
    print("\nAirtable not configured — check AIRTABLE_BASE_ID / AIRTABLE_TABLE_ID in .env")
    sys.exit(1)

print("\n── Airtable connection ──────────────────────────────")
try:
    from integrations.airtable import AirtableIntegration
    integration = AirtableIntegration(config.airtable)
    table = integration._get_table()
    if table is None:
        print("  ERROR: could not get table (API key missing or invalid)")
        sys.exit(1)
    # Actually test the connection with a minimal API call
    try:
        table.all(max_records=1)
        print("  connection       : OK")
    except Exception as api_err:
        print(f"  connection       : FAILED ← {api_err}")
        print("  → Check your PAT has scopes: data.records:read, data.records:write")
        print("  → Check the Matisse base is in the token's Access list")
        sys.exit(1)
except Exception as e:
    print(f"  ERROR: {e}")
    sys.exit(1)

print("\n── Pending records ──────────────────────────────────")
try:
    records = integration.get_pending_records()
    print(f"  records found    : {len(records)}")
    if not records:
        qc_field = config.airtable.fields.get("qc_status", "QC Status")
        print(f"  0 records match {{{qc_field}}} = {config.airtable.pending_value!r}")
        print("  → Check that some records in your table have that exact value")
        print("  → Check the field name is spelled correctly (case-sensitive)")

        # Show a sample of what QC Status values actually exist
        try:
            sample = table.all(max_records=5)
            print(f"\n  Sample of first {len(sample)} record(s) — QC Status values seen:")
            for r in sample:
                val = r.get("fields", {}).get(qc_field, "<field not found>")
                fp  = r.get("fields", {}).get(config.airtable.fields.get("file_path", "File Path"), "<no file_path>")
                print(f"    {r['id']}  {qc_field}={val!r}  file_path={str(fp)[:80]!r}")
        except Exception as e2:
            print(f"  (could not fetch sample: {e2})")
    else:
        fp_field = config.airtable.fields.get("file_path", "File Path")
        print(f"\n  First {min(3, len(records))} record(s):")
        for rec in records[:3]:
            print(f"    {rec['record_id']}  file_path={str(rec.get('file_path', ''))[:80]!r}")

        print("\n── Path resolution ──────────────────────────────────")
        from core.pipeline import _resolve_airtable_paths
        for rec in records[:3]:
            raw = rec.get("file_path") or ""
            files = _resolve_airtable_paths(raw, config)
            print(f"  {raw[:60]!r}")
            print(f"    → {len(files)} file(s) resolved")
            for f in files[:3]:
                print(f"       {f}  exists={f.exists()}")
            if len(files) > 3:
                print(f"       ... and {len(files)-3} more")
except Exception as e:
    print(f"  ERROR: {e}")
    sys.exit(1)

print("\n── Done ─────────────────────────────────────────────")
