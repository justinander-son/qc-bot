import streamlit as st
import pandas as pd
from pathlib import Path
import subprocess
import sys
import os
import shutil

# Local imports
import config
import database

# Set page config
st.set_page_config(page_title="Dailies QC", page_icon="🎬", layout="wide")

# Custom CSS for UI Overhaul
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

    /* Primary buttons (White background, Black text) */
    div.stButton > button[kind="primary"] {
        background-color: #FFFFFF !important;
        color: #000000 !important;
        border: 1px solid #FFFFFF !important;
    }

    div.stButton > button[kind="primary"]:hover {
        background-color: #CCCCCC !important;
        border-color: #CCCCCC !important;
    }

    /* Secondary buttons (Transparent, White border) */
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
    
    /* Input styling */
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

def load_data():
    return database.load_db(config.DATABASE_FILE)

def route_file(filename, strict=True):
    source_path = config.SOURCE_DIR / filename
    if not source_path.exists():
        matches = list(config.SOURCE_DIR.rglob(filename))
        if matches: source_path = matches[0]
        else: return False, f"Could not find source file {filename}"
    try:
        dest_path = config.get_routing_path(filename, strict=strict)
        if dest_path:
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, dest_path)
            return True, f"Routed to {dest_path.parent.relative_to(config.APPROVED_DIR)}"
        return False, "Failed to calculate target path"
    except Exception as e:
        return False, str(e)

def unroute_file(filename):
    try:
        dest_path = config.get_routing_path(filename, strict=False)
        if dest_path and dest_path.exists():
            os.remove(dest_path)
            return True, "Removed from Approved directory"
        return True, "File not found in Approved directory"
    except Exception as e:
        return False, str(e)

