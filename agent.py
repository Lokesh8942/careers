"""
Career Opportunity Agent v2 — Free Edition
-------------------------------------------
Sources:
  • DuckDuckGo Search
  • Adzuna API (free, India jobs)
  • JSearch RapidAPI (LinkedIn/Indeed scraper)
  • Remotive API (no key, remote tech jobs)
  • Arbeitnow API (no key, remote jobs)
  • The Muse API (no key, entry level jobs)
  • Unstop (direct scraper)

LLM      → Groq (free tier, llama-3.3-70b-versatile)
Delivery → Telegram Bot API (free)

New in v2:
  ✅ Resume match score  — Groq scores each job 0-100 vs your resume
  ✅ Duplicate filter    — seen.json skips already-sent jobs
  ✅ Apply tracker       — /applied /saved /skip /status via Telegram bot
  ✅ Deadline alerts     — 48hr reminders for saved jobs
"""

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

load_dotenv()

# ─── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("agent.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)


# ─── Config ────────────────────────────────────────────────────────────────────
GROQ_API_KEY       = os.getenv("GROQ_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")
ADZUNA_APP_ID      = os.getenv("ADZUNA_APP_ID", "")
ADZUNA_APP_KEY     = os.getenv("ADZUNA_APP_KEY", "")
JSEARCH_API_KEY    = os.getenv("JSEARCH_API_KEY", "")

# ── Resume text — paste your resume content here for match scoring ─────────────
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

# ── Job filtering ──────────────────────────────────────────────────────────────
RESUME_MATCH_THRESHOLD = 55   # Only send jobs scoring >= this (0-100)
SEND_TOP_N             = 10
SEARCH_RESULTS         = 5
DELAY_BETWEEN          = 2.0

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

SKILLS = [
    "Java", "Python", "C++", "JavaScript", "TypeScript",
    "React", "Node.js", "Spring Boot", "Django", "FastAPI",
    "DSA", "REST API", "SQL", "MySQL", "PostgreSQL", "MongoDB",
    "AWS", "GCP", "Azure", "Docker", "Kubernetes", "CI/CD",
    "Machine Learning", "Deep Learning", "TensorFlow", "PyTorch",
    "Git", "Linux", "System Design",
]

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

# ─── File paths ────────────────────────────────────────────────────────────────
SEEN_FILE = "seen.json"
DB_FILE   = "tracker.db"


# ══════════════════════════════════════════════════════════════════════════════
# FEATURE 1 — DUPLICATE FILTER
# Remembers every job URL ever sent. Skips on next scan.
# ══════════════════════════════════════════════════════════════════════════════

def load_seen_urls() -> set:
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r") as f:
            return set(json.load(f))
    return set()


def save_seen_urls(seen: set) -> None:
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen), f)


def filter_new_jobs(jobs: list[dict], seen: set) -> list[dict]:
    new_jobs = []
    for job in jobs:
        url = job.get("apply_url", "").strip()
        if url and url not in seen:
            new_jobs.append(job)
        elif not url:
            new_jobs.append(job)   # keep jobs without URL (can't dedup)
    skipped = len(jobs) - len(new_jobs)
    if skipped:
        log.info("Duplicate filter: skipped %d already-seen jobs", skipped)
    return new_jobs


# ══════════════════════════════════════════════════════════════════════════════
# FEATURE 2 — RESUME MATCH SCORE
# Groq scores each job 0-100 against your resume. Filters low matches.
# ══════════════════════════════════════════════════════════════════════════════

