"""
Career Opportunity Agent v3 — Multi-User Edition
--------------------------------------------------
Sources:
• DuckDuckGo Search
• Adzuna API (free, India jobs)
• JSearch RapidAPI (LinkedIn/Indeed scraper)
• Remotive API (no key, remote tech jobs)
• Arbeitnow API (no key, remote jobs)
• The Muse API (no key, entry level jobs)
​
LLM      → Groq (free tier, llama-3.3-70b-versatile)
Delivery → Telegram Bot API (free)
​
New in v3:
✅ Multi-user support  — /start to subscribe, /stop to unsubscribe
✅ All subscribers get daily job notifications automatically
✅ Resume match score  — Groq scores each job 0-100 vs your resume
✅ Duplicate filter    — seen.json skips already-sent jobs
✅ Apply tracker       — /applied /saved /skip /status via Telegram bot
✅ Deadline alerts     — 48hr reminders for saved jobs
"""
​
import os
import json
import time
import sqlite3
import logging
import httpx
from datetime import datetime, timedelta
from dotenv import load_dotenv
from ddgs import DDGS
from groq import Groq
​
load_dotenv()
​
# ─── Logging ───────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("agent.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)
​
​
# ─── Config ─────────────────────────────────────────────
GROQ_API_KEY       = os.getenv("GROQ_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")   # kept as fallback/admin
ADZUNA_APP_ID      = os.getenv("ADZUNA_APP_ID", "")
ADZUNA_APP_KEY     = os.getenv("ADZUNA_APP_KEY", "")
JSEARCH_API_KEY    = os.getenv("JSEARCH_API_KEY", "")
​
# ── File paths ─────────────────────────────────────────
SUBSCRIBERS_FILE = "subscribers.json"
SEEN_FILE        = "seen.json"
DB_FILE          = "tracker.db"
CARD_MAP_FILE    = "card_map.json"
​
# ── Job filtering ──────────────────────────────────────
RESUME_MATCH_THRESHOLD = 55
SEND_TOP_N             = 10
SEARCH_RESULTS         = 5
DELAY_BETWEEN          = 2.0
​
ROLES = [
    "SDE Intern", "Software Engineer Intern", "Backend Developer Intern",
    "Frontend Developer Intern", "Full Stack Developer Intern",
    "ML Engineer Intern", "Data Science Intern", "DevOps Intern",
    "Cloud Engineer Intern", "Software Engineer Fresher",
    "Backend Developer Fresher", "Full Stack Developer Fresher",
    "Data Engineer Fresher", "ML Engineer Fresher",
    "DevOps Engineer Fresher", "Associate Software Engineer",
    "Graduate Engineer Trainee",
]
​
SKILLS = [
    "Java", "Python", "C++", "JavaScript", "TypeScript",
    "React", "Node.js", "Spring Boot", "Django", "FastAPI",
    "DSA", "REST API", "SQL", "MySQL", "PostgreSQL", "MongoDB",
    "AWS", "GCP", "Azure", "Docker", "Kubernetes", "CI/CD",
    "Machine Learning", "Deep Learning", "TensorFlow", "PyTorch",
    "Git", "Linux", "System Design",
]
​
SEARCH_QUERIES = [
    "SDE intern 2026 2027 fresher apply now India",
    "software engineer intern India 2026 stipend apply",
    "backend developer intern India 2026 Java Python hiring",
    "frontend developer intern React JavaScript India 2026",
    "full stack developer intern India 2026 apply now",
    "ML AI intern fresher India 2026 apply",
    "data science intern India 2026 fresher hiring",
    "devops cloud intern India 2026 AWS Docker apply",
    "software engineer fresher job India 2026 hiring",
    "associate software engineer fresher India 2025 2026 apply",
    "graduate engineer trainee CSE India 2026 hiring",
    "product company fresher software engineer India 2026",
    "startup SDE fresher hiring India Bangalore 2026",
    "fintech SDE intern fresher India 2026 Java Python",
    "off campus drive CSE 2026 batch software engineer India",
    "site:internshala.com software developer intern 2026",
    "site:unstop.com software engineer fresher hiring 2026",
    "site:linkedin.com/jobs SDE intern fresher India 2026",
    "site:naukri.com fresher software engineer 2026 India",
    "site:hirist.tech SDE intern fresher India 2026",
    "site:cutshort.io software engineer fresher India 2026",
    "site:freshersworld.com software engineer 2026 apply",
    "site:foundit.in software engineer fresher 2026 India",
    "site:wellfound.com SDE intern fresher India 2026",
]
​
# ── Resume text ──────────────────────────────────────────
RESUME_TEXT = """
Lokesh Bosani — B.Tech CSE, Saveetha School of Engineering, 2027 batch. CGPA 8.68.
Oracle certified Java SE 11 and Database SQL.
Internships: AI Intern and Full Stack Developer Intern at Eduexpose.
Skills: Java, Python, JavaScript, Flask, REST APIs, MySQL, Scikit-learn, XGBoost,
HTML, CSS, Spring Boot basics, Git, Selenium, Telegram Bot API.
Projects: PhishGuard (XGBoost + Flask phishing detection API),
Enrollment Agent (Selenium + Telegram real-time portal monitor, deployed on Render),
Student Performance Predictor (multi-model ML pipeline),
CodeSentinel (multi-agent code review, CrewAI + Groq).
Certifications: Oracle Java SE 11, Oracle Database SQL.
Looking for: SDE Intern, Software Engineer Fresher, Backend Developer, Full Stack Developer,
ML Engineer roles at fintech or product companies in India.
"""
​
​
# ═════════════════════════════════════════════════════════════════════════
# TELEGRAM HELPERS
# ═════════════════════════════════════════════════════════════════════════
​
def escape_md(text: str) -> str:
    """Escape Telegram MarkdownV2 special characters."""
    if text is None:
        return ""
    text = str(text)
    special = r"_*[]()~`>#+-=|{}.!"
    return "".join("\\" + ch if ch in special else ch for ch in text)
