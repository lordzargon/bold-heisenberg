# Game Dev Automated Job Monitor 🎮

A zero-dependency job tracker and career crawler designed for **Game Developers across all disciplines** (Programming, Art, Tech Art, Design, Production, Audio, and QA). 

It continuously monitors direct game studio career portals (Greenhouse, Lever, Ashby, direct web) and Amir Satvat's global Looker Studio / ASGC board (41,000+ game industry postings), filtering for matching openings and delivering desktop notifications, Discord embeds, Telegram messages, or Slack alerts.

---

## ⚡ Key Highlights

- **Interactive Web GUI (`launch_gui.bat` / `web_app.py`)**:
  - **Visual Configuration**: Manage target job keywords, exclusion phrases, and studio blocklists with an interactive tag manager and game dev discipline presets.
  - **Live Search**: Scans live studio career portals and the Amir Satvat / ASGC Looker Studio database on demand, displaying matches in sortable cards and table views.
  - **Export & Filter**: Instant filtering, direct application links, and CSV/JSON exports.
  - **Studio Enrichment**: Verify and discover new studio career portals directly from the interface.
- **Dual-Engine Job Discovery**:
  - 🌐 **Amir Satvat / ASGC Games Board**: Live feed of 41,000+ game industry roles from the community [Looker Studio Dashboard](https://lookerstudio.google.com/reporting/2f39b56e-7393-4aa2-9fd5-bf8bf615c95f/page/5koHB).
  - 🏢 **Direct Studio Harvester**: Crawls 360+ verified game studio career sites and ATS portals (*Greenhouse, Lever, Ashby, Workable, etc.*).
- **Zero External Dependencies**: Pure Python 3.8+ standard library (`urllib`, `json`, `re`, `ssl`, `concurrent.futures`, `tkinter`, `http.server`). No `pip install` required!
- **Intelligent Keyword & Exclusion Filtering**: Pre-configured for Technical Art, Rendering/Shaders, Pipeline/Tools Engineering, and Tech Anim/Rigging, with noise filtering (e.g. subsea/civil exclusions).
- **Multiple Notification Channels**:
  - 🖥️ **Desktop Popup Toast** (Native floating window with clickable 1-click apply links).
  - 💬 **Discord Webhooks** (Rich formatted cards with studio names, location, and metadata).
  - 📱 **Telegram & Slack** bot integration.
- **Run Anywhere**:
  - 🪟 **Windows**: 1-Click Task Scheduler registration (`ensure_running.bat` or `setup_scheduler.ps1`).
  - 🍎 **macOS / 🐧 Linux**: Native `cron` setup.
  - ☁️ **GitHub Actions**: 100% cloud-hosted with zero local uptime needed.

---

## 🚀 Quick Start (Under 2 Minutes)

### Option 1: 1-Click Interactive Web GUI (Recommended)
Double-click **`launch_gui.bat`** (or run `python web_app.py` in terminal).
- Opens the configuration & live search interface in your browser at `http://127.0.0.1:8765`.
- Edit keywords, exclusions, companies to avoid, and alert channels.
- Click **"Save Settings"** to persist to `config.json`.
- Click **"Search Now"** to instantly query all matching game dev jobs!

---

### Option 2: CLI Setup & Configuration
1. Copy the example configuration file:
```bash
# Windows PowerShell / CMD:
copy config.example.json config.json

# macOS / Linux:
cp config.example.json config.json
```

2. Edit `config.json` to customize your search keywords, location preferences, or notification webhooks (e.g. Discord, Telegram).

3. Test Notifications:
```bash
python career_monitor.py --test-notify
```

---

## ⏰ Automated Scheduling & Running

### Option A: Windows 1-Click Background Setup (Recommended for Windows)

Double-click **`ensure_running.bat`** or run in PowerShell:
```powershell
powershell -ExecutionPolicy Bypass -File .\setup_scheduler.ps1
```
> This registers a silent background task (`GamesMap_Career_JobMonitor`) to run daily at your configured times (defaults: **9:00 AM**, **1:00 PM** lunchtime, and **6:00 PM**). You can customize or add any times via `config.json` or the Web GUI.

### Option B: macOS / Linux (`cron`)

Open your crontab:
```bash
crontab -e
```
Add an entry to run twice daily at 9:00 AM and 6:00 PM:
```bash
0 9,18 * * * cd /path/to/game-dev-job-monitor && /usr/bin/python3 career_monitor.py >> monitor.log 2>&1
```

### Option C: Free GitHub Actions Cloud Runner (No local computer needed)

You can run this monitor 100% in the cloud for free using GitHub Actions:
1. Fork or push this repository to your GitHub account.
2. In your repo settings, go to **Settings > Secrets and variables > Actions > New repository secret**.
3. Add `DISCORD_WEBHOOK_URL` as a secret containing your Discord channel webhook URL.
4. The workflow in `.github/workflows/job_monitor.yml` will automatically run twice daily and push any new alerts straight to your Discord!

---

## ⚙️ Configuration Guide (`config.json`)

```json
{
  "search": {
    "keywords": [
      "technical artist",
      "tech artist",
      "technical art",
      "character technical artist",
      "technical animator",
      "pipeline technical director",
      "pipeline td",
      "tools engineer",
      "tools programmer",
      "pipeline engineer",
      "vfx technical artist",
      "shader artist",
      "shader engineer",
      "rendering engineer",
      "rendering programmer",
      "graphics engineer",
      "graphics programmer",
      "rigging artist",
      "rigger"
    ],
    "exclude_keywords": [
      "unpaid",
      "subsea",
      "civil engineer",
      "oil and gas"
    ],
    "location_rules": [
      {
        "id": "rule_remote_eu",
        "enabled": true,
        "mode": "remote",
        "target": "Europe",
        "max_distance_miles": null,
        "description": "Remote in Europe"
      },
      {
        "id": "rule_hybrid_london",
        "enabled": true,
        "mode": "hybrid",
        "target": "London",
        "max_distance_miles": 30,
        "description": "Hybrid within 30 miles of London"
      },
      {
        "id": "rule_onsite_cambridge",
        "enabled": true,
        "mode": "on_site",
        "target": "Cambridge",
        "max_distance_miles": 20,
        "description": "On-site within 20 miles of Cambridge"
      }
    ],
    "location_filter": [],
    "remote_only": false
  },
  "notifications": {
    "windows_toast": true,
    "discord_webhook_url": "https://discord.com/api/webhooks/YOUR_WEBHOOK_URL",
    "telegram": {
      "enabled": false,
      "bot_token": "",
      "chat_id": ""
    },
    "slack_webhook_url": ""
  },
  "schedule": {
    "enabled": true,
    "times": [
      "09:00",
      "13:00",
      "18:00"
    ]
  }
}
```

### Schedule & Timer Options (`"schedule"`):
- **`times`**: List of 24-hour time strings (`"HH:MM"`) when the automated background monitor scans for new job postings (e.g. `["09:00", "13:00", "18:00"]` for morning, lunchtime, and evening updates).
- **`enabled`**: (`true`/`false`) Master switch to enable or disable background scheduled runs.
- **Timezone Flexibility**: All times trigger in your local computer timezone. You can add as many custom check times as you want (e.g. `["08:00", "12:30", "17:00", "22:00"]`).
- **1-Click Sync**: Manage times visually via the Web GUI (`launch_gui.bat`) and click **"Apply to Windows Task Scheduler"** to instantly update your system triggers.

### Location & Distance Rules:
- **`mode`**: `remote`, `hybrid`, `on_site`, or `any`.
- **`target`**: Target city, country, or region (e.g., `London`, `Cambridge`, `Europe`, `UK`, `Worldwide`).
- **`max_distance_miles`**: Distance radius in miles computed via Great-Circle Haversine formula (e.g. `30` miles from London matches Guildford). Set `null` for region or exact match.
- **`enabled`**: Quickly toggle rules on/off.
- Multi-rule support: A job passes if it matches **any** of your active rules.

### Notification Options:
- **`windows_toast`**: (`true`/`false`) Displays a floating, non-intrusive desktop card in the lower-right corner of your screen when a new job appears.
- **`discord_webhook_url`**: Paste your Discord Webhook URL to get formatted embeds in your server.
- **`telegram`**: Enable Telegram bot notifications by supplying your `bot_token` and `chat_id`.
- **`slack_webhook_url`**: Paste an incoming Slack Webhook URL.

---

## 🛠️ CLI Reference

| Command | Description |
| :--- | :--- |
| `python career_monitor.py` | Scans studio career pages for new job postings |
| `python career_monitor.py --dry-run` | Runs a scan without recording jobs to `seen_career_jobs.json` |
| `python career_monitor.py --init` | Marks all existing jobs as "seen" (prevents an initial alert flood) |
| `python career_monitor.py --test-notify` | Sends a mock test alert across all enabled notification channels |
| `python job_monitor.py` | Runs the ASGC global job aggregator check |
| `python gamesmap_scraper.py --status` | Shows status & counts of scraped UK studio websites and career portals |
| `python gamesmap_scraper.py --enrich` | Re-checks and updates studio ATS career links |

---

## 📄 License

MIT License - feel free to fork, customize, and share!
