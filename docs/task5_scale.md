# Task 5 — Stretch: launching the audio app to 5,000 gig workers over one weekend

*One page, no code. What breaks first, and what I'd change before launch.*

## What breaks first

The current app is a single Flask process writing files to local disk and rows
to a single-file SQLite database. That is perfect for the take-home and wrong
for 5,000 people over 48 hours. In rough order of what fails first:

1. **SQLite write contention.** SQLite locks the whole database file on write.
   With hundreds of concurrent submissions each doing an `INSERT`, writers
   serialize and start timing out. This is the very first thing to fall over.

2. **Local disk fills / disappears.** Recordings are saved to
   `app/static/recordings/`. 5,000 clips at ~1–3 MB each is 5–15 GB, and on
   an ephemeral host (Render/Railway free tier) that disk is wiped on redeploy.
   Uploads survive only until the next restart.

3. **Synchronous audio analysis blocks the request.** `analyze()` shells out to
   ffmpeg *inside the POST handler*. Each analysis takes hundreds of ms to a few
   seconds; under load the worker pool is exhausted and every user sees spinners
   and 502s, even though nothing is technically "down."

4. **Mobile uploads and flaky networks.** Gig workers are on phones and patchy
   connectivity. Large multipart uploads fail halfway; there is no resume, no
   retry, and no client-side size/duration cap, so people re-submit — inflating
   both load and duplicates.

5. **Duplicates and abuse.** No rate limiting and no idempotency key means one
   worker double-tapping "Submit" creates two rows and two files. At 5,000
   people that is real noise, and there is nothing stopping junk or empty clips.

## What I'd change before launch

**Move the datastore off SQLite.** Postgres (managed, e.g. RDS/Supabase/Neon)
for the rows; it handles concurrent writes and is a one-line SQLAlchemy swap.
Keep the same schema.

**Store audio in object storage, not on the app disk.** Upload directly from the
browser to S3/GCS/Cloudflare R2 using a **pre-signed URL**, so the big bytes
never pass through the Flask process at all. The app only records metadata +
the object key. This removes the disk-fill problem and most of the upload load
in one move. R2 is attractive on cost because egress is free.

**Make analysis asynchronous.** The POST handler should store the file and drop
a job on a queue (Celery/RQ + Redis, or a serverless worker). A background
worker runs ffmpeg and writes the properties back. The user gets an instant
"received"; the submissions table shows "analyzing…" until results land. This
decouples throughput from ffmpeg speed.

**Harden the client.** Enforce a max duration and file size in the browser,
show upload progress, retry on failure, and disable the Submit button after the
first tap. Add an idempotency key per submission so retries don't duplicate.

**Add guardrails.** Basic rate limiting per IP/phone, a CAPTCHA or phone OTP if
abuse appears, and server-side validation that the clip is real audio of
non-trivial length before it counts.

**Run more than one process.** Even two or three app instances behind a load
balancer (or a horizontally-scaling platform) plus a few queue workers. Nothing
here needs to be fancy; it needs to not be a single process on a single disk.

## Rough cost sketch (one weekend, 5,000 clips)

| Item | Estimate |
|---|---|
| Object storage (10–15 GB, R2) | ~$0.15–0.25/mo storage; egress free |
| Managed Postgres (small) | ~$15–25/mo, or free tier for a weekend |
| App + workers (2–3 small instances) | ~$20–40/mo, or free/trial tiers |
| Queue (Redis, small) | ~$10/mo, or free tier |

**Total: well under ~$100 for the weekend**, dominated by compute, not storage.
The expensive resource is not money — it is the single write path and the
single disk in today's design. Fixing those two things is 80% of the win.

## The one thing I'd do if I only had an hour

Swap local disk for pre-signed S3/R2 uploads and move `analyze()` to a
background worker. Those two changes alone take the app from "falls over at a
few dozen concurrent users" to "comfortably handles the weekend."