​
​
def send_message(chat_id: str, text: str, parse_mode: str = "MarkdownV2",
                 disable_preview: bool = True) -> bool:
    """Send a single Telegram message. Returns True on success."""
    if not TELEGRAM_BOT_TOKEN:
        log.warning("No TELEGRAM_BOT_TOKEN set — cannot send.")
        return False
​
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": disable_preview,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
​
    try:
        r = httpx.post(url, json=payload, timeout=15)
        if r.status_code != 200:
            log.warning("Telegram send failed (%s): %s", r.status_code, r.text)
            # Retry once without parse_mode in case of formatting errors
            payload.pop("parse_mode", None)
            r = httpx.post(url, json=payload, timeout=15)
        return r.status_code == 200
    except Exception as e:
        log.warning("Telegram send error: %s", e)
        return False
​
​
def broadcast(text: str, parse_mode: str = "MarkdownV2") -> None:
    """Send a message to every subscriber."""
    subs = load_subscribers()
    if not subs:
        log.info("No subscribers to broadcast to.")
        return
    for chat_id in subs:
        send_message(chat_id, text, parse_mode=parse_mode)
        time.sleep(0.3)  # gentle rate-limit
​
​
# ═════════════════════════════════════════════════════════════════════════
# MULTI-USER: Subscriber Management
# Users /start the bot to subscribe, /stop to unsubscribe.
# Their chat_id is saved to subscribers.json and used for all broadcasts.
# ═════════════════════════════════════════════════════════════════════════
​
def load_subscribers() -> set:
    """Load all subscribed chat IDs from file."""
    if os.path.exists(SUBSCRIBERS_FILE):
        with open(SUBSCRIBERS_FILE, "r") as f:
            data = json.load(f)
        return set(str(cid) for cid in data)
    # Seed with the owner's chat ID from env so they always get notifs
    if TELEGRAM_CHAT_ID:
        save_subscribers({str(TELEGRAM_CHAT_ID)})
        return {str(TELEGRAM_CHAT_ID)}
    return set()
