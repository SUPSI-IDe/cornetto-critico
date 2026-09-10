#!/usr/bin/env python3
"""
Print Monitor for macOS — local browser dashboard edition
==========================================================

No Tkinter is used. The app runs a local dashboard server on 127.0.0.1 and
is designed to run without Terminal using the supplied macOS LaunchAgent.

Dashboard contents:
- Current pending print jobs: print_status != "printed"
- Overdue/stuck jobs: pending + created_at older than STALE_MINUTES
- Last update time and countdown to the next update
- Latest registration in the entire table, including created_at and status,
  as a heartbeat that confirms the database poll is working
- A distinct "Monitor process" heartbeat with time since the last successful
  Supabase poll

Notifications:
- One summarized notification per newly detected set of overdue rows
- Urgent repeated alert when outstanding overdue rows >= threshold

Dependencies:
    pip install supabase python-dotenv

Required .env values (placed alongside this file):
    SUPABASE_URL=https://your-project.supabase.co
    SUPABASE_KEY=your-anon-or-service-role-key

Optional .env values:
    STALE_MINUTES=3
    POLL_SECONDS=15
    FAILURE_ESCALATION_THRESHOLD=3
    PRINTED_STATUS=printed
    PRINT_MONITOR_PORT=8765
"""

import json
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

try:
    from dotenv import load_dotenv
    from supabase import create_client
except ImportError:
    print("Missing dependency. Run: pip install supabase python-dotenv", file=sys.stderr)
    sys.exit(1)

APP_DIR = Path(__file__).resolve().parent
load_dotenv(APP_DIR / ".env")

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
PRINTED_STATUS = os.getenv("PRINTED_STATUS", "printed")
STALE_MINUTES = float(os.getenv("STALE_MINUTES", "3"))
POLL_SECONDS = int(os.getenv("POLL_SECONDS", "15"))
ESCALATION_THRESHOLD = int(os.getenv("FAILURE_ESCALATION_THRESHOLD", "3"))
HOST = "127.0.0.1"
PORT = int(os.getenv("PRINT_MONITOR_PORT", "8765"))
BERN_TZ = ZoneInfo("Europe/Zurich")


@dataclass
class Registration:
    record_id: str
    status: str
    created_at: datetime

    @property
    def age_seconds(self) -> int:
        return max(0, int((datetime.now(timezone.utc) - self.created_at).total_seconds()))

    @property
    def is_stale(self) -> bool:
        return self.age_seconds >= STALE_MINUTES * 60

    def to_dict(self) -> dict:
        age = self.age_seconds
        minutes, seconds = divmod(age, 60)
        hours, minutes = divmod(minutes, 60)
        elapsed = f"{hours}h {minutes}m {seconds}s" if hours else f"{minutes}m {seconds}s"
        local_created_at = self.created_at.astimezone(BERN_TZ)
        return {
            "id": self.record_id,
            "status": self.status,
            "created_at": local_created_at.strftime("%Y-%m-%d %H:%M:%S %Z"),
            "elapsed": elapsed,
            "age_seconds": age,
            "stale": self.is_stale,
        }


class MonitorState:
    def __init__(self):
        self.lock = threading.Lock()
        self.pending: List[Registration] = []
        self.latest_registration: Optional[Registration] = None
        self.last_success_at: Optional[datetime] = None
        self.last_attempt_at: Optional[datetime] = None
        self.next_update_at: Optional[float] = None
        self.error: Optional[str] = None
        self.started_at = datetime.now()

    def snapshot(self) -> dict:
        with self.lock:
            pending = [row.to_dict() for row in self.pending]
            stale_count = sum(1 for row in pending if row["stale"])
            return {
                "pending": pending,
                "pending_count": len(pending),
                "stale_count": stale_count,
                "latest_registration": self.latest_registration.to_dict() if self.latest_registration else None,
                "last_success_at": self.last_success_at.strftime("%Y-%m-%d %H:%M:%S") if self.last_success_at else None,
                "last_attempt_at": self.last_attempt_at.strftime("%Y-%m-%d %H:%M:%S") if self.last_attempt_at else None,
                "next_update_at": self.next_update_at,
                "error": self.error,
                "stale_minutes": STALE_MINUTES,
                "poll_seconds": POLL_SECONDS,
                "escalation_threshold": ESCALATION_THRESHOLD,
                "started_at": self.started_at.strftime("%Y-%m-%d %H:%M:%S"),
            }


