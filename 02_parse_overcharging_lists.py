"""
STEP 02 – Turn every NPPA "Status of Overcharging Cases" PDF into ONE clean table.

Input : the overcharging PDFs your crawler downloaded (any file whose name contains "overcharg")
Output: data/output/overcharging_cases_all_lists.csv   – one row per company + drug + list date
        data/output/overcharging_list_summary.csv      – totals per list (to check against NPPA's own total)
        data/output/overcharging_rows_to_review.csv    – rows the script was not sure about

Run:  python 02_parse_overcharging_lists.py
      python 02_parse_overcharging_lists.py --files "path\\one.pdf" "path\\two.pdf"   (only some files)

How it works (simple version):
  1. Opens each PDF and finds the tables on every page (PyMuPDF's table finder).
  2. Reads the header row to learn which column is which (company, principal, interest, outstanding...).
  3. Reads every data row. Some NPPA cells hold TWO OR MORE cases squeezed together
     (e.g. "Okasa Pharma / Cipla Ltd" with "14756.58 13500.82"); these are split into separate rows.
  4. Converts lakh -> crore, finds the list date from the file name, and saves everything.
"""
import argparse
import re
from pathlib import Path

import pandas as pd
import pymupdf

import config
from utils import number_tokens, to_number

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], 1)}

# Which header words mean which column. Checked IN THIS ORDER (order matters:
# "Total (overcharged + interest)" must become 'total', not 'principal').
HEADER_RULES = [
    ("company",       r"name of (the )?(company|firm|manufacturer)|^company|company name"),
    ("formulation",   r"formulation|name of (the )?drug|product|brand"),
    ("penalty",       r"penalty"),
    ("interest_upto", r"date"),
    ("total",         r"total|along ?with interest|\+ ?interest"),
    ("outstanding",   r"outstanding|balance|to be recovered|due"),
    ("recovered",     r"recovered|deposited|realised|realized|amount paid"),
    ("interest",      r"interest"),
    ("principal",     r"overcharg|principal|amount"),
    ("status",        r"status|stage|remarks"),
    ("dpco",          r"^\s*dpco"),
    ("period",        r"period|year"),
    ("serial",        r"^s\.? ?no|^sl|^sr|serial"),
]
NUMERIC = ["principal", "interest", "total", "recovered", "outstanding"]
COMPANY_SPLIT = re.compile(r"(?<=Ltd\.)\s+|(?<=Ltd)\s+|(?<=Limited)\s+|(?<=LLP)\s+|(?<=Labs)\s+|(?<=Inc\.)\s+")


MONTH_RX = (r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|"
            r"sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)")


def _month_end(year, month):
    return (pd.Timestamp(year=year, month=month, day=1) + pd.offsets.MonthEnd(0)).strftime("%Y-%m-%d")


def find_date(text):
    """Find a 'data up to' date in a file name or in the first page of text."""
    n = text.lower().replace("_", "-")
    m = re.search(MONTH_RX + r"[-\s,.']*(20\d\d)", n)
    if m:
        return _month_end(int(m.group(2)), MONTHS_SHORT[m.group(1)[:3]])
    m = re.search(r"(\d{1,2})[.\-/](\d{1,2})[.\-/](20\d\d)", n)
    if m and 1 <= int(m.group(2)) <= 12:
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    m = re.search(r"(?<!\d)([0-3]\d)([01]\d)(20\d\d)(?!\d)", n)          # 31032019
    if m and 1 <= int(m.group(2)) <= 12:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    return ""


def list_date_from_text(first_page_text):
    """Look for 'upto March, 2019' / 'till 28.02.2017' / 'as on ...' in the PDF itself."""
    t = re.sub(r"\s+", " ", first_page_text.lower())
    m = re.search(r"(?:up ?to|till|as on|ending)\s*[:\-]?\s*(.{0,25})", t)
    return find_date(m.group(1)) if m else ""


def list_date_from_name(name):
    return find_date(name)


MONTHS_SHORT = {k[:3]: v for k, v in MONTHS.items()}


def map_header(cells):
    """Header cells -> {column_number: field_name}."""
    mapping, used = {}, set()
    for i, raw in enumerate(cells):
        text = re.sub(r"\s+", " ", str(raw or "")).strip().lower()
        if not text:
            continue
        squeezed = text.replace(" ", "")            # some PDFs lose the spaces: "nameofcompany"
        for field, rule in HEADER_RULES:
            loose = rule.replace(" ", r"\s*")      # same rule, but spaces optional
            if field not in used and (re.search(rule, text) or re.search(loose, squeezed)):
                mapping[i] = field
                used.add(field)
                break
    return mapping


