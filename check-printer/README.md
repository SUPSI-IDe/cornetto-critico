# Print Monitor (macOS)

A small desktop app that watches a Supabase `registrations` table and warns
you when print jobs are stuck or failing.

## What it does

1. **Stale-job detection** — a row counts as a problem when `print_status`
   is anything other than `"printed"` **and** `created_at` is older than
   3 minutes.
2. **Live queue window** — a Tkinter window lists every row where
   `print_status != "printed"`, refreshing on every poll. Rows older than
   3 minutes are highlighted in red.
3. **Batched failure alert** — instead of one macOS notification per stuck
   row, all newly-detected problem rows in a polling cycle are combined into
   a single notification, e.g. *"3 registration(s) have not printed within
   3 minute(s)."*
4. **Urgent escalation** — once the number of currently outstanding problem
   rows reaches 3 (configurable), the app fires a louder, repeated "urgent"
   notification so it can't be missed.

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file next to `print_monitor.py`:

```
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-anon-or-service-role-key

# optional, these are the defaults:
STALE_MINUTES=3
POLL_SECONDS=15
FAILURE_ESCALATION_THRESHOLD=3
PRINTED_STATUS=printed
```

Your `registrations` table needs at least these columns: `id`, `created_at`
(timestamp), `print_status` (text, e.g. `pending` / `failed` / `printed`).

## Run

```bash
python3 print_monitor.py
```

A window titled **"Print Monitor — Pending Registrations"** opens and starts
polling immediately. Leave it running in the background; macOS notifications
appear in the top-right corner (Notification Center) as issues are found.

## How the notification logic maps to your rules

| Your rule | Implementation |
|---|---|
| `print_status != printed` and `created_at` older than 3 min → notify | Computed each poll as `problem_rows`; triggers a notification for any *newly* problematic rows |
| Show current pending prints (`print_status != printed`) in a window | `MonitorWindow` Treeview, refreshed every `POLL_SECONDS` |
| Don't spam — one notification summarizing count, not per row | Notification message is `"{total_problems} registration(s) have not printed..."`, sent once per cycle that has new problems |
| After 3 failures, send an urgent notification | When `len(problem_ids) >= FAILURE_ESCALATION_THRESHOLD` (default 3), a distinct, repeated "🚨 URGENT" notification fires; it won't re-fire every cycle while still above threshold, only when it newly crosses into escalation |

## Notes & tuning

- Notifications use the built-in `osascript`/AppleScript `display
  notification`, so there's no extra native dependency — just make sure
  **Terminal** (or whatever app you launch the script from) has notification
  permissions enabled in *System Settings → Notifications*.
- If you'd rather treat only rows explicitly marked `failed`/`error` as
  "failures" (rather than any non-`printed` stale row), change the
  `problem_rows` filter in `_poll_once()` to also check
  `r.print_status in ("failed", "error")`.
- To package this as a double-clickable `.app`, you can use `py2app`:
  `pip install py2app` then create a `setup.py` and run
  `python3 setup.py py2app`. This is optional — running via `python3` works
  fine for a background monitoring utility.
- The poll interval (`POLL_SECONDS`, default 15s) determines how quickly new
  stale/failed jobs are detected — it should be well under your 3-minute
  threshold for accurate timing.