​
​
def save_subscribers(subscribers: set) -> None:
    """Persist subscriber list to file."""
    with open(SUBSCRIBERS_FILE, "w") as f:
        json.dump(list(subscribers), f)
​
​
def add_subscriber(chat_id: str) -> bool:
    """Add a user. Returns True if newly added, False if already subscribed."""
    subs = load_subscribers()
    if str(chat_id) in subs:
        return False
    subs.add(str(chat_id))
    save_subscribers(subs)
    log.info("New subscriber: %s (total: %d)", chat_id, len(subs))
    return True
​
​
def remove_subscriber(chat_id: str) -> bool:
    """Remove a user. Returns True if removed, False if wasn't subscribed."""
    subs = load_subscribers()
    if str(chat_id) not in subs:
        return False
    subs.discard(str(chat_id))
    save_subscribers(subs)
    log.info("Unsubscribed: %s (total: %d)", chat_id, len(subs))
    return True
​
​
def poll_and_handle_commands() -> None:
    """
    Poll Telegram for new messages and handle bot commands.
    Processes: /start, /stop, /status, /applied <id>, /saved <id>, /skip <id>
    Saves the last processed update_id to avoid reprocessing.
    """
    offset_file = "telegram_offset.json"
    offset = 0
    if os.path.exists(offset_file):
        with open(offset_file) as f:
            offset = json.load(f).get("offset", 0)
​
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
        r = httpx.get(url, params={"offset": offset, "timeout": 5}, timeout=10)
        updates = r.json().get("result", [])
    except Exception as e:
        log.warning("Telegram poll failed: %s", e)
        return
​
    for update in updates:
        offset = update["update_id"] + 1
        msg = update.get("message", {})
        chat_id = str(msg.get("chat", {}).get("id", ""))
        text = msg.get("text", "").strip()
​
        if not chat_id or not text:
            continue
​
        log.info("Command from %s: %s", chat_id, text)
​
        if text.startswith("/start"):
            if add_subscriber(chat_id):
                send_message(
                    chat_id,
                    "✅ *You're subscribed\\!*\n\n"
                    "You'll receive daily job notifications every morning\\.\n\n"
                    "Commands:\n"
                    "/stop — unsubscribe\n"
                    "/status — your application stats\n"
                    "/applied \\<id\\> — mark job as applied\n"
                    "/saved \\<id\\> — save job to watchlist\n"
                    "/skip \\<id\\> — skip job",
                )
            else:
                send_message(chat_id, "You're already subscribed\\! I'll send jobs daily 🎯")
​
        elif text.startswith("/stop"):
            if remove_subscriber(chat_id):
                send_message(chat_id, "👋 Unsubscribed\\. Send /start anytime to resubscribe\\.")
            else:
                send_message(chat_id, "You weren't subscribed\\. Send /start to subscribe\\.")
​
        elif text.startswith("/status"):
            send_message(chat_id, get_status_summary(), parse_mode="MarkdownV2")
​
        elif text.startswith("/applied"):
            parts = text.split()
            if len(parts) == 2 and parts[1].isdigit():
                db_id = int(parts[1])
                if update_job_status(db_id, "applied"):
                    send_message(chat_id, f"✅ Job \\#{db_id} marked as *applied*\\!", parse_mode="MarkdownV2")
                else:
                    send_message(chat_id, f"Job \\#{db_id} not found\\.", parse_mode="MarkdownV2")
            else:
                send_message(chat_id, "Usage: /applied \\<job\\_id\\>", parse_mode="MarkdownV2")
​
        elif text.startswith("/saved"):
            parts = text.split()
            if len(parts) == 2 and parts[1].isdigit():
                db_id = int(parts[1])
                if update_job_status(db_id, "saved"):
                    send_message(chat_id, f"🔖 Job \\#{db_id} saved to watchlist\\!", parse_mode="MarkdownV2")
                else:
                    send_message(chat_id, f"Job \\#{db_id} not found\\.", parse_mode="MarkdownV2")
            else:
                send_message(chat_id, "Usage: /saved \\<job\\_id\\>", parse_mode="MarkdownV2")
