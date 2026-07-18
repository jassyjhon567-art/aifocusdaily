import os
import json
import re
import requests
import feedparser
import urllib.parse
from datetime import datetime
from google.oauth2 import service_account
from google.auth.transport.requests import AuthorizedSession

FEEDS = {
    "TechCrunch AI": "https://techcrunch.com/category/artificial-intelligence/feed/",
    "VentureBeat AI": "https://venturebeat.com/category/ai/feed/"
}
MAX_NEWS = 50
NEWS_FILE = "news.json"
POSTS_DIR = "posts"
IMAGES_DIR = "images"

def slugify(text):
    text = text.lower()
    text = re.sub(r'[^a-z0-9\s-]', '', text)
    text = re.sub(r'[\s-]+', '-', text)
    return text.strip('-')

# আরএসএস ফিড থেকে মূল আর্টিকেলের অরিজিনাল ইমেজ লিঙ্কটি খুঁজে বের করার ফাংশন
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
        
    if 'content' in entry and len(entry.content) > 0:
        content_value = entry.content[0].get('value', '')
        img_match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', content_value)
        if img_match:
            return img_match.group(1)
            
    return None

# জেমিনি ক্র্যাশ করলেও স্বয়ংক্রিয়ভাবে ১০০% অনুবাদ করার ব্যাকআপ ইঞ্জিন (ফ্রি ও সিকিউরড)
def translate_to_bengali_fallback(text):
    if not text:
        return ""
    
    chunk_size = 800
    chunks = [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]
    translated_chunks = []
    
    for chunk in chunks:
        try:
            url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=bn&dt=t&q={urllib.parse.quote(chunk)}"
            response = requests.get(url, timeout=15)
            if response.status_code == 200:
                res_json = response.json()
                translated_text = "".join([sentence[0] for sentence in res_json[0] if sentence[0]])
                translated_chunks.append(translated_text)
            else:
                translated_chunks.append(chunk)
        except Exception as e:
            print(f"Fallback translation failed for chunk: {e}")
            translated_chunks.append(chunk)
            
    return "".join(translated_chunks)

