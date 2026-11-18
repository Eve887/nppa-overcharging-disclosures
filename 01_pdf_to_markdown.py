"""
01_pdf_to_markdown.py
-----------------------
Turns every PDF downloaded by the NPPA crawler into a clean Markdown (.md) file.

What it does, in order:
  1. Finds every PDF inside the input folder (and its sub-folders).
  2. Skips exact duplicate files (same content = same SHA-256 fingerprint).
  3. For each page:
       - if the page has real text  -> pulls the text out
         (add --tables to try turning tables into Markdown tables; on NPPA's
          grid-style sheets this can split words, so it is OFF by default)
       - if the page is a scan/image -> reads the text with OCR (Tesseract, English + Hindi)
  4. Cleans the text (removes junk characters and extra blank lines).
  5. Guesses what kind of document it is (overcharging list, minutes, price sheet...)
     and saves the .md file into a matching folder.
  6. Writes INDEX.md and index.csv listing every file, plus errors.csv for any failures.

It is safe to stop and restart: files already converted are skipped.

Example (PowerShell):
  python 01_pdf_to_markdown.py --input "G:\\SANSK\\NPPA_Crawler\\downloads\\phase_10" --output "G:\\SANSK\\NPPA_Crawler\\markdown"

Low-power example (easy on CPU and battery):
  python 01_pdf_to_markdown.py --input "..." --output "..." --gentle --only-when-charging
"""

import argparse
import csv
import hashlib
import os
import re
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import pymupdf  # reads PDFs (pip package name: pymupdf)

try:
    import pymupdf4llm  # turns PDF pages into Markdown, including tables
except ImportError:
    pymupdf4llm = None

try:
    import pytesseract  # talks to the Tesseract OCR program
    from PIL import Image
except ImportError:
    pytesseract = None


# ----------------------------------------------------------------------------
# Settings you may want to change
# ----------------------------------------------------------------------------
MIN_TEXT_CHARS = 25   # a page with fewer real characters than this is treated as a scan
OCR_DPI = 300         # image sharpness for OCR; higher = better but slower (--gentle uses 200)
DEFAULT_TESSERACT = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# Document groups. The first rule that matches wins.
# Each rule: (folder name, words to look for in the file name, words to look for in the text)
GROUP_RULES = [
    ("01_overcharging_lists",       r"overcharg",                     r"status of overcharging|overcharging cases|summary of overcharging|complaints .{0,40}overcharging"),
    ("03_mdc_minutes",              r"mdc|multidisciplinary",         r"multidisciplinary committee"),
    ("02_authority_minutes",        r"minute|authority",              r"minutes of the .{0,40}meeting of (the )?authority|meeting of authority|discussions of the authority|meeting of nppa"),
    ("05_price_calculation_sheets", r"sheet|computation|working",     r"computa?tation of (ceiling|retail) price|computation of (ceiling|retail) price"),
    ("04_gazette_price_orders",     r"^(so)?\d{3,4}e|gazette|notification", r"gazette of india|in exercise of the powers conferred"),
    ("06_price_approval_status",    r"pending|website-data|status-as-on", r"pending (list|applications)|form[- ]i\b"),
    ("07_discontinuation_lists",    r"discontinu",                    r"discontinuation"),
    ("08_newsletters",              r"newsletter",                    r"newsletter"),
    ("09_pmru_dashboards",          r"pmru|dashboard",                r"price monitoring and resource unit"),
    ("10_office_orders_admin",      r"\bom\b|office-order|circular|adobe-scan", r"office memorandum|office order|establishment|estt|circular|last date for receipt|recruitment|consultants?"),
]
OTHER_GROUP = "99_other"


