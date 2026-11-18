"""
STEP 05 – Search every annual report for NPPA / DPCO / overcharging text, so you only read
the pages that matter instead of 300-450 pages per company.

Input : data/annual_reports/*.pdf  and  *.htm
Output: data/output/disclosures/<SYMBOL>_<FY>.md        the matching passages, page by page, to read
        data/output/disclosure_snippets.csv             every match: page, keyword, text, amounts seen
        data/output/disclosure_search_summary.csv/.xlsx one row per report:
                                                        does it name NPPA? DPCO? an auditor key audit matter?
Run:  python 05_find_disclosures.py

IMPORTANT: "not found" means the search found no such words. It does not prove the
report is silent: the money may sit inside a general line such as
"Claims against the Company not acknowledged as debts". Always read the
contingent-liabilities note yourself for any company marked "not found".
"""
import html as htmllib
import re

import pandas as pd
import pymupdf

import config
from utils import save_excel

KEYWORDS = {
    "NPPA":           r"\bNPPA\b|National Pharmaceutical Pricing Authority",
    "DPCO":           r"\bDPCO\b|Drugs? ?\(?Prices? ?Control\)? ?Order|Drug Price Control",
    "overcharging":   r"over-?charg",
    "DPEA":           r"\bDPEA\b|Drug Prices? Equali[sz]ation Account",
    "pricing_demand": r"pricing[- ]related demand|price fixation|ceiling price|demand notice",
}
CONTEXT = 700   # characters of text shown before and after each match
AMOUNT = re.compile(r"(?:₹|Rs\.?|INR|`)\s?(\d[\d,]*(?:\.\d+)?)\s*(crores?|cr\.?|lakhs?|lacs?|millions?|mn|billions?)?", re.I)


def pages_of(path):
    """Return a list of (page_number, text). For HTML files, 'pages' are 6,000-character pieces."""
    if path.suffix.lower() == ".pdf":
        doc = pymupdf.open(path)
        out = [(i + 1, doc[i].get_text("text")) for i in range(doc.page_count)]
        doc.close()
        return out
    raw = path.read_text(encoding="utf-8", errors="ignore")
    raw = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw)
    text = htmllib.unescape(re.sub(r"<[^>]+>", " ", raw))
    text = re.sub(r"[ \t\xa0]+", " ", text)
    step = 6000
    return [(i // step + 1, text[i:i + step]) for i in range(0, len(text), step)]


def main():
    out_dir = config.OUTPUT / "disclosures"
    out_dir.mkdir(exist_ok=True)
    files = sorted(p for p in config.ANNUAL_REPORTS.iterdir() if p.suffix.lower() in (".pdf", ".htm", ".html"))
    print(f"Annual reports found: {len(files)}")
    snippets, summary = [], []
    for f in files:
        symbol, _, fy = f.stem.partition("_")
        try:
            pages = pages_of(f)
        except Exception as e:
            print(f"  ERROR {f.name}: {e}")
            continue
        hits = {k: set() for k in KEYWORDS}
        kam_pages, md = set(), [f"# {f.stem} – NPPA / DPCO passages\n",
                                "Read these passages, then fill in data/input/company_disclosures.csv.\n"]
        empty_pages = sum(1 for _, t in pages if len(t.strip()) < 30)
        for pno, text in pages:
            flat = re.sub(r"\s+", " ", text)
            found_here = []
            for key, rx in KEYWORDS.items():
                for m in re.finditer(rx, flat, re.I):
                    hits[key].add(pno)
                    found_here.append((key, m.start(), m.end()))
            if not found_here:
                continue
            if re.search(r"key audit matter", flat, re.I) and any(k in ("NPPA", "DPCO", "overcharging", "pricing_demand") for k, _, _ in found_here):
                kam_pages.add(pno)
            # merge overlapping passages on the same page
            found_here.sort(key=lambda x: x[1])
            windows = []
            for key, s, e in found_here:
                a, b = max(0, s - CONTEXT), min(len(flat), e + CONTEXT)
                if windows and a <= windows[-1][1]:
                    windows[-1][1] = max(windows[-1][1], b)
                    windows[-1][2].add(key)
                else:
                    windows.append([a, b, {key}])
            for a, b, keys in windows:
                passage = flat[a:b]
                amounts = "; ".join(f"{m.group(1)} {m.group(2) or ''}".strip() for m in AMOUNT.finditer(passage))
                snippets.append({"nse_symbol": symbol, "fy": fy, "page": pno, "keywords": ", ".join(sorted(keys)),
                                 "amounts_seen": amounts, "passage": passage})
                md.append(f"\n## Page {pno}  –  {', '.join(sorted(keys))}\n\n{passage}\n")
                if amounts:
                    md.append(f"\n**Amounts seen:** {amounts}\n")
        (out_dir / f"{f.stem}.md").write_text("\n".join(md), encoding="utf-8")
        row = {"nse_symbol": symbol, "fy": fy, "file": f.name, "pages": len(pages),
               "pages_without_text": empty_pages,
               **{f"mentions_{k}": "yes" if v else "NOT FOUND" for k, v in hits.items()},
               **{f"pages_{k}": ", ".join(map(str, sorted(v)[:30])) for k, v in hits.items()},
               "auditor_key_audit_matter_on_pricing": "yes" if kam_pages else "not found",
               "kam_pages": ", ".join(map(str, sorted(kam_pages)))}
        summary.append(row)
        print(f"  {f.stem:28} NPPA:{row['mentions_NPPA']:9} DPCO:{row['mentions_DPCO']:9} "
              f"KAM:{row['auditor_key_audit_matter_on_pricing']:9} passages={sum(1 for s in snippets if s['nse_symbol'] == symbol and s['fy'] == fy)}")
        if empty_pages > len(pages) * 0.3:
            print(f"     WARNING: {empty_pages} pages have no text (scanned?). Run step 01 OCR on this PDF first.")

    pd.DataFrame(snippets).to_csv(config.OUTPUT / "disclosure_snippets.csv", index=False, encoding="utf-8-sig")
    s = pd.DataFrame(summary)
    s.to_csv(config.OUTPUT / "disclosure_search_summary.csv", index=False, encoding="utf-8-sig")
    if len(s):
        save_excel({"Search summary": s}, config.OUTPUT / "disclosure_search_summary.xlsx")
    print(f"\nRead the passages in {out_dir}, then fill in data/input/company_disclosures.csv")


if __name__ == "__main__":
    main()