def score_jobs_against_resume(jobs: list[dict]) -> list[dict]:
    """Add a match_score (0-100) to each job using Groq."""
    if not jobs:
        return jobs

    log.info("Scoring %d jobs against resume...", len(jobs))
    client = Groq(api_key=GROQ_API_KEY)

    # Build a compact job list for a single Groq call (saves tokens)
    jobs_text = ""
    for i, job in enumerate(jobs, 1):
        jobs_text += (
            f"\n[{i}] Title: {job.get('title', '')}\n"
            f"    Company: {job.get('company', '')}\n"
            f"    Skills: {', '.join(job.get('skills', []))}\n"
            f"    Description: {job.get('description', '')}\n"
            f"    Type: {job.get('type', '')}\n"
        )

    prompt = f"""You are a resume-to-job matcher. Score how well each job matches the candidate's resume.

CANDIDATE RESUME:
{RESUME_TEXT.strip()}

JOBS TO SCORE:
{jobs_text}

Scoring criteria:
- 80-100: Excellent match — skills align, role fits experience level, company type matches goals
- 60-79:  Good match — most skills present, worth applying
- 40-59:  Partial match — some skills missing but learnable
- 0-39:   Poor match — wrong domain, too senior, or skills mismatch

Return ONLY valid JSON. No markdown. Schema:
{{
  "scores": [
    {{"index": 1, "score": 85, "reason": "one short sentence why"}},
    {{"index": 2, "score": 62, "reason": "one short sentence why"}},
    ...
  ]
}}

Score all {len(jobs)} jobs."""

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

        raw   = response.choices[0].message.content.strip()
        clean = raw.replace("```json", "").replace("```", "").strip()
        start = clean.find("{")
        end   = clean.rfind("}") + 1
        data  = json.loads(clean[start:end])

        # Attach scores back to jobs
        score_map = {s["index"]: s for s in data.get("scores", [])}
        for i, job in enumerate(jobs, 1):
            s = score_map.get(i, {})
            job["match_score"]  = s.get("score", 50)
            job["match_reason"] = s.get("reason", "")

        log.info("Scoring done. Scores: %s", [j["match_score"] for j in jobs])

    except Exception as e:
        log.warning("Resume scoring failed (%s) — sending all jobs unscored", e)
        for job in jobs:
            job["match_score"]  = 50
            job["match_reason"] = ""

    return jobs


def filter_by_score(jobs: list[dict], threshold: int) -> list[dict]:
    passing = [j for j in jobs if j.get("match_score", 50) >= threshold]
    log.info(
        "Score filter (>=%d): %d/%d jobs passed",
        threshold, len(passing), len(jobs)
    )
    return passing


# ══════════════════════════════════════════════════════════════════════════════
# FEATURE 3 — APPLY TRACKER (SQLite + Telegram bot commands)
# Commands: /applied <id>, /saved <id>, /skip <id>, /status
# ══════════════════════════════════════════════════════════════════════════════

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


def save_jobs_to_db(jobs: list[dict]) -> dict[int, int]:
    """Save jobs to DB. Returns {list_index: db_id} mapping."""
    conn    = sqlite3.connect(DB_FILE)
    id_map  = {}
    today   = datetime.now().strftime("%Y-%m-%d")

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
        id_map[i + 1] = cur.lastrowid   # 1-indexed to match Telegram card numbers

    conn.commit()
    conn.close()
    return id_map


def update_job_status(db_id: int, status: str) -> bool:
    """Update status for a job. Returns True if found."""
    conn = sqlite3.connect(DB_FILE)
    cur  = conn.execute(
        "UPDATE jobs SET status=?, action_date=? WHERE id=?",
        (status, datetime.now().strftime("%Y-%m-%d"), db_id),
    )
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def get_status_summary() -> str:
    conn = sqlite3.connect(DB_FILE)
    rows = conn.execute(
        "SELECT status, COUNT(*) FROM jobs GROUP BY status"
    ).fetchall()
    conn.close()

    totals  = {r[0]: r[1] for r in rows}
    total   = sum(totals.values())
    applied = totals.get("applied", 0)
    saved   = totals.get("saved", 0)
    skipped = totals.get("skip", 0)
    new     = totals.get("new", 0)

    return (
        f"📊 *Application Tracker*\n\n"
        f"Total scanned:  *{total}*\n"
        f"Applied:        *{applied}*\n"
        f"Saved/watchlist: *{saved}*\n"
        f"Skipped:        *{skipped}*\n"
        f"New \\(unseen\\):  *{new}*"
    )