# ----------------------------------------------------------------------------
# Small helper functions
# ----------------------------------------------------------------------------
def file_fingerprint(path):
    """SHA-256 of the file's bytes. Two files with the same fingerprint are identical."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def set_low_priority():
    """Ask Windows (or Linux/Mac) to run this program only when the CPU is free."""
    try:
        if sys.platform.startswith("win"):
            import ctypes
            BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
            handle = ctypes.windll.kernel32.GetCurrentProcess()
            ctypes.windll.kernel32.SetPriorityClass(handle, BELOW_NORMAL_PRIORITY_CLASS)
        else:
            os.nice(10)
    except Exception:
        pass


def wait_for_charger():
    """If the laptop is on battery, wait here until it is plugged in again."""
    try:
        import psutil
    except ImportError:
        return
    battery = psutil.sensors_battery()
    if battery is None or battery.power_plugged:
        return
    print("On battery -> paused. Plug in the charger to continue (checking every 60 seconds)...")
    while True:
        time.sleep(60)
        battery = psutil.sensors_battery()
        if battery is None or battery.power_plugged:
            print("Charger connected -> continuing.")
            return


def safe_name(text, limit=80):
    """Make a short file name that Windows accepts (no \\ / : * ? " < > |)."""
    text = re.sub(r'[\\/:*?"<>|]+', "_", text)
    text = re.sub(r"\s+", "_", text).strip("._")
    return text[:limit] or "file"


def clean_text(text):
    """Remove junk so the Markdown is easy to read."""
    text = text.replace("\x00", "").replace("\r", "")
    text = re.sub(r"\(cid:\d+\)", "", text)          # broken font codes
    text = re.sub(r"[ \t]+\n", "\n", text)           # spaces at line ends
    text = re.sub(r"[ \t]{3,}", "  ", text)          # long runs of spaces
    text = re.sub(r"\n{3,}", "\n\n", text)           # more than one blank line
    return text.strip()


def guess_group(file_name, first_text):
    """Decide which folder a document belongs in: text first, then file name."""
    name = file_name.lower()
    text = first_text.lower()
    for folder, _name_rule, text_rule in GROUP_RULES:
        if re.search(text_rule, text):
            return folder
    for folder, name_rule, _text_rule in GROUP_RULES:
        if re.search(name_rule, name):
            return folder
    return OTHER_GROUP


def page_to_markdown(doc, page_number, use_tables):
    """Text page -> text. With use_tables, tries Markdown tables first."""
    if use_tables and pymupdf4llm is not None:
        try:
            try:
                md = pymupdf4llm.to_markdown(doc, pages=[page_number], use_ocr=False, show_progress=False)
            except TypeError:  # older/newer versions accept different options
                md = pymupdf4llm.to_markdown(doc, pages=[page_number])
            if md and md.strip():
                return md
        except Exception:
            pass
    return doc[page_number].get_text("text", sort=True)   # sort=True keeps reading order


def ocr_page(page, language, dpi):
    """Scanned page -> picture -> OCR text."""
    pix = page.get_pixmap(dpi=dpi)
    image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples) if pix.n < 4 \
        else Image.frombytes("RGBA", (pix.width, pix.height), pix.samples).convert("RGB")
    return pytesseract.image_to_string(image, lang=language)


# ----------------------------------------------------------------------------
# The main job for ONE PDF (runs in a worker process)
# ----------------------------------------------------------------------------
def convert_one(pdf_path, sha, out_root, ocr_language, tesseract_cmd, use_tables=False,
                skip_ocr=False, dpi=OCR_DPI, low_priority=False):
    if low_priority:
        set_low_priority()
    if pytesseract is not None and tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

    started = time.time()
    row = {"source_file": str(pdf_path), "sha256": sha, "group": "", "md_file": "",
           "pages": 0, "text_pages": 0, "ocr_pages": 0, "ocr_skipped": 0, "empty_pages": 0,
           "characters": 0, "seconds": 0, "status": "ok", "error": ""}
    try:
        doc = pymupdf.open(pdf_path)
        if doc.needs_pass:
            raise RuntimeError("PDF is password-protected")
        row["pages"] = doc.page_count

        page_blocks = []
        plain_for_grouping = []   # plain text of the first pages, used to guess the group
        for i in range(doc.page_count):
            page = doc[i]
            raw = page.get_text("text")
            if len(raw.strip()) >= MIN_TEXT_CHARS:
                body = page_to_markdown(doc, i, use_tables)
                method = "text"
                row["text_pages"] += 1
            elif skip_ocr:
                body = ""
                method = "OCR skipped for now (run again without --no-ocr)"
                row["ocr_skipped"] += 1
            elif pytesseract is not None:
                body = ocr_page(page, ocr_language, dpi)
                method = "OCR"
                row["ocr_pages"] += 1
            else:
                body = ""
                method = "no text (OCR not installed)"
            body = clean_text(body)
            if i < 3:
                plain_for_grouping.append(raw if method == "text" else body)
            if not body:
                row["empty_pages"] += 1
                body = "_(no readable text on this page)_"
            page_blocks.append(f"## Page {i + 1}  \n<sub>method: {method}</sub>\n\n{body}\n")
        doc.close()

        all_text = "\n".join(page_blocks)
        row["characters"] = len(all_text)
        group = guess_group(pdf_path.name, re.sub(r"\s+", " ", " ".join(plain_for_grouping))[:6000])
        row["group"] = group

        out_dir = Path(out_root) / group
        out_dir.mkdir(parents=True, exist_ok=True)
        md_path = out_dir / f"{sha[:10]}__{safe_name(pdf_path.stem)}.md"

        header = (
            f"# {pdf_path.stem}\n\n"
            f"| Field | Value |\n|---|---|\n"
            f"| Source file | `{pdf_path.name}` |\n"
            f"| Group (guessed) | {group} |\n"
            f"| Pages | {row['pages']} (text: {row['text_pages']}, OCR: {row['ocr_pages']}, empty: {row['empty_pages']}) |\n"
            f"| SHA-256 | `{sha}` |\n"
            f"| Converted on | {datetime.now():%Y-%m-%d %H:%M} |\n\n---\n\n"
        )
        md_path.write_text(header + all_text, encoding="utf-8")
        row["md_file"] = str(md_path)
        if row["ocr_skipped"]:
            row["status"] = "needs_ocr"   # not finished; the next normal run will redo it
    except Exception as e:
        row["status"] = "error"
        row["error"] = f"{type(e).__name__}: {e}"
    row["seconds"] = round(time.time() - started, 1)
    return row


