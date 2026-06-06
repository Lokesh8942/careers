"""
Career Opportunity Agent — Free Edition
----------------------------------------
100% free. No Anthropic API key needed.

Stack:
  • LLM      → Groq (free tier, llama-3.3-70b-versatile)
  • Search   → DuckDuckGo (no key, no limit)
  • Delivery → Telegram Bot API (free)

Setup:
  1. pip install -r requirements.txt
  2. cp .env.example .env  →  fill GROQ_API_KEY + Telegram creds
  3. python agent.py
  4. Schedule daily via cron / Task Scheduler (see README)
"""

import os
import json
import time
import logging
import httpx
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

# What to search for
ROLES = [
    "SDE Intern",
    "Software Engineer Fresher",
    "Backend Developer Fresher",
    "Full Stack Developer Fresher",
    "ML Engineer Fresher",
]

SKILLS         = ["Java", "Python", "DSA", "REST API", "SQL", "Spring Boot"]
LOCATIONS      = "Bangalore, Chennai, Hyderabad, Mumbai, Remote, Hybrid"
BATCH_YEARS    = "2025, 2026, 2027"
SEND_TOP_N     = 6       # job cards pushed to Telegram
SEARCH_RESULTS = 5       # DDG results fetched per query
DELAY_BETWEEN  = 2.0     # seconds between DDG queries (avoid rate limits)

# Search queries — mix of portals for best coverage
SEARCH_QUERIES = [
    "SDE intern 2026 2027 fresher apply now India",
    "software engineer fresher job opening India 2026",
    "backend developer intern India 2026 stipend apply",
    "full stack developer fresher job India hiring",
    "ML engineer intern fresher India 2026 apply",
    "fintech startup SDE intern India 2026 Java Python",
    "product company fresher software engineer India",
    "site:internshala.com software developer intern 2026",
    "site:unstop.com software engineer fresher hiring 2026",
    "site:linkedin.com/jobs SDE intern fresher India 2026",
]


# ─── Step 1: Search DuckDuckGo ─────────────────────────────────────────────────
def search_jobs() -> list[dict]:
    """Run multiple DDG queries and collect raw search snippets."""
    all_results = []
    seen_urls   = set()

    log.info("Starting DuckDuckGo search across %d queries...", len(SEARCH_QUERIES))

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
                    })
                    new += 1
            log.info("Query %d/%d → %d new results", i + 1, len(SEARCH_QUERIES), new)
        except Exception as e:
            log.warning("Query %d failed: %s", i + 1, e)

        if i < len(SEARCH_QUERIES) - 1:
            time.sleep(DELAY_BETWEEN)

    log.info("Total unique search results: %d", len(all_results))
    return all_results


# ─── Step 2: Send to Groq for extraction ──────────────────────────────────────
def extract_jobs_with_groq(raw_results: list[dict]) -> dict:
    """Feed raw search snippets to Groq and ask it to extract structured jobs."""

    if not raw_results:
        raise ValueError("No search results to process.")

    today = datetime.now().strftime("%d %B %Y")

    # Build a compact text block of search results
    snippets_text = ""
    for i, r in enumerate(raw_results[:40], 1):   # cap at 40 to stay in context
        snippets_text += (
            f"\n[{i}] Title: {r['title']}\n"
            f"    URL: {r['url']}\n"
            f"    Snippet: {r['snippet'][:300]}\n"
        )

    prompt = f"""You are a career opportunity extraction agent. Today is {today}.

Below are web search results about fresher job openings in India.
Your job: extract REAL job postings from these snippets and return structured data.

Only include jobs that are:
- Genuinely for freshers / 2025-2027 batch
- In India (or Remote / Hybrid)
- Related to: {', '.join(ROLES)}
- Requiring skills from: {', '.join(SKILLS)}
- Active / recently posted (not expired)

Ignore news articles, course ads, and non-job content.

SEARCH RESULTS:
{snippets_text}

Return ONLY valid JSON. No markdown, no preamble, no explanation. Schema:
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
      "description": "1-2 sentences about what you will do in this role",
      "apply_url": "direct URL from the search results",
      "source": "LinkedIn / Naukri / Internshala / Unstop / Company Site / Other",
      "deadline": "deadline if mentioned, else empty string"
    }}
  ],
  "market_pulse": "2-3 sentences on what roles and skills are trending for freshers this week based on these results"
}}

Extract up to {SEND_TOP_N + 2} jobs. If fewer real jobs are found, return only those."""

    log.info("Sending %d snippets to Groq for extraction...", len(raw_results[:40]))

    client = Groq(api_key=GROQ_API_KEY)

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a precise JSON extraction agent. "
                    "You output only valid JSON with no markdown fences, "
                    "no preamble, no trailing text. Nothing else."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
        max_tokens=3000,
    )

    raw = response.choices[0].message.content.strip()
    log.info("Groq responded (%d chars)", len(raw))

    # Strip accidental markdown fences
    clean = raw.replace("```json", "").replace("```", "").strip()

    start = clean.find("{")
    end   = clean.rfind("}") + 1
    if start == -1 or end == 0:
        raise ValueError(f"No JSON in Groq response. Raw:\n{raw[:500]}")

    data = json.loads(clean[start:end])
    log.info("Extracted %d jobs", len(data.get("jobs", [])))
    return data


