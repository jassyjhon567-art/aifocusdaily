#!/usr/bin/env python3
"""
Manab AI - Autonomous Bilingual (EN/BN) Knowledge & News Engine
=================================================================
Serverless, database-free content pipeline. Reads RSS feeds across
10 niches, deduplicates stories, expands + translates content with
Gemini (with a MyMemory fallback translator), sources or generates
images, writes static HTML posts, updates a flat-file JSON index,
and (optionally) pings the Google Indexing API.

Designed to run inside GitHub Actions on a cron schedule.
"""

import os
import re
import ssl
import json
import time
import socket
import random
import string
import hashlib
import datetime
import urllib.parse

import requests
import feedparser

try:
    from google.oauth2 import service_account
    from google.auth.transport.requests import AuthorizedSession
    GOOGLE_AUTH_AVAILABLE = True
except ImportError:
    GOOGLE_AUTH_AVAILABLE = False

# ---------------------------------------------------------------------------
# 1. SSL / NETWORK COMPATIBILITY PATCHES (GitHub Runner fix)
# ---------------------------------------------------------------------------
# Some GitHub-hosted runners / older feed hosts trip SSL verification for
# reasons unrelated to real security issues on our side (missing intermediate
# certs on the feed's server, etc). We relax verification globally for the
# feed-fetching step only, and set a realistic User-Agent so WAFs/Cloudflare
# don't silently reject us.
ssl._create_default_https_context = ssl._create_unverified_context

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
feedparser.USER_AGENT = USER_AGENT

socket.setdefaulttimeout(20)

# ---------------------------------------------------------------------------
# 2. GLOBAL CONFIG
# ---------------------------------------------------------------------------
MAX_NEWS = 50
NEWS_FILE = "news.json"
POSTS_DIR = "posts"
IMAGES_DIR = "images"

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GCLOUD_KEY = os.environ.get("GCLOUD_KEY", "")
SITE_BASE_URL = os.environ.get("SITE_BASE_URL", "https://example.github.io/manab-ai")

# NOTE: gemini-1.5-flash was retired long ago and now returns 400/404 errors.
# gemini-flash-latest is a Google-maintained alias that always points at the
# current recommended Flash model, so this pipeline doesn't break again the
# next time Google rotates model versions. The v1beta path is required for
# generationConfig.responseMimeType support.
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")
GEMINI_ENDPOINT = (
    f"https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent"
)

MYMEMORY_ENDPOINT = "https://api.mymemory.translated.net/get"

REQUEST_HEADERS = {"User-Agent": USER_AGENT}