STATE = MonitorState()


def parse_created_at(value: str) -> datetime:
    value = str(value).replace("Z", "+00:00")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def row_to_registration(row: dict) -> Optional[Registration]:
    if not row.get("created_at"):
        return None
    try:
        return Registration(
            record_id=str(row.get("id", "")),
            status=str(row.get("print_status") or "unknown"),
            created_at=parse_created_at(row["created_at"]),
        )
    except (TypeError, ValueError):
        return None


def fetch_monitor_data(client):
    """Fetch pending jobs and the newest registration across the entire table."""
    pending_response = (
        client.table("registrations")
        .select("id,created_at,print_status")
        .neq("print_status", PRINTED_STATUS)
        .order("created_at", desc=False)
        .execute()
    )
    latest_response = (
        client.table("registrations")
        .select("id,created_at,print_status")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )

    pending = []
    for row in pending_response.data or []:
        registration = row_to_registration(row)
        if registration:
            pending.append(registration)

    latest = None
    if latest_response.data:
        latest = row_to_registration(latest_response.data[0])
    return pending, latest


def notify(title: str, message: str, sound: str = "Basso"):
    """Use macOS's built-in notification system without an extra dependency."""
    def escape(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')

    script = (
        f'display notification "{escape(message)}" '
        f'with title "{escape(title)}" sound name "{escape(sound)}"'
    )
    try:
        subprocess.run(["osascript", "-e", script], check=False)
    except OSError as exc:
        print(f"macOS notification error: {exc}", file=sys.stderr)


def monitor_loop(stop_event: threading.Event):
    try:
        client = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as exc:
        with STATE.lock:
            STATE.error = f"Cannot create Supabase client: {exc}"
            STATE.last_attempt_at = datetime.now()
            STATE.next_update_at = time.time() + POLL_SECONDS
        return

    alerted_problem_ids = set()
    urgent_sent = False

    while not stop_event.is_set():
        next_at = time.time() + POLL_SECONDS
        with STATE.lock:
            STATE.last_attempt_at = datetime.now()
            STATE.next_update_at = next_at

        try:
            pending, latest = fetch_monitor_data(client)
            problems = [row for row in pending if row.is_stale]
            problem_ids = {row.record_id for row in problems}
            new_problem_ids = problem_ids - alerted_problem_ids

            if new_problem_ids:
                notify(
                    "Print Monitor — Issue Detected",
                    f"{len(problem_ids)} registration(s) have not printed within "
                    f"{int(STALE_MINUTES)} minute(s).",
                )

            if len(problem_ids) >= ESCALATION_THRESHOLD and not urgent_sent:
                for _ in range(3):
                    notify(
                        "Print Monitor — URGENT",
                        f"{len(problem_ids)} print jobs are stuck or failed. "
                        f"Threshold: {ESCALATION_THRESHOLD}.",
                        sound="Sosumi",
                    )
                    if stop_event.wait(0.5):
                        return
                urgent_sent = True
            elif len(problem_ids) < ESCALATION_THRESHOLD:
                urgent_sent = False

            alerted_problem_ids = problem_ids
            with STATE.lock:
                STATE.pending = pending
                STATE.latest_registration = latest
                STATE.error = None
                STATE.last_success_at = datetime.now()
        except Exception as exc:
            with STATE.lock:
                STATE.error = f"Supabase query error: {exc}"

        stop_event.wait(POLL_SECONDS)


DASHBOARD_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Print Monitor</title>
<style>
:root { color-scheme: light; }
* { box-sizing: border-box; }
body { margin:0; background:#f5f5f7; color:#1d1d1f; font-family:-apple-system,BlinkMacSystemFont,"SF Pro Display","Helvetica Neue",Arial,sans-serif; }
main { max-width:1180px; margin:0 auto; padding:34px 28px 44px; }
h1 { margin:0; font-size:31px; letter-spacing:-.6px; }
.subtitle { margin:7px 0 23px; color:#6e6e73; font-size:15px; }
.card,.panel { background:#fff; border-radius:16px; box-shadow:0 1px 2px rgba(0,0,0,.08),0 4px 16px rgba(0,0,0,.04); }
.card { padding:21px; }
.health { display:flex; gap:12px; align-items:center; font-size:21px; font-weight:700; }
.dot { width:13px; height:13px; border-radius:50%; background:#8e8e93; flex:0 0 13px; }
.ok .dot { background:#34c759; } .warning .dot { background:#ff9f0a; } .error .dot { background:#ff3b30; }
.meta { display:flex; align-items:center; flex-wrap:wrap; gap:8px 24px; margin-top:15px; color:#6e6e73; font-size:14px; }
button { border:0; border-radius:9px; padding:9px 14px; color:#fff; background:#007aff; font-size:14px; cursor:pointer; } button:hover { background:#0071e3; }
.error-box { display:none; margin-top:15px; border:1px solid #ffccc7; background:#fff1f0; color:#9d0000; border-radius:10px; padding:12px; font-size:14px; overflow-wrap:anywhere; }
.grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:14px; margin:21px 0; }
.stat { padding:18px; } .number { font-size:27px; font-weight:700; } .label { color:#6e6e73; font-size:13px; margin-top:5px; }
.latest { margin:0 0 21px; padding:19px 20px; }
.latest-head { display:flex; align-items:baseline; justify-content:space-between; gap:12px; }
h2 { margin:0; font-size:18px; } .muted { color:#6e6e73; font-size:13px; }
.latest-details { display:grid; grid-template-columns:1.2fr 1fr 1.2fr; gap:12px; margin-top:14px; }
.kv { min-width:0; } .key { color:#6e6e73; text-transform:uppercase; letter-spacing:.2px; font-size:11px; font-weight:600; } .value { margin-top:4px; font-size:14px; overflow-wrap:anywhere; }
.panel { overflow:hidden; } .panel-head { display:flex; justify-content:space-between; align-items:baseline; padding:19px 20px; border-bottom:1px solid #e5e5ea; }
table { width:100%; border-collapse:collapse; text-align:left; font-size:14px; } th { background:#fbfbfd; color:#6e6e73; font-size:12px; text-transform:uppercase; letter-spacing:.2px; } th,td { padding:14px 20px; border-bottom:1px solid #ececf0; } tbody tr:last-child td { border-bottom:0; } tbody tr.stale { background:#fff2f1; }
.badge { display:inline-block; padding:4px 9px; border-radius:999px; background:#e8e8ed; color:#3a3a3c; font-size:12px; font-weight:600; } .stale .badge { background:#ffdad6; color:#a40000; }
.empty { padding:42px 20px; text-align:center; color:#6e6e73; } .empty strong { display:block; color:#1d1d1f; font-size:17px; margin-bottom:7px; }
@media(max-width:720px){main{padding:22px 14px}.grid{grid-template-columns:repeat(2,1fr)}.latest-details{grid-template-columns:1fr}th:nth-child(3),td:nth-child(3){display:none}th,td{padding:12px}}
</style>
</head>
<body>
<main>
<h1>Print Monitor</h1>
<p class="subtitle">Live status for Supabase registrations</p>
<section id="statusCard" class="card">
  <div class="health"><span class="dot"></span><span id="health">Starting monitor…</span></div>
  <div class="meta"><span id="lastSuccess">Last successful update: never</span><span id="next">Next update: loading…</span><span id="interval"></span><button onclick="loadStatus()">Refresh now</button></div>
  <div id="error" class="error-box"></div>
</section>
<section class="grid">
  <div class="card stat"><div id="pendingCount" class="number">—</div><div class="label">Pending print jobs</div></div>
  <div class="card stat"><div id="overdueCount" class="number">—</div><div id="overdueLabel" class="label">Overdue jobs</div></div>
  <div class="card stat"><div id="threshold" class="number">—</div><div class="label">Urgent-alert threshold</div></div>
  <div class="card stat"><div id="processState" class="number">—</div><div class="label">Monitor process</div></div>
</section>
<section class="card latest">
  <div class="latest-head"><h2>Latest registration</h2><span class="muted">Fetched from the whole registrations table</span></div>
  <div id="latestDetails" class="latest-details"><div class="muted">Loading latest registration…</div></div>
</section>
<section class="panel">
  <div class="panel-head"><h2>Current pending prints</h2><span class="muted">Rows older than the configured limit are red</span></div>
  <div id="table"><div class="empty"><strong>Loading…</strong>Connecting to the local monitor.</div></div>
</section>
</main>
<script>
let latestState=null;
function esc(value){const x=document.createElement('div');x.textContent=value==null?'':String(value);return x.innerHTML;}
function setLatest(record){const box=document.getElementById('latestDetails');if(!record){box.innerHTML='<div class="muted">No registrations were returned from the table yet.</div>';return;}box.innerHTML=`<div class="kv"><div class="key">Registration ID</div><div class="value">${esc(record.id)}</div></div><div class="kv"><div class="key">Print status</div><div class="value"><span class="badge">${esc(record.status)}</span></div></div><div class="kv"><div class="key">Created at</div><div class="value">${esc(record.created_at)}</div></div>`;}
function render(data){latestState=data;const card=document.getElementById('statusCard'),health=document.getElementById('health'),err=document.getElementById('error');card.className='card';if(data.error){card.classList.add('error');health.textContent='Unable to update monitor';err.style.display='block';err.textContent=data.error;}else if(data.stale_count){card.classList.add('error');health.textContent=`${data.stale_count} overdue print job(s) need attention`;err.style.display='none';}else if(data.pending_count){card.classList.add('warning');health.textContent=`${data.pending_count} print job(s) pending — none overdue yet`;err.style.display='none';}else{card.classList.add('ok');health.textContent='All clear — no pending print jobs';err.style.display='none';}
document.getElementById('lastSuccess').textContent=`Last successful update: ${data.last_success_at||'never'}`;document.getElementById('interval').textContent=`Poll interval: ${data.poll_seconds}s`;document.getElementById('pendingCount').textContent=data.pending_count;document.getElementById('overdueCount').textContent=data.stale_count;document.getElementById('overdueLabel').textContent=`Overdue (>${data.stale_minutes} min)`;document.getElementById('threshold').textContent=data.escalation_threshold;document.getElementById('processState').textContent=data.last_success_at?'Running':'Starting';setLatest(data.latest_registration);const area=document.getElementById('table');if(!data.pending.length){area.innerHTML='<div class="empty"><strong>All clear</strong>No pending registrations. Everything is printed.</div>';return;}const rows=data.pending.map(r=>`<tr class="${r.stale?'stale':''}"><td>${esc(r.id)}</td><td><span class="badge">${esc(r.status)}</span></td><td>${esc(r.created_at)}</td><td>${esc(r.elapsed)}</td></tr>`).join('');area.innerHTML=`<table><thead><tr><th>ID</th><th>Print status</th><th>Created at</th><th>Elapsed</th></tr></thead><tbody>${rows}</tbody></table>`;}
function countdown(){if(!latestState||!latestState.next_update_at)return;const remaining=Math.max(0,Math.ceil(latestState.next_update_at-Date.now()/1000));document.getElementById('next').textContent=`Next automatic update in: ${remaining}s`;}
async function loadStatus(){try{const response=await fetch('/api/status',{cache:'no-store'});render(await response.json());}catch(e){document.getElementById('statusCard').className='card error';document.getElementById('health').textContent='Cannot reach local monitor';}}
loadStatus();setInterval(loadStatus,5000);setInterval(countdown,1000);
</script>
</body>
</html>"""


class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            content = DASHBOARD_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return
        if path == "/api/status":
            content = json.dumps(STATE.snapshot()).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return
        self.send_error(404)


def main():
    if not SUPABASE_URL or not SUPABASE_KEY:
        print(f"Missing SUPABASE_URL or SUPABASE_KEY in {APP_DIR / '.env'}", file=sys.stderr)
        sys.exit(1)

    stop_event = threading.Event()
    threading.Thread(target=monitor_loop, args=(stop_event,), daemon=True).start()

    try:
        server = ThreadingHTTPServer((HOST, PORT), DashboardHandler)
    except OSError as exc:
        print(f"Cannot start dashboard at http://{HOST}:{PORT}: {exc}", file=sys.stderr)
        print("Set PRINT_MONITOR_PORT=8766 in .env if port 8765 is in use.", file=sys.stderr)
        stop_event.set()
        sys.exit(1)

    print(f"Print Monitor running locally at http://{HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