# ----------------------------------------------------------------------------
# Index files
# ----------------------------------------------------------------------------
INDEX_FIELDS = ["source_file", "sha256", "group", "md_file", "pages", "text_pages",
                "ocr_pages", "ocr_skipped", "empty_pages", "characters", "seconds", "status", "error"]


def load_index(csv_path):
    rows = {}
    if csv_path.exists():
        with open(csv_path, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                rows[r["sha256"]] = r
    return rows


def save_index(out_root, rows, duplicates):
    out_root = Path(out_root)
    with open(out_root / "index.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=INDEX_FIELDS)
        w.writeheader()
        for r in sorted(rows.values(), key=lambda r: (r["group"], r["source_file"])):
            w.writerow({k: r.get(k, "") for k in INDEX_FIELDS})

    with open(out_root / "errors.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["source_file", "error"])
        w.writeheader()
        for r in rows.values():
            if r["status"] == "error":
                w.writerow({"source_file": r["source_file"], "error": r["error"]})

    with open(out_root / "duplicates.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["duplicate_file", "same_content_as"])
        w.writerows(duplicates)

    # INDEX.md: one section per group, one line per document, with links
    lines = ["# NPPA documents – Markdown index", "",
             f"Updated: {datetime.now():%Y-%m-%d %H:%M}", ""]
    groups = {}
    for r in rows.values():
        if r["status"] in ("ok", "needs_ocr"):
            groups.setdefault(r["group"], []).append(r)
    lines.append("| Group | Documents | Pages | OCR pages |")
    lines.append("|---|---|---|---|")
    for g in sorted(groups):
        rs = groups[g]
        lines.append(f"| {g} | {len(rs)} | {sum(int(r['pages']) for r in rs)} | {sum(int(r['ocr_pages']) for r in rs)} |")
    lines.append("")
    for g in sorted(groups):
        lines += [f"## {g}", "", "| Document | Pages | OCR pages |", "|---|---|---|"]
        for r in sorted(groups[g], key=lambda r: r["md_file"]):
            rel = Path(r["md_file"]).relative_to(out_root).as_posix()
            lines.append(f"| [{Path(r['source_file']).name}]({rel}) | {r['pages']} | {r['ocr_pages']} |")
        lines.append("")
    (out_root / "INDEX.md").write_text("\n".join(lines), encoding="utf-8")


# ----------------------------------------------------------------------------
# Start here
# ----------------------------------------------------------------------------
def main():
    p = argparse.ArgumentParser(description="Convert crawled NPPA PDFs into clean Markdown.")
    p.add_argument("--input", required=True, help="Folder with the downloaded PDFs")
    p.add_argument("--output", required=True, help="Folder where Markdown files will be saved")
    p.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1),
                   help="How many PDFs to process at the same time (default: CPU cores minus 1)")
    p.add_argument("--lang", default=None, help='OCR languages, e.g. "eng+hin" (default: auto)')
    p.add_argument("--tesseract", default=None, help="Full path to tesseract.exe if not found automatically")
    p.add_argument("--limit", type=int, default=0, help="Only do the first N PDFs (for a test run)")
    p.add_argument("--tables", action="store_true", help="Try to keep tables as Markdown tables (slower; may split words)")
    p.add_argument("--gentle", action="store_true",
                   help="Low-power mode: 1 PDF at a time, low priority, OCR on 1 CPU core, lighter OCR images, short rests")
    p.add_argument("--pause", type=float, default=None, help="Seconds to rest after each PDF (default 0; --gentle uses 2)")
    p.add_argument("--dpi", type=int, default=None, help="OCR image sharpness (default 300; --gentle uses 200)")
    p.add_argument("--no-ocr", action="store_true", help="Do only text pages now; scanned pages are left for a later run")
    p.add_argument("--only-when-charging", action="store_true",
                   help="Pause automatically when the laptop is on battery (needs: pip install psutil)")
    args = p.parse_args()

    # --- low-power settings ---
    workers = args.workers
    pause = args.pause if args.pause is not None else 0.0
    dpi = args.dpi or OCR_DPI
    if args.gentle:
        workers = 1
        pause = args.pause if args.pause is not None else 2.0
        dpi = args.dpi or 200
        set_low_priority()
    # Tesseract normally uses ALL CPU cores for one page. This limits it to 1 core.
    os.environ["OMP_THREAD_LIMIT"] = "1" if (args.gentle or workers > 1) else os.environ.get("OMP_THREAD_LIMIT", "")
    if not os.environ["OMP_THREAD_LIMIT"]:
        del os.environ["OMP_THREAD_LIMIT"]
    if args.only_when_charging:
        try:
            import psutil  # noqa: F401
        except ImportError:
            print("WARNING: --only-when-charging needs psutil. Run: python -m pip install psutil")
    print(f"Mode: workers={workers}, pause={pause}s, OCR dpi={dpi}, low priority={'yes' if args.gentle else 'no'}, OCR={'off' if args.no_ocr else 'on'}")

    in_root, out_root = Path(args.input), Path(args.output)
    out_root.mkdir(parents=True, exist_ok=True)

    # --- find Tesseract and choose OCR languages ---
    tesseract_cmd = args.tesseract or (DEFAULT_TESSERACT if Path(DEFAULT_TESSERACT).exists() else None)
    ocr_language = "eng"
    if pytesseract is None:
        print("WARNING: pytesseract not installed -> scanned pages will be left empty.")
    else:
        if tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
        try:
            available = pytesseract.get_languages(config="")
            ocr_language = args.lang or ("eng+hin" if "hin" in available else "eng")
            print(f"OCR ready. Languages: {ocr_language}")
        except Exception:
            print("WARNING: Tesseract program not found -> scanned pages will be left empty.")
            print("         Install it, or pass --tesseract \"C:\\path\\to\\tesseract.exe\"")
            tesseract_cmd = None
            globals()["pytesseract"] = None
    if args.tables and pymupdf4llm is None:
        print("NOTE: pymupdf4llm not installed -> plain text only, tables will not be Markdown tables.")

    # --- list PDFs and skip duplicates / already-done files ---
    pdfs = sorted(q for q in in_root.rglob("*") if q.suffix.lower() == ".pdf" and q.is_file())
    if args.limit:
        pdfs = pdfs[: args.limit]
    print(f"Found {len(pdfs)} PDF files. Checking for duplicates...")

    rows = load_index(out_root / "index.csv")
    seen, todo, duplicates = {}, [], []
    for q in pdfs:
        sha = file_fingerprint(q)
        if sha in seen:
            duplicates.append([str(q), str(seen[sha])])
            continue
        seen[sha] = q
        done = rows.get(sha)
        if done and done["status"] == "ok" and Path(done["md_file"]).exists():
            continue
        todo.append((q, sha))
    print(f"Duplicates skipped: {len(duplicates)}. Already done: {len(seen) - len(todo)}. To convert now: {len(todo)}")

    # --- convert (one at a time, or several at once) ---
    started = time.time()
    ocr_cmd = tesseract_cmd if pytesseract else None
    extra = dict(skip_ocr=args.no_ocr, dpi=dpi, low_priority=args.gentle)

    def results():
        if workers == 1:   # one at a time, in this same program: lightest on the CPU
            for q, sha in todo:
                if args.only_when_charging:
                    wait_for_charger()
                yield convert_one(q, sha, out_root, ocr_language, ocr_cmd, args.tables, **extra)
                if pause:
                    time.sleep(pause)
        else:
            with ProcessPoolExecutor(max_workers=workers) as pool:
                futures = [pool.submit(convert_one, q, sha, out_root, ocr_language, ocr_cmd, args.tables, **extra)
                           for q, sha in todo]
                for fut in as_completed(futures):
                    yield fut.result()

    for n, r in enumerate(results(), 1):
        rows[r["sha256"]] = r
        flag = {"ok": "OK ", "needs_ocr": "OCR-LATER", "error": "ERR"}[r["status"]]
        print(f"[{n}/{len(todo)}] {flag} {r['group'] or '-':28} pages={r['pages']:>3} ocr={r['ocr_pages']:>3}  {Path(r['source_file']).name[:70]}")
        if n % 25 == 0:          # save progress regularly, so a crash loses little
            save_index(out_root, rows, duplicates)
    save_index(out_root, rows, duplicates)

    ok = sum(1 for r in rows.values() if r["status"] == "ok")
    err = sum(1 for r in rows.values() if r["status"] == "error")
    later = sum(1 for r in rows.values() if r["status"] == "needs_ocr")
    print(f"\nFinished in {round((time.time() - started) / 60, 1)} min. Converted OK: {ok}. Errors: {err}. Waiting for OCR: {later}.")
    print(f"Open {out_root / 'INDEX.md'} to see everything.")


if __name__ == "__main__":   # needed on Windows when using several worker processes
    main()