# জেমিনি এপিআই দিয়ে একবারে বাংলা ও ইংরেজি অনুবাদ এবং এসইও কন্টেন্ট তৈরি করা
def rewrite_bilingual_gemini(api_key, title, raw_desc):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
    headers = {'Content-Type': 'application/json'}
    
    prompt = f"""
    You are an expert bilingual SEO content writer and tech journalist. Optimize the following AI news in both highly engaging Bengali (Bangla) and professional English.
    
    Original Title: {title}
    Original Content Summary: {raw_desc}

    Make both versions highly informative and keyword-rich for Google Search.
    Also, write a highly descriptive English image prompt (max 15 words) to generate a unique high-tech illustration related to this news.

    Provide the output STRICTLY in the following JSON format:
    {{
        "seo_title_en": "Catchy, SEO-optimized English title",
        "seo_summary_en": "A 150-character SEO meta description in English",
        "seo_content_en": "Full rewritten article in English. Wrap paragraphs in HTML <p> tags. Add a section 'Why It Matters' as <h3>.",
        "seo_title_bn": "Catchy, SEO-optimized Bengali title",
        "seo_summary_bn": "A 150-character SEO meta description in Bengali",
        "seo_content_bn": "Full rewritten article in Bengali. Wrap paragraphs in HTML <p> tags. Add a section 'কেন এটি গুরুত্বপূর্ণ' as <h3>.",
        "image_prompt": "Futuristic digital art of AI technology relevant to this article"
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

# কপিরাইট ও হটলিঙ্কিং এড়াতে নতুন এআই ইমেজ জেনারেট বা আসল ছবি ডাউনলোড করা
def download_ai_image(orig_img_url, prompt, slug):
    local_path = f"{IMAGES_DIR}/{slug}.jpg"
    fallback_url = "https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?auto=format&fit=crop&w=800&q=80"
    
    # ১. প্রথমে মূল খবরের আসল ছবি ডাউনলোড করার চেষ্টা করা হচ্ছে
    if orig_img_url and orig_img_url.startswith("http"):
        try:
            headers = {'User-Agent': 'Mozilla/5.0'}
            img_response = requests.get(orig_img_url, headers=headers, timeout=20)
            if img_response.status_code == 200:
                with open(local_path, "wb") as f:
                    f.write(img_response.content)
                print(f"Successfully saved original image for: {slug}")
                return local_path
        except Exception as e:
            print(f"Original image download failed for {slug}: {str(e)}. Trying AI generation...")

    # ২. আসল ছবি কাজ না করলে জেমিনির টাইটেল অনুসারে এআই ইমেজ জেনারেট হবে
    try:
        prompt_encoded = urllib.parse.quote(prompt)
        img_api_url = f"https://image.pollinations.ai/p/{prompt_encoded}?width=800&height=450&nologo=true"
        img_response = requests.get(img_api_url, timeout=25)
        if img_response.status_code == 200:
            with open(local_path, "wb") as f:
                f.write(img_response.content)
            print(f"Successfully saved AI generated image for: {slug}")
            return local_path
    except Exception as e:
        print(f"Error downloading AI image: {str(e)}")
        
    return fallback_url

# বাংলা ও ইংরেজি পৃথক এসইও স্ট্যাটিক পেজ জেনারেট করা
def generate_post_html(slug, title, summary, content, img_path, lang, other_lang_url, source):
    lang_dir = os.path.join(POSTS_DIR, lang)
    os.makedirs(lang_dir, exist_ok=True)
    file_path = os.path.join(lang_dir, f"{slug}.html")
    
    hreflang_bn = f'<link rel="alternate" hreflang="bn" href="../bn/{slug}.html" />'
    hreflang_en = f'<link rel="alternate" hreflang="en" href="../en/{slug}.html" />'
    
    back_text = "হোমে ফিরে যান" if lang == "bn" else "Back to Home"
    read_other_lang = "ইংরেজিতে পড়ুন" if lang == "bn" else "Read in Bengali"
    published_by = "প্রকাশিত" if lang == "bn" else "Published"
    source_label = "সূত্র" if lang == "bn" else "Source"

    # ইমেজ লিঙ্কের পাথ ঠিক করা (লোকাল ফাইল হলে ডাবল-ব্যাক স্লাশ হবে, বাহ্যিক হলে ইউআরএল ডিরেক্ট বসবে)
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
    </style>
</head>
<body>
    <div class="container">
        <div class="nav-links">
            <a href="../../" class="btn">&larr; {back_text}</a>
            <a href="{other_lang_url}" class="btn">{read_other_lang} &rarr;</a>
        </div>
        <img src="{display_img_path}" alt="{title}" onerror="this.src='https://images.unsplash.com/photo-1677442136019-21780efad99a?auto=format&fit=crop&w=800&q=80'">
        <h1>{title}</h1>
        <div class="meta">
            <span>{published_by}: {datetime.now().strftime("%Y-%m-%d")} | {source_label}: {source}</span>
        </div>
        <div class="content">
            {content}
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

    for source, url in FEEDS.items():
        try:
            response = requests.get(url, headers=headers, timeout=15)
            feed = feedparser.parse(response.content)
            
            for entry in feed.entries:
                orig_link = entry.get('link', '')
                if orig_link in existing_links:
                    continue 

                title = entry.get('title', 'No Title')
                raw_desc = re.sub('<[^<]+?>', '', entry.get('summary', ''))
                
                print(f"Processing bilingual article: {title}")
                
                # অরিজিনাল ইমেজ লিঙ্ক আরএসএস থেকে সংগ্রহ
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
                    # ফলব্যাক (জেমিনি ফেইল করলে স্বয়ংক্রিয় গুগল ট্র্যান্সলেশন ইঞ্জিন চালু হবে)
                    print("Gemini API failed. Initiating Google Translate Fallback Engine...")
                    title_en = title
                    summary_en = (raw_desc[:150] + "...") if len(raw_desc) > 150 else raw_desc
                    content_en = f"<p>{raw_desc}</p>"
                    
                    # ১০০% বাংলায় ট্র্যান্সলেট করা হচ্ছে
                    title_bn = translate_to_bengali_fallback(title)
                    summary_bn = translate_to_bengali_fallback(summary_en)
                    content_bn = f"<p>{translate_to_bengali_fallback(raw_desc)}</p>"
                    
                    image_prompt = f"Futuristic technology abstract digital illustration of {title_en[:30]}"

                # আসল ছবি ডাউনলোড অথবা জেমিনির টাইটেল অনুসারে এআই ইমেজ জেনারেশন
                img_url = download_ai_image(orig_img, image_prompt, slug)

                # বাংলা ও ইংরেজি দুটি পৃথক পেজ জেনারেশন
                generate_post_html(slug, title_bn, summary_bn, content_bn, img_url, "bn", f"../en/{slug}.html", source)
                generate_post_html(slug, title_en, summary_en, content_en, img_url, "en", f"../bn/{slug}.html", source)
                
                existing_news.insert(0, {
                    "title_en": title_en,
                    "title_bn": title_bn,
                    "link_en": f"posts/en/{slug}.html",
                    "link_bn": f"posts/bn/{slug}.html",
                    "original_link": orig_link,
                    "published": datetime.now().strftime("%Y-%m-%d"),
                    "source": source,
                    "image": img_url,
                    "description_en": summary_en,
                    "description_bn": summary_bn
                })
                new_articles_count += 1
                
        except Exception as e:
            print(f"Error processing feed {source}: {str(e)}")

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
        submit_to_google_indexing()

def submit_to_google_indexing():
    repo_full = os.environ.get("GITHUB_REPOSITORY", "")
    if not repo_full or "/" not in repo_full:
        return
    owner, repo = repo_full.split("/")
    target_url = f"https://{owner}.github.io/" if repo.lower() == f"{owner.lower()}.github.io" else f"https://{owner}.github.io/{repo}/"
    gcloud_key = os.environ.get("GCLOUD_KEY")
    if not gcloud_key:
        return
    try:
        info = json.loads(gcloud_key)
        credentials = service_account.Credentials.from_service_account_info(
            info,
            scopes=["https://www.googleapis.com/auth/indexing"]
        )
        session = AuthorizedSession(credentials)
        endpoint = "https://indexing.googleapis.com/v3/urlNotifications:publish"
        session.post(endpoint, json={"url": target_url, "type": "URL_UPDATED"})
        print("Google Indexing API successfully notified.")
    except Exception as e:
        print(f"Indexing API error: {str(e)}")

if __name__ == "__main__":
    main()
