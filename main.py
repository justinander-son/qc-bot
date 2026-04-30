import shutil
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn

import config
import database
from checkers.metadata import run_metadata_qc
from checkers.content import run_content_qc

console = Console()

def process_single_file(file_path):
    """Function to process a single file, intended for parallel execution."""
    if not file_path.is_file() or file_path.name.startswith("."):
        return None

    # Check if file is in an excluded directory
    if config.is_path_excluded(file_path):
        return {"filename": file_path.name, "skipped": True, "reason": "Excluded folder"}

    if database.has_file_passed(config.DATABASE_FILE, file_path.name):
        return {"filename": file_path.name, "skipped": True, "reason": "Already passed"}

    # 1. Run Phase 1: Metadata & Filename Validation
    passed, errors, warnings, duration_str, actual_res = run_metadata_qc(file_path)

    # 2. Extract Data using Centralized Logic
    meta = config.parse_metadata(file_path.name)
    
    # Store relative path for troubleshooting
    rel_path = str(file_path.relative_to(config.SOURCE_DIR))
    
    if meta:
        meta["actual_res"] = actual_res
        meta["rel_path"] = rel_path
    else:
        meta = {"actual_res": actual_res, "rel_path": rel_path}

    try:
        total_duration = float(duration_str)
    except:
        total_duration = 0.0

    # 3. Run Phase 2: Content (Skip for JPG and PNG)
    is_image = file_path.name.lower().endswith((".jpg", ".png"))
    if passed and not is_image:
        content_passed, content_errors = run_content_qc(file_path, total_duration)
        passed = passed and content_passed
        errors.extend(content_errors)

    # 4. Save Results
    database.log_result(config.DATABASE_FILE, file_path.name, passed, 
                       str(total_duration), errors, warnings, meta=meta)

    # 5. Handle Routing using Centralized Logic
    dest_path_str = "N/A"
    if passed:
        dest_path = config.get_routing_path(file_path.name)
        if dest_path:
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file_path, dest_path)
            dest_path_str = str(dest_path.relative_to(config.APPROVED_DIR))

    return {
        "filename": file_path.name,
        "passed": passed,
        "skipped": False,
        "errors": errors,
        "warnings": warnings,
        "dest": dest_path_str
    }

def main():
    console.print("\n[bold cyan]🎬 Starting Parallel Dailies QC Pipeline...[/bold cyan]\n")

    config.SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    config.APPROVED_DIR.mkdir(parents=True, exist_ok=True)

    all_files = [f for f in config.SOURCE_DIR.rglob('*') if f.is_file() and not f.name.startswith(".")]
    
    if not all_files:
        console.print("[bold yellow]No files found in source directory.[/bold yellow]")
        print(">> PROGRESS: 100")
        return

    results = []
    total_count = len(all_files)
    processed_count = 0
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        console=console
    ) as progress:
        
        task = progress.add_task("[cyan]Processing files...", total=total_count)
        
        with ThreadPoolExecutor(max_workers=config.NUM_WORKERS) as executor:
            futures = [executor.submit(process_single_file, f) for f in all_files]
            
            for future in futures:
                res = future.result()
                processed_count += 1
                
                # Print machine-readable progress for Streamlit
                progress_pct = int((processed_count / total_count) * 100)
                print(f">> PROGRESS: {progress_pct}")
                
                if res:
                    results.append(res)
                    if res.get("skipped"):
                        if res.get("reason") != "Excluded folder":
                            progress.console.print(f"[dim]⏩ Skipped: {res['filename']} ({res.get('reason')})[/dim]")
                    elif res.get("passed"):
                        progress.console.print(f"[bold green]✅ PASS:[/bold green] {res['filename']} -> {res['dest']}")
                    else:
                        progress.console.print(f"[bold red]❌ FAIL:[/bold red] {res['filename']}")
                
                progress.update(task, advance=1)

    # Summary Report
    files_analyzed = [r for r in results if not r.get("skipped")]
    if files_analyzed:
        report_lines = ["🎬 DAILIES QC REPORT", "=" * 30, ""]
        for r in results:
            if r.get("skipped"): continue
            report_lines.append(f"FILE: {r['filename']}")
            report_lines.append(f"STATUS: {'PASS' if r['passed'] else 'FAIL'}")
            for err in r['errors']: report_lines.append(f"  - ERROR: {err}")
            for warn in r['warnings']: report_lines.append(f"  - WARNING: {warn}")
            report_lines.append("-" * 30)
            
        with open("QC_Report.txt", "w", encoding="utf-8") as f:
            f.write("\n".join(report_lines))
        console.print(f"\n[bold cyan]Analysis complete. Report saved to QC_Report.txt[/bold cyan]")
    else:
        console.print("\n[bold yellow]Everything is up to date. No new files analyzed.[/bold yellow]")

if __name__ == "__main__":
    main()