# ---------------------------------------------------------------------------
# 3. RSS FEED REGISTRY - 10 niches x 10 feeds = 100 sources
# ---------------------------------------------------------------------------
RSS_FEEDS = {
    "AI": [
        "https://www.artificialintelligence-news.com/feed/",
        "https://venturebeat.com/category/ai/feed/",
        "https://www.technologyreview.com/topic/artificial-intelligence/feed",
        "https://www.marktechpost.com/feed/",
        "https://syncedreview.com/feed/",
        "https://www.unite.ai/feed/",
        "https://bair.berkeley.edu/blog/feed.xml",
        "https://openai.com/blog/rss.xml",
        "https://www.deeplearning.ai/the-batch/feed/",
        "https://www.analyticsinsight.net/feed/",
    ],
    "Gadgets": [
        "https://www.theverge.com/rss/index.xml",
        "https://www.engadget.com/rss.xml",
        "https://gizmodo.com/rss",
        "https://www.techradar.com/rss",
        "https://www.cnet.com/rss/news/",
        "https://www.slashgear.com/feed/",
        "https://9to5mac.com/feed/",
        "https://9to5google.com/feed/",
        "https://www.pocket-lint.com/rss/news/",
        "https://www.tomsguide.com/feeds/all",
    ],
    "Software Dev": [
        "https://dev.to/feed",
        "https://www.infoq.com/feed/",
        "https://stackoverflow.blog/feed/",
        "https://github.blog/feed/",
        "https://www.smashingmagazine.com/feed/",
        "https://css-tricks.com/feed/",
        "https://blog.jetbrains.com/feed/",
        "https://martinfowler.com/feed.atom",
        "https://www.freecodecamp.org/news/rss/",
        "https://www.reddit.com/r/programming/.rss",
    ],
    "How-To Guides": [
        "https://www.wikihow.com/rss/all",
        "https://lifehacker.com/rss",
        "https://www.makeuseof.com/feed/",
        "https://www.howtogeek.com/feed/",
        "https://www.instructables.com/feed/",
        "https://www.tomsguide.com/feeds/how-to",
        "https://www.pcmag.com/feeds/rss/how-to",
        "https://www.techrepublic.com/rssfeeds/topic/how-to/",
        "https://helpdeskgeek.com/feed/",
        "https://www.digitaltrends.com/how-to/feed/",
    ],
    "SEO Marketing": [
        "https://moz.com/blog/feed",
        "https://searchengineland.com/feed",
        "https://www.searchenginejournal.com/feed/",
        "https://neilpatel.com/feed/",
        "https://blog.hubspot.com/marketing/rss.xml",
        "https://ahrefs.com/blog/feed/",
        "https://www.semrush.com/blog/feed/",
        "https://backlinko.com/feed",
        "https://contentmarketinginstitute.com/feed/",
        "https://www.socialmediaexaminer.com/feed/",
    ],
    "Cyber Security": [
        "https://krebsonsecurity.com/feed/",
        "https://threatpost.com/feed/",
        "https://www.darkreading.com/rss.xml",
        "https://www.bleepingcomputer.com/feed/",
        "https://thehackernews.com/feeds/posts/default",
        "https://www.securityweek.com/feed/",
        "https://www.schneier.com/feed/atom/",
        "https://www.cshub.com/rss/articles",
        "https://cyware.com/allnews/feed",
        "https://www.infosecurity-magazine.com/rss/news/",
    ],
    "Business": [
        "https://www.forbes.com/business/feed/",
        "https://fortune.com/feed/",
        "https://www.entrepreneur.com/latest.rss",
        "https://hbr.org/feed",
        "https://www.businessinsider.com/rss",
        "https://www.inc.com/rss/",
        "https://www.fastcompany.com/rss.xml",
        "https://www.economist.com/business/rss.xml",
        "https://www.cnbc.com/id/10001147/device/rss/rss.html",
        "https://www.ft.com/rss/home",
    ],
    "Science": [
        "https://www.sciencedaily.com/rss/all.xml",
        "https://www.livescience.com/feeds/all",
        "https://phys.org/rss-feed/",
        "https://www.newscientist.com/feed/home/",
        "https://www.nature.com/nature.rss",
        "https://www.scientificamerican.com/platform/syndication/rss/",
        "https://www.sciencenews.org/feed",
        "https://www.space.com/feeds/all",
        "https://www.eurekalert.org/rss.xml",
        "https://www.popsci.com/feed/",
    ],
    "Health": [
        "https://www.medicalnewstoday.com/rss",
        "https://www.healthline.com/rss",
        "https://www.webmd.com/rss/rss.aspx?RSSSource=RSS_PUBLIC",
        "https://www.sciencedaily.com/rss/health_medicine.xml",
        "https://www.who.int/rss-feeds/news-english.xml",
        "https://www.nih.gov/news-events/news-releases/feed",
        "https://www.health.harvard.edu/blog/feed",
        "https://www.everydayhealth.com/rss/all.xml",
        "https://www.self.com/feed/rss",
        "https://www.verywellhealth.com/feeds/all",
    ],
    "Lifestyle": [
        "https://www.realsimple.com/feeds/all-recipes",
        "https://www.goodhousekeeping.com/rss/all.xml/",
        "https://www.marthastewart.com/rss",
        "https://www.travelandleisure.com/feeds/all",
        "https://www.bonappetit.com/feed/rss",
        "https://www.self.com/feed/all",
        "https://www.mindbodygreen.com/rss",
        "https://www.apartmenttherapy.com/main.rss",
        "https://www.thespruce.com/feeds/all",
        "https://www.psychologytoday.com/intl/rss",
    ],
}

