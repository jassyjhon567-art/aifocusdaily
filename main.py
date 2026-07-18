import os
import json
import re
import time
import requests
import feedparser
import urllib.parse
from datetime import datetime
from google.oauth2 import service_account
from google.auth.transport.requests import AuthorizedSession

# ১০টি নিশের প্রতিটিতে ১০টি করে মোট ১০০টি গ্লোবাল সোর্স (১০০% স্কেলযোগ্য)
NICHES_FEEDS = {
    "Artificial Intelligence": [
        "https://techcrunch.com/category/artificial-intelligence/feed/",
        "https://venturebeat.com/category/ai/feed/",
        "https://www.wired.com/feed/tag/ai/latest/rss",
        "https://www.forbes.com/artificial-intelligence/feed/",
        "https://www.technologyreview.com/topic/artificial-intelligence/feed/",
        "https://www.sciencedaily.com/rss/computers_math/artificial_intelligence.xml",
        "https://www.reddit.com/r/MachineLearning/.rss",
        "https://openai.com/news/rss.xml",
        "https://blog.google/technology/ai/rss/",
        "https://www.artificialintelligence-news.com/feed/"
    ],
    "Technology & Gadgets": [
        "https://www.wired.com/feed/category/gear/latest/rss",
        "https://www.theverge.com/rss/index.xml",
        "https://www.engadget.com/rss.xml",
        "https://mashable.com/feeds/rss/technology",
        "https://www.techradar.com/rss",
        "https://gizmodo.com/rss",
        "https://www.digitaltrends.com/feed/",
        "https://www.cnet.com/rss/all/",
        "https://www.slashgear.com/feed/",
        "https://www.pocket-lint.com/rss.xml"
    ],
    "Software & Development": [
        "https://feed.infoq.com/",
        "https://dev.to/feed",
        "https://news.ycombinator.com/rss",
        "https://www.sitepoint.com/feed/",
        "https://codepen.io/blog/feed/",
        "https://www.smashingmagazine.com/feed/",
        "https://www.kodeco.com/feed",
        "https://feeds.dzone.com/home",
        "https://sdtimes.com/feed/",
        "https://css-tricks.com/feed/"
    ],
    "How-To Guides & Tutorials": [
        "https://www.howtogeek.com/feed/",
        "https://www.makeuseof.com/feed/",
        "https://lifehacker.com/rss",
        "https://www.guidingtech.com/feed/",
        "https://techpp.com/feed/",
        "https://www.pcworld.com/index.rss",
        "https://www.techlicious.com/rss/",
        "https://www.onlinetechtips.com/feed/",
        "https://helpdeskgeek.com/feed/",
        "https://techwiser.com/feed/"
    ],
    "Blogging, SEO & Digital Marketing": [
        "https://searchengineland.com/feed",
        "https://www.searchenginejournal.com/feed/",
        "https://neilpatel.com/blog/feed/",
        "https://copyblogger.com/feed/",
        "https://moz.com/blog/feed",
        "https://blog.hubspot.com/marketing/rss.xml",
        "https://contentmarketinginstitute.com/feed/",
        "https://backlinko.com/feed",
        "https://www.socialmediaexaminer.com/feed/",
        "https://ahrefs.com/blog/feed/"
    ],
    "Cyber Security & Privacy": [
        "https://www.darkreading.com/rss.xml",
        "https://krebsonsecurity.com/feed/",
        "https://thehackernews.com/feeds/posts/default",
        "https://nakedsecurity.sophos.com/feed/",
        "https://feeds.feedburner.com/securityweek",
        "https://www.bleepingcomputer.com/feed/",
        "https://www.malwarebytes.com/blog/feed/",
        "https://grahamcluley.com/feed/",
        "https://www.schneier.com/blog/index.rdf"
    ],
    "Business & Productivity": [
        "https://www.fastcompany.com/latest/rss",
        "https://feeds.hbr.org/harvardbusiness",
        "https://www.entrepreneur.com/latest.rss",
        "https://www.forbes.com/technology/feed/",
        "https://www.inc.com/latest.rss",
        "https://productivityland.com/feed/",
        "https://www.asianefficiency.com/feed/",
        "https://todoist.com/inspiration/feed",
        "https://blog.trello.com/feed",
        "https://slack.com/blog/feed"
    ],
    "Education & Science": [
        "https://www.scientificamerican.com/news/rss/",
        "https://www.newscientist.com/feed/",
        "https://www.sciencedaily.com/rss/all.xml",
        "https://phys.org/rss-feed/",
        "https://www.space.com/feeds/all",
        "https://www.edutopia.org/rss.xml",
        "https://blog.ted.com/feed/",
        "https://www.insidehighered.com/rss/news",
        "https://www.smithsonianmag.com/rss/",
        "https://www.nasa.gov/news-release/feed/"
    ],
    "Health & Wellness": [
        "https://www.healthline.com/feed",
        "https://www.medicalnewstoday.com/feed",
        "https://www.health.harvard.edu/blog/feed",
        "https://www.sciencedaily.com/rss/health_medicine.xml",
        "https://rssfeeds.webmd.com/rss/rss.aspx",
        "https://www.mindbodygreen.com/rss",
        "https://www.wellandgood.com/feed/",
        "https://greatist.com/feed",
        "https://newsnetwork.mayoclinic.org/feed/",
        "https://www.activebeat.com/feed/"
    ],
    "Lifestyle & Internet Tips": [
        "https://www.gq.com/feed/rss",
        "https://www.vogue.com/feed/rss",
        "https://www.apartmenttherapy.com/main.rss",
        "https://www.thespruce.com/rss",
        "https://www.realsimple.com/rss",
        "https://mashable.com/feeds/rss/lifestyle",
        "https://www.howtogeek.com/category/internet/feed/",
        "https://www.makeuseof.com/category/internet/feed/",
        "https://www.digitaltrends.com/cool-tech/feed/",
        "https://www.wired.com/feed/category/culture/latest/rss"
    ]
}

