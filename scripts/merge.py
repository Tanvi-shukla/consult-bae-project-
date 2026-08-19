"""
merge.py  —  Task 1: merge 3 messy CSVs into ONE clean SQLite database.
=======================================================================

Pipeline
--------
1. Load all three CSVs, mapping each system's odd column names to a common
   internal record shape and remembering the raw source values (provenance).
2. Normalize the identity fields (name / email / phone) with scripts/normalize.py.
3. Cluster records that refer to the same human using a union-find over these
   match rules (strongest first):

      RULE A (strong):  same valid 10-digit phone number.
      RULE B (medium):  same email AND overlapping name tokens
                        -- BUT blocked if both records have valid phones that
                        differ (guards against one email shared by two people).

4. Elect a canonical record per cluster and write:
      - person          : one clean row per real human
      - source_record   : every original row, linked to its person (nothing lost)
      - audio_submission: empty table the Task-3 app writes into.

Run:  python scripts/merge.py
Idempotent: it rebuilds the DB from scratch each run.
"""

import csv
import os
import sqlite3
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(__file__))
from normalize import (  # noqa: E402
    clean_text,
    normalize_email,
    normalize_phone,
    normalize_name,
    phone_is_valid,
    name_tokens_overlap,
)

BASE = os.path.join(os.path.dirname(__file__), "..")
RAW = os.path.join(BASE, "data", "raw")
DB_PATH = os.path.join(BASE, "data", "consultbae.db")


# ---------------------------------------------------------------------------
# 1. Load + map each system's columns into a common record shape.
# ---------------------------------------------------------------------------
def load_records():
    records = []

    def add(source, source_id, name, email, phone, city, skills, applied, rate, raw):
        records.append({
            "source": source,
            "source_id": source_id,
            "raw_name": name,
            "raw_email": email,
            "raw_phone": phone,
            "city": clean_text(city),
            "skills": clean_text(skills),
            "applied": clean_text(applied),
            "rate": clean_text(rate),
            "raw_row": raw,
        })

    # --- recruitment_gigs.csv ---
    with open(os.path.join(RAW, "recruitment_gigs.csv"), encoding="utf-8") as f:
        for r in csv.DictReader(f):
            add("recruitment_gigs", r["gig_id"], r["full_name"], r["email"],
                r["phone"], r["city"], r["skills"], r["applied_on"],
                r["pay_per_day"], dict(r))

    # --- cbnexus.csv ---
    with open(os.path.join(RAW, "cbnexus.csv"), encoding="utf-8") as f:
        for r in csv.DictReader(f):
            add("cbnexus", r["user_id"], r["name"], r["email_address"],
                r["contact_number"], r["location"], r["skillset"],
                r["joined_date"], r["hourly_usd"], dict(r))

    # --- internal_automations.csv (first/last split) ---
    with open(os.path.join(RAW, "internal_automations.csv"), encoding="utf-8") as f:
        for r in csv.DictReader(f):
            full = f"{r['first_name']} {r['last_name']}".strip()
            add("internal_automations", r["emp_code"], full, r["mail"],
                r["mobile"], r["region"], r["tags"], r["created"],
                r["rate_inr_hr"], dict(r))

    return records


# ---------------------------------------------------------------------------
# 2. Normalize each record's identity fields.
# ---------------------------------------------------------------------------
def normalize_records(records):
    kept, dropped = [], []
    for rec in records:
        rec["email"] = normalize_email(rec["raw_email"])
        rec["phone"] = normalize_phone(rec["raw_phone"])
        display, tokens = normalize_name(rec["raw_name"])
        rec["name"] = display
        rec["name_tokens"] = tokens

        # A row with no name, no email and no phone identifies nobody -> drop it,
        # but record why (Task 4).
        if not rec["name"] and not rec["email"] and not rec["phone"]:
            rec["drop_reason"] = "blank row: no name/email/phone"
            dropped.append(rec)
        else:
            kept.append(rec)
    return kept, dropped