UNSPLASH_FALLBACKS = {
    "train": "https://images.unsplash.com/photo-1474487548417-781cb71495f3?w=1200&h=675&fit=crop",
    "railway": "https://images.unsplash.com/photo-1474487548417-781cb71495f3?w=1200&h=675&fit=crop",
    "cloud": "https://images.unsplash.com/photo-1451187580459-43490279c0fa?w=1200&h=675&fit=crop",
    "server": "https://images.unsplash.com/photo-1558494949-ef010cbdcc31?w=1200&h=675&fit=crop",
    "ai": "https://images.unsplash.com/photo-1620712943543-bcc4688e7485?w=1200&h=675&fit=crop",
    "robot": "https://images.unsplash.com/photo-1485827404703-89b55fcc595e?w=1200&h=675&fit=crop",
    "security": "https://images.unsplash.com/photo-1550751827-4bd374c3f58b?w=1200&h=675&fit=crop",
    "hacker": "https://images.unsplash.com/photo-1526374965328-7f61d4dc18c5?w=1200&h=675&fit=crop",
    "health": "https://images.unsplash.com/photo-1505751172876-fa1923c5c528?w=1200&h=675&fit=crop",
    "medicine": "https://images.unsplash.com/photo-1584308666744-24d5c474f2ae?w=1200&h=675&fit=crop",
    "business": "https://images.unsplash.com/photo-1454165804606-c3d57bc86b40?w=1200&h=675&fit=crop",
    "finance": "https://images.unsplash.com/photo-1611974789855-9c2a0a7236a3?w=1200&h=675&fit=crop",
    "science": "https://images.unsplash.com/photo-1507413245164-6160d8298b31?w=1200&h=675&fit=crop",
    "space": "https://images.unsplash.com/photo-1446776653964-20c1d3a81b06?w=1200&h=675&fit=crop",
    "phone": "https://images.unsplash.com/photo-1511707171634-5f897ff02aa9?w=1200&h=675&fit=crop",
    "laptop": "https://images.unsplash.com/photo-1496181133206-80ce9b88a853?w=1200&h=675&fit=crop",
    "code": "https://images.unsplash.com/photo-1461749280684-dccba630e2f6?w=1200&h=675&fit=crop",
    "marketing": "https://images.unsplash.com/photo-1533750349088-cd871a92f312?w=1200&h=675&fit=crop",
    "seo": "https://images.unsplash.com/photo-1571677246347-5040036b95cc?w=1200&h=675&fit=crop",
    "lifestyle": "https://images.unsplash.com/photo-1483721310020-03333e577078?w=1200&h=675&fit=crop",
    "food": "https://images.unsplash.com/photo-1495521821757-a1efb6729352?w=1200&h=675&fit=crop",
    "travel": "https://images.unsplash.com/photo-1488646953014-85cb44e25828?w=1200&h=675&fit=crop",
    "default": "https://images.unsplash.com/photo-1495020689067-958852a7765e?w=1200&h=675&fit=crop",
}

STOPWORDS = set(
    "a an the of to in on for and or is are was were be been being with "
    "at by from as it its this that these those into over under after "
    "before out up down not no new says say said will can could would".split()
)


# ---------------------------------------------------------------------------
# 4. UTILITY / CORE FUNCTIONS
# ---------------------------------------------------------------------------
def slugify(text):
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")[:80] or hashlib.md5(text.encode()).hexdigest()[:10]


def tokenize(text):
    words = re.findall(r"[a-zA-Z']+", (text or "").lower())
    return [w for w in words if w not in STOPWORDS and len(w) > 2]


def is_duplicate(title1, title2):
    """Word-overlap similarity check. Returns True if overlap ratio > 0.5."""
    if not title1 or not title2:
        return False
    set1, set2 = set(tokenize(title1)), set(tokenize(title2))
    if not set1 or not set2:
        return False
    overlap = len(set1 & set2)
    smaller = min(len(set1), len(set2))
    ratio = overlap / smaller if smaller else 0
    return ratio > 0.5


def extract_rss_image(entry):
    """Search common RSS/Atom image locations for a usable image URL."""
    try:
        if hasattr(entry, "media_content") and entry.media_content:
            for m in entry.media_content:
                url = m.get("url")
                if url:
                    return url
        if hasattr(entry, "media_thumbnail") and entry.media_thumbnail:
            for m in entry.media_thumbnail:
                url = m.get("url")
                if url:
                    return url
        if hasattr(entry, "enclosures") and entry.enclosures:
            for enc in entry.enclosures:
                url = enc.get("href") or enc.get("url")
                if url and enc.get("type", "").startswith("image"):
                    return url
                if url and re.search(r"\.(jpg|jpeg|png|webp)", url, re.I):
                    return url
        raw_html = ""
        if hasattr(entry, "summary"):
            raw_html += entry.summary
        if hasattr(entry, "content"):
            for c in entry.content:
                raw_html += c.get("value", "")
        match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', raw_html, re.I)
        if match:
            return match.group(1)
    except Exception:
        pass
    return None