def is_duplicate(title1, title2):
    words1 = set(re.sub(r'[^a-z0-9\s]', '', title1.lower()).split())
    words2 = set(re.sub(r'[^a-z0-9\s]', '', title2.lower()).split())
    if not words1 or not words2:
        return False
    overlap = words1.intersection(words2)
    ratio = len(overlap) / min(len(words1), len(words2))
    return ratio > 0.5

# আরএসএস ফিড থেকে মূল আর্টিকেলের অরিজিনাল ইমেজ লিঙ্ক খুঁজে বের করার ফাংশন
def extract_rss_image(entry):
    if 'media_content' in entry and len(entry.media_content) > 0:
        if 'url' in entry.media_content[0]:
            return entry.media_content[0]['url']
            
    if 'media_thumbnail' in entry and len(entry.media_thumbnail) > 0:
        if 'url' in entry.media_thumbnail[0]:
            return entry.media_thumbnail[0]['url']
            
    summary = entry.get('summary', '')
    img_match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', summary)
    if img_match:
        return img_match.group(1)
        
    return None

# MyMemory translation API (প্যারাগ্রাফ বাই প্যারাগ্রাফ অনুবাদের জন্য)
def translate_to_bengali_fallback(text):
    if not text:
        return ""
    try:
        url = f"https://api.mymemory.translated.net/get?q={urllib.parse.quote(text[:500])}&langpair=en|bn"
        response = requests.get(url, timeout=15)
        if response.status_code == 200:
            res_json = response.json()
            return res_json["responseData"]["translatedText"]
    except Exception as e:
        print(f"MyMemory translation failed: {e}")
    return text