​
        elif text.startswith("/skip"):
            parts = text.split()
            if len(parts) == 2 and parts[1].isdigit():
                db_id = int(parts[1])
                if update_job_status(db_id, "skip"):
                    send_message(chat_id, f"⏭ Job \\#{db_id} skipped\\.", parse_mode="MarkdownV2")
                else:
                    send_message(chat_id, f"Job \\#{db_id} not found\\.", parse_mode="MarkdownV2")
            else:
                send_message(chat_id, "Usage: /skip \\<job\\_id\\>", parse_mode="MarkdownV2")
​
    # Save updated offset
    with open(offset_file, "w") as f:
        json.dump({"offset": offset}, f)
​
​
# ═════════════════════════════════════════════════════════════════════════
# JOB SOURCES
# Each fetcher returns a list of dicts with a common shape:
#   { title, company, location, type, stipend_or_ctc, apply_url, source,
#     deadline, skills, description }
# ═════════════════════════════════════════════════════════════════════════
​
def _job(title="", company="", location="India", jtype="", stipend="",
         apply_url="", source="", deadline="", skills=None, description=""):
    return {
        "title": title.strip(),
        "company": company.strip(),
        "location": location.strip(),
        "type": jtype,
        "stipend_or_ctc": stipend,
        "apply_url": apply_url.strip(),
        "source": source,
        "deadline": deadline,
        "skills": skills or [],
        "description": description.strip(),
    }
​
​
def fetch_duckduckgo() -> list:
    """Search the web via DuckDuckGo for job postings."""
    jobs = []
    try:
        with DDGS() as ddgs:
            for query in SEARCH_QUERIES:
                try:
                    results = ddgs.text(query, max_results=SEARCH_RESULTS)
                    for res in results:
                        jobs.append(_job(
                            title=res.get("title", ""),
                            company="",
                            apply_url=res.get("href", ""),
                            source="DuckDuckGo",
                            description=res.get("body", ""),
                        ))
                    time.sleep(DELAY_BETWEEN)
                except Exception as e:
                    log.warning("DDG query failed (%s): %s", query, e)
    except Exception as e:
        log.warning("DuckDuckGo unavailable: %s", e)
    log.info("DuckDuckGo: %d results", len(jobs))
    return jobs
​
​
def fetch_adzuna() -> list:
    """Adzuna India jobs (free API)."""
    if not (ADZUNA_APP_ID and ADZUNA_APP_KEY):
        return []
    jobs = []
    base = "https://api.adzuna.com/v1/api/jobs/in/search/1"
    for role in ["software engineer", "backend developer", "full stack developer", "data scientist"]:
        try:
            r = httpx.get(base, params={
                "app_id": ADZUNA_APP_ID,
                "app_key": ADZUNA_APP_KEY,
                "results_per_page": SEARCH_RESULTS,
                "what": role,
                "where": "India",
                "content-type": "application/json",
            }, timeout=15)
            for res in r.json().get("results", []):
                jobs.append(_job(
                    title=res.get("title", ""),
                    company=res.get("company", {}).get("display_name", ""),
                    location=res.get("location", {}).get("display_name", "India"),
                    stipend=str(res.get("salary_min", "")) if res.get("salary_min") else "",
                    apply_url=res.get("redirect_url", ""),
                    source="Adzuna",
                    description=res.get("description", ""),
                ))
            time.sleep(DELAY_BETWEEN)
        except Exception as e:
            log.warning("Adzuna failed (%s): %s", role, e)
    log.info("Adzuna: %d results", len(jobs))
    return jobs