def get_smart_fallback_image(title):
    """Return a high-res, contextually relevant Unsplash URL based on keywords."""
    title_lower = (title or "").lower()
    for keyword, url in UNSPLASH_FALLBACKS.items():
        if keyword == "default":
            continue
        if keyword in title_lower:
            return url
    return UNSPLASH_FALLBACKS["default"]


def clean_html(raw_html):
    text = re.sub(r"<[^>]+>", " ", raw_html or "")
    text = re.sub(r"&nbsp;|&#160;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&quot;", '"', text)
    text = re.sub(r"&#39;|&apos;", "'", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ---------------------------------------------------------------------------
# 5. TRANSLATION (fallback path via MyMemory)
# ---------------------------------------------------------------------------
def translate_to_bengali_fallback(text):
    """Translate a single chunk of text to Bengali via MyMemory (free, no key)."""
    if not text or not text.strip():
        return text
    try:
        chunk = text[:490]  # MyMemory has a ~500 char limit per request
        params = {"q": chunk, "langpair": "en|bn"}
        resp = requests.get(
            MYMEMORY_ENDPOINT, params=params, headers=REQUEST_HEADERS, timeout=15
        )
        if resp.status_code == 200:
            data = resp.json()
            translated = data.get("responseData", {}).get("translatedText")
            if translated:
                return translated
    except Exception as e:
        print(f"  [translate_to_bengali_fallback] error: {e}")
    return text  # graceful degrade: return original if translation fails


def translate_full_content_bn(text):
    """Iterate paragraph-by-paragraph and translate the entire article body."""
    if not text:
        return text
    paragraphs = [p for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        paragraphs = [text]
    translated_paragraphs = []
    for para in paragraphs:
        translated_paragraphs.append(translate_to_bengali_fallback(para))
        time.sleep(1)  # be polite to the free API
    return "\n\n".join(translated_paragraphs)


# ---------------------------------------------------------------------------
# 6. AI CONTENT REWRITE (Gemini, JSON structured output)
# ---------------------------------------------------------------------------
def rewrite_bilingual_gemini(api_key, title, raw_desc):
    """
    Ask Gemini to expand the short RSS summary into a 3-paragraph, 250-300
    word English article AND a full, equally detailed Bengali translation,
    returned as strict JSON so we never have to parse markdown fences.
    Returns a dict: {"title_en", "content_en", "title_bn", "content_bn",
    "summary_en", "summary_bn"} or None on failure.
    """
    if not api_key:
        return None

    prompt = f"""You are a professional bilingual (English/Bengali) news editor.

Given this article title and short summary, produce a JSON object with
these exact keys: title_en, summary_en, content_en, title_bn, summary_bn, content_bn.

Rules:
- title_en: a clean, engaging English headline (rewrite/polish the original).
- content_en: expand the short summary into a well-structured, informative
  3-paragraph article of 250-300 words in English. Do not fabricate specific
  statistics, quotes, or names not implied by the source. Write in a neutral,
  journalistic tone. Separate paragraphs with a blank line (\\n\\n).
- summary_en: a single-sentence (max 30 words) summary of content_en.
- title_bn: a natural, fluent Bengali translation of title_en (not transliteration).
- content_bn: a complete, fluent Bengali translation of content_en, matching
  it paragraph for paragraph, equally detailed - not a shortened summary.
- summary_bn: a fluent Bengali translation of summary_en.
- Return ONLY the raw JSON object. No markdown, no code fences, no commentary.

Title: {title}
Summary: {raw_desc}
"""

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.7,
        },
    }

    url = f"{GEMINI_ENDPOINT}?key={api_key}"

    try:
        resp = requests.post(url, json=payload, timeout=45)
        if resp.status_code != 200:
            print(f"  [gemini] non-200 status: {resp.status_code} {resp.text[:500]}")
            return None
        data = resp.json()
        candidates = data.get("candidates", [])
        if not candidates:
            return None
        parts = candidates[0].get("content", {}).get("parts", [])
        if not parts:
            return None
        raw_text = parts[0].get("text", "")
        raw_text = raw_text.strip()
        # Defensive strip in case markdown fences slip through anyway.
        raw_text = re.sub(r"^```(json)?", "", raw_text.strip())
        raw_text = re.sub(r"```$", "", raw_text.strip())
        parsed = json.loads(raw_text)
        required_keys = [
            "title_en", "summary_en", "content_en",
            "title_bn", "summary_bn", "content_bn",
        ]
        if all(k in parsed and parsed[k] for k in required_keys):
            return parsed
        return None
    except Exception as e:
        print(f"  [rewrite_bilingual_gemini] error: {e}")
        return None