def get_applied_list() -> str:
    conn = sqlite3.connect(DB_FILE)
    rows = conn.execute(
        "SELECT title, company, action_date FROM jobs WHERE status='applied' ORDER BY action_date DESC LIMIT 10"
    ).fetchall()
    conn.close()

    if not rows:
        return "No applications tracked yet\\."

    lines = ["📋 *Recent Applications:*\n"]
    for title, company, date in rows:
        lines.append(f"✅ {escape_md(title)} @ {escape_md(company)} \\({escape_md(date)}\\)")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# FEATURE 4 — DEADLINE ALERTS
# Checks saved jobs daily. Sends 48hr reminder if deadline is approaching.
# ══════════════════════════════════════════════════════════════════════════════

def check_deadline_alerts() -> list[str]:
    """Return alert messages for jobs with deadlines within 48 hours."""
    conn  = sqlite3.connect(DB_FILE)
    rows  = conn.execute(
        "SELECT id, title, company, deadline, apply_url FROM jobs "
        "WHERE status IN ('new','saved') AND deadline != ''"
    ).fetchall()
    conn.close()

    alerts   = []
    now      = datetime.now()
    in_48hrs = now + timedelta(hours=48)

    for db_id, title, company, deadline_str, url in rows:
        # Try common date formats
        for fmt in ("%d %B %Y", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%B %d, %Y"):
            try:
                deadline_dt = datetime.strptime(deadline_str.strip(), fmt)
                if now <= deadline_dt <= in_48hrs:
                    hrs_left = int((deadline_dt - now).total_seconds() / 3600)
                    msg = (
                        f"⏰ *Deadline Alert\\!*\n\n"
                        f"*{escape_md(title)}* at *{escape_md(company)}*\n"
                        f"Deadline in *{hrs_left} hours* \\({escape_md(deadline_str)}\\)\n"
                    )
                    if url:
                        msg += f"[→ Apply now]({url})"
                    alerts.append(msg)
                break
            except ValueError:
                continue

    if alerts:
        log.info("Deadline alerts: %d jobs due within 48hrs", len(alerts))
    return alerts


# ══════════════════════════════════════════════════════════════════════════════
# TELEGRAM BOT COMMAND LISTENER
# Runs in background thread. Handles /applied, /saved, /skip, /status
# ══════════════════════════════════════════════════════════════════════════════

# Card map file — written after each scan so bot_listener.py can use it
CARD_MAP_FILE = "card_map.json"


def save_card_map(id_map: dict) -> None:
    """Persist card→DB id mapping so bot_listener.py can read it."""
    with open(CARD_MAP_FILE, "w") as f:
        json.dump({str(k): v for k, v in id_map.items()}, f)
    log.info("Card map saved to %s", CARD_MAP_FILE)


# ─── Search Sources (unchanged from your v1) ──────────────────────────────────

def search_ddg() -> list[dict]:
    all_results = []
    seen_urls   = set()
    log.info("DDG: searching %d queries...", len(SEARCH_QUERIES))

    for i, query in enumerate(SEARCH_QUERIES):
        try:
            results = list(DDGS().text(query, max_results=SEARCH_RESULTS))
            new = 0
            for r in results:
                url = r.get("href", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    all_results.append({
                        "title":   r.get("title", ""),
                        "snippet": r.get("body", ""),
                        "url":     url,
                        "source":  "DuckDuckGo",
                    })
                    new += 1
            log.info("DDG query %d/%d → %d new", i + 1, len(SEARCH_QUERIES), new)
        except Exception as e:
            log.warning("DDG query %d failed: %s", i + 1, e)

        if i < len(SEARCH_QUERIES) - 1:
            time.sleep(DELAY_BETWEEN)

    log.info("DDG total: %d results", len(all_results))
    return all_results


def search_adzuna() -> list[dict]:
    if not ADZUNA_APP_ID or not ADZUNA_APP_KEY:
        log.warning("Adzuna: skipping — no credentials")
        return []

    results = []
    queries = [
        "software engineer intern", "software engineer fresher",
        "ML engineer fresher", "backend developer intern",
        "graduate engineer trainee",
    ]
    log.info("Adzuna: fetching jobs...")

    for query in queries:
        try:
            url = (
                f"https://api.adzuna.com/v1/api/jobs/in/search/1"
                f"?app_id={ADZUNA_APP_ID}&app_key={ADZUNA_APP_KEY}"
                f"&results_per_page=5&what={query.replace(' ', '%20')}"
                f"&content-type=application/json"
            )
            r    = httpx.get(url, timeout=15)
            data = r.json()

            for job in data.get("results", []):
                results.append({
                    "title":    job.get("title", ""),
                    "snippet":  job.get("description", "")[:300],
                    "url":      job.get("redirect_url", ""),
                    "source":   "Adzuna",
                    "company":  job.get("company", {}).get("display_name", ""),
                    "location": job.get("location", {}).get("display_name", ""),
                })
            time.sleep(1)
        except Exception as e:
            log.warning("Adzuna '%s' failed: %s", query, e)

    log.info("Adzuna total: %d results", len(results))
    return results


def search_jsearch() -> list[dict]:
    if not JSEARCH_API_KEY:
        log.warning("JSearch: skipping — no API key")
        return []

    results = []
    queries = [
        "software engineer intern India", "SDE fresher India 2026",
        "backend developer intern Bangalore", "ML engineer intern India",
        "graduate engineer trainee India",
    ]
    log.info("JSearch: fetching jobs...")
    headers = {
        "X-RapidAPI-Key":  JSEARCH_API_KEY,
        "X-RapidAPI-Host": "jsearch.p.rapidapi.com",
    }

    for query in queries:
        try:
            r = httpx.get(
                "https://jsearch.p.rapidapi.com/search",
                headers=headers,
                params={"query": query, "page": "1", "num_pages": "1",
                        "country": "in", "date_posted": "week"},
                timeout=15,
            )
            data = r.json()
            for job in data.get("data", []):
                results.append({
                    "title":    job.get("job_title", ""),
                    "snippet":  job.get("job_description", "")[:300],
                    "url":      job.get("job_apply_link", ""),
                    "source":   "JSearch",
                    "company":  job.get("employer_name", ""),
                    "location": job.get("job_city", "") + ", " + job.get("job_country", ""),
                })
            time.sleep(1)
        except Exception as e:
            log.warning("JSearch '%s' failed: %s", query, e)

    log.info("JSearch total: %d results", len(results))
    return results


def search_remotive() -> list[dict]:
    results = []
    queries = ["software engineer", "backend developer",
               "machine learning", "data engineer", "devops"]
    log.info("Remotive: fetching remote jobs...")

    for query in queries:
        try:
            r    = httpx.get(
                f"https://remotive.com/api/remote-jobs?search={query.replace(' ','%20')}&limit=5",
                timeout=15,
            )
            data = r.json()
            for job in data.get("jobs", []):
                results.append({
                    "title":    job.get("title", ""),
                    "snippet":  job.get("description", "")[:300],
                    "url":      job.get("url", ""),
                    "source":   "Remotive",
                    "company":  job.get("company_name", ""),
                    "location": "Remote",
                })
            time.sleep(1)
        except Exception as e:
            log.warning("Remotive '%s' failed: %s", query, e)

    log.info("Remotive total: %d results", len(results))
    return results


def search_arbeitnow() -> list[dict]:
    results  = []
    keywords = ["software", "backend", "frontend", "fullstack", "ml",
                "data", "devops", "python", "java", "engineer"]
    log.info("Arbeitnow: fetching jobs...")

    try:
        r    = httpx.get("https://www.arbeitnow.com/api/job-board-api", timeout=15)
        data = r.json()
        for job in data.get("data", [])[:50]:
            if any(kw in job.get("title", "").lower() for kw in keywords):
                results.append({
                    "title":    job.get("title", ""),
                    "snippet":  job.get("description", "")[:300],
                    "url":      job.get("url", ""),
                    "source":   "Arbeitnow",
                    "company":  job.get("company_name", ""),
                    "location": job.get("location", "Remote"),
                })
        log.info("Arbeitnow → %d results", len(results))
    except Exception as e:
        log.warning("Arbeitnow failed: %s", e)

    return results


def search_themuse() -> list[dict]:
    results    = []
    categories = ["Software Engineer", "Data Science", "Dev & Ops"]
    log.info("The Muse: fetching entry level jobs...")

    for category in categories:
        try:
            r = httpx.get(
                f"https://www.themuse.com/api/public/jobs"
                f"?category={category.replace(' ','%20')}&level=Entry%20Level&page=0",
                timeout=15,
            )
            data = r.json()
            for job in data.get("results", []):
                results.append({
                    "title":    job.get("name", ""),
                    "snippet":  job.get("contents", "")[:300],
                    "url":      job.get("refs", {}).get("landing_page", ""),
                    "source":   "TheMuse",
                    "company":  job.get("company", {}).get("name", ""),
                    "location": job.get("locations", [{}])[0].get("name", "Remote"),
                })
            time.sleep(1)
        except Exception as e:
            log.warning("TheMuse '%s' failed: %s", category, e)

    log.info("TheMuse total: %d results", len(results))
    return results


def search_unstop() -> list[dict]:
    results = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept":     "application/json",
    }
    queries = ["software engineer", "SDE intern",
               "backend developer", "data science", "machine learning"]
    log.info("Unstop: scraping jobs...")

    for query in queries:
        try:
            url  = (
                f"https://unstop.com/api/public/opportunity/search-result"
                f"?opportunity=jobs&searchTerm={query.replace(' ','%20')}"
                f"&oppStage=ALL&page=1&per_page=5"
            )
            r    = httpx.get(url, headers=headers, timeout=15)
            data = r.json()

            for item in data.get("data", {}).get("data", []):
                opp_id = item.get("id", "")
                slug   = item.get("slug", "")
                min_s  = item.get("minSalary", "")
                max_s  = item.get("maxSalary", "")
                results.append({
                    "title":    item.get("title", ""),
                    "snippet":  item.get("desc", "")[:300],
                    "url":      f"https://unstop.com/jobs/{slug}-{opp_id}",
                    "source":   "Unstop",
                    "company":  item.get("organisation", {}).get("name", ""),
                    "location": item.get("city", "India"),
                    "stipend":  f"{min_s}-{max_s} LPA" if min_s and max_s else "Not disclosed",
                })
            time.sleep(1)
        except Exception as e:
            log.warning("Unstop '%s' failed: %s", query, e)

    log.info("Unstop total: %d results", len(results))
    return results


def search_all_sources() -> list[dict]:
    all_results = []
    seen_urls   = set()
    sources = [
        ("DuckDuckGo", search_ddg),
        ("Adzuna",     search_adzuna),
        ("JSearch",    search_jsearch),
        ("Remotive",   search_remotive),
        ("Arbeitnow",  search_arbeitnow),
        ("TheMuse",    search_themuse),
        ("Unstop",     search_unstop),
    ]

    for name, fn in sources:
        try:
            for r in fn():
                url = r.get("url", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    all_results.append(r)
                elif not url:
                    all_results.append(r)
        except Exception as e:
            log.error("Source %s crashed: %s", name, e)

    log.info("TOTAL unique results: %d", len(all_results))
    return all_results


# ─── Groq Extraction ──────────────────────────────────────────────────────────

def extract_jobs_with_groq(raw_results: list[dict]) -> dict:
    if not raw_results:
        raise ValueError("No search results to process.")

    today = datetime.now().strftime("%d %B %Y")
    snippets_text = ""
    for i, r in enumerate(raw_results[:60], 1):
        snippets_text += (
            f"\n[{i}] Title: {r['title']}\n"
            f"    URL: {r['url']}\n"
            f"    Source: {r.get('source','')}\n"
            f"    Snippet: {r['snippet'][:300]}\n"
        )

    prompt = f"""You are a career opportunity extraction agent. Today is {today}.

Extract REAL job postings from the search results below.

Only include:
- Fresher / intern / 2025-2027 batch roles
- Tech roles matching: {', '.join(ROLES[:8])}
- Active / recently posted jobs
- Skills overlap with: {', '.join(SKILLS[:10])}

Ignore expired jobs, course ads, non-job content.

SEARCH RESULTS:
{snippets_text}

Return ONLY valid JSON. No markdown. Schema:
{{
  "scan_date": "{today}",
  "total_found": <int>,
  "jobs": [
    {{
      "title": "exact job title",
      "company": "company name",
      "location": "city or Remote/Hybrid",
      "type": "Internship or Full-time",
      "skills": ["skill1","skill2","skill3"],
      "stipend_or_ctc": "e.g. 25000/month or 8-12 LPA or Not disclosed",
      "description": "1-2 sentences about the role",
      "apply_url": "direct URL",
      "source": "source name",
      "deadline": "deadline if mentioned, else empty string"
    }}
  ],
  "market_pulse": "2-3 sentences on trending roles and skills for freshers this week"
}}

Extract up to {SEND_TOP_N + 4} best matching jobs."""

    log.info("Groq: extracting from %d snippets...", len(raw_results[:60]))
    client   = Groq(api_key=GROQ_API_KEY)
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": "You are a precise JSON extraction agent. Output only valid JSON."},
            {"role": "user",   "content": prompt},
        ],
        temperature=0.2,
        max_tokens=4000,
    )

    raw   = response.choices[0].message.content.strip()
    clean = raw.replace("```json", "").replace("```", "").strip()
    start = clean.find("{")
    end   = clean.rfind("}") + 1

    if start == -1 or end == 0:
        raise ValueError(f"No JSON in Groq response:\n{raw[:500]}")

    data = json.loads(clean[start:end])
    log.info("Extracted %d jobs", len(data.get("jobs", [])))
    return data


