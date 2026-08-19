"""
app.py  —  Task 3: mini audio collection app (Flask).

Routes
------
GET  /             submission form: name, phone, record-in-browser OR upload.
POST /submit       stores the audio file, extracts properties, writes a row to
                   the SAME SQLite DB from Task 1 (linking to an existing person
                   by phone when possible, else creating a new person).
GET  /submissions  table of all submissions with a play button + properties.
GET  /audio/<f>    serves a stored audio file.

Run:  python app/app.py     then open http://localhost:5000
"""

import os
import sqlite3
import sys
import datetime

from flask import (Flask, request, redirect, url_for, render_template,
                   send_from_directory, flash, jsonify)

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from audio_analysis import analyze          # noqa: E402
from normalize import normalize_phone, normalize_name  # noqa: E402

BASE = os.path.join(os.path.dirname(__file__), "..")
DB_PATH = os.path.join(BASE, "data", "consultbae.db")
UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "static", "recordings")
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = Flask(__name__)
app.secret_key = "consultbae-dev-key"  # only for flash messages in dev


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_schema():
    """Create the audio_submission table if the DB was built without it."""
    conn = db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS audio_submission (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            person_id INTEGER, name TEXT, phone TEXT, filename TEXT,
            duration_sec REAL, sample_rate_hz INTEGER, bitrate_kbps INTEGER,
            loudness_dbfs REAL, noise_estimate TEXT, created_at TEXT)""")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS person (
            person_id INTEGER PRIMARY KEY, full_name TEXT, email TEXT,
            phone TEXT, city TEXT, skills TEXT, sources TEXT, record_count INTEGER)""")
    conn.commit()
    conn.close()


def link_or_create_person(conn, name, phone):
    """Return a person_id: reuse an existing person by phone, else insert one."""
    norm = normalize_phone(phone)
    if norm:
        row = conn.execute("SELECT person_id FROM person WHERE phone = ?", (norm,)).fetchone()
        if row:
            return row["person_id"]
    # No match -> create a new person sourced from the audio app.
    display, _ = normalize_name(name)
    next_id = (conn.execute("SELECT COALESCE(MAX(person_id), 0) + 1 FROM person").fetchone()[0])
    conn.execute(
        "INSERT INTO person (person_id, full_name, email, phone, city, skills, sources, record_count) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (next_id, display, "", norm, "", "", "audio_app", 1))
    return next_id


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/submit", methods=["POST"])
def submit():
    name = (request.form.get("name") or "").strip()
    phone = (request.form.get("phone") or "").strip()
    audio = request.files.get("audio")

    if not name or not phone:
        flash("Name and phone are required.")
        return redirect(url_for("index"))
    if not audio or audio.filename == "":
        flash("Please record or upload an audio clip.")
        return redirect(url_for("index"))

    # Save with a timestamped, collision-proof filename.
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    ext = os.path.splitext(audio.filename)[1] or ".webm"
    safe = "".join(c for c in name if c.isalnum()) or "clip"
    filename = f"{stamp}_{safe}{ext}"
    path = os.path.join(UPLOAD_DIR, filename)
    audio.save(path)

    props = analyze(path)

    conn = db()
    person_id = link_or_create_person(conn, name, phone)
    conn.execute(
        "INSERT INTO audio_submission (person_id, name, phone, filename, duration_sec, "
        "sample_rate_hz, bitrate_kbps, loudness_dbfs, noise_estimate, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (person_id, name, phone, filename, props["duration_sec"],
         props["sample_rate_hz"], props["bitrate_kbps"], props["loudness_dbfs"],
         props["noise_estimate"], datetime.datetime.now().isoformat(timespec="seconds")))
    conn.commit()
    conn.close()

    flash(f"Thanks {name}! Your recording was analyzed and stored.")
    return redirect(url_for("submissions"))


@app.route("/submissions")
def submissions():
    conn = db()
    rows = conn.execute(
        "SELECT * FROM audio_submission ORDER BY id DESC").fetchall()
    conn.close()
    return render_template("submissions.html", rows=rows)


@app.route("/audio/<path:filename>")
def audio(filename):
    return send_from_directory(UPLOAD_DIR, filename)


@app.route("/api/check_duplicate", methods=["POST"])
def check_duplicate():
    """
    Used by the Task-2 n8n flow. Accepts JSON {name, email, phone}, normalizes
    it with the SAME logic as the merge pipeline, and reports whether this
    person already exists in the merged database.

    Returns: {is_duplicate, matched_on, person: {...} | null}
    """
    data = request.get_json(silent=True) or {}
    from normalize import normalize_email  # local import keeps top clean
    phone = normalize_phone(data.get("phone", ""))
    email = normalize_email(data.get("email", ""))

    conn = db()
    match, matched_on = None, None
    if phone:
        match = conn.execute("SELECT * FROM person WHERE phone = ?", (phone,)).fetchone()
        matched_on = "phone" if match else None
    if not match and email:
        match = conn.execute("SELECT * FROM person WHERE email = ?", (email,)).fetchone()
        matched_on = "email" if match else None
    conn.close()

    return jsonify({
        "is_duplicate": match is not None,
        "matched_on": matched_on,
        "query": {"name": data.get("name"), "email": email, "phone": phone},
        "person": (dict(match) if match else None),
    })


# Ensure the tables exist whether launched via `python app/app.py` or gunicorn.
ensure_schema()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
