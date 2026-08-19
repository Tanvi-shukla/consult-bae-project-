"""
generate_csvs.py
----------------
Creates three *intentionally messy* CSV files, each pretending to come from a
different ConsultBae system:

    data/raw/recruitment_gigs.csv   (the recruitment product)
    data/raw/cbnexus.csv            (CBNexus)
    data/raw/internal_automations.csv (an internal ops tool)

The same real person shows up in more than one file, but nothing lines up
cleanly: no shared ID, names in different cases / orders, phones in different
formats, emails with typos, inconsistent dates, currency symbols in rate
fields, duplicate rows, missing values, and a couple of genuinely ambiguous
conflicts. Every planted issue is catalogued in docs/PLANTED_ISSUES.md and in
the README data-issues report.

Run:  python scripts/generate_csvs.py
The output is deterministic (no randomness) so the graders see the same data.
"""

import csv
import os

RAW_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "raw")
os.makedirs(RAW_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# recruitment_gigs.csv  — system A
# Columns are lowercase_snake, phones as "+91-98765 43210", dates DD/MM/YYYY,
# skills comma-separated, pay in "₹/day".
# ---------------------------------------------------------------------------
recruitment_rows = [
    # header
    ["gig_id", "full_name", "email", "phone", "city", "skills", "applied_on", "pay_per_day"],

    # --- clean-ish anchors (these people also appear elsewhere) ---
    ["G-1001", "Aarav Sharma", "aarav.sharma@gmail.com", "+91-98765 43210", "Mumbai",
     "python, data cleaning, sql", "03/02/2024", "₹1500"],
    ["G-1002", "Priya Nair", "priya.nair@gmail.com", "9845012345", "Bengaluru",
     "react, node, web dev", "15/01/2024", "₹2000"],
    ["G-1003", "Mohammed Iqbal", "m.iqbal@outlook.com", "+91 99000 11223", "Hyderabad",
     "n8n, zapier, automation", "22/03/2024", "1800"],
    ["G-1004", "Sara D'Souza", "sara.dsouza@gmail.com", "098200 34567", "Mumbai",
     "excel, data entry", "01/04/2024", "₹1200"],

    # --- ISSUE: exact duplicate row (same gig submitted twice) ---
    ["G-1004", "Sara D'Souza", "sara.dsouza@gmail.com", "098200 34567", "Mumbai",
     "excel, data entry", "01/04/2024", "₹1200"],

    # --- ISSUE: name in "Last, First" order; email typo gmial.com ---
    ["G-1005", "Verma, Rohan", "rohan.verma@gmial.com", "+91-90000-55667", "Pune",
     "python; automation; scraping", "2024-02-20", "₹1600"],

    # --- ISSUE: missing email, phone has letters/extension noise ---
    ["G-1006", "Neha Gupta", "", "98111 22334 ext 5", "Delhi",
     "figma, ui, web dev", "07/03/2024", "₹1750"],

    # --- ISSUE: title prefix + trailing whitespace in name ---
    ["G-1007", "Dr. Anil Kumar  ", "anil.kumar@consultbae.com", "+91 98765 00000", "Chennai",
     "ml, python, data", "11/02/2024", "₹2500"],

    # --- ISSUE: negative pay (impossible value) ---
    ["G-1008", "Kavya Reddy", "kavya.reddy@gmail.com", "9700012345", "Hyderabad",
     "content, seo", "28/02/2024", "-500"],

    # --- ISSUE: two DIFFERENT people share one email (data conflict) ---
    ["G-1009", "Amit Joshi", "shared.family@gmail.com", "9820011111", "Mumbai",
     "sales, crm", "05/03/2024", "₹1400"],
]


# ---------------------------------------------------------------------------
# cbnexus.csv  — system B
# Different column names, phones as raw 10-digit or with 0 prefix, dates
# YYYY-MM-DD or "Month DD, YYYY", skills semicolon-separated, rate hourly USD.
# ---------------------------------------------------------------------------
cbnexus_rows = [
    ["user_id", "name", "email_address", "contact_number", "location", "skillset", "joined_date", "hourly_usd"],

    # Aarav Sharma again — different case, phone without country code, email same
    ["CBX-77", "AARAV SHARMA", "Aarav.Sharma@Gmail.com", "9876543210", "mumbai",
     "Python; SQL; ETL", "2024-01-10", "6"],

    # Priya Nair again — phone matches (last 10), email has a dot typo, name spaced oddly
    ["CBX-78", "Priya  Nair", "priyanair@gmail.com", "098450 12345", "Bangalore",
     "React; Node.js; JavaScript", "January 5, 2024", "8"],

    # Mohammed Iqbal — name spelled "Mohd", email different, but phone matches
    ["CBX-79", "Mohd Iqbal", "iqbal.m@outlook.com", "9900011223", "Hyderabad",
     "n8n; make; automation", "2024-02-01", "7.5"],

    # --- ISSUE: whitespace-only / placeholder junk in location, missing skillset ---
    ["CBX-80", "Divya Menon", "divya.menon@gmail.com", "9700088776", "   ",
     "", "2024-03-12", "5"],

    # --- ISSUE: same person, first/last name SWAPPED vs other file (see internal) ---
    ["CBX-81", "Nair Vishnu", "vishnu.nair@gmail.com", "9812345678", "Kochi",
     "Data; Python", "2024-02-15", "6.5"],

    # --- ISSUE: bitrate-of-nonsense: hourly rate as text ---
    ["CBX-82", "Rahul Bose", "rahul.bose@gmail.com", "9765432101", "Kolkata",
     "Design; Figma", "2024-03-01", "not disclosed"],

    # --- ISSUE: duplicate person within same file, different casing + trailing space ---
    ["CBX-83", "rahul bose ", "rahul.bose@gmail.com", "9765432101", "kolkata",
     "design; figma", "2024-03-01", "5.5"],

    # --- ISSUE: the OTHER person on the shared email — different human, same address ---
    ["CBX-84", "Sneha Joshi", "shared.family@gmail.com", "9820099999", "Mumbai",
     "HR; Recruiting", "2024-03-20", "6"],

    # A genuinely unique person (only in this file)
    ["CBX-85", "Tara Singh", "tara.singh@gmail.com", "+919811100011", "Delhi",
     "Marketing; SEO; Content", "2024-04-02", "7"],
]


# ---------------------------------------------------------------------------
# internal_automations.csv — system C
# first_name/last_name split, phones with +91 and no separators or with 91
# prefix and no +, dates as DD-Mon-YYYY, tags pipe-separated, rate "INR/hr".
# Uses a different notion of "id" (employee code) and has encoding quirks.
# ---------------------------------------------------------------------------
internal_rows = [
    ["emp_code", "first_name", "last_name", "mail", "mobile", "region", "tags", "created", "rate_inr_hr"],

    # Aarav Sharma yet again — email UPPER, phone with 91 prefix no plus
    ["EMP007", "Aarav", "Sharma", "AARAV.SHARMA@GMAIL.COM", "919876543210", "West",
     "python|data|sql", "10-Jan-2024", "200"],

    # Sara D'Souza — note the apostrophe encoding + phone with +91 and last-10 match
    ["EMP008", "Sara", "D`Souza", "sara.dsouza@gmail.com", "+918200034567", "West",
     "excel|data-entry", "01-Apr-2024", "150"],

    # --- ISSUE: Vishnu Nair — matches CBX-81 but name order normal here ---
    ["EMP009", "Vishnu", "Nair", "vishnu.nair@gmail.com", "9812345678", "South",
     "data|python", "15-Feb-2024", "180"],

    # --- ISSUE: missing last name, phone too short (only 9 digits) ---
    ["EMP010", "Rohan", "", "rohan.verma@gmail.com", "900005566", "West",
     "python|automation", "20-Feb-2024", "190"],

    # --- ISSUE: future/impossible created date + duplicate mail with EMP009 typo'd ---
    ["EMP011", "Farah", "Khan", "farah.khan@gmail.com", "9898989898", "North",
     "content|seo|social", "31-Dec-2099", "160"],

    # --- ISSUE: leading apostrophe (Excel text-guard) on phone, name has trailing tab ---
    ["EMP012", "Anil", "Kumar\t", "anil.kumar@consultbae.com", "'919876500000", "South",
     "ml|python|data", "11-Feb-2024", "300"],

    # --- ISSUE: completely blank-ish row (only an emp_code) ---
    ["EMP013", "", "", "", "", "", "", "", ""],

    # --- ISSUE: comma inside an unquoted-looking field is fine here, but tags use
    #     a stray delimiter mismatch (semicolon instead of pipe) ---
    ["EMP014", "Priya", "Nair", "priya.nair@gmail.com", "9845012345", "South",
     "react;node;webdev", "05-Jan-2024", "220"],

    # A unique internal-only person
    ["EMP015", "Karan", "Malhotra", "karan.malhotra@consultbae.com", "9811223344", "North",
     "devops|aws|python", "18-Mar-2024", "260"],
]


def write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows(rows)
    print(f"wrote {path}  ({len(rows) - 1} data rows)")


if __name__ == "__main__":
    write_csv(os.path.join(RAW_DIR, "recruitment_gigs.csv"), recruitment_rows)
    write_csv(os.path.join(RAW_DIR, "cbnexus.csv"), cbnexus_rows)
    write_csv(os.path.join(RAW_DIR, "internal_automations.csv"), internal_rows)
    print("done. 3 messy CSVs generated in data/raw/")
