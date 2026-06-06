"""
Career Opportunity Agent — Free Edition
----------------------------------------
Sources:
  • DuckDuckGo Search
  • Adzuna API (free, India jobs)
  • JSearch RapidAPI (LinkedIn/Indeed scraper)
  • Remotive API (no key, remote tech jobs)
  • RSS feeds (Internshala, Naukri, Freshersworld)

LLM    → Groq (free tier, llama-3.3-70b-versatile)
Delivery → Telegram Bot API (free)
"""

import os
import json
import time
import logging
import httpx
import xml.etree.ElementTree as ET
from datetime import datetime
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

SEND_TOP_N     = 10
SEARCH_RESULTS = 5
DELAY_BETWEEN  = 2.0

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


# ─── Source 1: DuckDuckGo Search ──────────────────────────────────────────────
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


# ─── Source 2: Adzuna API ─────────────────────────────────────────────────────
def search_adzuna() -> list[dict]:
    if not ADZUNA_APP_ID or not ADZUNA_APP_KEY:
        log.warning("Adzuna: skipping — no credentials")
        return []

    results = []
    queries = [
        "software engineer intern",
        "software engineer fresher",
        "ML engineer fresher",
        "backend developer intern",
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
            r = httpx.get(url, timeout=15)
            data = r.json()

            for job in data.get("results", []):
                results.append({
                    "title":   job.get("title", ""),
                    "snippet": job.get("description", "")[:300],
                    "url":     job.get("redirect_url", ""),
                    "source":  "Adzuna",
                    "company": job.get("company", {}).get("display_name", ""),
                    "location": job.get("location", {}).get("display_name", ""),
                })
            log.info("Adzuna query '%s' → %d results", query, len(data.get("results", [])))
            time.sleep(1)
        except Exception as e:
            log.warning("Adzuna query '%s' failed: %s", query, e)

    log.info("Adzuna total: %d results", len(results))
    return results


# ─── Source 3: JSearch RapidAPI ───────────────────────────────────────────────
def search_jsearch() -> list[dict]:
    if not JSEARCH_API_KEY:
        log.warning("JSearch: skipping — no API key")
        return []

    results = []
    queries = [
        "software engineer intern India",
        "SDE fresher India 2026",
        "backend developer intern Bangalore",
        "ML engineer intern India",
        "graduate engineer trainee India",
    ]

    log.info("JSearch: fetching jobs...")

    headers = {
        "X-RapidAPI-Key":  JSEARCH_API_KEY,
        "X-RapidAPI-Host": "jsearch.p.rapidapi.com",
    }

    for query in queries:
        try:
            url = "https://jsearch.p.rapidapi.com/search"
            params = {
                "query":        query,
                "page":         "1",
                "num_pages":    "1",
                "country":      "in",
                "date_posted":  "week",
            }
            r = httpx.get(url, headers=headers, params=params, timeout=15)
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
            log.info("JSearch query '%s' → %d results", query, len(data.get("data", [])))
            time.sleep(1)
        except Exception as e:
            log.warning("JSearch query '%s' failed: %s", query, e)

    log.info("JSearch total: %d results", len(results))
    return results


# ─── Source 4: Remotive API (no key needed) ───────────────────────────────────
def search_remotive() -> list[dict]:
    results = []
    queries = [
        "software engineer",
        "backend developer",
        "machine learning",
        "data engineer",
        "devops",
    ]

    log.info("Remotive: fetching remote jobs...")

    for query in queries:
        try:
            url = f"https://remotive.com/api/remote-jobs?search={query.replace(' ', '%20')}&limit=5"
            r = httpx.get(url, timeout=15)
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
            log.info("Remotive query '%s' → %d results", query, len(data.get("jobs", [])))
            time.sleep(1)
        except Exception as e:
            log.warning("Remotive query '%s' failed: %s", query, e)

    log.info("Remotive total: %d results", len(results))
    return results


# ─── Source 5: RSS Feeds ──────────────────────────────────────────────────────
RSS_FEEDS = [
    {
        "name": "Freshersworld",
        "url":  "https://www.freshersworld.com/rss/jobs-for-freshers.xml",
    },
    {
        "name": "Naukri Fresher",
        "url":  "https://www.naukri.com/rss/fresher-jobs.xml",
    },
    {
        "name": "Internshala Intern",
        "url":  "https://internshala.com/rss/internships.xml",
    },
]

def search_rss() -> list[dict]:
    results = []

    log.info("RSS: fetching feeds...")

    for feed in RSS_FEEDS:
        try:
            r = httpx.get(feed["url"], timeout=15, follow_redirects=True)
            root = ET.fromstring(r.text)

            items = root.findall(".//item")[:10]
            for item in items:
                title   = item.findtext("title", "")
                url     = item.findtext("link", "")
                snippet = item.findtext("description", "")[:300]

                # Filter for tech/CSE relevant titles
                keywords = ["software", "developer", "engineer", "python", "java",
                           "backend", "frontend", "full stack", "ml", "data", "devops",
                           "intern", "fresher", "trainee", "cse", "it"]
                if any(kw in title.lower() for kw in keywords):
                    results.append({
                        "title":   title,
                        "snippet": snippet,
                        "url":     url,
                        "source":  feed["name"],
                    })

            log.info("RSS %s → %d relevant results", feed["name"], len(results))
        except Exception as e:
            log.warning("RSS feed %s failed: %s", feed["name"], e)

    log.info("RSS total: %d results", len(results))
    return results


# ─── Combine all sources ──────────────────────────────────────────────────────
def search_all_sources() -> list[dict]:
    all_results = []
    seen_urls   = set()

    sources = [
        ("DuckDuckGo", search_ddg),
        ("Adzuna",     search_adzuna),
        ("JSearch",    search_jsearch),
        ("Remotive",   search_remotive),
        ("RSS",        search_rss),
    ]

    for name, fn in sources:
        try:
            results = fn()
            new = 0
            for r in results:
                url = r.get("url", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    all_results.append(r)
                    new += 1
            log.info("Source %s added %d unique results", name, new)
        except Exception as e:
            log.error("Source %s crashed: %s", name, e)

    log.info("TOTAL unique results across all sources: %d", len(all_results))
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
            f"    Source: {r.get('source', '')}\n"
            f"    Snippet: {r['snippet'][:300]}\n"
        )

    prompt = f"""You are a career opportunity extraction agent. Today is {today}.

Below are job listings from multiple sources: DuckDuckGo, Adzuna, JSearch, Remotive, and RSS feeds.
Extract REAL job postings and return structured data.

Only include jobs that are:
- For freshers / interns / 2025-2027 batch
- Related to: {', '.join(ROLES[:8])} (and similar tech roles)
- Requiring skills from: {', '.join(SKILLS[:10])}
- Active / recently posted

Ignore expired jobs, course ads, and non-job content.

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
      "skills": ["skill1", "skill2", "skill3"],
      "stipend_or_ctc": "e.g. 25000/month or 8-12 LPA or Not disclosed",
      "description": "1-2 sentences about the role",
      "apply_url": "direct URL",
      "source": "LinkedIn / Naukri / Internshala / Adzuna / JSearch / Remotive / Other",
      "deadline": "deadline if mentioned, else empty string"
    }}
  ],
  "market_pulse": "2-3 sentences on trending roles and skills for freshers this week"
}}

Extract up to {SEND_TOP_N + 2} best matching jobs."""

    log.info("Sending %d snippets to Groq...", len(raw_results[:60]))
    client = Groq(api_key=GROQ_API_KEY)

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {
                "role": "system",
                "content": "You are a precise JSON extraction agent. Output only valid JSON, no markdown, no preamble.",
            },
            {"role": "user", "content": prompt},
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


# ─── Telegram formatting ──────────────────────────────────────────────────────
def escape_md(text: str) -> str:
    if not text:
        return ""
    for ch in r"\_*[]()~`>#+-=|{}.!":
        text = text.replace(ch, f"\\{ch}")
    return text


def format_job_card(job: dict, index: int) -> str:
    type_emoji = "🎓" if "intern" in job.get("type", "").lower() else "🏢"
    loc_emoji  = "🌐" if "remote" in job.get("location", "").lower() else "📍"
    skills_str = " · ".join(job.get("skills", [])[:4])

    lines = [
        f"{type_emoji} *{escape_md(job.get('title', 'N/A'))}*",
        f"🏷 {escape_md(job.get('company', 'N/A'))}  ·  {escape_md(job.get('source', ''))}",
        f"{loc_emoji} {escape_md(job.get('location', 'India'))}  ·  {escape_md(job.get('type', ''))}",
        f"💰 {escape_md(str(job.get('stipend_or_ctc', 'Not disclosed')))}",
        f"🛠 `{escape_md(skills_str)}`",
        f"📝 {escape_md(job.get('description', ''))}",
    ]

    deadline = job.get("deadline", "").strip()
    if deadline:
        lines.append(f"⏰ Deadline: {escape_md(deadline)}")

    url = job.get("apply_url", "").strip()
    if url:
        lines.append(f"[→ Apply here]({url})")

    return "\n".join(lines)


def build_telegram_messages(data: dict) -> list[str]:
    jobs  = data.get("jobs", [])[:SEND_TOP_N]
    date  = data.get("scan_date", datetime.now().strftime("%d %B %Y"))
    total = data.get("total_found", len(jobs))
    pulse = data.get("market_pulse", "")

    messages = []

    messages.append(
        f"🔍 *Career Scan — {escape_md(date)}*\n"
        f"Found *{total}* openings for freshers\\.\n"
        f"Showing top {len(jobs)}\\.\n\n"
        f"📊 *Market pulse:*\n_{escape_md(pulse)}_"
    )

    for i, job in enumerate(jobs, 1):
        messages.append(
            f"━━━━━━━━━━━━━━━━\n"
            f"*\\#{i}*\n\n"
            f"{format_job_card(job, i)}"
        )

    messages.append(
        "━━━━━━━━━━━━━━━━\n"
        "⚡ _Powered by Career Agent \\(Groq \\+ DDG \\+ Adzuna \\+ JSearch \\+ Remotive \\+ RSS\\)_\n"
        "🔁 _Runs daily at 9:00 AM IST_\n"
        "💡 _Edit agent\\.py to change roles/skills_"
    )

    return messages


def send_telegram(messages: list[str]) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise ValueError("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env")

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    for i, text in enumerate(messages):
        payload = {
            "chat_id":                  TELEGRAM_CHAT_ID,
            "text":                     text,
            "parse_mode":               "MarkdownV2",
            "disable_web_page_preview": True,
        }
        try:
            r = httpx.post(url, json=payload, timeout=15)
            if r.status_code == 200:
                log.info("Telegram %d/%d sent ✓", i + 1, len(messages))
            else:
                log.error("Telegram error %d: %s", r.status_code, r.text[:200])
        except httpx.HTTPError as e:
            log.error("HTTP error sending message %d: %s", i + 1, e)
        time.sleep(0.4)


def save_results(data: dict) -> None:
    os.makedirs("history", exist_ok=True)
    path = f"history/{datetime.now().strftime('%Y-%m-%d')}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    log.info("Saved to %s", path)


# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    log.info("=" * 55)
    log.info("Career Opportunity Agent (Free Edition) starting")
    log.info("=" * 55)

    try:
        raw_results = search_all_sources()

        if not raw_results:
            send_telegram(["⚠️ Career Agent: No results found today\\."])
            return

        data = extract_jobs_with_groq(raw_results)
        save_results(data)

        jobs = data.get("jobs", [])
        if not jobs:
            send_telegram(["📭 Career Agent: No matching fresher jobs found today\\."])
            return

        messages = build_telegram_messages(data)
        send_telegram(messages)

        log.info("✅ Done. Sent %d messages (%d jobs).", len(messages), len(jobs))

    except json.JSONDecodeError as e:
        log.error("JSON parse failed: %s", e)
        send_telegram(["❌ Career Agent: JSON parse failed\\."])
    except Exception as e:
        log.exception("Unexpected error: %s", e)
        send_telegram([f"❌ Career Agent crashed: {escape_md(str(e)[:200])}"])


if __name__ == "__main__":
    main()