def build_content_via_fallback(title, raw_desc):
    """
    No-Gemini / Gemini-failed path: lightly expand the summary using the
    original text (no fabrication) and translate everything with MyMemory.
    """
    clean_desc = clean_html(raw_desc)
    if len(clean_desc) < 40:
        clean_desc = f"{clean_desc} This story is developing and further details are expected as more information becomes available from the original source."

    para1 = clean_desc
    para2 = (
        f"The report highlights key developments related to \"{title}\", offering "
        f"context for readers who want to understand the broader implications of "
        f"this story as it continues to unfold."
    )
    para3 = (
        "Readers interested in the full details, including direct quotes and "
        "additional context, are encouraged to consult the original source linked "
        "at the end of this article."
    )
    content_en = f"{para1}\n\n{para2}\n\n{para3}"
    summary_en = clean_desc[:180].rsplit(" ", 1)[0] + "..." if len(clean_desc) > 180 else clean_desc

    content_bn = translate_full_content_bn(content_en)
    title_bn = translate_to_bengali_fallback(title)
    summary_bn = translate_to_bengali_fallback(summary_en)

    return {
        "title_en": title,
        "summary_en": summary_en,
        "content_en": content_en,
        "title_bn": title_bn,
        "summary_bn": summary_bn,
        "content_bn": content_bn,
    }


# ---------------------------------------------------------------------------
# 7. IMAGE SOURCING
# ---------------------------------------------------------------------------
def download_ai_image(prompt, slug, title):
    """
    Try to source an image, in order:
      1. Pollinations.ai (free, no key, text-to-image)
      2. Smart Unsplash fallback based on title keywords
    Returns a local relative path (e.g. images/slug.jpg) or None if
    everything failed (caller must then skip publishing per the
    "No Image, No Publish" rule).
    """
    os.makedirs(IMAGES_DIR, exist_ok=True)
    local_path = os.path.join(IMAGES_DIR, f"{slug}.jpg")

    # Attempt 1: Pollinations AI image generation
    try:
        encoded_prompt = urllib.parse.quote(
            f"{prompt}, professional editorial photo, 16:9, high detail, no text, no watermark"
        )
        poll_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1200&height=675&nologo=true"
        resp = requests.get(poll_url, headers=REQUEST_HEADERS, timeout=30)
        if resp.status_code == 200 and len(resp.content) > 5000:
            with open(local_path, "wb") as f:
                f.write(resp.content)
            return local_path
    except Exception as e:
        print(f"  [download_ai_image] pollinations failed: {e}")

    # Attempt 2: smart keyword-matched Unsplash fallback (downloaded locally)
    try:
        fallback_url = get_smart_fallback_image(title)
        resp = requests.get(fallback_url, headers=REQUEST_HEADERS, timeout=30)
        if resp.status_code == 200 and len(resp.content) > 5000:
            with open(local_path, "wb") as f:
                f.write(resp.content)
            return local_path
    except Exception as e:
        print(f"  [download_ai_image] unsplash fallback failed: {e}")

    return None


def download_original_image(image_url, slug):
    """Try to download the article's own image before falling back to AI/Unsplash."""
    if not image_url:
        return None
    os.makedirs(IMAGES_DIR, exist_ok=True)
    local_path = os.path.join(IMAGES_DIR, f"{slug}.jpg")
    try:
        resp = requests.get(image_url, headers=REQUEST_HEADERS, timeout=20)
        if resp.status_code == 200 and len(resp.content) > 5000:
            with open(local_path, "wb") as f:
                f.write(resp.content)
            return local_path
    except Exception as e:
        print(f"  [download_original_image] failed: {e}")
    return None