# ─── Telegram helpers ─────────────────────────────────────────────────────────

def escape_md(text: str) -> str:
    if not text:
        return ""
    for ch in r"\_*[]()~`>#+-=|{}.!":
        text = text.replace(ch, f"\\{ch}")
    return text


def format_job_card(job: dict, index: int) -> str:
    type_emoji  = "🎓" if "intern" in job.get("type", "").lower() else "🏢"
    loc_emoji   = "🌐" if "remote" in job.get("location", "").lower() else "📍"
    skills_str  = " · ".join(job.get("skills", [])[:4])
    score       = job.get("match_score", 0)
    score_emoji = "🟢" if score >= 75 else ("🟡" if score >= 55 else "🔴")

    lines = [
        f"{type_emoji} *{escape_md(job.get('title','N/A'))}*",
        f"🏷 {escape_md(job.get('company','N/A'))}  ·  {escape_md(job.get('source',''))}",
        f"{loc_emoji} {escape_md(job.get('location','India'))}  ·  {escape_md(job.get('type',''))}",
        f"💰 {escape_md(str(job.get('stipend_or_ctc','Not disclosed')))}",
        f"🛠 `{escape_md(skills_str)}`",
        f"{score_emoji} Match: *{score}/100* \\— _{escape_md(job.get('match_reason',''))}_",
        f"📝 {escape_md(job.get('description',''))}",
    ]

    deadline = job.get("deadline", "").strip()
    if deadline:
        lines.append(f"⏰ Deadline: {escape_md(deadline)}")

    url = job.get("apply_url", "").strip()
    if url:
        lines.append(f"[→ Apply here]({url})")

    return "\n".join(lines)


