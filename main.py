import os
import json
import re
import requests
import feedparser
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

# Gemini API দিয়ে বাংলায় নতুন কন্টেন্ট ও ইমেজ জেনারেট করার প্রম্পট তৈরি করা
def rewrite_with_gemini(api_key, title, raw_desc):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
    headers = {'Content-Type': 'application/json'}
    
    prompt = f"""
    You are an expert SEO content writer and technology journalist. Rewrite the following AI news or launch in highly engaging, friendly Bengali (Bangla) language.
    Keep technical terms in English (e.g. 'Artificial Intelligence', 'LLM', 'neural network') if they are commonly searched.

    Original Title: {title}
    Original Content Summary: {raw_desc}

    Make it highly informative and SEO-optimized.
    Also, write a highly descriptive English image prompt (max 15 words) for generating a futuristic, high-tech, or AI-themed illustration relevant to this news. Do not use words like 'photorealistic' or 'copied'.

    Provide the output STRICTLY in the following JSON format:
    {{
        "seo_title": "A catchy, SEO-optimized title in Bengali",
        "seo_summary": "A 150-character meta description/summary in Bengali",
        "seo_content": "The full rewritten article in Bengali. Wrap paragraphs in HTML <p> tags. Add a section 'কেন এটি গুরুত্বপূর্ণ' (Why it matters) as <h3>.",
        "image_prompt": "Futuristic digital art of [insert key element based on article]"
    }}
    Ensure your output is valid JSON. Do not wrap in markdown codeblocks like ```json.
    """
    
    data = {
        "contents": [{
            "parts": [{
                "text": prompt
            }]
        }]
    }
    
    try:
        response = requests.post(url, headers=headers, json=data, timeout=30)
        if response.status_code == 200:
            res_json = response.json()
            raw_text = res_json['candidates'][0]['content']['parts'][0]['text']
            raw_text = raw_text.replace("```json", "").replace("```", "").strip()
            return json.loads(raw_text)
        else:
            print(f"Gemini API returned error: {response.status_code}")
            return None
    except Exception as e:
        print(f"Error during Gemini rewrite: {str(e)}")
        return None

# প্রতিটি নিউজের জন্য এসইও বান্ধব স্ট্যাটিক HTML পেজ জেনারেশন
def generate_post_html(slug, post_data, img_path):
    os.makedirs(POSTS_DIR, exist_ok=True)
    file_path = os.path.join(POSTS_DIR, f"{slug}.html")
    
    html_content = f"""<!DOCTYPE html>
<html lang="bn">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{post_data['seo_title']} - Manab AI</title>
    <meta name="description" content="{post_data['seo_summary']}">
    <meta property="og:title" content="{post_data['seo_title']}">
    <meta property="og:description" content="{post_data['seo_summary']}">
    <meta property="og:image" content="../{img_path}">
    <meta property="og:type" content="article">

    <style>
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
            width: 90%;
            margin: 3rem auto;
            background-color: #151824;
            padding: 2.5rem;
            border-radius: 16px;
            border: 1px solid rgba(255, 255, 255, 0.05);
            box-shadow: 0 10px 30px rgba(0, 242, 254, 0.15);
        }}
        img {{
            width: 100%;
            height: auto;
            border-radius: 12px;
            margin-bottom: 2rem;
            border: 1px solid rgba(255, 255, 255, 0.05);
        }}
        h1 {{
            font-size: 2.2rem;
            color: #00f2fe;
            line-height: 1.4;
            margin-bottom: 1.5rem;
        }}
        .meta {{
            color: #94a3b8;
            font-size: 0.9rem;
            margin-bottom: 2rem;
            border-bottom: 1px solid rgba(255,255,255,0.1);
            padding-bottom: 1rem;
        }}
        .content {{
            font-size: 1.1rem;
            line-height: 1.8;
            color: #e2e8f0;
        }}
        .content p {{
            margin-bottom: 1.5rem;
        }}
        .content h3 {{
            color: #00f2fe;
            margin-top: 2rem;
        }}
        a.back {{
            color: #00f2fe;
            text-decoration: none;
            font-weight: bold;
            display: inline-block;
            margin-bottom: 2rem;
        }}
    </style>
</head>
<body>
    <div class="container">
        <a href="../" class="back">&larr; হোমে ফিরে যান</a>
        <img src="../{img_path}" alt="{post_data['seo_title']}">
        <h1>{post_data['seo_title']}</h1>
        <div class="meta">প্রকাশিত: {datetime.now().strftime("%Y-%m-%d")} | Manab AI অটোমেশন</div>
        <div class="content">
            {post_data['seo_content']}
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
    if not gemini_key:
        print("GEMINI_API_KEY is not set. Exiting.")
        return

    # ডাটাবেজ লোড করা
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

    for source, url in FEEDS.items():
        try:
            response = requests.get(url, headers=headers, timeout=15)
            feed = feedparser.parse(response.content)
            
            for entry in feed.entries:
                orig_link = entry.get('link', '')
                if orig_link in existing_links:
                    continue 

                title = entry.get('title', '')
                raw_desc = re.sub('<[^<]+?>', '', entry.get('summary', ''))
                
                print(f"New article found: {title}. Rewriting and generating image...")
                
                # Gemini দিয়ে রিরাইট
                rewritten = rewrite_with_gemini(gemini_key, title, raw_desc)
                if not rewritten:
                    continue
                
                slug = slugify(rewritten["seo_title"])
                local_img_path = f"{IMAGES_DIR}/{slug}.jpg"
                
                # ৫. নতুন এআই ইমেজ জেনারেট করে ডাউনলোড করা (কপি না করে নতুন তৈরি করা)
                img_prompt_encoded = requests.utils.quote(rewritten["image_prompt"])
                img_api_url = f"https://image.pollinations.ai/p/{img_prompt_encoded}?width=800&height=450&nologo=true"
                
                try:
                    img_response = requests.get(img_api_url, timeout=30)
                    if img_response.status_code == 200:
                        with open(local_img_path, "wb") as f:
                            f.write(img_response.content)
                        img_url = local_img_path
                    else:
                        img_url = "https://images.unsplash.com/photo-1677442136019-21780efad99a?auto=format&fit=crop&w=800&q=80"
                except Exception as e:
                    print(f"Failed to generate image: {str(e)}")
                    img_url = "https://images.unsplash.com/photo-1677442136019-21780efad99a?auto=format&fit=crop&w=800&q=80"

                # ৬. স্ট্যাটিক পোস্ট পেজ জেনারেট করা
                generate_post_html(slug, rewritten, img_url)
                
                existing_news.insert(0, {
                    "title": rewritten["seo_title"],
                    "link": f"posts/{slug}.html", 
                    "original_link": orig_link,
                    "published": datetime.now().strftime("%Y-%m-%d"),
                    "source": source,
                    "image": img_url,
                    "description": rewritten["seo_summary"]
                })
                new_articles_count += 1
                
        except Exception as e:
            print(f"Error processing feed {source}: {str(e)}")

    if new_articles_count > 0:
        existing_news = existing_news[:MAX_NEWS]
        with open(NEWS_FILE, "w", encoding="utf-8") as f:
            json.dump(existing_news, f, ensure_ascii=False, indent=4)
        print(f"Added {new_articles_count} new posts.")
        submit_to_google_indexing()
    else:
        print("No new updates.")

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
