import os
import sys
import time
import json
import argparse
import select
import requests
from collections import deque

# ================= CONFIG =================
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")
ERROR_RATE_THRESHOLD = float(os.getenv("ERROR_RATE_THRESHOLD", "2"))  # %
WINDOW_SIZE = int(os.getenv("WINDOW_SIZE", "200"))
ALERT_COOLDOWN_SEC = int(os.getenv("ALERT_COOLDOWN_SEC", "60"))
MAINTENANCE_MODE = os.getenv("MAINTENANCE_MODE", "0").lower() in ("1", "true", "yes")
LOG_PATH = os.getenv("NGINX_ACCESS_LOG", "/var/log/nginx/access.log")
LOG_INPUT = os.getenv("LOG_INPUT", "auto")  # auto|file|stdin

# ================= STATE =================
last_alert_time = 0
last_seen_pool = None
recent_statuses = deque(maxlen=WINDOW_SIZE)
recent_logs = deque(maxlen=WINDOW_SIZE)  # store parsed dicts for snippets

# ================= HELPERS =================
def parse_log_line(line):
    try:
        return json.loads(line)
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


def send_slack_blocks(title, details_dict=None, snippet=None):
    if not SLACK_WEBHOOK_URL:
        print("⚠️ SLACK_WEBHOOK_URL not set. Skipping alert.")
        return
    try:
        details_dict = details_dict or {}
        # Build a readable details string
        details_lines = [f"• *{k}*: {v}" for k, v in details_dict.items()]
        details_text = "\n".join(details_lines) if details_lines else ""
        blocks = [
            {"type": "header", "text": {"type": "plain_text", "text": title, "emoji": True}},
            {"type": "context", "elements": [{"type": "mrkdwn", "text": f"`{now_iso8601()}`"}]},
        ]
        if details_text:
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": details_text}})
        if snippet:
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"```{snippet}```"}})
        payload = {"text": title, "blocks": blocks}
        response = requests.post(SLACK_WEBHOOK_URL, json=payload)
        if response.status_code != 200:
            print(f"⚠️ Slack error: {response.status_code} {response.text}")
    except Exception as e:
        print(f"⚠️ Exception sending Slack alert: {e}")

def check_error_rate():
    if not recent_statuses:
        return 0.0
    error_count = sum(1 for s in recent_statuses if s.startswith("5"))
    return (error_count / len(recent_statuses)) * 100

def derive_pool(log_dict):
    pool = log_dict.get("pool")
    if pool:
        return pool
    # Fallback to using the final upstream address as identity when pool header is absent
    final_upstream = get_final_upstream_addr(log_dict)
    if final_upstream:
        return final_upstream
    return None


def split_csv_field(value):
    if value is None:
        return []
    return [part.strip() for part in str(value).split(',') if part.strip()]


def get_final_upstream_addr(log_dict):
    statuses = split_csv_field(log_dict.get("upstream_status"))
    addrs = split_csv_field(log_dict.get("upstream_addr"))
    if addrs and len(addrs) == len(statuses) and len(addrs) > 0:
        # Return the addr corresponding to the final upstream status (last attempt)
        return addrs[-1]
    # If lengths mismatch, fallback to last addr if present
    if addrs:
        return addrs[-1]
    return None


def is_error_request(log_dict):
    # Consider an error if final status is 5xx OR any upstream attempt had 5xx
    status = str(log_dict.get("status", ""))
    if status.startswith("5"):
        return True
    for s in split_csv_field(log_dict.get("upstream_status")):
        if s and str(s).strip().startswith("5"):
            return True
    return False


def follow_file(path):
    try:
        with open(path, "r") as f:
            f.seek(0, os.SEEK_END)
            while True:
                if MAINTENANCE_MODE:
                    time.sleep(10)
                    continue
                line = f.readline()
                if not line:
                    time.sleep(0.2)
                    continue
                yield line
    except FileNotFoundError:
        print(f"⚠️ Log file not found: {path}")
        while True:
            time.sleep(5)
            try:
                with open(path, "r") as f:
                    f.seek(0, os.SEEK_END)
                    break
            except FileNotFoundError:
                print(f"Waiting for log file at {path}...")
                continue
        yield from follow_file(path)