# ইংরেজি আর্টিকেলের প্রতিটি প্যারাগ্রাফকে সমমানের বড় বাংলায় অনুবাদ করার ফাংশন
def translate_full_content_bn(text):
    if not text:
        return ""
    paragraphs = text.split("</p>")
    translated_paragraphs = []
    for p in paragraphs:
        p_clean = p.replace("<p>", "").strip()
        if p_clean:
            translated_p = translate_to_bengali_fallback(p_clean)
            translated_paragraphs.append(f"<p>{translated_p}</p>")
    return "".join(translated_paragraphs)

# টাইটেল কিওয়ার্ড বিশ্লেষণ করে গ্যারান্টিড বাস্তবধর্মী হাই-কোয়ালিটি কপিরাইট-মুক্ত ছবি সেট করার অ্যালগরিদম
def get_smart_fallback_image(title):
    title_lower = title.lower()
    if any(w in title_lower for w in ["railway", "train", "transport", "infrastructure"]):
        return "https://images.unsplash.com/photo-1532103054090-334e6e60ab29?auto=format&fit=crop&w=800&q=80"
    elif any(w in title_lower for w in ["database", "data", "cloud", "server", "aws", "azure", "databricks"]):
        return "https://images.unsplash.com/photo-1600132806370-bf17e65e942f?auto=format&fit=crop&w=800&q=80"
    elif any(w in title_lower for w in ["security", "hack", "cyber", "lock", "protect", "zoom", "exploit"]):
        return "https://images.unsplash.com/photo-1550751827-4bd374c3f58b?auto=format&fit=crop&w=800&q=80"
    elif any(w in title_lower for w in ["phone", "iphone", "android", "mobile", "vertu", "foldable", "gadget"]):
        return "https://images.unsplash.com/photo-1511707171634-5f897ff02aa9?auto=format&fit=crop&w=800&q=80"
    elif any(w in title_lower for w in ["code", "dev", "developer", "software", "website", "app", "tutorial"]):
        return "https://images.unsplash.com/photo-1555066931-4365d14bab8c?auto=format&fit=crop&w=800&q=80"
    elif any(w in title_lower for w in ["health", "lifestyle", "fitness", "doctor", "medical"]):
        return "https://images.unsplash.com/photo-1506126613408-eca07ce68773?auto=format&fit=crop&w=800&q=80"
    elif any(w in title_lower for w in ["ai", "artificial intelligence", "model", "llm", "chatgpt", "gemini", "robot", "brain"]):
        return "https://images.unsplash.com/photo-1677442136019-21780efad99a?auto=format&fit=crop&w=800&q=80"
    return "https://images.unsplash.com/photo-1488590528505-98d2b5aba04b?auto=format&fit=crop&w=800&q=80"

# জেমিনি এপিআই দিয়ে একবারে বাংলা ও ইংরেজি অনুবাদ এবং বিস্তারিত কন্টেন্ট তৈরি করা
def rewrite_bilingual_gemini(api_key, title, raw_desc):
    url = f"https://generativelanguage.googleapis.com/v1/models/gemini-1.5-flash:generateContent?key={api_key}"
    headers = {'Content-Type': 'application/json'}
    
    prompt = f"""
    You are an expert bilingual SEO content writer and tech journalist. Optimize the following AI or tech news in both highly engaging Bengali (Bangla) and professional English.
    
    Original Title: {title}
    Original Content Summary: {raw_desc}

    Since the input content summary might be short, you MUST EXPAND it into a fully comprehensive, highly detailed, and informative 3-paragraph news article of about 250-300 words for each language version. Do not summarize or make it short. The Bengali and English versions must be equally detailed, paragraph-by-paragraph.
    Use your knowledge about the tech industry to explain the background of the company, what this launch means, and why it is important for developers and businesses. Make the title and content extremely engaging, SEO-optimized, and compelling.
    
    Write a highly descriptive English image prompt (max 15 words) to generate a professional, highly realistic news photograph related to this news. Avoid abstract art.

    Provide the output STRICTLY in the following JSON format:
    {{
        "seo_title_en": "Catchy, SEO-optimized English title",
        "seo_summary_en": "A 150-character SEO meta description in English",
        "seo_content_en": "Full expanded, highly-detailed rewritten article in English. Wrap paragraphs in HTML <p> tags. Add a section 'Why It Matters' as <h3>.",
        "seo_title_bn": "Catchy, SEO-optimized Bengali title",
        "seo_summary_bn": "A 150-character SEO meta description in Bengali",
        "seo_content_bn": "Full expanded, highly-detailed rewritten article in Bengali. Wrap paragraphs in HTML <p> tags. Add a section 'কেন এটি গুরুত্বপূর্ণ' as <h3>.",
        "image_prompt": "A professional realistic news photograph of [key element], 16:9 aspect ratio, high resolution"
    }}
    """
    
    data = {
        "contents": [{
            "parts": [{
                "text": prompt
            }]
        }],
        "generationConfig": {
            "responseMimeType": "application/json"
        }
    }
    
    try:
        response = requests.post(url, headers=headers, json=data, timeout=30)
        if response.status_code == 200:
            res_json = response.json()
            raw_text = res_json['candidates'][0]['content']['parts'][0]['text'].strip()
            
            start = raw_text.find('{')
            end = raw_text.rfind('}')
            if start != -1 and end != -1:
                return json.loads(raw_text[start:end+1])
            else:
                return json.loads(raw_text)
        else:
            print(f"Gemini API returned error: {response.status_code}")
            return None
    except Exception as e:
        print(f"Error during Gemini rewrite: {str(e)}")
        return None

