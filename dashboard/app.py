from __future__ import annotations

import os
import shutil
import sys
import threading
import time
from pathlib import Path
from typing import Optional

# Ensure project root is on sys.path when launched via `streamlit run dashboard/app.py`
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import streamlit as st
from sqlalchemy import select

from core.database import Check, Result, get_session
from core.models import JobSummary

st.set_page_config(
    page_title="QC Dashboard",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;700&display=swap');

    html, body, [data-testid="stAppViewContainer"], [data-testid="stHeader"], .main {
        background-color: #000000 !important;
        color: #FFFFFF !important;
        font-family: 'Inter', sans-serif !important;
    }

    [data-testid="stSidebar"] {
        background-color: #111111 !important;
    }

    [data-testid="stMetricValue"] {
        font-size: 1.8rem !important;
        font-weight: 700 !important;
        color: #FFFFFF !important;
    }

    [data-testid="stMetricLabel"] {
        text-transform: uppercase !important;
        color: #888888 !important;
        font-size: 0.7rem !important;
        letter-spacing: 0.15rem !important;
    }

    div.stButton > button {
        border-radius: 0px !important;
        text-transform: uppercase !important;
        font-weight: 700 !important;
        letter-spacing: 0.1rem !important;
        padding: 0.5rem 2rem !important;
        height: auto !important;
        width: 100% !important;
    }

    div.stButton > button[kind="primary"] {
        background-color: #FFFFFF !important;
        color: #000000 !important;
        border: 1px solid #FFFFFF !important;
    }

    div.stButton > button[kind="primary"]:hover {
        background-color: #CCCCCC !important;
        border-color: #CCCCCC !important;
    }

    div.stButton > button[kind="secondary"] {
        background-color: transparent !important;
        color: #FFFFFF !important;
        border: 1px solid #FFFFFF !important;
    }

    div.stButton > button[kind="secondary"]:hover {
        background-color: #FFFFFF !important;
        color: #000000 !important;
    }

    .streamlit-expanderHeader {
        background-color: #000000 !important;
        border: 1px solid #222222 !important;
        border-radius: 0px !important;
        color: #FFFFFF !important;
        text-transform: uppercase !important;
        letter-spacing: 0.1rem !important;
    }

    .stDataFrame {
        border: 1px solid #222222 !important;
    }

    hr {
        border-color: #222222 !important;
    }

    h1, h2, h3 {
        text-transform: uppercase !important;
        letter-spacing: 0.3rem !important;
        font-weight: 700 !important;
    }

    div[data-baseweb="input"] {
        background-color: #111111 !important;
        border-radius: 0px !important;
        border: 1px solid #333333 !important;
    }

    input {
        color: #FFFFFF !important;
    }

    label {
        text-transform: uppercase !important;
        letter-spacing: 0.1rem !important;
        color: #888888 !important;
        font-size: 0.8rem !important;
    }
</style>
""", unsafe_allow_html=True)

# Thread-safe lock for progress writes from the background pipeline thread.
_progress_lock = threading.Lock()


def _get_db_url() -> str:
    from dotenv import load_dotenv
    load_dotenv(_ROOT / ".env")
    db_url = os.environ.get("QC_DATABASE_URL")
    if db_url:
        return db_url
    return f"sqlite:///{_ROOT / 'qc.db'}"


def load_results() -> list[dict]:
    """Load all results from SQLite as a list of dicts for the dataframe."""
    db_url = _get_db_url()
    db_path_str = db_url.removeprefix("sqlite:///")
    if not Path(db_path_str).exists():
        return []
    rows = []
    try:
        with get_session(db_url) as session:
            results = session.execute(
                select(Result).order_by(Result.checked_at.desc())
            ).scalars().all()
            for r in results:
                rows.append({
                    "status": r.status.upper(),
                    "filename": r.filename,
                    "shot": r.meta.get("shot", "") if r.meta else "",
                    "uv_area": r.meta.get("uv_area", "") if r.meta else "",
                    "duration": r.meta.get("duration", "") if r.meta else "",
                    "actual_res": r.meta.get("actual_res", "") if r.meta else "",
                    "checked_on": r.checked_at.strftime("%Y-%m-%d %H:%M:%S") if r.checked_at else "",
                    "rel_path": r.rel_path,
                    "airtable_synced": r.airtable_synced,
                    "_id": r.id,
                })
    except Exception:
        return []
    return rows


def _load_checks_for_result(result_id: str) -> list[dict]:
    db_url = _get_db_url()
    try:
        with get_session(db_url) as session:
            checks = session.execute(
                select(Check).where(Check.result_id == result_id)
            ).scalars().all()
            return [
                {
                    "checker": c.checker,
                    "passed": c.passed,
                    "severity": c.severity,
                    "message": c.message,
                    "details": c.details,
                }
                for c in checks
            ]
    except Exception:
        return []


def _get_routing_path(filename: str) -> Optional[Path]:
    """Derive destination path under approved_dir using shot-folder conventions."""
    try:
        from core.config import load_config
        cfg = load_config()
        import re
        m = re.match(cfg.filename_regex, filename)
        if not m:
            return None
        groups = m.groups()
        keys = ["shot", "name", "uv_area", "res_name", "version", "frame", "ext"]
        meta = {k: v for k, v in zip(keys, groups)}
        shot_str = meta["shot"]
        chapter_num = (int(shot_str) // 100) * 100
        chapter_str = f"{chapter_num:03d}"
        return cfg.approved_dir / chapter_str / shot_str / filename
    except Exception:
        return None


def override_file(result_id: str, filename: str) -> tuple[bool, str]:
    """Set status to 'overridden' in SQLite and copy file to approved dir."""
    db_url = _get_db_url()
    try:
        from core.config import load_config
        cfg = load_config()
        matches = list(cfg.source_dir.rglob(filename))
        if not matches:
            return False, f"Source file not found: {filename}"
        source_path = matches[0]

        dest_path = _get_routing_path(filename)
        if dest_path:
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, dest_path)

        with get_session(db_url) as session:
            result = session.execute(
                select(Result).where(Result.id == result_id)
            ).scalar_one_or_none()
            if result:
                result.status = "overridden"

        return True, f"Overridden and routed to {dest_path.parent.relative_to(cfg.approved_dir) if dest_path else 'N/A'}"
    except Exception as e:
        return False, str(e)


def unroute_file(result_id: str, filename: str) -> tuple[bool, str]:
    """Remove from approved dir and set status back to 'fail'."""
    db_url = _get_db_url()
    try:
        dest_path = _get_routing_path(filename)
        if dest_path and dest_path.exists():
            os.remove(dest_path)

        with get_session(db_url) as session:
            result = session.execute(
                select(Result).where(Result.id == result_id)
            ).scalar_one_or_none()
            if result:
                result.status = "fail"

        return True, "Override removed; status reset to FAIL"
    except Exception as e:
        return False, str(e)


def _pipeline_worker(project: Optional[str]) -> None:
    """Run in a daemon thread. Updates session_state and never propagates exceptions."""
    from core.pipeline import run_pipeline

    def _update_progress(completed: int, total: int) -> None:
        with _progress_lock:
            st.session_state.pipeline_progress = (completed, total)

    try:
        summary = run_pipeline(project=project, progress_callback=_update_progress)
        with _progress_lock:
            st.session_state.pipeline_summary = summary
    except Exception as e:
        with _progress_lock:
            st.session_state.pipeline_error = str(e)
    finally:
        with _progress_lock:
            st.session_state.pipeline_running = False


def _init_session_state() -> None:
    defaults = {
        "pipeline_running": False,
        "pipeline_progress": (0, 0),
        "pipeline_error": None,
        "pipeline_summary": None,
        "confirm_reset": False,
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


def main() -> None:
    _init_session_state()

    st.title("QC Dashboard")

    results = load_results()

    # --- STATS BAR ---
    total = len(results)
    passed = sum(1 for r in results if r["status"] in ("PASS", "OVERRIDDEN"))
    failed = sum(1 for r in results if r["status"] == "FAIL")
    pass_rate = (passed / total * 100) if total > 0 else 0.0

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Files", total)
    col2.metric("Passed", passed)
    col3.metric("Failed", failed)
    col4.metric("Pass Rate", f"{pass_rate:.0f}%")

    st.divider()

    # --- CONTROL PANEL ---
    col_btn1, col_btn2 = st.columns(2)

    with col_btn1:
        start_disabled = st.session_state.pipeline_running
        if st.button("Start QC Processing", type="primary", use_container_width=True, disabled=start_disabled):
            st.session_state.pipeline_running = True
            st.session_state.pipeline_progress = (0, 0)
            st.session_state.pipeline_error = None
            st.session_state.pipeline_summary = None
            thread = threading.Thread(target=_pipeline_worker, args=(None,), daemon=True)
            thread.start()
            st.rerun()

    with col_btn2:
        if not st.session_state.confirm_reset:
            if st.button("Reset Database", type="secondary", use_container_width=True):
                st.session_state.confirm_reset = True
                st.rerun()
        else:
            st.warning("This will permanently delete qc.db. All QC results will be lost.")
            col_yes, col_no = st.columns(2)
            with col_yes:
                if st.button("Confirm Reset", type="primary", use_container_width=True):
                    db_url = _get_db_url()
                    db_path = Path(db_url.removeprefix("sqlite:///"))
                    if db_path.exists():
                        db_path.unlink()
                    st.session_state.confirm_reset = False
                    st.rerun()
            with col_no:
                if st.button("Cancel", type="secondary", use_container_width=True):
                    st.session_state.confirm_reset = False
                    st.rerun()

    # --- PROGRESS DISPLAY ---
    if st.session_state.pipeline_running:
        completed, total_files = st.session_state.pipeline_progress
        progress_val = (completed / total_files) if total_files > 0 else 0.0
        st.progress(progress_val, text=f"PROCESSING: {completed}/{total_files} files")
        with st.spinner("Pipeline running..."):
            time.sleep(0.5)
        st.rerun()
    elif st.session_state.pipeline_error:
        st.error(f"Pipeline error: {st.session_state.pipeline_error}")
    elif st.session_state.pipeline_summary is not None:
        s: JobSummary = st.session_state.pipeline_summary
        st.success(
            f"Pipeline complete — {s.total} files processed: "
            f"{s.passed} passed, {s.failed} failed, {s.errors} errors"
        )

    st.divider()

    if not results:
        st.markdown(
            "<p style='color:#888888; text-transform:uppercase; letter-spacing:0.1rem;'>"
            "Run the QC pipeline above to see results</p>",
            unsafe_allow_html=True,
        )
        return

    import pandas as pd

    df = pd.DataFrame(results)

    # --- SEARCH & FILTER ---
    search_query = st.text_input("Search Filename", "")

    with st.expander("Filter By", expanded=False):
        col_m1, col_m2, col_m3 = st.columns(3)
        with col_m1:
            all_statuses = sorted(df["status"].unique().tolist())
            status_filter = st.multiselect("By Status", all_statuses, default=all_statuses)
        with col_m2:
            shot_list = sorted(s for s in df["shot"].unique().tolist() if s)
            shot_filter = st.multiselect("By Shot", shot_list)
        with col_m3:
            uv_list = sorted(u for u in df["uv_area"].unique().tolist() if u)
            uv_filter = st.multiselect("By UV Area", uv_list)

    mask = (
        df["filename"].str.contains(search_query, case=False, na=False)
        & df["status"].isin(status_filter)
    )
    if shot_filter:
        mask = mask & df["shot"].isin(shot_filter)
    if uv_filter:
        mask = mask & df["uv_area"].isin(uv_filter)

    filtered_df = df[mask].reset_index(drop=True)

    # --- RESULTS TABLE ---
    display_cols = ["status", "filename", "shot", "uv_area", "actual_res", "duration", "checked_on", "airtable_synced"]
    col_labels = {
        "status": "Status",
        "filename": "Filename",
        "shot": "Shot",
        "uv_area": "UV",
        "actual_res": "Res",
        "duration": "Duration",
        "checked_on": "Checked On",
        "airtable_synced": "Synced",
    }
    display_df = filtered_df[display_cols].rename(columns=col_labels)

    event = st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
    )

    # --- EXPORT ---
    with st.expander("Export", expanded=False):
        from core.reporter import to_csv, to_html

        filtered_records = filtered_df.to_dict("records")

        col_exp1, col_exp2 = st.columns(2)
        with col_exp1:
            csv_data = to_csv(filtered_records)
            st.download_button(
                label="Download CSV",
                data=csv_data,
                file_name="qc_results.csv",
                mime="text/csv",
                use_container_width=True,
            )
        with col_exp2:
            html_data = to_html(filtered_records, project="QC Report")
            st.download_button(
                label="Download HTML Report",
                data=html_data,
                file_name="qc_report.html",
                mime="text/html",
                use_container_width=True,
            )

    st.divider()

    # --- DETAIL PANEL ---
    selected_indices = event.get("selection", {}).get("rows", [])
    if not selected_indices:
        st.markdown(
            "<p style='color:#888888; text-transform:uppercase; letter-spacing:0.1rem;'>"
            "Select a row for details</p>",
            unsafe_allow_html=True,
        )
        return

    selected_row = filtered_df.iloc[selected_indices[0]]
    result_id: str = selected_row["_id"]
    filename: str = selected_row["filename"]
    current_status: str = selected_row["status"].lower()

    st.subheader(f"Details // {filename}")

    col_det1, col_det2, col_det3 = st.columns(3)

    with col_det1:
        st.markdown("### QC Info")
        _status_colors = {
            "pass": "#22c55e",
            "fail": "#ef4444",
            "error": "#f97316",
            "overridden": "#eab308",
            "skipped": "#6b7280",
        }
        color = _status_colors.get(current_status, "#ffffff")
        st.markdown(
            f"**STATUS:** <span style='color:{color}; font-weight:bold;'>{current_status.upper()}</span>",
            unsafe_allow_html=True,
        )
        st.write(f"**DURATION:** {selected_row.get('duration', 'N/A')}s")
        st.write(f"**CHECKED:** {selected_row.get('checked_on', 'N/A')}")
        synced = selected_row.get("airtable_synced", False)
        st.write(f"**AIRTABLE SYNCED:** {'Yes' if synced else 'No'}")

        if current_status == "fail":
            if st.button("Override & Route", type="primary", use_container_width=True, key="btn_override"):
                ok, msg = override_file(result_id, filename)
                if ok:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)
        elif current_status == "overridden":
            if st.button("Undo Override", type="secondary", use_container_width=True, key="btn_unroute"):
                ok, msg = unroute_file(result_id, filename)
                if ok:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)

    with col_det2:
        st.markdown("### Metadata")
        meta_row = selected_row
        st.write(f"**SHOT:** {meta_row.get('shot', 'N/A') or 'N/A'}")
        st.write(f"**UV:** {meta_row.get('uv_area', 'N/A') or 'N/A'}")
        st.write(f"**RES:** {meta_row.get('actual_res', 'N/A') or 'N/A'}")
        st.write(f"**PATH:**")
        st.code(meta_row.get("rel_path", "N/A"))

    with col_det3:
        st.markdown("### Checks")
        checks = _load_checks_for_result(result_id)
        if not checks:
            st.success("NO CHECK DATA FOUND")
        else:
            errors = [c for c in checks if not c["passed"] and c["severity"] == "error"]
            warnings = [c for c in checks if not c["passed"] and c["severity"] == "warning"]
            infos = [c for c in checks if c["passed"] or c["severity"] == "info"]

            if errors:
                st.error("ERRORS DETECTED")
                for c in errors:
                    st.write(f"- [{c['checker']}] {c['message']}")
            if warnings:
                st.warning("WARNINGS")
                for c in warnings:
                    st.write(f"- [{c['checker']}] {c['message']}")
            if not errors and not warnings:
                st.success("ALL CHECKS PASSED")
            elif infos and not errors:
                for c in infos:
                    if c["severity"] == "info":
                        st.info(f"[{c['checker']}] {c['message']}")


if __name__ == "__main__":
    main()
