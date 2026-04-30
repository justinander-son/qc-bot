🎬 DAILIES QC PIPELINE - SETUP & USAGE GUIDE
==========================================

This pipeline is a modular, high-performance tool for validating and organizing 
animation/VFX dailies. It uses FFmpeg for technical analysis and Streamlit for 
a web-based management dashboard.

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
2. PORTING TO A NEW PROJECT
---
Everything required to customize the tool lives in 'config.py'. 

To move to a new show:
1. Update SOURCE_DIR and APPROVED_DIR paths.
2. Update FILENAME_REGEX to match your show's naming convention.
3. Edit parse_metadata() to map your regex groups to meaningful keys.
4. Edit get_routing_path() to define your desired folder structure.
5. Update ALLOWED_RESOLUTIONS and TARGET_FPS to match show delivery specs.

---
3. USAGE
---
A) THE DASHBOARD (Recommended)
   Run the following command to launch the web interface:
   ./.venv/bin/streamlit run dashboard.py
   
   From here you can:
   - Start the QC Engine.
   - View detailed PASS/FAIL logs.
   - Manually OVERRIDE failures and route files.
   - View real-time technical metadata.

B) THE ENGINE (Terminal Only)
   Run the following command to process files without the dashboard:
   ./.venv/bin/python main.py

---
4. PROJECT STRUCTURE
---
- config.py      : THE SINGLE SOURCE OF TRUTH. Logic, paths, and specs.
- main.py        : The parallel processing engine.
- dashboard.py   : The Streamlit web interface.
- database.py    : Thread-safe JSON database management.
- checkers/      : Individual QC logic (Metadata and FFmpeg content checks).
- requirements.txt: List of required Python packages.

---
5. DATABASE RESET
---
If you need to re-analyze all files from scratch, click 'Reset Database' in 
the dashboard or delete 'qc_database.json' manually.