def looks_like_header(cells):
    joined = " ".join(str(c or "") for c in cells).lower()
    return "company" in joined and ("outstanding" in joined or "overcharg" in joined or "recover" in joined)


def split_names(cell, n):
    """Split a cell that holds n company names (or n drug names)."""
    text = str(cell or "").strip()
    parts = [p.strip() for p in text.split("\n") if p.strip()]
    if len(parts) == n:
        return parts, True
    parts = [p for p in COMPANY_SPLIT.split(re.sub(r"\s+", " ", text)) if p]
    if len(parts) == n:
        return parts, True
    return [re.sub(r"\s+", " ", text)] * n, False


YEAR_CELL = re.compile(r"^((19|20)\d\d\s*)+$")
TOTAL_CELL = re.compile(r"^(grand\s+)?total\s*[:.]?$")


def _clean_text(s):
    s = re.sub(r"[^a-z0-9 ]", " ", str(s or "").lower())
    return re.sub(r"\s+", " ", s).strip()


def _clean_company(s):
    """Collapse a doubled name, e.g. 'Cipla Ltd Cipla Ltd.' -> 'cipla ltd' (some PDFs print a row twice)."""
    words = _clean_text(s).split()
    n = len(words)
    if n >= 2 and n % 2 == 0 and words[: n // 2] == words[n // 2 :]:
        return " ".join(words[: n // 2])
    return " ".join(words)


def _formulation_overlaps(a, b):
    """Same drug, allowing for a truncated/garbled copy (one name is a substring of the other)."""
    if not a or not b:
        return a == b
    return a == b or a in b or b in a


def drop_duplicate_cases(rows):
    """
    Some PDFs print the same case twice within one list (the row is duplicated on the page,
    or the same list was uploaded twice under different names). Within the same list_date,
    if a case has the same cleaned company name, the same principal/interest/total/outstanding
    at the PDF's OWN precision (lakh, not the coarser crore rounding - rounding to crore makes
    many small, genuinely different cases collide), and an overlapping drug name, keep only the
    first copy. Rows with no outstanding amount are never matched (nothing reliable to compare).
    Returns (kept_rows, dropped_rows).
    """
    seen, kept, dropped = {}, [], []
    for r in rows:
        out = r.get("outstanding_lakh")
        if out is None:
            kept.append(r)
            continue
        group_key = r.get("list_date") or ("FILE:" + r["source_file"])
        num_key = tuple(
            None if r.get(f + "_lakh") is None else round(r[f + "_lakh"], 2)
            for f in ("outstanding", "principal", "interest", "total")
        )
        key = (group_key, _clean_company(r["company_raw"]), num_key)
        cf = _clean_text(r.get("formulation", ""))
        bucket = seen.setdefault(key, [])
        match = next((b for b in bucket if _formulation_overlaps(b[1], cf)), None)
        if match is None:
            bucket.append((r, cf))
            kept.append(r)
        else:
            dropped.append(r)
    return kept, dropped


def parse_row(cells, mapping):
    """
    One table row -> list of case dicts (usually 1; more if NPPA merged several cases).

    The most reliable anchor in NPPA's lists is the DPCO column (it only holds years like
    1979 / 1987 / 1995 / 2013). Reading from it towards the left gives:
        Status, Outstanding, Recovered, Total (overcharged + interest)
    and the cells to its right give the Period. Company, drug, principal and interest are
    read from the header positions. If no DPCO cell is found, the header positions are used
    for everything.
    """
    cells = [str(c or "") for c in cells]
    get = lambda f: next((cells[i] for i, x in mapping.items() if x == f and i < len(cells)), "")
    filled = [i for i, c in enumerate(cells) if c.strip()]
    anchor = next((i for i in reversed(filled) if YEAR_CELL.match(cells[i].strip())), None)

    if anchor is not None:
        left = [i for i in filled if i < anchor]
        status_cell = cells[left[-1]] if left else ""
        numeric_left = [i for i in left[:-1] if number_tokens(cells[i]) and
                        len(number_tokens(cells[i])) == len(cells[i].split())]
        out_cell = cells[numeric_left[-1]] if len(numeric_left) >= 1 else ""
        rec_cell = cells[numeric_left[-2]] if len(numeric_left) >= 2 else ""
        tot_cell = cells[numeric_left[-3]] if len(numeric_left) >= 3 else ""
        dpco_cell = cells[anchor]
        period_cell = " ".join(cells[i] for i in filled if i > anchor)
    else:
        status_cell, out_cell, rec_cell, tot_cell = get("status"), get("outstanding"), get("recovered"), get("total")
        dpco_cell, period_cell = get("dpco"), get("period")

    outs = number_tokens(out_cell)
    if not outs:
        return []                                     # not a data row
    n = len(outs)
    companies, ok1 = split_names(get("company") or cells[0], n)
    drugs, _ = split_names(get("formulation") or (cells[1] if len(cells) > 1 else ""), n)
    principal_cell = get("principal")
    if not number_tokens(principal_cell):             # fallback: first numeric cell after the drug name
        principal_cell = next((cells[i] for i in filled if i >= 2 and number_tokens(cells[i])), "")
    nums = {"principal": number_tokens(principal_cell), "interest": number_tokens(get("interest")),
            "total": number_tokens(tot_cell), "recovered": number_tokens(rec_cell), "outstanding": outs}
    statuses = [x.strip() for x in re.split(r"\n|(?<=\S)\s+(?=Under |Recovered|Closed|Stay)", status_cell) if x.strip()]
    dpcos = re.findall(r"(?:19|20)\d\d", dpco_cell)
    rows = []
    for k in range(n):
        r = {"company_raw": companies[k], "formulation": drugs[k],
             "status": statuses[k] if len(statuses) == n else re.sub(r"\s+", " ", status_cell).strip(),
             "dpco": dpcos[k] if len(dpcos) == n else " ".join(dpcos),
             "interest_upto": " ".join(re.findall(r"\d{2}[-./]\d{2}[-./]\d{4}", " ".join(cells))),
             "period": re.sub(r"\s+", " ", period_cell).strip(),
             "cases_in_cell": n, "needs_review": ""}
        for f in NUMERIC:
            vals = nums[f]
            r[f + "_lakh"] = to_number(vals[k]) if len(vals) == n else None
        problems = []
        if n > 1 and not ok1:
            problems.append(f"{n} cases in one cell; company names could not be split")
        if r["outstanding_lakh"] is None:
            problems.append("outstanding not readable")
        if not r["company_raw"].strip() or r["company_raw"].strip().lower() in ("total", "grand total"):
            problems.append("no company name")
        if anchor is None:
            problems.append("no DPCO column found; columns taken from header")
        r["needs_review"] = "; ".join(problems)
        rows.append(r)
    return rows


def unit_of(doc):
    """Find whether amounts are in lakh or crore (default: lakh, as in NPPA's lists)."""
    first = " ".join(doc[i].get_text("text").lower() for i in range(min(2, doc.page_count)))
    if re.search(r"in\s*(rs\.?|₹)?\s*crore|\(rs\.? in crore", first):
        return "crore"
    return "lakh"


def _undouble(token):
    h = len(token) // 2
    return token[:h] if len(token) >= 2 and len(token) % 2 == 0 and token[:h] == token[h:] else token


def fix_doubled_row(cells):
    """
    Some NPPA PDFs print a row twice on top of itself, so the text reads
    'KiviKivi LabsLabs' and '35.9735.97'. If most longer words in the row are doubled,
    halve every word in that row. (Only whole doubled rows are changed, so a normal
    number like 2020 is never cut to 20.)
    """
    words = [w for c in cells for w in str(c).split() if len(w) >= 4]
    if not words:
        return cells
    doubled = sum(1 for w in words if _undouble(w) != w)
    if doubled / len(words) < 0.6:
        return cells
    return ["\n".join(" ".join(_undouble(w) for w in line.split()) for line in str(c).split("\n")) for c in cells]


def table_rows(page, table):
    """
    Read every cell's text straight from its position on the page.
    (PyMuPDF's quick table.extract() can drop spaces and split '192.01' into '19201' + '.'.)
    """
    rows = []
    try:
        for row in table.rows:
            rows.append(fix_doubled_row([page.get_text("text", clip=pymupdf.Rect(c)).strip() if c else "" for c in row.cells]))
        return rows
    except Exception:
        try:
            return table.extract()
        except Exception:
            return []


def parse_pdf(path):
    doc = pymupdf.open(path)
    unit = unit_of(doc)
    cases, totals, mapping, table_unit = [], [], None, unit
    for pno in range(doc.page_count):
        page = doc[pno]
        try:
            tables = page.find_tables().tables
        except Exception:
            tables = []
        for t in tables:
            data = table_rows(page, t)
            for cells in data:
                cells = [c if c is not None else "" for c in cells]
                if looks_like_header(cells):
                    mapping = map_header(cells)
                    head = " ".join(cells).lower()           # the unit printed in THIS table's header
                    table_unit = "lakh" if "lakh" in head else "crore" if "crore" in head else unit
                    continue
                if not mapping:
                    continue
                first_cell = re.sub(r"\s+", " ", str(cells[0] or "")).strip().lower()
                if TOTAL_CELL.match(first_cell):
                    # NOTE: NPPA's "Status of Overcharging Cases" PDFs checked so far (Mar 2017,
                    # Mar 2020, Mar 2026) print NO grand-total row at all - the table just ends.
                    # The old check here matched company names that merely START WITH "total"
                    # (e.g. "Total Healthcare / Biochem Pharmaceuticals"), which produced a wrong,
                    # near-zero "total". This stricter match (the whole first cell must just say
                    # "total"/"grand total") means totals stays empty for such files, and
                    # nppa_printed_total_crore is correctly left blank instead of wrong.
                    out_i = [i for i, f in mapping.items() if f == "outstanding"]
                    if out_i:
                        totals.append(to_number((number_tokens(cells[out_i[0]]) or [None])[0]))
                    continue
                for r in parse_row(cells, mapping):
                    r["page"] = pno + 1
                    r["unit_in_pdf"] = table_unit
                    cases.append(r)
    scanned = all(len(doc[i].get_text("text").strip()) < 25 for i in range(min(3, doc.page_count)))
    text_date = list_date_from_text(doc[0].get_text("text")) if doc.page_count else ""
    doc.close()
    return cases, unit, totals, scanned, text_date


def find_list_files():
    """
    Collect every likely overcharging list:
      - file names with 'overcharg', 'stmt-' or 'detailed-statement' / 'detailed-sheet'
      - every PDF that step 01 put in the group 01_overcharging_lists (read from its index.csv)
    Files that are not company lists (year-wise summaries, minutes) give 0 rows and are reported, which is fine.
    """
    found = {}
    if config.CRAWLER_DOWNLOADS.exists():
        for pat in ("*overcharg*.pdf", "*Overcharg*.pdf", "*stmt*.pdf", "*etailed*.pdf"):
            for f in config.CRAWLER_DOWNLOADS.rglob(pat):
                found[f.name.lower()] = f
    index = config.MARKDOWN_OUTPUT / "index.csv"
    if index.exists():
        idx = pd.read_csv(index, encoding="utf-8")
        for src in idx.loc[idx["group"] == "01_overcharging_lists", "source_file"]:
            f = Path(src)
            if f.exists():
                found[f.name.lower()] = f
        print(f"Also used step 01's index: {index}")
    skip = re.compile(r"year-?wise|yearwise|summary|minutes|mdc|memorandum|guideline", re.I)
    files = sorted(f for f in found.values() if not skip.search(f.name))
    skipped = len(found) - len(files)
    if skipped:
        print(f"Skipped {skipped} year-wise summaries / minutes / memos (not company-wise lists).")
    return files


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--files", nargs="*", help="Only these PDF files (default: all overcharging PDFs)")
    args = ap.parse_args()

    files = [Path(f) for f in args.files] if args.files else find_list_files()
    print(f"Overcharging PDFs to read: {len(files)}")
    all_rows, summary = [], []
    for f in files:
        try:
            cases, unit, totals, scanned, text_date = parse_pdf(f)
        except Exception as e:
            print(f"  ERROR  {f.name}: {e}")
            summary.append({"file": f.name, "list_date": list_date_from_name(f.name), "status": f"error: {e}"})
            continue
        name_date = list_date_from_name(f.name)
        date = text_date or name_date            # the date printed inside the PDF wins
        for r in cases:
            r["list_date"], r["source_file"] = date, f.name
            row_unit = r.get("unit_in_pdf") or unit
            factor = 1 if row_unit == "crore" else 0.01   # 1 lakh = 0.01 crore
            for col in NUMERIC:
                v = r.get(col + "_lakh")
                if row_unit == "crore":                   # keep the column names honest
                    r[col + "_lakh"] = None if v is None else v * 100
                r[col + "_crore"] = None if v is None else round(v * factor, 4)
        factor = 1 if unit == "crore" else 0.01
        all_rows += cases
        total_out = sum((r["outstanding_crore"] or 0) for r in cases)
        nppa_total = (totals[-1] * factor) if totals and totals[-1] is not None else None
        kind = "company-wise list" if cases else ("SCANNED - run step 01 OCR, then check by hand" if scanned else "no company table found (maybe a year-wise summary)")
        summary.append({"file": f.name, "list_date": date, "date_in_pdf": text_date, "date_in_file_name": name_date,
                        "unit_in_pdf": unit, "kind": kind,
                        "case_rows": len(cases), "rows_to_review": sum(1 for r in cases if r["needs_review"]),
                        "outstanding_total_crore_parsed": round(total_out, 2),
                        "nppa_printed_total_crore": round(nppa_total, 2) if nppa_total is not None else "",
                        "difference_crore": round(total_out - nppa_total, 2) if nppa_total is not None else "",
                        "status": "ok"})
        print(f"  {date or 'NO DATE':10}  rows={len(cases):5}  outstanding={total_out:10,.1f} cr  {kind:30}  {f.name[:60]}")

    # ---- one list per date: if NPPA uploaded the same list twice, keep the file with the most rows ----
    by_date = {}
    for srow in summary:
        if srow.get("case_rows") and srow.get("list_date"):
            best = by_date.get(srow["list_date"])
            if best is None or srow["case_rows"] > best["case_rows"]:
                by_date[srow["list_date"]] = srow
    keep = {srow["file"] for srow in by_date.values()}
    for srow in summary:
        if srow.get("case_rows") and srow.get("list_date") and srow["file"] not in keep:
            srow["status"] = "NOT USED: another file has the same date (kept: " + by_date[srow["list_date"]]["file"] + ")"
            print(f"  Same date twice -> not used: {srow['file'][:70]}")
    all_rows = [r for r in all_rows if r["source_file"] in keep or not r.get("list_date")]

    cols = ["list_date", "company_raw", "formulation", "principal_lakh", "interest_lakh", "interest_upto",
            "total_lakh", "recovered_lakh", "outstanding_lakh", "principal_crore", "interest_crore",
            "total_crore", "recovered_crore", "outstanding_crore", "status", "dpco", "period",
            "cases_in_cell", "needs_review", "page", "unit_in_pdf", "source_file"]

    all_rows, dup_rows = drop_duplicate_cases(all_rows)
    if dup_rows:
        pd.DataFrame(dup_rows, columns=cols).to_csv(
            config.OUTPUT / "overcharging_duplicates_removed.csv", index=False, encoding="utf-8-sig")
        dup_crore = round(sum((r["outstanding_crore"] or 0) for r in dup_rows), 2)
        print(f"Removed {len(dup_rows)} duplicate rows (same case counted twice within one list), "
              f"Rs{dup_crore} cr -> data/output/overcharging_duplicates_removed.csv")

    # The per-file totals above were computed BEFORE deduplication (dedup can only run once all
    # files are read, since the same case can repeat across files for an undated list). Recompute
    # each summary row's row count / outstanding total from the DEDUPED rows, and record what was
    # removed, so overcharging_list_summary.csv reflects the cleaned data.
    kept_by_file, removed_by_file = {}, {}
    for r in all_rows:
        b = kept_by_file.setdefault(r["source_file"], {"rows": 0, "out": 0.0, "review": 0})
        b["rows"] += 1
        b["out"] += r["outstanding_crore"] or 0
        b["review"] += 1 if r["needs_review"] else 0
    for r in dup_rows:
        b = removed_by_file.setdefault(r["source_file"], {"rows": 0, "out": 0.0})
        b["rows"] += 1
        b["out"] += r["outstanding_crore"] or 0
    for srow in summary:
        if not srow.get("case_rows"):
            continue
        kept = kept_by_file.get(srow["file"], {"rows": 0, "out": 0.0, "review": 0})
        removed = removed_by_file.get(srow["file"], {"rows": 0, "out": 0.0})
        srow["case_rows"] = kept["rows"]
        srow["rows_to_review"] = kept["review"]
        srow["outstanding_total_crore_parsed"] = round(kept["out"], 2)
        srow["duplicate_rows_removed"] = removed["rows"]
        srow["duplicate_crore_removed"] = round(removed["out"], 2)

    df = pd.DataFrame(all_rows, columns=cols)
    df.to_csv(config.OUTPUT / "overcharging_cases_all_lists.csv", index=False, encoding="utf-8-sig")
    df[df["needs_review"] != ""].to_csv(config.OUTPUT / "overcharging_rows_to_review.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(summary).sort_values("list_date").to_csv(config.OUTPUT / "overcharging_list_summary.csv", index=False, encoding="utf-8-sig")
    print(f"\nSaved {len(df)} case rows. Rows to review: {(df['needs_review'] != '').sum()}")
    print("CHECK: open overcharging_list_summary.csv and compare 'outstanding_total_crore_parsed'")
    print("       with NPPA's printed total (or with PIB / Parliament figures for that date).")


if __name__ == "__main__":
    main()