# বাস্তবধর্মী এআই ছবি জেনারেশন
def download_ai_image(prompt, slug, title):
    local_path = f"{IMAGES_DIR}/{slug}.jpg"
    fallback_url = get_smart_fallback_image(title)
    try:
        prompt_encoded = urllib.parse.quote(prompt)
        img_api_url = f"https://image.pollinations.ai/p/{prompt_encoded}?width=800&height=450&nologo=true"
        img_response = requests.get(img_api_url, timeout=25)
        if img_response.status_code == 200:
            with open(local_path, "wb") as f:
                f.write(img_response.content)
            return local_path
    except Exception as e:
        print(f"Error downloading AI image: {str(e)}")
    return fallback_url

# বাংলা ও ইংরেজি পৃথক এসইও স্ট্যাটিক পেজ জেনারেট করা
def generate_post_html(slug, title, summary, content, img_path, lang, other_lang_url, source, original_date, orig_link):
    lang_dir = os.path.join(POSTS_DIR, lang)
    os.makedirs(lang_dir, exist_ok=True)
    file_path = os.path.join(lang_dir, f"{slug}.html")
    
    hreflang_bn = f'<link rel="alternate" hreflang="bn" href="../bn/{slug}.html" />'
    hreflang_en = f'<link rel="alternate" hreflang="en" href="../en/{slug}.html" />'
    
    back_text = "হোমে ফিরে যান" if lang == "bn" else "Back to Home"
    read_other_lang = "ইংরেজিতে পড়ুন" if lang == "bn" else "Read in Bengali"
    published_by = "প্রকাশিত" if lang == "bn" else "Published"
    source_label = "সূত্র" if lang == "bn" else "Source"

    display_img_path = img_path
    if not img_path.startswith("http"):
        display_img_path = f"../../{img_path}"

    html_content = f"""<!DOCTYPE html>
<html lang="{lang}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} - Manab AI</title>
    <meta name="description" content="{summary}">
    
    {hreflang_bn}
    {hreflang_en}

    <meta property="og:title" content="{title}">
    <meta property="og:description" content="{summary}">
    <meta property="og:image" content="{display_img_path}">
    <meta property="og:type" content="article">

    <style>
        * {{
            box-sizing: border-box;
        }}
        body {{ 
            background-color: #0d0e15; 
            color: #ffffff; 
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; 
            margin: 0; 
            padding: 0; 
            display: flex; 
            flex-direction: column; 
            align-items: center; 
        }}
        .container {{ 
            max-width: 800px; 
            width: 95%; 
            margin: 1.5rem auto; 
            background-color: #151824; 
            padding: 1.5rem; 
            border-radius: 16px; 
            border: 1px solid rgba(255, 255, 255, 0.05); 
            box-shadow: 0 10px 30px rgba(0, 242, 254, 0.15); 
        }}
        @media (min-width: 768px) {{
            .container {{
                width: 90%;
                margin: 3rem auto;
                padding: 2.5rem;
            }}
        }}
        img {{ 
            width: 100%; 
            height: auto; 
            border-radius: 12px; 
            margin-bottom: 2rem; 
            border: 1px solid rgba(255, 255, 255, 0.05); 
        }}
        h1 {{ 
            font-size: 1.8rem; 
            color: #00f2fe; 
            line-height: 1.4; 
            margin-bottom: 1.5rem; 
        }}
        @media (min-width: 768px) {{
            h1 {{
                font-size: 2.2rem;
            }}
        }}
        .meta {{ 
            color: #94a3b8; 
            font-size: 0.9rem; 
            margin-bottom: 2rem; 
            border-bottom: 1px solid rgba(255,255,255,0.1); 
            padding-bottom: 1rem; 
            display: flex; 
            justify-content: space-between; 
        }}
        .content {{ 
            font-size: 1.05rem; 
            line-height: 1.8; 
            color: #e2e8f0; 
        }}
        @media (min-width: 768px) {{
            .content {{
                font-size: 1.1rem;
            }}
        }}
        .content p {{ margin-bottom: 1.5rem; }}
        .content h3 {{ color: #00f2fe; margin-top: 2rem; }}
        .nav-links {{ display: flex; justify-content: space-between; margin-bottom: 2rem; }}
        a.btn {{ color: #00f2fe; text-decoration: none; font-weight: bold; font-size: 0.95rem; }}
        a.btn:hover {{ text-decoration: underline; }}
        
        /* 'Read More – Original Article' গ্লোয়িং বাটনের স্টাইল */
        .btn-original-container {{
            text-align: center;
            margin-top: 3rem;
            margin-bottom: 1.5rem;
        }}
        .original-article-btn {{
            display: inline-block;
            background: linear-gradient(45deg, #00f2fe, #4facfe);
            color: #0d0e15;
            padding: 12px 30px;
            border-radius: 30px;
            font-weight: bold;
            text-decoration: none;
            box-shadow: 0 0 15px rgba(0, 242, 254, 0.4);
            transition: all 0.3s ease;
        }}
        .original-article-btn:hover {{
            transform: translateY(-3px);
            box-shadow: 0 0 25px rgba(0, 242, 254, 0.8);
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="nav-links">
            <a href="../../" class="btn">&larr; {back_text}</a>
            <a href="{other_lang_url}" class="btn">{read_other_lang} &rarr;</a>
        </div>
        <img src="{display_img_path}" alt="{title}" referrerpolicy="no-referrer" onerror="this.src='https://images.unsplash.com/photo-1677442136019-21780efad99a?auto=format&fit=crop&w=800&q=80'">
        <h1>{title}</h1>
        <div class="meta">
            <span>{published_by}: {original_date} | {source_label}: {source}</span>
        </div>
        <div class="content">
            {content}
        </div>
        <!-- অরিজিনাল নিউজ ভেরিফাই করার চূড়ান্ত গ্লোয়িং বাটন -->
        <div class="btn-original-container">
            <a href="{orig_link}" target="_blank" rel="noopener noreferrer" class="original-article-btn">Read More – Original Article</a>
        </div>
    </div>
</body>
</html>
"""
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    return file_path

