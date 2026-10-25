#!/usr/bin/env python3
"""
scrape_quienes_somos.py
========================
Fetches the Quiénes Somos content and sidebar widgets
from socneurociencia.cl (WordPress).

Produces:
  scn_quienes/quienes_content.txt   ← main page text + headings
  scn_quienes/sidebar_news.json     ← recent-posts widget items
  scn_quienes/sidebar_links.json    ← links/blogroll widget
  scn_quienes/raw_page.html         ← full HTML for manual inspection

Requirements:
    pip install requests beautifulsoup4 lxml

Run:
    python3 scrape_quienes_somos.py
"""

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import json, os, re, time

BASE    = "https://socneurociencia.cl"
OUT     = "scn_quienes"
DELAY   = 1.0

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-CL,es;q=0.9,en;q=0.8",
}

# Candidate URLs for the Quiénes somos page — tries each in order
CANDIDATE_URLS = [
    f"{BASE}/quienes-somos/",
    f"{BASE}/la-sociedad/",
    f"{BASE}/sobre-nosotros/",
    f"{BASE}/quienes-somos",
    f"{BASE}/nosotros/",
    f"{BASE}/",          # fall back to homepage if no dedicated page
]

os.makedirs(OUT, exist_ok=True)

def clean(t):
    return re.sub(r"\s+", " ", t or "").strip()

def fetch(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=20, allow_redirects=True)
        print(f"  {r.status_code}  {r.url}")
        if r.status_code == 200:
            return r.text, r.url
    except Exception as e:
        print(f"  ERROR {url}: {e}")
    return None, None

# ── 1. Find the right page ────────────────────────────────────────────────────
print("\n── Looking for Quiénes somos page ──")
html = final_url = None
for candidate in CANDIDATE_URLS:
    print(f"  Trying {candidate}")
    html, final_url = fetch(candidate)
    if html:
        break
    time.sleep(DELAY)

if not html:
    print("ERROR: Could not reach any candidate URL.")
    raise SystemExit(1)

# Save raw HTML
with open(os.path.join(OUT, "raw_page.html"), "w", encoding="utf-8") as f:
    f.write(html)
print(f"\n  Raw HTML saved → {OUT}/raw_page.html")

soup = BeautifulSoup(html, "lxml")

# ── 2. Extract main content ───────────────────────────────────────────────────
print("\n── Extracting main content ──")

# WordPress content selectors, most specific first
CONTENT_SELECTORS = [
    {"class": re.compile(r"entry__article")},
    {"class": re.compile(r"entry-content")},
    {"class": re.compile(r"post-content")},
    {"class": re.compile(r"page-content")},
    {"id":    "content"},
    {"class": re.compile(r"main-content|site-content")},
]

content_el = None
for sel in CONTENT_SELECTORS:
    content_el = soup.find(True, sel)
    if content_el:
        print(f"  Found content with selector: {sel}")
        break

if not content_el:
    print("  Warning: no specific content block found, using <body>")
    content_el = soup.body

# Extract headings and paragraphs
headings = []
paragraphs = []

for tag in content_el.find_all(["h1","h2","h3","h4","p","li"], limit=200):
    t = clean(tag.get_text())
    if not t or len(t) < 3:
        continue
    if tag.name in ("h1","h2","h3","h4"):
        headings.append({"level": tag.name, "text": t})
    elif tag.name in ("p","li"):
        if len(t) > 20:          # skip nav crumbs / single words
            paragraphs.append(t)

full_text = clean(content_el.get_text())

output_text = (
    f"SOURCE: {final_url}\n"
    + "=" * 60 + "\n\n"
    + "HEADINGS:\n"
    + "\n".join(f"  [{h['level'].upper()}] {h['text']}" for h in headings)
    + "\n\n"
    + "PARAGRAPHS:\n"
    + "\n\n".join(f"  • {p}" for p in paragraphs)
    + "\n\n"
    + "FULL TEXT (raw):\n"
    + full_text
)

with open(os.path.join(OUT, "quienes_content.txt"), "w", encoding="utf-8") as f:
    f.write(output_text)