# ─── Step 3: Format a job card for Telegram ───────────────────────────────────
def escape_md(text: str) -> str:
    """Escape Telegram MarkdownV2 special characters."""
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


# ─── Step 4: Build Telegram message list ──────────────────────────────────────
def build_telegram_messages(data: dict) -> list[str]:
    jobs   = data.get("jobs", [])[:SEND_TOP_N]
    date   = data.get("scan_date", datetime.now().strftime("%d %B %Y"))
    total  = data.get("total_found", len(jobs))
    pulse  = data.get("market_pulse", "")

    messages = []

    # Header
    messages.append(
        f"🔍 *Career Scan — {escape_md(date)}*\n"
        f"Found *{total}* openings for freshers\\.\n"
        f"Showing top {len(jobs)}\\.\n\n"
        f"📊 *Market pulse:*\n_{escape_md(pulse)}_"
    )

    # One card per job
    for i, job in enumerate(jobs, 1):
        messages.append(
            f"━━━━━━━━━━━━━━━━\n"
            f"*\\#{i}*\n\n"
            f"{format_job_card(job, i)}"
        )

    # Footer
    messages.append(
        "━━━━━━━━━━━━━━━━\n"
        "⚡ _Powered by Career Agent \\(Groq \\+ DDG\\)_\n"
        "🔁 _Runs daily at 8:00 AM_\n"
        "💡 _Edit agent\\.py to change roles/skills_"
    )

    return messages


# ─── Step 5: Send to Telegram ─────────────────────────────────────────────────
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
                log.info("Telegram message %d/%d sent ✓", i + 1, len(messages))
            else:
                log.error("Telegram error %d: %s", r.status_code, r.text[:200])
                # Plain-text fallback for job cards
                if i > 0:
                    httpx.post(url, json={
                        "chat_id":   TELEGRAM_CHAT_ID,
                        "text":      f"[Job #{i} — formatting error, check agent.log]",
                        "parse_mode": "",
                    }, timeout=10)
        except httpx.HTTPError as e:
            log.error("HTTP error sending message %d: %s", i + 1, e)

        time.sleep(0.4)   # Telegram rate limit: 30 messages/sec max


# ─── Step 6: Save results locally ─────────────────────────────────────────────
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
        # 1. Search
        raw_results = search_jobs()

        if not raw_results:
            log.warning("No search results found. Sending notification.")
            send_telegram(["⚠️ Career Agent: No search results found today\\. DDG may be rate\\-limiting\\. Will retry tomorrow\\."])
            return

        # 2. Extract with Groq
        data = extract_jobs_with_groq(raw_results)

        # 3. Save
        save_results(data)

        jobs = data.get("jobs", [])
        if not jobs:
            log.warning("Groq found no matching jobs in the search results.")
            send_telegram(["📭 Career Agent: Scanned the web but found no matching fresher openings today\\. Try again tomorrow or broaden your search in agent\\.py\\."])
            return

        # 4. Build messages
        messages = build_telegram_messages(data)

        # 5. Send
        send_telegram(messages)

        log.info("✅ Done. Sent %d messages (%d jobs).", len(messages), len(jobs))

    except json.JSONDecodeError as e:
        log.error("JSON parse failed: %s", e)
        send_telegram([f"❌ Career Agent error: JSON parse failed\\. Check agent\\.log\\."])
    except Exception as e:
        log.exception("Unexpected error: %s", e)
        send_telegram([f"❌ Career Agent crashed: {escape_md(str(e)[:200])}"])


if __name__ == "__main__":
    main()
