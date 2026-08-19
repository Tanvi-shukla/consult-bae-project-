# ConsultBae — AI Automation Take-Home

Merge three messy source systems into one clean database, automate a duplicate
check on top with a no-code tool, and collect + analyze audio submissions.

| Task | What | Where |
|---|---|---|
| 1 | Merge 3 CSVs → one clean SQLite DB with de-duplicated people | `scripts/merge.py`, `scripts/normalize.py` |
| 2 | No-code duplicate-alert automation (n8n) | `automation/` |
| 3 | Mini audio collection app (Flask) with property extraction | `app/` |
| 4 | Data issues report | this README + `scripts/data_issues_report.py` |
| 5 | Scale write-up (5,000 workers) | `docs/task5_scale.md` |

---

## Quick start

```bash
# 1. install deps (ffmpeg is required for audio analysis)
python -m pip install -r requirements.txt
#    macOS:  brew install ffmpeg      Ubuntu: sudo apt-get install ffmpeg

# 2. generate the 3 messy CSVs (deterministic)
python scripts/generate_csvs.py

# 3. Task 1 — merge them into data/consultbae.db
python scripts/merge.py

# 4. Task 4 — print the auto-detected data-issues report
python scripts/data_issues_report.py

# 5. Task 3 — run the audio app, then open http://localhost:5000
python app/app.py
```

`data/consultbae.db` is rebuilt from scratch every time `merge.py` runs.
Requires Python 3.9+ and `ffmpeg`/`ffprobe` on PATH.

---

## Task 1 — merge & matching logic

**The hard part:** no ID is shared across the three files, and the same person
appears with different name casing, name order (`Nair Vishnu` vs `Vishnu Nair`),
phone formats (`+91-98765 43210`, `098450 12345`, `919876543210`), and email
typos (`gmial.com`). So identity has to be *reconstructed*.

**Pipeline** (`scripts/merge.py`):

1. **Load & map** each system's odd columns into one internal record shape,
   keeping every raw value (provenance is never thrown away).
2. **Normalize** the identity fields (`scripts/normalize.py`):
   - phone → last 10 digits after stripping `+91` / `91` / leading `0` / spaces
     / an Excel text-guard apostrophe / trailing `ext` noise; anything that
     can't reach a clean 10 digits becomes empty (so broken numbers can't
     create false matches).
   - email → lowercased, trimmed, and well-known domain typos corrected.
   - name → strip honorifics, fix `Last, First` order, unify apostrophes, and
     reduce to an **order-independent token set** so a swapped first/last name
     still matches.
3. **Cluster** with union-find over two rules:
   - **Rule A (strong):** identical valid 10-digit phone → same person.
   - **Rule B (medium):** same email **and** overlapping name tokens — *unless*
     both records have valid phones that differ **and** the names are only a
     weak match. That exception is the guard for the planted trap below.
4. **Elect a canonical record** per cluster (most common non-empty value per
   field; skills merged and de-duplicated across sources) and write:
   - `person` — one clean row per human,
   - `source_record` — every original row linked to its person,
   - `audio_submission` — filled by Task 3.

**Result:** 28 raw rows → 1 dropped (blank) → **27 rows collapse to 16 people.**

Two decisions I'm most willing to defend on a call:

- **One email, two different humans.** `shared.family@gmail.com` belongs to both
  *Amit Joshi* (phone …11111) and *Sneha Joshi* (phone …99999). Matching on
  email alone would wrongly merge them. The pipeline keeps them **separate**
  because their phones are both valid and different and the names are only a
  weak match. Logged as a `BLOCK`.
- **One person, mistyped phone.** *Sara D'Souza*'s recruitment row has a
  garbled phone that normalizes differently from her real number, but the name
  and email match exactly. Here the pipeline **merges anyway** and notes
  "likely typo", because a strong name+email match should beat a single bad
  phone. The two cases pull in opposite directions on purpose — that tension is
  the whole point of Rule B.

---

## Task 2 — no-code automation (n8n)

A **New Person → Duplicate Alert** flow. n8n receives a person via webhook,
calls the Python `/api/check_duplicate` endpoint (which reuses the exact Task-1
normalization against the merged DB), and if it's a duplicate, posts a Slack
alert; otherwise it responds "new". Full run/import steps and test commands are
in [`automation/README.md`](automation/README.md). Flow JSON:
`automation/n8n_duplicate_alert_flow.json`.