def main():
    gemini_key = os.environ.get("GEMINI_API_KEY")
    
    if os.path.exists(NEWS_FILE):
        try:
            with open(NEWS_FILE, "r", encoding="utf-8") as f:
                existing_news = json.load(f)
        except:
            existing_news = []
    else:
        existing_news = []

    existing_links = {item['original_link'] for item in existing_news}
    headers = {'User-Agent': 'Mozilla/5.0'}
    new_articles_count = 0

    os.makedirs(IMAGES_DIR, exist_ok=True)
    os.makedirs(os.path.join(POSTS_DIR, "bn"), exist_ok=True)
    os.makedirs(os.path.join(POSTS_DIR, "en"), exist_ok=True)

    # সব সোর্স থেকে খবরের ডেটা স্ক্যান
    raw_feed_entries = []
    for niche, feeds_list in NICHES_FEEDS.items():
        for url in feeds_list:
            try:
                response = requests.get(url, headers=headers, timeout=15)
                feed = feedparser.parse(response.content)
                for entry in feed.entries:
                    raw_feed_entries.append((entry, niche))
            except Exception as e:
                print(f"Error reading feed {url} under {niche}: {e}")

    # ডুপ্লিকেট নিউজ এড়ানো এবং সবচেয়ে ভালো সোর্স নির্বাচন করা
    unique_entries = []
    for entry, source in raw_feed_entries:
        orig_link = entry.get('link', '')
        if orig_link in existing_links:
            continue
            
        is_dup = False
        for u_entry, u_source in unique_entries:
            if is_duplicate(entry.get('title', ''), u_entry.get('title', '')):
                is_dup = True
                break
        if not is_dup:
            unique_entries.append((entry, source))

    # প্রতি রানে সর্বোচ্চ ৫টি নতুন খবর রিরাইট করা হবে
    for entry, source in unique_entries[:5]:
        try:
            title = entry.get('title', 'No Title')
            raw_desc = re.sub('<[^<]+?>', '', entry.get('summary', ''))
            original_date = entry.get('published', datetime.now().strftime("%Y-%m-%d"))
            orig_link = entry.get('link', '')
            
            print(f"Processing: {title} (Source Category: {source})")
            
            # আরএসএস থেকে অরিজিনাল ছবি
            orig_img = extract_rss_image(entry)
            
            rewritten = None
            if gemini_key:
                rewritten = rewrite_bilingual_gemini(gemini_key, title, raw_desc)
            
            slug = slugify(title[:50])
            
            if rewritten:
                title_en = rewritten["seo_title_en"]
                summary_en = rewritten["seo_summary_en"]
                content_en = rewritten["seo_content_en"]
                
                title_bn = rewritten["seo_title_bn"]
                summary_bn = rewritten["seo_summary_bn"]
                content_bn = rewritten["seo_content_bn"]
                
                image_prompt = rewritten["image_prompt"]
            else:
                print("Gemini API failed. Initiating MyMemory Fallback Engine...")
                title_en = title
                summary_en = (raw_desc[:150] + "...") if len(raw_desc) > 150 else raw_desc
                content_en = f"<p>{raw_desc}</p>"
                
                # বাংলায় প্যারাগ্রাফ বাই প্যারাগ্রাফ অনুবাদ
                title_bn = translate_to_bengali_fallback(title)
                summary_bn = translate_to_bengali_fallback(summary_en)
                content_bn = translate_full_content_bn(content_en)
                
                image_prompt = f"Professional realistic news photograph of {title_en[:30]}"

            # অরিজিনাল ইমেজ লিঙ্ক থাকলে সেটি ব্যবহার, অন্যথায় বাস্তবধর্মী এআই ইমেজ জেনারেশন
            if orig_img:
                img_url = orig_img
            else:
                img_url = download_ai_image(image_prompt, slug, title)

            # কঠোর নিয়ম: যদি কোনো ছবি না পাওয়া যায়, তবে নিউজটি প্রকাশ করা হবে না (Skip করা হবে)
            if not img_url or img_url == "":
                print(f"Skipping article '{title}' because no valid image is available.")
                continue

            # বাংলা ও ইংরেজি দুটি পৃথক পেজ জেনারেশন
            generate_post_html(slug, title_bn, summary_bn, content_bn, img_url, "bn", f"../en/{slug}.html", source, original_date, orig_link)
            generate_post_html(slug, title_en, summary_en, content_en, img_url, "en", f"../bn/{slug}.html", source, original_date, orig_link)
            
            existing_news.insert(0, {
                "title_en": title_en,
                "title_bn": title_bn,
                "link_en": f"posts/en/{slug}.html",
                "link_bn": f"posts/bn/{slug}.html",
                "original_link": orig_link,
                "published": original_date,
                "source": source,
                "image": img_url,
                "description_en": summary_en,
                "description_bn": summary_bn
            })
            new_articles_count += 1
            
        except Exception as e:
            print(f"Error processing article: {str(e)}")

    if not existing_news:
        existing_news.append({
            "title_en": "Manab AI System is Successfully Active!",
            "title_bn": "মানব এআই (Manab AI) সফলভাবে সক্রিয় হয়েছে!",
            "link_en": "#",
            "link_bn": "#",
            "original_link": "https://manab.ai",
            "published": datetime.now().strftime("%Y-%m-%d"),
            "source": "Manab System",
            "image": "https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?auto=format&fit=crop&w=800&q=80",
            "description_en": "Welcome! Your bilingual AI news publishing bot is successfully activated. As soon as new AI updates are released, it will update automatically.",
            "description_bn": "স্বাগতম! আপনার দ্বিভাষিক এআই নিউজ পোস্টিং বটটি সফলভাবে চালু হয়েছে। নতুন কোনো এআই আপডেট আসামাত্রই এখানে তা স্বয়ংক্রিয়ভাবে আপডেট হতে থাকবে।"
        })

    existing_news = existing_news[:MAX_NEWS]
    with open(NEWS_FILE, "w", encoding="utf-8") as f:
        json.dump(existing_news, f, ensure_ascii=False, indent=4)
    print(f"Database updated. Total articles: {len(existing_news)}")
    
    if new_articles_count > 0:
        # সফলভাবে জেনারেট হওয়া পেজগুলোর ডায়নামিক লিঙ্ক ইনডেক্স করা
        repo_full = os.environ.get("GITHUB_REPOSITORY", "")
        if repo_full and "/" in repo_full:
            owner, repo = repo_full.split("/")
            base_url = f"https://{owner}.github.io/" if repo.lower() == f"{owner.lower()}.github.io" else f"https://{owner}.github.io/{repo}/"
            # মেইন পেজ ইনডেক্সিং
            submit_to_google_indexing_with_retry(base_url)