print(f"  Content saved → {OUT}/quienes_content.txt")
print(f"  {len(headings)} headings, {len(paragraphs)} paragraphs")

# ── 3. Extract sidebar widgets ────────────────────────────────────────────────
print("\n── Extracting sidebar ──")

SIDEBAR_SELECTORS = [
    {"id":    "sidebar"},
    {"class": re.compile(r"sidebar")},
    {"class": re.compile(r"widget-area")},
    {"id":    "secondary"},
    {"role":  "complementary"},
]

sidebar_el = None
for sel in SIDEBAR_SELECTORS:
    sidebar_el = soup.find(True, sel)
    if sidebar_el:
        print(f"  Found sidebar with selector: {sel}")
        break

if not sidebar_el:
    print("  No sidebar found — trying to scrape homepage for sidebar")
    time.sleep(DELAY)
    home_html, _ = fetch(BASE + "/")
    if home_html:
        home_soup = BeautifulSoup(home_html, "lxml")
        for sel in SIDEBAR_SELECTORS:
            sidebar_el = home_soup.find(True, sel)
            if sidebar_el:
                print(f"  Found sidebar on homepage with: {sel}")
                break

# Recent posts
sidebar_news = []
if sidebar_el:
    RECENT_SELECTORS = [
        {"class": re.compile(r"recent-posts|widget_recent_entries")},
        {"id":    re.compile(r"recent")},
    ]
    recent_el = None
    for sel in RECENT_SELECTORS:
        recent_el = sidebar_el.find(True, sel)
        if recent_el:
            break

    if not recent_el:
        recent_el = sidebar_el   # fall back: scan the whole sidebar

    for a in recent_el.find_all("a", href=True)[:10]:
        text = clean(a.get_text())
        href = a["href"]
        # Get date near the link if available
        date_el = a.find_next(class_=re.compile(r"date|time|post-date"))
        date = clean(date_el.get_text()) if date_el else ""
        if text and len(text) > 5:
            sidebar_news.append({"title": text, "url": href, "date": date})

    print(f"  Sidebar news items: {len(sidebar_news)}")
else:
    print("  No sidebar found.")

with open(os.path.join(OUT, "sidebar_news.json"), "w", encoding="utf-8") as f:
    json.dump(sidebar_news, f, ensure_ascii=False, indent=2)

# Links/Blogroll widget
sidebar_links = []
if sidebar_el:
    LINKS_SELECTORS = [
        {"class": re.compile(r"widget_links|blogroll|bookmarks")},
        {"id":    re.compile(r"links|blogroll")},
    ]
    links_widget = None
    for sel in LINKS_SELECTORS:
        links_widget = sidebar_el.find(True, sel)
        if links_widget:
            break

    # If no specific links widget, grab all external links in sidebar
    search_el = links_widget or sidebar_el
    for a in search_el.find_all("a", href=True):
        href = a["href"]
        text = clean(a.get_text())
        if href.startswith("http") and "socneurociencia" not in href and text:
            sidebar_links.append({"name": text, "url": href})

    # Deduplicate
    seen = set()
    sidebar_links = [
        d for d in sidebar_links
        if d["url"] not in seen and not seen.add(d["url"])
    ]
    print(f"  Sidebar external links: {len(sidebar_links)}")

with open(os.path.join(OUT, "sidebar_links.json"), "w", encoding="utf-8") as f:
    json.dump(sidebar_links, f, ensure_ascii=False, indent=2)

# ── 4. Summary ────────────────────────────────────────────────────────────────
print(f"""
── Done ────────────────────────────────────────────────
Files written to  {os.path.abspath(OUT)}/
  quienes_content.txt   ← paste this to Claude
  sidebar_news.json     ← paste this to Claude
  sidebar_links.json    ← paste this to Claude
  raw_page.html         ← open in browser to inspect

Next steps:
  1. Paste sidebar_links.json to Claude
  2. Run fetch_logos.py on those URLs to get logos/favicons
  3. Paste quienes_content.txt to update quienes-somos.html
────────────────────────────────────────────────────────
""")