def build_telegram_messages(data: dict, id_map: dict) -> list[str]:
    jobs  = data.get("jobs", [])[:SEND_TOP_N]
    date  = data.get("scan_date", datetime.now().strftime("%d %B %Y"))
    total = data.get("total_found", len(jobs))
    pulse = data.get("market_pulse", "")

    avg_score = int(sum(j.get("match_score", 50) for j in jobs) / len(jobs)) if jobs else 0

    messages = []

    messages.append(
        f"🔍 *Career Scan — {escape_md(date)}*\n"
        f"Found *{total}* openings \\| Showing top *{len(jobs)}*\n"
        f"Avg match score: *{avg_score}/100*\n\n"
        f"📊 *Market pulse:*\n_{escape_md(pulse)}_\n\n"
        f"💬 Commands: `/applied 1` `/saved 2` `/skip 3` `/status`"
    )

    for i, job in enumerate(jobs, 1):
        messages.append(
            f"━━━━━━━━━━━━━━━━\n"
            f"*\\#{i}*\n\n"
            f"{format_job_card(job, i)}"
        )

    messages.append(
        "━━━━━━━━━━━━━━━━\n"
        "⚡ _Groq \\+ DDG \\+ Adzuna \\+ JSearch \\+ Remotive \\+ Unstop_\n"
        "🔁 _Daily 9:00 AM IST_  ·  `/help` for all commands"
    )

    return messages