The decision + orchestration are no-code in n8n; the one genuinely code-shaped
step (normalize messy input, query SQLite) is a tiny testable HTTP endpoint the
flow calls.

---

## Task 3 — audio collection app

Flask app (`app/app.py`) with two views:

- **`/`** — enter name + phone, then **record in the browser** (MediaRecorder)
  *or* **upload** an audio file, and submit.
- **`/submissions`** — every submission with a play button and its extracted
  properties.

On submit the app stores the file, runs `app/audio_analysis.py`, writes a row to
the **same** `consultbae.db`, and **links to an existing person by phone** when
possible (else creates a new person sourced from the app).

**Extracted for every clip:** `duration_sec`, `sample_rate_hz`, `bitrate_kbps`,
`loudness_dbfs` (RMS level), and a bonus `noise_estimate` (clean / moderate /
noisy, from the dynamic range between the quietest and loudest frames).
Extraction uses `ffprobe` for container metadata and `ffmpeg`→PCM + numpy for
loudness, so no per-codec decoder library is needed and browser WebM/Opus works
out of the box.

---

## Task 4 — data issues report

Run `python scripts/data_issues_report.py` to reproduce this automatically.
Every issue below is **planted on purpose** in `scripts/generate_csvs.py` and
catalogued so the matching logic has real problems to solve.

| # | Problem | Example | What the pipeline does |
|---|---|---|---|
| 1 | **Exact duplicate row** | `G-1004` Sara appears twice, identical | Collapsed by phone match; both rows kept in `source_record`, one `person` |
| 2 | **No common ID across files** | gig_id / user_id / emp_code are unrelated | Identity reconstructed from name + email + phone, not IDs |
| 3 | **Same person, different name spelling** | `Mohammed Iqbal` vs `Mohd Iqbal`; `Nair Vishnu` vs `Vishnu Nair` | Matched on phone; name tokens compared order-independently |
| 4 | **Phone format drift** | `+91-98765 43210`, `098450 12345`, `919876543210` | Normalized to last-10 digits before matching |
| 5 | **Wrong-length / broken phone** | `EMP010` = `900005566` (9 digits) | Rejected as invalid; person recovered via email+name instead |
| 6 | **Email domain typo** | `rohan.verma@gmial.com` | Auto-corrected `gmial→gmail`; then matches the real address |
| 7 | **Missing email** | `G-1006` Neha Gupta | Kept (phone identifies her); flagged in report |
| 8 | **Completely blank row** | `EMP013` (only an emp_code) | Dropped as unusable, with a logged reason |
| 9 | **One email, two different people** | `shared.family@gmail.com` = Amit & Sneha | Kept **separate** (phones differ, weak name match) |
| 10 | **One person, mistyped phone** | Sara's recruitment phone ≠ her real one | **Merged anyway** on strong name+email match (noted as typo) |
| 11 | **Negative / impossible rate** | `G-1008` pay = `-500` | Flagged; not used as an identity signal |
| 12 | **Non-numeric rate** | `CBX-82` hourly = `not disclosed` | Flagged as non-numeric |
| 13 | **Impossible / future date** | `EMP011` created `31-Dec-2099` | Flagged |
| 14 | **Inconsistent date formats** | `DD/MM/YYYY`, `YYYY-MM-DD`, `DD-Mon-YYYY`, `Month DD, YYYY` | Flagged (not needed for matching, would be normalized before analytics) |
| 15 | **Whitespace / tab / apostrophe noise** | `Dr. Anil Kumar  `, `Kumar\t`, `'919876500000` | Cleaned in normalization |
| 16 | **Honorific prefixes** | `Dr. Anil Kumar` | Stripped before name comparison |
| 17 | **First/last-name swap** | `Nair Vishnu` vs `Vishnu Nair` | Handled by order-independent token set |
| 18 | **Inconsistent skill delimiters** | commas vs `;` vs `\|` across files | Split on all three when merging skills |
| 19 | **Region used where city expected** | internal file has `West/South` not a city | Kept as-is; noted as a schema mismatch to reconcile later |