​
​
def fetch_jsearch() -> list:
    """JSearch (RapidAPI) — LinkedIn/Indeed aggregator."""
    if not JSEARCH_API_KEY:
        return []
    jobs = []
    url = "https://jsearch.p.rapidapi.com/search"
    headers = {
        "X-RapidAPI-Key": JSEARCH_API_KEY,
        "X-RapidAPI-Host": "jsearch.p.rapidapi.com",
    }
    for query in ["software engineer fresher India", "SDE intern India"]:
        try:
            r = httpx.get(url, headers=headers, params={
                "query": query, "page": "1", "num_pages": "1",
            }, timeout=15)
            for res in r.json().get("data", []):
                jobs.append(_job(
                    title=res.get("job_title", ""),
                    company=res.get("employer_name", ""),
                    location=res.get("job_city", "") or "India",
                    jtype=res.get("job_employment_type", ""),
                    apply_url=res.get("job_apply_link", ""),
                    source="JSearch",
                    description=(res.get("job_description", "") or "")[:500],
                ))
            time.sleep(DELAY_BETWEEN)
        except Exception as e:
            log.warning("JSearch failed (%s): %s", query, e)
    log.info("JSearch: %d results", len(jobs))
    return jobs
​
​
def fetch_remotive() -> list:
    """Remotive remote tech jobs (no key)."""
    jobs = []
    try:
        r = httpx.get("https://remotive.com/api/remote-jobs",
                      params={"category": "software-dev", "limit": 20}, timeout=15)
        for res in r.json().get("jobs", []):
            jobs.append(_job(
                title=res.get("title", ""),
                company=res.get("company_name", ""),
                location=res.get("candidate_required_location", "Remote"),
                jtype=res.get("job_type", ""),
                stipend=res.get("salary", ""),
                apply_url=res.get("url", ""),
                source="Remotive",
                description=(res.get("description", "") or "")[:500],
            ))
    except Exception as e:
        log.warning("Remotive failed: %s", e)
    log.info("Remotive: %d results", len(jobs))
    return jobs
​
​
def fetch_arbeitnow() -> list:
    """Arbeitnow remote jobs (no key)."""
    jobs = []
    try:
        r = httpx.get("https://www.arbeitnow.com/api/job-board-api", timeout=15)
        for res in r.json().get("data", [])[:20]:
            jobs.append(_job(
                title=res.get("title", ""),
                company=res.get("company_name", ""),
                location=res.get("location", "Remote"),
                jtype=", ".join(res.get("job_types", []) or []),
                apply_url=res.get("url", ""),
                source="Arbeitnow",
                description=(res.get("description", "") or "")[:500],
            ))
    except Exception as e:
        log.warning("Arbeitnow failed: %s", e)
    log.info("Arbeitnow: %d results", len(jobs))
    return jobs
​
​
def fetch_themuse() -> list:
    """The Muse entry-level jobs (no key)."""
    jobs = []
    try:
        r = httpx.get("https://www.themuse.com/api/public/jobs", params={
            "category": "Software Engineering",
            "level": "Entry Level",
            "page": 1,
        }, timeout=15)
        for res in r.json().get("results", []):
            locs = ", ".join(l.get("name", "") for l in res.get("locations", [])) or "India"
            jobs.append(_job(
                title=res.get("name", ""),
                company=res.get("company", {}).get("name", ""),
                location=locs,
                apply_url=res.get("refs", {}).get("landing_page", ""),
                source="The Muse",
                description=(res.get("contents", "") or "")[:500],
            ))
    except Exception as e:
        log.warning("The Muse failed: %s", e)
    log.info("The Muse: %d results", len(jobs))
    return jobs
​
​
def fetch_all_jobs() -> list:
    """Run every source and combine results."""
    all_jobs = []
    for fetcher in (
        fetch_duckduckgo, fetch_adzuna, fetch_jsearch,
        fetch_remotive, fetch_arbeitnow, fetch_themuse,
    ):
        try:
            all_jobs.extend(fetcher())
        except Exception as e:
            log.warning("%s crashed: %s", fetcher.__name__, e)
    log.info("Total raw jobs from all sources: %d", len(all_jobs))
    return all_jobs
​
​
# ═════════════════════════════════════════════════════════════════════════
# DUPLICATE FILTER
# ═════════════════════════════════════════════════════════════════════════
​
def load_seen_urls() -> set:
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r") as f:
            return set(json.load(f))
    return set()
