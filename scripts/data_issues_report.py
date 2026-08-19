"""
data_issues_report.py  —  Task 4 helper.

Scans the three raw CSVs and programmatically flags data-quality problems, so
the written report in the README is backed by an automated pass rather than
just eyeballing. Prints a categorized list with the exact source rows.

Run:  python scripts/data_issues_report.py
"""

import csv
import os
import re
import sys
from collections import defaultdict, Counter

sys.path.insert(0, os.path.dirname(__file__))
from normalize import normalize_email, normalize_phone, normalize_name  # noqa: E402

RAW = os.path.join(os.path.dirname(__file__), "..", "data", "raw")

FILES = {
    "recruitment_gigs.csv": dict(id="gig_id", name="full_name", email="email",
                                 phone="phone", rate="pay_per_day", date="applied_on"),
    "cbnexus.csv": dict(id="user_id", name="name", email="email_address",
                        phone="contact_number", rate="hourly_usd", date="joined_date"),
    "internal_automations.csv": dict(id="emp_code", name=None, email="mail",
                                     phone="mobile", rate="rate_inr_hr", date="created"),
}


def rows(fname):
    with open(os.path.join(RAW, fname), encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_all():
    all_rows = []
    for fname, cols in FILES.items():
        for r in rows(fname):
            if cols["name"]:
                name = r[cols["name"]]
            else:
                name = f"{r.get('first_name','')} {r.get('last_name','')}".strip()
            all_rows.append({
                "file": fname, "id": r[cols["id"]], "name": name,
                "email": r[cols["email"]], "phone": r[cols["phone"]],
                "rate": r[cols["rate"]], "date": r[cols["date"]], "raw": r,
            })
    return all_rows


def main():
    data = load_all()
    findings = defaultdict(list)

    # 1. Exact duplicate rows within a file.
    for fname, cols in FILES.items():
        seen = {}
        for r in rows(fname):
            key = tuple(r.values())
            if key in seen:
                findings["Exact duplicate row"].append(f"{fname}: {r[cols['id']]} repeats an identical row")
            seen[key] = True

    # 2. Missing critical identifiers.
    for r in data:
        if not r["email"].strip() and not r["phone"].strip():
            findings["No email AND no phone (unusable)"].append(f"{r['file']} {r['id']} ({r['name'] or 'blank'})")
        elif not r["email"].strip():
            findings["Missing email"].append(f"{r['file']} {r['id']} ({r['name']})")

    # 3. Phone numbers that don't reduce to 10 digits.
    for r in data:
        if r["phone"].strip() and not normalize_phone(r["phone"]):
            findings["Un-parseable / wrong-length phone"].append(
                f"{r['file']} {r['id']}: '{r['phone']}'")

    # 4. Email typos (domain fixed by normalizer differs from raw).
    for r in data:
        raw = r["email"].strip().lower()
        norm = normalize_email(r["email"])
        if raw and norm and raw != norm:
            findings["Email domain typo (auto-corrected)"].append(
                f"{r['file']} {r['id']}: '{r['email']}' -> '{norm}'")

    # 5. Non-numeric or impossible rate values.
    for r in data:
        val = re.sub(r"[₹$,\s]", "", r["rate"])
        val = val.replace("INR", "").strip()
        if r["rate"].strip() and not re.fullmatch(r"-?\d+(\.\d+)?", val):
            findings["Non-numeric rate"].append(f"{r['file']} {r['id']}: rate='{r['rate']}'")
        elif re.fullmatch(r"-?\d+(\.\d+)?", val) and float(val) < 0:
            findings["Negative rate (impossible)"].append(f"{r['file']} {r['id']}: rate='{r['rate']}'")

    # 6. Inconsistent / impossible dates.
    for r in data:
        d = r["date"].strip()
        if d and re.search(r"20\d{2}", d):
            year = int(re.search(r"(20\d{2})", d).group(1))
            if year > 2026:
                findings["Impossible/future date"].append(f"{r['file']} {r['id']}: '{d}'")
    date_formats = set()
    for r in data:
        d = r["date"].strip()
        if not d:
            continue
        if re.fullmatch(r"\d{2}/\d{2}/\d{4}", d):
            date_formats.add("DD/MM/YYYY")
        elif re.fullmatch(r"\d{4}-\d{2}-\d{2}", d):
            date_formats.add("YYYY-MM-DD")
        elif re.fullmatch(r"\d{2}-[A-Za-z]{3}-\d{4}", d):
            date_formats.add("DD-Mon-YYYY")
        elif re.search(r"[A-Za-z]+ \d{1,2}, \d{4}", d):
            date_formats.add("Month DD, YYYY")
        else:
            date_formats.add(f"other('{d}')")
    if len(date_formats) > 1:
        findings["Inconsistent date formats across files"].append(", ".join(sorted(date_formats)))

    # 7. Whitespace / control-char noise in names.
    for r in data:
        if r["name"] != r["name"].strip() or "\t" in r["name"] or "  " in r["name"]:
            findings["Whitespace/tab noise in name"].append(f"{r['file']} {r['id']}: '{r['name']}'")

    # 8. Same email used by clearly different people (name+phone differ).
    by_email = defaultdict(list)
    for r in data:
        e = normalize_email(r["email"])
        if e:
            by_email[e].append(r)
    for e, rs in by_email.items():
        phones = {normalize_phone(x["phone"]) for x in rs if normalize_phone(x["phone"])}
        names = {frozenset(normalize_name(x["name"])[1]) for x in rs}
        if len(phones) > 1 and len(names) > 1:
            findings["One email shared by different people (kept separate)"].append(
                f"{e}: {[ (x['file'], x['id'], x['name']) for x in rs ]}")

    # 9. Cross-file identity drift (same person, different spelling/order).
    #    Detected via phone that appears under >1 distinct display name.
    by_phone = defaultdict(set)
    for r in data:
        p = normalize_phone(r["phone"])
        if p:
            by_phone[p].add(normalize_name(r["name"])[0])
    for p, names in by_phone.items():
        if len(names) > 1:
            findings["Same person, inconsistent name across files"].append(
                f"phone {p}: {sorted(names)}")

    # 10. Inconsistent skill delimiters across files.
    delims_by_file = defaultdict(set)
    for fname in FILES:
        for r in rows(fname):
            s = r.get("skills") or r.get("skillset") or r.get("tags") or ""
            if "|" in s:
                delims_by_file[fname].add("pipe |")
            elif ";" in s:
                delims_by_file[fname].add("semicolon ;")
            elif "," in s:
                delims_by_file[fname].add("comma ,")
    distinct = {d for ds in delims_by_file.values() for d in ds}
    if len(distinct) > 1:
        summary = "; ".join(f"{f}: {sorted(ds)}" for f, ds in delims_by_file.items())
        findings["Inconsistent skill delimiters across files"].append(summary)

    # ---- print ----
    print("=" * 70)
    print("DATA QUALITY REPORT  (auto-detected)")
    print("=" * 70)
    total = 0
    for category, items in findings.items():
        print(f"\n[{len(items)}] {category}")
        for it in items:
            print(f"    - {it}")
            total += 1
    print("\n" + "-" * 70)
    print(f"{total} individual issues across {len(findings)} categories.")


if __name__ == "__main__":
    main()