# ---------------------------------------------------------------------------
# 8. STATIC HTML POST GENERATION
# ---------------------------------------------------------------------------
POST_TEMPLATE = """<!DOCTYPE html>
<html lang="{lang}">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} | Manab AI</title>
<meta name="description" content="{summary}">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{summary}">
<meta property="og:image" content="{img_path}">
<meta property="og:type" content="article">
<link rel="alternate" hreflang="{other_lang_code}" href="{other_lang_url}">
<style>
  :root {{
    --bg: #0b0e14;
    --card: #131722;
    --accent: #6c5ce7;
    --accent-glow: #a29bfe;
    --text: #e6e6f0;
    --muted: #9aa0b4;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    line-height: 1.7;
  }}
  .wrap {{
    max-width: 780px;
    margin: 0 auto;
    padding: 1.5rem;
  }}
  @media (min-width: 768px) {{
    .wrap {{ padding: 2.5rem; }}
  }}
  .nav {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 2rem;
  }}
  .nav a {{
    color: var(--accent-glow);
    text-decoration: none;
    font-weight: 600;
  }}
  .lang-badge {{
    background: var(--card);
    border: 1px solid #262b3d;
    border-radius: 999px;
    padding: 0.3rem 0.9rem;
    font-size: 0.8rem;
    color: var(--muted);
  }}
  h1 {{
    font-size: 1.8rem;
    line-height: 1.3;
    margin-bottom: 0.5rem;
  }}
  .meta {{
    color: var(--muted);
    font-size: 0.9rem;
    margin-bottom: 1.5rem;
  }}
  .hero-img {{
    width: 100%;
    height: auto;
    aspect-ratio: 16 / 9;
    object-fit: cover;
    border-radius: 14px;
    margin-bottom: 1.5rem;
    box-shadow: 0 8px 30px rgba(0,0,0,0.4);
  }}
  .content p {{
    margin-bottom: 1.2rem;
    font-size: 1.05rem;
    color: var(--text);
  }}
  .summary {{
    font-style: italic;
    color: var(--muted);
    border-left: 3px solid var(--accent);
    padding-left: 1rem;
    margin-bottom: 1.5rem;
  }}
  .cta-wrap {{
    text-align: center;
    margin: 3rem 0 1.5rem;
  }}
  .original-btn {{
    display: inline-block;
    padding: 0.9rem 2rem;
    background: linear-gradient(135deg, var(--accent), var(--accent-glow));
    color: #fff;
    text-decoration: none;
    font-weight: 700;
    border-radius: 999px;
    box-shadow: 0 0 20px rgba(108, 92, 231, 0.6), 0 0 40px rgba(108, 92, 231, 0.3);
    transition: transform 0.2s ease, box-shadow 0.2s ease;
  }}
  .original-btn:hover {{
    transform: translateY(-2px);
    box-shadow: 0 0 28px rgba(108, 92, 231, 0.85), 0 0 55px rgba(108, 92, 231, 0.45);
  }}
  footer {{
    text-align: center;
    color: var(--muted);
    font-size: 0.85rem;
    margin-top: 2rem;
  }}
</style>
</head>
<body>
<div class="wrap">
  <div class="nav">
    <a href="../../index.html">&larr; Manab AI</a>
    <a class="lang-badge" href="{other_lang_url}">{other_lang_label}</a>
  </div>
  <h1>{title}</h1>
  <div class="meta">{source} &middot; {original_date}</div>
  <img class="hero-img" src="{img_path}" alt="{title}" referrerpolicy="no-referrer"
       onerror="this.onerror=null;this.src='{fallback_img}';">
  <p class="summary">{summary}</p>
  <div class="content">
    {content_html}
  </div>
  <div class="cta-wrap">
    <a class="original-btn" href="{orig_link}" target="_blank" rel="noopener noreferrer">
      Read More &mdash; Original Article
    </a>
  </div>
  <footer>&copy; {year} Manab AI &mdash; Automated Knowledge Platform</footer>
</div>
</body>
</html>
"""