​
​
def save_seen_urls(seen: set) -> None:
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen), f)
​
​
def filter_new_jobs(jobs: list, seen: set) -> list:
    new_jobs = []
    for job in jobs:
        url = job.get("apply_url", "").strip()
        if url and url not in seen:
            new_jobs.append(job)
        elif not url:
            new_jobs.append(job)
    skipped = len(jobs) - len(new_jobs)
    if skipped:
        log.info("Duplicate filter: skipped %d already-seen jobs", skipped)
    return new_jobs
​
​
# ═════════════════════════════════════════════════════════════════════════
# RESUME MATCH SCORE
# ═════════════════════════════════════════════════════════════════════════
​
def score_jobs_against_resume(jobs: list) -> list:
    if not jobs:
        return jobs
​
    log.info("Scoring %d jobs against resume...", len(jobs))
    client = Groq(api_key=GROQ_API_KEY)
​
    jobs_text = ""
    for i, job in enumerate(jobs, 1):
        jobs_text += (
            f"\n[{i}] Title: {job.get('title', '')}\n"
            f"    Company: {job.get('company', '')}\n"
            f"    Skills: {', '.join(job.get('skills', []))}\n"
            f"    Description: {job.get('description', '')}\n"
            f"    Type: {job.get('type', '')}\n"
        )
​
    schema_example = (
        '{\n'
        '  "scores": [\n'
        '    {"index": 1, "score": 85, "reason": "one short sentence why"},\n'
        '    {"index": 2, "score": 62, "reason": "one short sentence why"}\n'
        '  ]\n'
        '}'
    )
​
    prompt = f"""You are a resume-to-job matcher. Score how well each job matches the candidate's resume.
​
CANDIDATE RESUME:
{RESUME_TEXT.strip()}
​
JOBS TO SCORE:
{jobs_text}
​
Scoring criteria:
- 80-100: Excellent match — skills align, role fits experience level, company type matches goals
- 60-79:  Good match — most skills present, worth applying
- 40-59:  Partial match — some skills missing but learnable
- 0-39:   Poor match — wrong domain, too senior, or skills mismatch
​
Return ONLY valid JSON. No markdown. Schema:
{schema_example}
​
Score all {len(jobs)} jobs."""
​
    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "You are a precise JSON scoring agent. Output only valid JSON."},
                {"role": "user",   "content": prompt},
            ],
            temperature=0.1,
            max_tokens=1500,
        )
​
        raw   = response.choices[0].message.content.strip()
        clean = raw.replace("```json", "").replace("```", "").strip()
        start = clean.find("{")
        end   = clean.rfind("}") + 1
        data  = json.loads(clean[start:end])
​
        score_map = {s["index"]: s for s in data.get("scores", [])}
        for i, job in enumerate(jobs, 1):
            s = score_map.get(i, {})
            job["match_score"]  = s.get("score", 50)
            job["match_reason"] = s.get("reason", "")
​
        log.info("Scoring done. Scores: %s", [j["match_score"] for j in jobs])
​
    except Exception as e:
        log.warning("Resume scoring failed (%s) — sending all jobs unscored", e)
        for job in jobs:
            job["match_score"]  = 50
            job["match_reason"] = ""
​
    return jobs
​
​
def filter_by_score(jobs: list, threshold: int) -> list:
    passing = [j for j in jobs if j.get("match_score", 50) >= threshold]
    log.info("Score filter (>=%d): %d/%d jobs passed", threshold, len(passing), len(jobs))
    return passing