def send_single_message(text: str) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        httpx.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                "chat_id":                  TELEGRAM_CHAT_ID,
                "text":                     text,
                "parse_mode":               "MarkdownV2",
                "disable_web_page_preview": True,
            },
            timeout=15,
        )
    except Exception as e:
        log.warning("send_single_message failed: %s", e)


def send_telegram(messages: list[str]) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise ValueError("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env")

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    for i, text in enumerate(messages):
        try:
            r = httpx.post(
                url,
                json={
                    "chat_id":                  TELEGRAM_CHAT_ID,
                    "text":                     text,
                    "parse_mode":               "MarkdownV2",
                    "disable_web_page_preview": True,
                },
                timeout=15,
            )
            if r.status_code == 200:
                log.info("Telegram %d/%d sent ✓", i + 1, len(messages))
            else:
                log.error("Telegram error %d: %s", r.status_code, r.text[:200])
        except httpx.HTTPError as e:
            log.error("HTTP error on message %d: %s", i + 1, e)
        time.sleep(0.4)


def save_results(data: dict) -> None:
    os.makedirs("history", exist_ok=True)
    path = f"history/{datetime.now().strftime('%Y-%m-%d')}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    log.info("Saved to %s", path)


# ─── Main scan logic (also callable by /rescan) ───────────────────────────────