def generate_post_html(
    slug,
    title,
    summary,
    content,
    img_path,
    lang,
    other_lang_url,
    source,
    original_date,
    orig_link,
):
    """
    Generate a static HTML post file.
    lang: "en" or "bn"
    Returns the relative file path written (e.g. posts/en/slug.html)
    """
    other_lang_code = "bn" if lang == "en" else "en"
    other_lang_label = "বাংলা" if lang == "en" else "English"

    paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
    content_html = "\n    ".join(f"<p>{p}</p>" for p in paragraphs)

    # img_path passed in is relative to repo root, e.g. "images/slug.jpg".
    # Posts live two levels deep (posts/en/slug.html), so walk up.
    img_rel = f"../../{img_path}" if img_path else ""
    fallback_img = get_smart_fallback_image(title)

    html = POST_TEMPLATE.format(
        lang=lang,
        title=title,
        summary=summary,
        img_path=img_rel,
        other_lang_code=other_lang_code,
        other_lang_url=other_lang_url,
        other_lang_label=other_lang_label,
        source=source,
        original_date=original_date,
        content_html=content_html,
        orig_link=orig_link,
        fallback_img=fallback_img,
        year=datetime.datetime.now().year,
    )

    out_dir = os.path.join(POSTS_DIR, lang)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{slug}.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    return out_path


# ---------------------------------------------------------------------------
# 9. GOOGLE INDEXING API (with retry queue)
# ---------------------------------------------------------------------------
def submit_to_google_indexing_with_retry(target_url, max_retries=3, delay_seconds=2):
    """
    Submit a URL to the Google Indexing API for faster crawl/index pickup.
    Requires GCLOUD_KEY env var containing a service-account JSON string.
    Silently no-ops if credentials or the google-auth library are unavailable.
    """
    if not GCLOUD_KEY or not GOOGLE_AUTH_AVAILABLE:
        return False

    try:
        creds_info = json.loads(GCLOUD_KEY)
    except Exception as e:
        print(f"  [indexing] GCLOUD_KEY is not valid JSON: {e}")
        return False

    scopes = ["https://www.googleapis.com/auth/indexing"]
    try:
        credentials = service_account.Credentials.from_service_account_info(
            creds_info, scopes=scopes
        )
        session = AuthorizedSession(credentials)
    except Exception as e:
        print(f"  [indexing] credential setup failed: {e}")
        return False

    endpoint = "https://indexing.googleapis.com/v3/urlNotifications:publish"
    body = {"url": target_url, "type": "URL_UPDATED"}

    for attempt in range(1, max_retries + 1):
        try:
            resp = session.post(endpoint, json=body, timeout=20)
            if resp.status_code == 200:
                print(f"  [indexing] submitted: {target_url}")
                return True
            print(
                f"  [indexing] attempt {attempt}/{max_retries} failed "
                f"({resp.status_code}): {resp.text[:150]}"
            )
        except Exception as e:
            print(f"  [indexing] attempt {attempt}/{max_retries} error: {e}")
        if attempt < max_retries:
            time.sleep(delay_seconds)
    return False