​
​
# ═════════════════════════════════════════════════════════════════════════
# APPLY TRACKER (SQLite)
# ═════════════════════════════════════════════════════════════════════════
​
def init_db() -> None:
    conn = sqlite3.connect(DB_FILE)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            title       TEXT,
            company     TEXT,
            location    TEXT,
            type        TEXT,
            stipend     TEXT,
            apply_url   TEXT,
            source      TEXT,
            deadline    TEXT,
            match_score INTEGER DEFAULT 50,
            status      TEXT DEFAULT 'new',
            sent_date   TEXT,
            action_date TEXT
        )
    """)
    conn.commit()
    conn.close()
​
​
def save_jobs_to_db(jobs: list) -> dict:
    conn   = sqlite3.connect(DB_FILE)
    id_map = {}
    today  = datetime.now().strftime("%Y-%m-%d")
​
    for i, job in enumerate(jobs):
        cur = conn.execute(
            """INSERT INTO jobs
               (title, company, location, type, stipend, apply_url,
                source, deadline, match_score, status, sent_date)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                job.get("title", ""),
                job.get("company", ""),
                job.get("location", ""),
                job.get("type", ""),
                job.get("stipend_or_ctc", ""),
                job.get("apply_url", ""),
                job.get("source", ""),
                job.get("deadline", ""),
                job.get("match_score", 50),
                "new",
                today,
            ),
        )
        id_map[i + 1] = cur.lastrowid
​
    conn.commit()
    conn.close()
    return id_map
​
​
def update_job_status(db_id: int, status: str) -> bool:
    conn = sqlite3.connect(DB_FILE)
    cur  = conn.execute(
        "UPDATE jobs SET status=?, action_date=? WHERE id=?",
        (status, datetime.now().strftime("%Y-%m-%d"), db_id),
    )
    conn.commit()
    conn.close()
    return cur.rowcount > 0
​
​
def get_status_summary() -> str:
    conn   = sqlite3.connect(DB_FILE)
    rows   = conn.execute("SELECT status, COUNT(*) FROM jobs GROUP BY status").fetchall()
    conn.close()
​
    totals  = {r[0]: r[1] for r in rows}
    total   = sum(totals.values())
    applied = totals.get("applied", 0)
    saved   = totals.get("saved", 0)
    skipped = totals.get("skip", 0)
    new     = totals.get("new", 0)
​
    return (
        f"📊 Application Tracker\n\n"
        f"Total scanned:   {total}\n"
        f"Applied:         {applied}\n"
        f"Saved/watchlist: {saved}\n"
        f"Skipped:         {skipped}\n"
        f"New \\(unseen\\):   {new}"
    )
​
​
def get_applied_list() -> str:
    conn = sqlite3.connect(DB_FILE)
    rows = conn.execute(
        "SELECT title, company, action_date FROM jobs WHERE status='applied' ORDER BY action_date DESC LIMIT 10"
    ).fetchall()
    conn.close()
​
    if not rows:
        return "No applications tracked yet\\."
​
    lines = ["📋 Recent Applications:\n"]
    for title, company, date in rows:
        lines.append(f"✅ {escape_md(title)} @ {escape_md(company)} \\({escape_md(date)}\\)")
    return "\n".join(lines)
​
​
# ═════════════════════════════════════════════════════════════════════════
# DEADLINE ALERTS
# ═════════════════════════════════════════════════════════════════════════
​
def check_deadline_alerts() -> list:
    conn  = sqlite3.connect(DB_FILE)
    rows  = conn.execute(
        "SELECT id, title, company, deadline, apply_url FROM jobs "
        "WHERE status IN ('new','saved') AND deadline != ''"
    ).fetchall()
    conn.close()
​
    alerts   = []
    now      = datetime.now()
    in_48hrs = now + timedelta(hours=48)