def run_scan() -> None:
    log.info("=" * 55)
    log.info("Starting scan — %s", datetime.now().strftime("%d %B %Y %H:%M"))
    log.info("=" * 55)

    try:
        # 1. Load seen URLs for dedup
        seen = load_seen_urls()
        log.info("Loaded %d seen URLs", len(seen))

        # 2. Check deadline alerts before scan
        alerts = check_deadline_alerts()
        for alert in alerts:
            send_single_message(alert)

        # 3. Search all sources
        raw_results = search_all_sources()
        if not raw_results:
            send_single_message("⚠️ Career Agent: No search results today\\.")
            return

        # 4. Extract jobs with Groq
        data = extract_jobs_with_groq(raw_results)
        save_results(data)

        jobs = data.get("jobs", [])
        if not jobs:
            send_single_message("📭 No matching fresher jobs found today\\.")
            return

        # 5. Duplicate filter
        jobs = filter_new_jobs(jobs, seen)
        if not jobs:
            send_single_message("📭 All jobs today were already sent before\\. Nothing new\\.")
            return

        # 6. Resume match scoring
        jobs = score_jobs_against_resume(jobs)

        # 7. Score filter — only send relevant jobs
        jobs_to_send = filter_by_score(jobs, RESUME_MATCH_THRESHOLD)
        if not jobs_to_send:
            send_single_message(
                f"📭 Found jobs but none scored above {RESUME_MATCH_THRESHOLD}/100 match\\. "
                f"Lowering threshold or broadening skills may help\\."
            )
            return

        # Store filtered jobs back in data for message building
        data["jobs"] = jobs_to_send

        # 8. Save to tracker DB + persist card→DB id map for bot_listener.py
        id_map = save_jobs_to_db(jobs_to_send)
        save_card_map(id_map)
        log.info("Saved %d jobs to tracker DB", len(jobs_to_send))

        # 9. Mark sent URLs as seen
        for job in jobs_to_send:
            url = job.get("apply_url", "").strip()
            if url:
                seen.add(url)
        save_seen_urls(seen)

        # 10. Build and send Telegram messages
        messages = build_telegram_messages(data, id_map)
        send_telegram(messages)

        log.info("✅ Scan done. Sent %d jobs.", len(jobs_to_send))

    except json.JSONDecodeError as e:
        log.error("JSON parse failed: %s", e)
        send_single_message("❌ Career Agent: JSON parse error\\. Check agent\\.log\\.")
    except Exception as e:
        log.exception("Unexpected error: %s", e)
        send_single_message(f"❌ Career Agent crashed: {escape_md(str(e)[:200])}")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    init_db()
    run_scan()


if __name__ == "__main__":
    main()