# গুগল ক্লাউড এপিআই ইনডেক্সিং রিকোয়েস্ট উইথ রিট্রাই কিউ (Retry Queue System)
def submit_to_google_indexing_with_retry(target_url):
    gcloud_key = os.environ.get("GCLOUD_KEY")
    if not gcloud_key:
        print("GCLOUD_KEY secret not found. Skipping Google Indexing.")
        return
        
    print(f"Submitting Indexing Request for: {target_url}")
    max_retries = 3
    for attempt in range(max_retries):
        try:
            info = json.loads(gcloud_key)
            credentials = service_account.Credentials.from_service_account_info(
                info,
                scopes=["https://www.googleapis.com/auth/indexing"]
            )
            session = AuthorizedSession(credentials)
            endpoint = "https://indexing.googleapis.com/v3/urlNotifications:publish"
            data = {
                "url": target_url,
                "type": "URL_UPDATED"
            }
            response = session.post(endpoint, json=data, timeout=20)
            if response.status_code == 200:
                print(f"Google Indexing API Success (Attempt {attempt+1}): {response.text}")
                return True
            else:
                print(f"Google Indexing API returned status {response.status_code} on attempt {attempt+1}. Retrying...")
        except Exception as e:
            print(f"Error calling Google Indexing API on attempt {attempt+1}: {str(e)}")
        time.sleep(2)
    print("Failed to notify Google Indexing after all attempts.")
    return False

if __name__ == "__main__":
    main()