​
    for db_id, title, company, deadline_str, url in rows:
        for fmt in ("%d %B %Y", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%B %d, %Y"):
            try:
                deadline_dt = datetime.strptime(deadline_str.strip(), fmt)
                if now <= deadline_dt <= in_48hrs:
                    hrs_left = int((deadline_dt - now).total_seconds() / 3600)
                    msg = (
                        f"⏰ Deadline Alert\\!\n\n"
                        f"*{escape_md(title)}* at *{escape_md(company)}*\n"
                        f"Deadline in *{hrs_left} hours* \\({escape_md(deadline_str)}\\)\n"
                    )
                    if url:
                        msg += f"[→ Apply now]({url})"
                    alerts.append(msg)
                break
            except ValueError:
                continue
​
    if alerts:
        log.info("Deadline alerts: %d jobs due within 48hrs", len(alerts))
    return alerts
​
​
# ═════════════════════════════════════════════════════════════════════════
# FORMAT & BROADCAST JOBS
# ═════════════════════════════════════════════════════════════════════════
​
def format_job_message(db_id: int, job: dict) -> str:
    """Build a MarkdownV2 message for one job."""
    title   = escape_md(job.get("title", "Untitled"))
    company = escape_md(job.get("company", "")) or "Unknown"
    loc     = escape_md(job.get("location", ""))
    source  = escape_md(job.get("source", ""))
    score   = job.get("match_score", 50)
    reason  = escape_md(job.get("match_reason", ""))
    stipend = escape_md(job.get("stipend_or_ctc", ""))
    url     = job.get("apply_url", "")
​
    lines = [
        f"🚀 *{title}*",
        f"🏢 {company}" + (f" — {loc}" if loc else ""),
        f"📊 Match: *{score}/100*" + (f" — {reason}" if reason else ""),
    ]
    if stipend:
        lines.append(f"💰 {stipend}")
    if source:
        lines.append(f"🔗 Source: {source}")
    if url:
        lines.append(f"[→ Apply now]({url})")
    lines.append(
        f"\nTrack: /applied {db_id}  •  /saved {db_id}  •  /skip {db_id}"
    )
    return "\n".join(lines)
​
​
def broadcast_jobs(jobs: list, id_map: dict) -> None:
    """Send each job to all subscribers."""
    for i, job in enumerate(jobs, 1):
        db_id = id_map.get(i)
        if db_id is None:
            continue
        msg = format_job_message(db_id, job)
        broadcast(msg)
        time.sleep(0.5)
​
​
# ═════════════════════════════════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════════════════════════════════
​
def run_daily_scan() -> None:
    """Fetch → dedupe → score → filter → store → broadcast."""
    log.info("=== Starting daily scan ===")
    init_db()
​
    seen = load_seen_urls()
​
    raw_jobs  = fetch_all_jobs()
    new_jobs  = filter_new_jobs(raw_jobs, seen)
    if not new_jobs:
        log.info("No new jobs found today.")
        return
​
    scored    = score_jobs_against_resume(new_jobs)
    passing   = filter_by_score(scored, RESUME_MATCH_THRESHOLD)
​
    # Best matches first, cap at SEND_TOP_N
    passing.sort(key=lambda j: j.get("match_score", 0), reverse=True)
    to_send = passing[:SEND_TOP_N]
​
    if not to_send:
        log.info("No jobs passed the score threshold today.")
        return
​
    id_map = save_jobs_to_db(to_send)
    broadcast_jobs(to_send, id_map)
​
    # Mark every fetched URL as seen so we don't resend it
    for job in raw_jobs:
        url = job.get("apply_url", "").strip()
        if url:
            seen.add(url)
    save_seen_urls(seen)
​
    log.info("=== Scan complete: sent %d jobs ===", len(to_send))
​
​
def run_deadline_alerts() -> None:
    alerts = check_deadline_alerts()
    for msg in alerts:
        broadcast(msg)
        time.sleep(0.5)
​
​
def command_listener(poll_interval: int = 5) -> None:
    """Continuously poll for and handle Telegram bot commands."""
    log.info("Command listener started (Ctrl+C to stop).")
    while True:
        poll_and_handle_commands()
        time.sleep(poll_interval)
​
​
def main() -> None:
    import sys
​
    init_db()
    mode = sys.argv[1] if len(sys.argv) > 1 else "scan"
​
    if mode == "scan":
        run_daily_scan()
        run_deadline_alerts()
    elif mode == "listen":
        # Long-running process to answer /start, /stop, /status, etc.
        command_listener()
    elif mode == "alerts":
        run_deadline_alerts()
    elif mode == "commands":
        # Single poll pass (useful for cron-driven command handling)
        poll_and_handle_commands()
    else:
        print("Usage: python agent.py [scan|listen|alerts|commands]")
​
​
if __name__ == "__main__":
    main()
​
