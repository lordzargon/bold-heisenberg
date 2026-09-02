"""
ASGC Technical Artist Job Monitor
Checks https://jobs.asgc.gg/ for new Technical Artist postings and sends notifications.
"""

import os
import sys
import json
import gzip
import urllib.request
import urllib.parse
import urllib.error
import argparse
import datetime
import subprocess
try:
    from geo_utils import evaluate_location_rules
except ImportError:
    evaluate_location_rules = None

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
    try:
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.json")
API_URL = "https://jobs.asgc.gg/api/job-listings"

DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip',
    'Referer': 'https://jobs.asgc.gg/',
    'Sec-Ch-Ua': '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    'Sec-Ch-Ua-Mobile': '?0',
    'Sec-Ch-Ua-Platform': '"Windows"',
    'Sec-Fetch-Dest': 'empty',
    'Sec-Fetch-Mode': 'cors',
    'Sec-Fetch-Site': 'same-origin',
}

def load_config():
    target_path = CONFIG_PATH
    if not os.path.exists(target_path):
        example_path = os.path.join(SCRIPT_DIR, "config.example.json")
        if os.path.exists(example_path):
            target_path = example_path
    if os.path.exists(target_path):
        try:
            with open(target_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[!] Warning reading config ({target_path}): {e}")
    return {
        "search": {
            "keywords": [
                "technical artist",
                "tech artist",
                "technical art",
                "character technical artist",
                "character tech artist",
                "technical animator",
                "tech anim",
                "pipeline technical director",
                "pipeline td",
                "art td",
                "art technical director",
                "technical art director",
                "tools artist",
                "tools engineer",
                "tools programmer",
                "tools developer",
                "pipeline engineer",
                "pipeline developer",
                "vfx technical artist",
                "vfx tech artist",
                "shader artist",
                "shader engineer",
                "shader programmer",
                "shader developer",
                "rendering engineer",
                "rendering programmer",
                "graphics engineer",
                "graphics programmer",
                "graphics technical artist",
                "graphics tech artist",
                "performance engineer",
                "optimization engineer",
                "lighting technical artist",
                "technical lighting artist",
                "rigging artist",
                "rigging technical artist",
                "rigger",
                "environment technical artist"
            ],
            "exclude_keywords": [
                "unpaid",
                "subsea",
                "civil engineer",
                "oil and gas",
                "drilling"
            ],
            "location_filter": [],
            "remote_only": False
        },
        "notifications": {
            "windows_toast": True,
            "discord_webhook_url": "",
            "telegram": {"enabled": False, "bot_token": "", "chat_id": ""},
            "slack_webhook_url": ""
        },
        "database_file": "seen_jobs.json"
    }

def get_db_path(config):
    db_file = config.get("database_file", "seen_jobs.json")
    if not os.path.isabs(db_file):
        db_file = os.path.join(SCRIPT_DIR, db_file)
    return db_file

def load_seen_jobs(db_path):
    if os.path.exists(db_path):
        try:
            with open(db_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return set(data)
                elif isinstance(data, dict):
                    return set(data.get("seen_ids", []))
        except Exception as e:
            print(f"[!] Warning reading seen jobs DB: {e}")
    return set()

def save_seen_jobs(db_path, seen_ids):
    data = {
        "last_updated": datetime.datetime.now().isoformat(),
        "total_seen": len(seen_ids),
        "seen_ids": list(seen_ids)
    }
    with open(db_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def fetch_jobs():
    print(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Fetching jobs from ASGC...")
    req = urllib.request.Request(API_URL, headers=DEFAULT_HEADERS)
    with urllib.request.urlopen(req, timeout=60) as resp:
        content = resp.read()
        enc = resp.info().get('Content-Encoding')
        if enc == 'gzip' or (len(content) > 2 and content[:2] == b'\x1f\x8b'):
            content = gzip.decompress(content)
        data = json.loads(content.decode('utf-8'))
        if isinstance(data, dict) and 'rows' in data:
            return data['rows']
        return data

def matches_filters(job, search_config):
    title = (job.get('title') or '').strip()
    category = (job.get('overallCategory') or '').strip()
    company = (job.get('companyName') or '').strip()
    country = (job.get('country') or '').strip()
    location_type = (job.get('locationType') or '').strip()
    
    full_text = f"{title} {category} {company}".lower()
    
    # 0. Exclude companies check
    exclude_companies = [c.lower().strip() for c in search_config.get("exclude_companies", []) if c.strip()]
    if exclude_companies:
        if any(c in company.lower() for c in exclude_companies):
            return False

    # 1. Keyword check
    keywords = [k.lower().strip() for k in search_config.get("keywords", []) if k.strip()]
    if keywords:
        if not any(k in full_text for k in keywords):
            return False
            
    # 2. Exclude keywords check
    exclude_keywords = [k.lower().strip() for k in search_config.get("exclude_keywords", []) if k.strip()]
    if any(k in full_text for k in exclude_keywords):
        return False
        
    # 3. Location rules & distance check
    if evaluate_location_rules is not None:
        loc_match, _ = evaluate_location_rules(
            job,
            location_rules=search_config.get("location_rules", []),
            legacy_location_filter=search_config.get("location_filter", []),
            legacy_remote_only=search_config.get("remote_only", False)
        )
        if not loc_match:
            return False
    else:
        # Fallback legacy checks
        if search_config.get("remote_only", False):
            if "remote" not in location_type.lower():
                return False
                
        locations = [loc.lower() for loc in search_config.get("location_filter", []) if loc.strip()]
        if locations:
            loc_text = f"{country} {location_type} {job.get('city', '')} {job.get('state', '')}".lower()
            if not any(loc in loc_text for loc in locations):
                return False

    return True

# --- Notifications ---

def show_standalone_toast(title, message, url=None, duration=8):
    """
    Renders a standalone floating popup toast in the bottom-right corner.
    Bypasses Windows Notification Service (WNS) and Action Center entirely,
    making it 100% reliable on debloated or customized Windows installs.
    """
    try:
        import tkinter as tk
        import webbrowser
        import threading
        import time

        def _run():
            try:
                root = tk.Tk()
                root.overrideredirect(True)
                root.attributes("-topmost", True)
                root.attributes("-alpha", 0.0)

                card_bg = "#21252b"
                fg_title = "#61afef"
                fg_text = "#abb2bf"
                btn_bg = "#98c379"
                btn_fg = "#1e1e1e"

                frame = tk.Frame(root, bg=card_bg, highlightthickness=1, highlightbackground="#3e4451", padx=16, pady=12)
                frame.pack(fill="both", expand=True)

                lbl_title = tk.Label(frame, text=title, font=("Segoe UI", 10, "bold"), fg=fg_title, bg=card_bg, anchor="w")
                lbl_title.pack(fill="x")

                lbl_msg = tk.Label(frame, text=message, font=("Segoe UI", 9), fg=fg_text, bg=card_bg, justify="left", anchor="w", wraplength=280)
                lbl_msg.pack(fill="x", pady=(4, 8))

                btn_frame = tk.Frame(frame, bg=card_bg)
                btn_frame.pack(fill="x")

                def open_url(event=None):
                    if url:
                        webbrowser.open(url)
                    root.destroy()

                if url:
                    btn_open = tk.Button(btn_frame, text="View Job ↗", font=("Segoe UI", 9, "bold"), bg=btn_bg, fg=btn_fg,
                                         activebackground="#98c379", activeforeground="#000000", bd=0, padx=10, pady=3,
                                         cursor="hand2", command=open_url)
                    btn_open.pack(side="left")

                btn_close = tk.Button(btn_frame, text="Dismiss", font=("Segoe UI", 8), bg="#3e4451", fg="#abb2bf",
                                      activebackground="#4b5263", activeforeground="#ffffff", bd=0, padx=8, pady=3,
                                      cursor="hand2", command=root.destroy)
                btn_close.pack(side="right")

                root.update_idletasks()
                width = 320
                height = frame.winfo_reqheight()

                screen_width = root.winfo_screenwidth()
                screen_height = root.winfo_screenheight()

                x = screen_width - width - 24
                y = screen_height - height - 50

                root.geometry(f"{width}x{height}+{x}+{y}")

                for i in range(1, 11):
                    root.attributes("-alpha", i / 10.0)
                    root.update()
                    time.sleep(0.015)

                def auto_close():
                    time.sleep(duration)
                    try:
                        for i in range(10, -1, -1):
                            root.attributes("-alpha", i / 10.0)
                            root.update()
                            time.sleep(0.015)
                        root.destroy()
                    except Exception:
                        pass

                threading.Thread(target=auto_close, daemon=True).start()
                root.mainloop()
            except Exception as e:
                print(f"[!] Toast window error: {e}")

        t = threading.Thread(target=_run)
        t.start()
        return t
    except Exception as e:
        print(f"[!] Failed to launch popup: {e}")
        return None

def send_windows_toast(title, message, link=None):
    # Try native Windows toast via PowerShell
    try:
        safe_title = title.replace('"', '`"').replace('$', '`$')
        safe_msg = message.replace('"', '`"').replace('$', '`$')
        safe_link = (link or '').replace('"', '`"').replace('$', '`$')
        
        ps_script = f'''
        [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
        [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] > $null
        $template = @"
        <toast launch="{safe_link}">
            <visual>
                <binding template="ToastGeneric">
                    <text>{safe_title}</text>
                    <text>{safe_msg}</text>
                </binding>
            </visual>
            <actions>
                <action content="View Job" arguments="{safe_link}" activationType="protocol"/>
            </actions>
        </toast>
"@
        $xml = New-Object Windows.Data.Xml.Dom.XmlDocument
        $xml.LoadXml($template)
        $toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
        $notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("ASGC Job Monitor")
        $notifier.Show($toast)
        '''
        res = subprocess.run(["powershell", "-NoProfile", "-Command", ps_script], capture_output=True, text=True)
    except Exception as e:
        pass
    
    # Also show the standalone popup which works on debloated/custom Windows
    show_standalone_toast(title, message, link)

def send_discord_webhook(webhook_url, new_jobs):
    if not webhook_url:
        return
    try:
        embeds = []
        for job in new_jobs[:10]:  # Discord limit: max 10 embeds per message
            title = job.get('title', 'Unknown Title')
            company = job.get('companyName', 'Unknown Studio')
            link = job.get('jobLink') or job.get('applyLink') or job.get('url') or ''
            loc = f"{job.get('locationType', '')} • {job.get('country', '')}".strip(" •")
            exp = job.get('experienceDisplay') or job.get('experienceRange') or 'Not specified'
            date = job.get('activatedDate', '')

            embeds.append({
                "title": f"🎨 {title}",
                "url": link,
                "color": 3066993,  # Teal/Blue
                "fields": [
                    {"name": "Studio", "value": company, "inline": True},
                    {"name": "Location", "value": loc or "N/A", "inline": True},
                    {"name": "Experience", "value": exp, "inline": True},
                    {"name": "Posted / Activated", "value": date or "Recently", "inline": True}
                ],
                "footer": {"text": "ASGC Job Monitor • Technical Artist Tracker"}
            })

        payload = {
            "content": f"🔔 **{len(new_jobs)} new Technical Artist job(s) found on ASGC!**",
            "embeds": embeds
        }
        
        req = urllib.request.Request(
            webhook_url,
            data=json.dumps(payload).encode('utf-8'),
            headers={'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            pass
        print(f"[+] Sent Discord notification for {len(new_jobs)} jobs.")
    except Exception as e:
        print(f"[!] Failed to send Discord webhook: {e}")

def send_slack_webhook(webhook_url, new_jobs):
    if not webhook_url:
        return
    try:
        blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"🎨 {len(new_jobs)} New Technical Artist Jobs Found!"}
            }
        ]
        for job in new_jobs[:10]:
            title = job.get('title', 'Unknown')
            company = job.get('companyName', 'Unknown Studio')
            link = job.get('jobLink') or job.get('applyLink') or job.get('url') or ''
            loc = f"{job.get('locationType', '')} • {job.get('country', '')}".strip(" •")
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*<{link}|{title}>* at *{company}*\n📍 {loc}"
                }
            })

        req = urllib.request.Request(
            webhook_url,
            data=json.dumps({"blocks": blocks}).encode('utf-8'),
            headers={'Content-Type': 'application/json'}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            pass
        print(f"[+] Sent Slack notification for {len(new_jobs)} jobs.")
    except Exception as e:
        print(f"[!] Failed to send Slack webhook: {e}")

def send_telegram_message(bot_token, chat_id, new_jobs):
    if not bot_token or not chat_id:
        return
    try:
        lines = [f"🔔 <b>{len(new_jobs)} new Technical Artist job(s) found!</b>\n"]
        for job in new_jobs[:10]:
            title = job.get('title', 'Unknown')
            company = job.get('companyName', 'Unknown')
            link = job.get('jobLink') or job.get('applyLink') or job.get('url') or ''
            loc = f"{job.get('locationType', '')}, {job.get('country', '')}".strip(", ")
            lines.append(f"• <a href='{link}'><b>{title}</b></a>\n  🏢 {company} | 📍 {loc}\n")
        
        text = "\n".join(lines)
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode('utf-8'),
            headers={'Content-Type': 'application/json'}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            pass
        print(f"[+] Sent Telegram notification for {len(new_jobs)} jobs.")
    except Exception as e:
        print(f"[!] Failed to send Telegram message: {e}")

def notify_all(config, new_jobs):
    notifs = config.get("notifications", {})
    
    # 1. Console display
    print(f"\n[!] Found {len(new_jobs)} new matching job(s):")
    for j in new_jobs:
        title = j.get('title')
        company = j.get('companyName')
        loc = f"{j.get('locationType', '')}, {j.get('country', '')}".strip(", ")
        link = j.get('jobLink') or j.get('applyLink') or j.get('url') or ''
        print(f"  * [{j.get('activatedDate', 'New')}] {title} @ {company} ({loc})")
        print(f"    Link: {link}")
    print()

    # 2. Windows Toast / Desktop Popup
    if notifs.get("windows_toast", True) and new_jobs:
        if len(new_jobs) == 1:
            job = new_jobs[0]
            send_windows_toast(
                title=f"New Job: {job.get('title')}",
                message=f"{job.get('companyName')} • {job.get('locationType', '')} ({job.get('country', '')})",
                link=job.get('jobLink') or job.get('applyLink') or job.get('url')
            )
        else:
            first = new_jobs[0]
            send_windows_toast(
                title=f"{len(new_jobs)} New Technical Artist Jobs!",
                message=f"Latest: {first.get('title')} at {first.get('companyName')}",
                link=first.get('jobLink') or first.get('applyLink') or first.get('url')
            )

    # 3. Discord
    if notifs.get("discord_webhook_url"):
        send_discord_webhook(notifs["discord_webhook_url"], new_jobs)

    # 4. Slack
    if notifs.get("slack_webhook_url"):
        send_slack_webhook(notifs["slack_webhook_url"], new_jobs)

    # 5. Telegram
    tg = notifs.get("telegram", {})
    if tg.get("enabled") and tg.get("bot_token") and tg.get("chat_id"):
        send_telegram_message(tg["bot_token"], tg["chat_id"], new_jobs)

def main():
    parser = argparse.ArgumentParser(description="ASGC Technical Artist Job Monitor")
    parser.add_argument("--init", action="store_true", help="Initialize database with all current jobs without sending notifications")
    parser.add_argument("--dry-run", action="store_true", help="Check for jobs without updating seen jobs database")
    parser.add_argument("--test-notify", action="store_true", help="Send a test notification across enabled channels")
    args = parser.parse_args()

    config = load_config()
    db_path = get_db_path(config)

    if args.test_notify:
        print("[*] Sending test notification...")
        sample_job = {
            "id": 99999999,
            "title": "Senior Technical Artist (Test Notification)",
            "companyName": "Sample Games Studio",
            "locationType": "Remote",
            "country": "Worldwide",
            "experienceDisplay": "3-5 yrs",
            "activatedDate": datetime.date.today().strftime("%d %b %Y"),
            "jobLink": "https://job-boards.greenhouse.io/sample/jobs/123456"
        }
        notify_all(config, [sample_job])
        return

    seen_ids = load_seen_jobs(db_path)
    is_first_run = len(seen_ids) == 0 and not os.path.exists(db_path)

    try:
        all_jobs = fetch_jobs()
    except Exception as e:
        print(f"[!] Failed to fetch job listings: {e}")
        sys.exit(1)

    print(f"Total listings fetched: {len(all_jobs)}")

    # Filter matching jobs
    matching_jobs = [j for j in all_jobs if matches_filters(j, config.get("search", {}))]
    print(f"Matching search criteria: {len(matching_jobs)}")

    if args.init or is_first_run:
        all_match_ids = {str(j.get('id')) for j in all_jobs if j.get('id')}
        save_seen_jobs(db_path, all_match_ids)
        print(f"[OK] Initialized seen jobs database ({len(all_match_ids)} total jobs recorded).")
        print("[OK] Future runs will now alert on any new postings!")
        return

    # Identify new jobs
    new_jobs = []
    for job in matching_jobs:
        job_id = str(job.get('id'))
        if job_id and job_id not in seen_ids:
            new_jobs.append(job)

    if new_jobs:
        notify_all(config, new_jobs)
        if not args.dry_run:
            for job in new_jobs:
                job_id = str(job.get('id'))
                if job_id:
                    seen_ids.add(job_id)
            save_seen_jobs(db_path, seen_ids)
            print(f"[OK] Database updated with {len(new_jobs)} new jobs.")
    else:
        print(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] No new Technical Artist jobs found.")

if __name__ == "__main__":
    main()