---

## Stuck log

The 2–3 places I actually got stuck, and how I got unstuck.

### 1. The matching rule kept being *either* too greedy *or* too timid

My first version clustered anyone who shared an email. That instantly merged
`Amit Joshi` and `Sneha Joshi` — two different people who happen to share
`shared.family@gmail.com`. So I flipped to "block any email merge when the two
phones differ." That fixed Amit/Sneha but then **split Sara D'Souza into two
people**, because her recruitment row has a mistyped phone even though her name
and email match perfectly.

I was stuck because the two cases want opposite behavior from the same signal (a
phone mismatch). What unstuck me was stopping treating "phone mismatch" as one
thing: I added a *name-strength* test. A phone mismatch only blocks a merge when
the names are a **weak** match (Amit vs Sneha, sharing only a surname); when the
names are a **strong** match (Sara == Sara), the mismatch is treated as a typo
and the merge proceeds. I considered fuzzy string distance (Levenshtein /
`rapidfuzz`) for names and **rejected it** for now — it adds a dependency and a
threshold to tune, and exact token-set comparison already handled every case in
this dataset. I'd revisit fuzzy matching only if real data showed near-miss
spellings. I verified the final rule by printing every MERGE/BLOCK decision (see
`merge.py` output) and checking each against what I expected by hand.

### 2. Getting audio properties out of browser recordings without a decoder zoo

Browsers record **WebM/Opus**, but people also upload MP3/WAV/M4A. My first
instinct was `librosa`/`soundfile`, but those pull in `libsndfile` and don't
love Opus, and I didn't want a fragile per-codec dependency stack on a free
host. What I searched: "get audio duration bitrate without decoding python",
"ffprobe json output", "compute dBFS from PCM numpy". The unlock was realizing
**ffmpeg/ffprobe already handle every codec** and are available everywhere — so
I use `ffprobe` for duration/sample-rate/bitrate (deriving bitrate from
size÷duration when the container omits it, which WebM often does) and decode to
a mono 16-bit WAV with ffmpeg to compute RMS loudness and the noise estimate
with just numpy + the stdlib `wave` module. I rejected the heavy-library path
because "one system tool + numpy" is far easier to deploy and defend. Verified
by analyzing both a WAV and a real Opus/WebM clip and confirming sane numbers.

### 3. Keeping Task 2 genuinely no-code while reusing my real logic

The brief is explicit that pure-code Task-2 answers score zero, but the actual
duplicate check needs the messy-phone normalization I already wrote. I didn't
want to reimplement that logic inside an n8n Code node (that's just code in a
different box, and it would drift from Task 1). The design I landed on: n8n owns
the trigger, the branch, and the alert (all no-code nodes), and calls my Python
`/api/check_duplicate` endpoint over HTTP for the one normalization+lookup step.
The thing I got briefly stuck on was networking — from n8n-in-Docker, `localhost`
is the *container*, not my Flask app. Searched "n8n docker reach host localhost";
the fix is `host.docker.internal` (and `--add-host` on Linux), which is baked
into the flow's HTTP node and documented in `automation/README.md`.

---

## Repo layout

```
consultbae-assignment/
├── README.md                     ← you are here (setup + data issues + stuck log)
├── requirements.txt
├── data/raw/                     ← the 3 generated messy CSVs
├── scripts/
│   ├── generate_csvs.py          ← makes the messy data (deterministic)
│   ├── normalize.py              ← shared field-cleaning rules
│   ├── merge.py                  ← Task 1 pipeline → data/consultbae.db
│   └── data_issues_report.py     ← Task 4 auto-detector
├── app/                          ← Task 3 Flask audio app
│   ├── app.py
│   ├── audio_analysis.py
│   └── templates/
├── automation/                   ← Task 2 n8n flow + how to run it
└── docs/task5_scale.md           ← Task 5 write-up
```

## A note on AI use

I used an AI assistant while building this (as the brief allows) — mainly to
move faster on ffmpeg flags, the n8n JSON shape, and boilerplate. Every design
decision here (the matching rules, the block-vs-merge trade-off, the
ffmpeg-over-librosa call, the no-code/Python split for Task 2) is one I can walk
through and defend line by line, which is the point of the stuck log above.