def main():
    st.title("QC Dashboard")
    data = load_data()
    
    if data:
        df_rows = []
        for filename, info in data.items():
            status = info.get("status", "pass" if info.get("passed") else "fail")
            status_map = {"pass": "PASS", "fail": "FAIL", "overridden": "OVERRIDDEN"}
            meta = info.get("meta", {})
            
            row = {
                "Filename": filename,
                "Status": status_map.get(status, "FAIL"),
                "Duration (s)": round(float(info.get("duration", 0)), 2),
                "Checked On": info.get("checked_on", ""),
                "raw_status": status,
                "Shot": meta.get("shot", "N/A"),
                "UV": meta.get("uv_area", "N/A"),
                "Path": meta.get("rel_path", "N/A")
            }
            df_rows.append(row)
        df = pd.DataFrame(df_rows)
        df["Checked On"] = pd.to_datetime(df["Checked On"])
        df = df.sort_values(by="Checked On", ascending=False)
        
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total", len(df))
        passed_over = len(df[df["raw_status"].isin(["pass", "overridden"])])
        col2.metric("Passed", passed_over)
        col3.metric("Failed", len(df[df["raw_status"] == "fail"]))
        pass_rate = (passed_over / len(df) * 100) if len(df) > 0 else 0
        col4.metric("Rate", f"{pass_rate:.0f}%")
    else:
        # Standardize empty state for better UI consistency
        st.markdown("<p style='color:#888888; text-transform:uppercase; letter-spacing:0.1rem;'>No data in database yet</p>", unsafe_allow_html=True)

    st.divider()
    
    # --- CONTROL PANEL ---
    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        if st.button("Start QC Processing", type="primary", use_container_width=True):
            with st.status("PIPELINE ACTIVE", expanded=True) as status:
                progress_bar = st.progress(0, text="INITIALIZING...")
                log_output = st.empty()
                full_log = ""
                process = subprocess.Popen(
                    [sys.executable, "main.py"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    universal_newlines=True
                )
                for line in iter(process.stdout.readline, ""):
                    if line.startswith(">> PROGRESS:"):
                        try:
                            pct = int(line.split(":")[1].strip())
                            progress_bar.progress(pct / 100, text=f"PROCESSING: {pct}%")
                        except: pass
                    else:
                        full_log += line
                        log_output.code(full_log)
                process.stdout.close()
                process.wait()
                status.update(label="PIPELINE COMPLETE", state="complete", expanded=False)
                st.success("PROCESSING FINISHED")
                st.rerun()
    with col_btn2:
        if st.button("Reset Database", type="secondary", use_container_width=True):
            if os.path.exists(config.DATABASE_FILE): os.remove(config.DATABASE_FILE)
            st.rerun()

    st.divider()
    if not data:
        st.markdown("<p style='color:#888888; text-transform:uppercase; letter-spacing:0.1rem;'>Run the QC pipeline above to see results</p>", unsafe_allow_html=True)
        return

    # --- FILTERS ---
    search_query = st.text_input("Search Filename", "")

    with st.expander("Filter By", expanded=False):
        col_m1, col_m2, col_m3 = st.columns(3)
        with col_m1:
            status_filter = st.multiselect("By Status", ["PASS", "FAIL", "OVERRIDDEN"], default=["PASS", "FAIL", "OVERRIDDEN"])
        with col_m2:
            shot_list = sorted(df["Shot"].unique().tolist())
            shot_filter = st.multiselect("By Shot", shot_list)
        with col_m3:
            path_query = st.text_input("By Source Path", "")

    # Apply all filters
    mask = (
        (df["Filename"].str.contains(search_query, case=False)) &
        (df["Status"].isin(status_filter)) &
        (df["Path"].str.contains(path_query, case=False))
    )
    if shot_filter:
        mask = mask & (df["Shot"].isin(shot_filter))

    filtered_df = df[mask]

    # --- DATA TABLE ---
    display_cols = ["Status", "Filename", "Shot", "UV", "Duration (s)", "Checked On"]
    event = st.dataframe(filtered_df[display_cols], use_container_width=True, hide_index=True, on_select="rerun", selection_mode="single-row")

    st.divider()
    
    # --- DETAILS ---
    selected_indices = event.get("selection", {}).get("rows", [])
    if selected_indices:
        selected_filename = filtered_df.iloc[selected_indices[0]]["Filename"]
        file_info = data[selected_filename]
        meta = file_info.get("meta", {})
        current_status = file_info.get("status", "pass" if file_info.get("passed") else "fail")
        
        st.subheader(f"Details // {selected_filename}")
        col_det1, col_det2, col_det3 = st.columns(3)
        with col_det1:
            st.markdown("### QC Info")
            color = "#00FF00" if current_status=="pass" else "#FFA500" if current_status=="overridden" else "#FF0000"
            label = "PASS" if current_status=="pass" else "OVERRIDDEN" if current_status=="overridden" else "FAIL"
            st.markdown(f"**STATUS:** <span style='color:{color}; font-weight:bold;'>{label}</span>", unsafe_allow_html=True)
            st.write(f"**DURATION:** {file_info.get('duration')}S")
            st.write(f"**CHECKED:** {file_info.get('checked_on')}")

            if current_status == "fail":
                if st.button("Override & Route", type="primary", use_container_width=True):
                    if route_file(selected_filename, strict=False)[0]:
                        database.log_result(config.DATABASE_FILE, selected_filename, True, file_info.get("duration"), file_info.get("errors"), file_info.get("warnings"), status="overridden", meta=meta)
                        st.rerun()
            elif current_status == "overridden":
                if st.button("Undo Override", type="secondary", use_container_width=True):
                    if unroute_file(selected_filename)[0]:
                        database.log_result(config.DATABASE_FILE, selected_filename, False, file_info.get("duration"), file_info.get("errors"), file_info.get("warnings"), status="fail", meta=meta)
                        st.rerun()
        with col_det2:
            st.markdown("### Metadata")
            st.write(f"**SHOT:** {meta.get('shot', 'N/A')}")
            st.write(f"**UV:** {meta.get('uv_area', 'N/A')}")
            st.write(f"**RES:** {meta.get('res_name', 'N/A')} ({meta.get('actual_res', 'N/A')})")
            st.write(f"**VER:** {meta.get('version', 'N/A')}")
            st.write(f"**PATH:**")
            st.code(meta.get('rel_path', 'N/A'))
            
        with col_det3:
            if file_info.get("errors"):
                st.error("ERRORS DETECTED")
                for error in file_info["errors"]: st.write(f"- {error}")
            elif file_info.get("warnings"):
                st.warning("WARNINGS")
                for warning in file_info["warnings"]: st.write(f"- {warning}")
            else:
                st.success("NO ISSUES FOUND")
    else:
        st.markdown("<p style='color:#888888; text-transform:uppercase; letter-spacing:0.1rem;'>Select a row for details</p>", unsafe_allow_html=True)

if __name__ == "__main__": main()