def follow_stdin():
    # Yield lines from stdin (non-blocking when no data available yet)
    # We use select to avoid busy-waiting
    print("Reading logs from stdin...")
    while True:
        if MAINTENANCE_MODE:
            time.sleep(10)
            continue
        rlist, _, _ = select.select([sys.stdin], [], [], 0.5)
        if sys.stdin in rlist:
            line = sys.stdin.readline()
            if not line:
                time.sleep(0.2)
                continue
            yield line
        else:
            # no input available
            continue


def choose_stream():
    # Decide between stdin and file tailing
    if LOG_INPUT == "stdin":
        return follow_stdin()
    if LOG_INPUT == "file":
        return follow_file(LOG_PATH)
    # auto mode: always prefer file tailing in containers; stdin is rarely piped
    # If you need stdin, set LOG_INPUT=stdin explicitly.
    return follow_file(LOG_PATH)


def format_log_snippet(log_dict):
    # Select key fields for human-friendly context
    fields = {
        "time": log_dict.get("time"),
        "pool": derive_pool(log_dict) or log_dict.get("pool"),
        "status": log_dict.get("status"),
        "upstream_status": log_dict.get("upstream_status"),
        "release": log_dict.get("release"),
        "request_time": log_dict.get("request_time"),
        "upstream_response_time": log_dict.get("upstream_response_time"),
        "uri": log_dict.get("uri"),
        "upstream_addr": log_dict.get("upstream_addr"),
    }
    # Compact JSON representation
    try:
        return json.dumps(fields, indent=2)
    except Exception:
        return str(fields)


def now_iso8601():
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime())


def main():
    parser = argparse.ArgumentParser(description="Nginx log watcher for Slack alerts")
    parser.add_argument("--test-alert", action="store_true", help="Send a test alert and exit")
    args = parser.parse_args()

    global last_seen_pool

    if args.test_alert:
        send_slack_alert("✅ Test alert from alert_watcher: configuration OK")
        return

    print(f"Starting watcher... Source={LOG_INPUT} Path={LOG_PATH}")
    stream = choose_stream()
    for line in stream:
        line = line.strip()
        if not line:
            continue

        log = parse_log_line(line)
        if not log:
            continue

        pool = derive_pool(log)
        status = str(log.get("status", ""))
        recent_logs.append(log)

        if pool and pool != last_seen_pool and should_send_alert():
            snippet = format_log_snippet(log)
            prev = last_seen_pool if last_seen_pool is not None else "unknown"
            send_slack_blocks(
                title="⚠️ Failover detected",
                details_dict={
                    "from": prev,
                    "to": pool,
                },
                snippet=snippet,
            )
            last_seen_pool = pool

        # Track status window; treat request as 5xx if upstream chain had any 5xx
        if is_error_request(log):
            recent_statuses.append("5xx")
        else:
            recent_statuses.append(status)
        error_rate = check_error_rate()
        if error_rate >= ERROR_RATE_THRESHOLD and should_send_alert():
            # Use the most recent error entry as the single snippet for readability
            last_error = None
            for entry in reversed(recent_logs):
                if str(entry.get("status", "")).startswith("5") or is_error_request(entry):
                    last_error = entry
                    break
            snippet_block = format_log_snippet(last_error or log)
            send_slack_blocks(
                title="⚠️ High error rate",
                details_dict={
                    "error_rate": f"{error_rate:.2f}%",
                    "window": len(recent_statuses),
                    "threshold": f"{ERROR_RATE_THRESHOLD}%",
                },
                snippet=snippet_block,
            )


if __name__ == "__main__":
    main()