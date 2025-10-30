#!/usr/bin/env python3
import os
import sys
import time
import json
import requests
from collections import deque

# ================= CONFIG =================
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")
ERROR_RATE_THRESHOLD = float(os.getenv("ERROR_RATE_THRESHOLD", "50"))
WINDOW_SIZE = int(os.getenv("WINDOW_SIZE", "200"))
ALERT_COOLDOWN_SEC = int(os.getenv("ALERT_COOLDOWN_SEC", "60"))
MAINTENANCE_MODE = os.getenv("MAINTENANCE_MODE", "0") == "1"

# ================= STATE =================
last_alert_time = 0
last_seen_pool = None
recent_statuses = deque(maxlen=WINDOW_SIZE)

# ================= HELPERS =================
def parse_log_line(line):
    """Parse JSON log line from Nginx."""
    try:
        log = json.loads(line)
        return log
    except json.JSONDecodeError:
        return None

def should_send_alert():
    global last_alert_time
    now = time.time()
    if now - last_alert_time >= ALERT_COOLDOWN_SEC:
        last_alert_time = now
        return True
    return False

def send_slack_alert(message):
    if not SLACK_WEBHOOK_URL:
        print("⚠️ SLACK_WEBHOOK_URL not set. Skipping alert.")
        return
    try:
        response = requests.post(SLACK_WEBHOOK_URL, json={"text": message})
        if response.status_code != 200:
            print(f"⚠️ Slack error: {response.status_code} {response.text}")
    except Exception as e:
        print(f"⚠️ Exception sending Slack alert: {e}")

def check_error_rate():
    if not recent_statuses:
        return 0.0
    error_count = sum(1 for s in recent_statuses if s.startswith("5"))
    return (error_count / len(recent_statuses)) * 100

# ================= LOG SOURCE =================
if sys.stdin.isatty():
    # Normal mode: read from the access log file
    LOG_FILE_PATH = "/var/log/nginx/access.log"
    print(f"Starting watcher... Monitoring {LOG_FILE_PATH}")
    log_source = open(LOG_FILE_PATH, "r", buffering=1)
else:
    # Piped input mode (docker logs -f nginx_gateway | watcher.py)
    print("Starting watcher... Monitoring piped log stream")
    log_source = sys.stdin

# ================= MAIN LOOP =================
for line in log_source:
    if MAINTENANCE_MODE:
        time.sleep(10)
        continue

    line = line.strip()
    if not line:
        continue

    log = parse_log_line(line)
    if not log:
        continue

    pool = log.get("pool")
    status = str(log.get("status", ""))

    # Pool failover detection
    if pool:
        global last_seen_pool
        if pool != last_seen_pool and should_send_alert():
            send_slack_alert(f"⚠️ Failover detected! Pool switched from `{last_seen_pool}` to `{pool}`.")
            last_seen_pool = pool

    # Track recent statuses and check error rate
    recent_statuses.append(status)
    error_rate = check_error_rate()
    if error_rate >= ERROR_RATE_THRESHOLD and should_send_alert():
        send_slack_alert(
            f"⚠️ High error rate detected! {error_rate:.2f}% of last {len(recent_statuses)} requests were 5xx."
        )