# ---------------------------------------------------------------------------
# 3. Union-find clustering.
# ---------------------------------------------------------------------------
class UnionFind:
    def __init__(self, n):
        self.parent = list(range(n))

    def find(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def cluster(records):
    uf = UnionFind(len(records))
    decisions = []  # human-readable log of why merges happened / were blocked

    # RULE A: identical valid phone.
    by_phone = defaultdict(list)
    for i, r in enumerate(records):
        if r["phone"]:
            by_phone[r["phone"]].append(i)
    for phone, idxs in by_phone.items():
        for j in idxs[1:]:
            uf.union(idxs[0], j)
            decisions.append(
                f"MERGE (phone {phone}): '{records[idxs[0]]['name']}' "
                f"[{records[idxs[0]]['source']}] + '{records[j]['name']}' [{records[j]['source']}]")

    # RULE B: same email + name overlap, unless phones are both valid & differ.
    by_email = defaultdict(list)
    for i, r in enumerate(records):
        if r["email"]:
            by_email[r["email"]].append(i)
    for email, idxs in by_email.items():
        for a in range(len(idxs)):
            for b in range(a + 1, len(idxs)):
                ia, ib = idxs[a], idxs[b]
                ra, rb = records[ia], records[ib]
                shared = ra["name_tokens"] & rb["name_tokens"]
                # "Strong" name match = identical token sets or >=2 shared tokens.
                names_strong = (ra["name_tokens"] == rb["name_tokens"]
                                and bool(ra["name_tokens"])) or len(shared) >= 2
                phones_conflict = (
                    ra["phone"] and rb["phone"] and ra["phone"] != rb["phone"]
                )

                # Two different phones on one email: only a red flag when the
                # names are NOT a strong match. Strong name match => treat the
                # phone difference as a typo and merge anyway.
                if phones_conflict and not names_strong:
                    if uf.find(ia) != uf.find(ib):
                        decisions.append(
                            f"BLOCK  (email {email} shared by different phones "
                            f"{ra['phone']} vs {rb['phone']}, weak name match): kept "
                            f"'{ra['name']}' and '{rb['name']}' SEPARATE")
                    continue

                if shared:
                    if uf.find(ia) != uf.find(ib):
                        note = " despite phone mismatch (likely typo)" if phones_conflict else ""
                        decisions.append(
                            f"MERGE (email {email} + name overlap{note}): "
                            f"'{ra['name']}' [{ra['source']}] + '{rb['name']}' [{rb['source']}]")
                    uf.union(ia, ib)

    clusters = defaultdict(list)
    for i in range(len(records)):
        clusters[uf.find(i)].append(i)
    return list(clusters.values()), decisions


# ---------------------------------------------------------------------------
# 4. Elect a canonical record per cluster.
# ---------------------------------------------------------------------------
def canonical(records, idxs):
    members = [records[i] for i in idxs]

    def pick(field, valid=lambda v: bool(v)):
        # Prefer the most common non-empty value; tie-break by longest.
        counts = defaultdict(int)
        for m in members:
            if valid(m[field]):
                counts[m[field]] += 1
        if not counts:
            return ""
        return sorted(counts, key=lambda v: (counts[v], len(str(v))), reverse=True)[0]

    # Merge skills across all sources (split on , ; |).
    skills = set()
    import re
    for m in members:
        for tok in re.split(r"[,;|]", m["skills"]):
            tok = tok.strip().lower()
            if tok:
                skills.add(tok)

    return {
        "name": pick("name"),
        "email": pick("email"),
        "phone": pick("phone"),
        "city": pick("city", valid=lambda v: bool(v) and v.strip()),
        "skills": ", ".join(sorted(skills)),
        "sources": ",".join(sorted({m["source"] for m in members})),
        "record_count": len(members),
    }


# ---------------------------------------------------------------------------
# 5. Write the clean database.
# ---------------------------------------------------------------------------
SCHEMA = """
DROP TABLE IF EXISTS person;
DROP TABLE IF EXISTS source_record;
DROP TABLE IF EXISTS audio_submission;

CREATE TABLE person (
    person_id     INTEGER PRIMARY KEY,
    full_name     TEXT,
    email         TEXT,
    phone         TEXT,          -- normalized 10-digit
    city          TEXT,
    skills        TEXT,          -- merged, de-duplicated
    sources       TEXT,          -- which systems this person came from
    record_count  INTEGER        -- how many raw rows collapsed into this person
);

CREATE TABLE source_record (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id     INTEGER REFERENCES person(person_id),
    source_system TEXT,
    source_id     TEXT,
    raw_name      TEXT,
    raw_email     TEXT,
    raw_phone     TEXT,
    norm_email    TEXT,
    norm_phone    TEXT
);

CREATE TABLE audio_submission (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id      INTEGER REFERENCES person(person_id),
    name           TEXT,
    phone          TEXT,
    filename       TEXT,
    duration_sec   REAL,
    sample_rate_hz INTEGER,
    bitrate_kbps   INTEGER,
    loudness_dbfs  REAL,
    noise_estimate TEXT,
    created_at     TEXT
);

CREATE INDEX idx_person_email ON person(email);
CREATE INDEX idx_person_phone ON person(phone);
"""


def build_db(records, clusters):
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    cur = conn.cursor()

    for pid, idxs in enumerate(clusters, start=1):
        c = canonical(records, idxs)
        cur.execute(
            "INSERT INTO person (person_id, full_name, email, phone, city, skills, sources, record_count) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (pid, c["name"], c["email"], c["phone"], c["city"], c["skills"],
             c["sources"], c["record_count"]))
        for i in idxs:
            r = records[i]
            cur.execute(
                "INSERT INTO source_record (person_id, source_system, source_id, raw_name, "
                "raw_email, raw_phone, norm_email, norm_phone) VALUES (?,?,?,?,?,?,?,?)",
                (pid, r["source"], r["source_id"], r["raw_name"], r["raw_email"],
                 r["raw_phone"], r["email"], r["phone"]))
    conn.commit()
    conn.close()


def main():
    print("Loading raw CSVs...")
    records = load_records()
    print(f"  {len(records)} raw rows across 3 files")

    kept, dropped = normalize_records(records)
    print(f"  {len(dropped)} unusable rows dropped, {len(kept)} kept")

    clusters, decisions = cluster(kept)
    print(f"  {len(clusters)} unique people after matching\n")

    print("Merge decisions:")
    for d in decisions:
        print("  -", d)
    for d in dropped:
        print(f"  - DROP [{d['source']} {d['source_id']}]: {d['drop_reason']}")

    build_db(kept, clusters)
    print(f"\nDatabase written -> {os.path.relpath(DB_PATH, BASE)}")
    print(f"  {len(kept)} source rows -> {len(clusters)} people")


if __name__ == "__main__":
    main()