# ---------------------------------------------------------------------------
# 10. NEWS.JSON PERSISTENCE
# ---------------------------------------------------------------------------
def load_existing_news():
    if os.path.exists(NEWS_FILE):
        try:
            with open(NEWS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def save_news(news_list):
    news_list = news_list[:MAX_NEWS]
    with open(NEWS_FILE, "w", encoding="utf-8") as f:
        json.dump(news_list, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# 11. FEED FETCHING
# ---------------------------------------------------------------------------
def fetch_feed_entries(niche, url, limit=5):
    entries = []
    try:
        parsed = feedparser.parse(url, agent=USER_AGENT)
        for entry in parsed.entries[:limit]:
            title = getattr(entry, "title", "").strip()
            if not title:
                continue
            summary = getattr(entry, "summary", "") or getattr(entry, "description", "")
            link = getattr(entry, "link", "")
            published = getattr(entry, "published", "") or getattr(entry, "updated", "")
            image = extract_rss_image(entry)
            entries.append(
                {
                    "niche": niche,
                    "title": title,
                    "summary": clean_html(summary),
                    "link": link,
                    "published": published,
                    "image": image,
                    "source_domain": urllib.parse.urlparse(url).netloc,
                }
            )
    except Exception as e:
        print(f"  [fetch_feed_entries] {url} failed: {e}")
    return entries


# ---------------------------------------------------------------------------
# 12. MAIN PIPELINE
# ---------------------------------------------------------------------------
def main():
    print("=== Manab AI content engine starting ===")
    os.makedirs(POSTS_DIR + "/en", exist_ok=True)
    os.makedirs(POSTS_DIR + "/bn", exist_ok=True)
    os.makedirs(IMAGES_DIR, exist_ok=True)

    existing_news = load_existing_news()
    existing_titles = [item.get("title_en", "") for item in existing_news]

    candidate_entries = []
    for niche, feeds in RSS_FEEDS.items():
        for feed_url in feeds:
            entries = fetch_feed_entries(niche, feed_url, limit=3)
            candidate_entries.extend(entries)
            time.sleep(0.2)

    print(f"Collected {len(candidate_entries)} raw candidate entries from RSS feeds.")

    # Deduplicate against each other and against existing published titles
    unique_entries = []
    seen_titles = list(existing_titles)
    for entry in candidate_entries:
        if any(is_duplicate(entry["title"], seen) for seen in seen_titles):
            continue
        seen_titles.append(entry["title"])
        unique_entries.append(entry)

    print(f"{len(unique_entries)} unique, non-duplicate entries remain after filtering.")

    random.shuffle(unique_entries)
    new_posts = []
    max_new_per_run = 12

    for entry in unique_entries:
        if len(new_posts) >= max_new_per_run:
            break

        title = entry["title"]
        slug = slugify(title)

        # Skip if we've already generated this slug before (belt-and-suspenders)
        if os.path.exists(os.path.join(POSTS_DIR, "en", f"{slug}.html")):
            continue

        print(f"Processing: {title[:70]}")

        # --- AI rewrite (Gemini) with fallback path ---
        rewritten = rewrite_bilingual_gemini(GEMINI_API_KEY, title, entry["summary"])
        if not rewritten:
            print("  Gemini unavailable/failed, using fallback expansion+translation.")
            rewritten = build_content_via_fallback(title, entry["summary"])

        # --- Image sourcing: original -> AI-generated -> smart fallback ---
        img_path = None
        if entry.get("image"):
            img_path = download_original_image(entry["image"], slug)
        if not img_path:
            img_path = download_ai_image(rewritten["title_en"], slug, title)

        # STRICT "No Image, No Publish" rule
        if not img_path:
            print("  No image could be sourced or generated. Skipping article.")
            continue

        img_path = img_path.replace("\\", "/")  # normalize for Windows-safety

        original_date = entry.get("published") or datetime.datetime.utcnow().strftime(
            "%a, %d %b %Y %H:%M:%S GMT"
        )
        source = entry.get("source_domain", "Source")
        orig_link = entry.get("link", "#")

        en_url = f"{SITE_BASE_URL}/{POSTS_DIR}/en/{slug}.html"
        bn_url = f"{SITE_BASE_URL}/{POSTS_DIR}/bn/{slug}.html"

        # --- Generate both static HTML posts ---
        generate_post_html(
            slug,
            rewritten["title_en"],
            rewritten["summary_en"],
            rewritten["content_en"],
            img_path,
            "en",
            bn_url,
            source,
            original_date,
            orig_link,
        )
        generate_post_html(
            slug,
            rewritten["title_bn"],
            rewritten["summary_bn"],
            rewritten["content_bn"],
            img_path,
            "bn",
            en_url,
            source,
            original_date,
            orig_link,
        )

        post_record = {
            "slug": slug,
            "niche": entry["niche"],
            "title_en": rewritten["title_en"],
            "summary_en": rewritten["summary_en"],
            "title_bn": rewritten["title_bn"],
            "summary_bn": rewritten["summary_bn"],
            "image": img_path,
            "source": source,
            "orig_link": orig_link,
            "date": original_date,
            "url_en": f"{POSTS_DIR}/en/{slug}.html",
            "url_bn": f"{POSTS_DIR}/bn/{slug}.html",
            "created_at": datetime.datetime.utcnow().isoformat() + "Z",
        }
        new_posts.append(post_record)

        # --- Submit both language URLs to Google Indexing API ---
        submit_to_google_indexing_with_retry(en_url)
        submit_to_google_indexing_with_retry(bn_url)

    if new_posts:
        combined = new_posts + existing_news
        save_news(combined)
        print(f"Published {len(new_posts)} new bilingual articles. news.json updated.")
    else:
        print("No new articles published this run.")

    print("=== Manab AI content engine finished ===")


if __name__ == "__main__":
    main()
