#!/usr/bin/env python3
"""
fetch_logos.py
==============
Fetches the best available logo or favicon from a list of URLs.
Tries (in order of quality): SVG logo, PNG logo, og:image, apple-touch-icon, favicon.

For each URL it produces:
  logos/<slug>.svg / .png / .ico    ← best image found
  logos/logos.json                  ← name, url, local file, size info

Usage:
    # Option A — use the built-in list
    python3 fetch_logos.py

    # Option B — pipe URLs from sidebar_links.json
    python3 fetch_logos.py --from scn_quienes/sidebar_links.json

Requirements:
    pip install requests beautifulsoup4 lxml pillow

Run from:   ~/PATO/USACH/scn_repo   (images will go into img/logos/)
"""

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import json, os, re, time, argparse, sys

# ── Built-in Vínculos list ────────────────────────────────────────────────────
# Edit / extend this list freely; or supply --from file.json
DEFAULT_LINKS = [
    {"name": "Society for Neuroscience (SfN)", "url": "https://www.sfn.org"},
    {"name": "IBRO",                           "url": "https://ibro.org"},
    {"name": "FALAN",                          "url": "https://neurocienciasfalan.org"},
    {"name": "LACONEU",                        "url": "https://laconeu.org"},
    {"name": "ANID",                           "url": "https://www.anid.cl"},
    {"name": "Congreso FALAN 2026",            "url": "https://congress2026.neurocienciasfalan.org"},
    {"name": "BrainMind Institute",            "url": "https://brainmindinstitute.org"},
]

OUT      = "logos"
DELAY    = 1.2

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
}

IMG_HEADERS = {
    "User-Agent": HEADERS["User-Agent"],
    "Accept":     "image/svg+xml,image/webp,image/png,image/jpeg,image/*,*/*;q=0.8",
}

os.makedirs(OUT, exist_ok=True)

# ── Helpers ───────────────────────────────────────────────────────────────────
def slug(url):
    netloc = urlparse(url).netloc.replace("www.", "")
    return re.sub(r"[^\w]", "_", netloc)

def ext_from_url(url):
    path = urlparse(url).path
    e = os.path.splitext(path)[1].lower()
    return e if e in (".svg", ".png", ".jpg", ".jpeg", ".webp", ".ico", ".gif") else ""

def fetch_html(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=15, allow_redirects=True)
        if r.status_code == 200 and "text/html" in r.headers.get("content-type",""):
            return r.text, r.url
    except Exception as e:
        print(f"    HTML fetch failed: {e}")
    return None, None

def download_image(url, out_path):
    """Download image to out_path. Returns (success, bytes_written)."""
    try:
        r = requests.get(url, headers=IMG_HEADERS, timeout=15, allow_redirects=True)
        if r.status_code == 200 and len(r.content) > 100:
            with open(out_path, "wb") as f:
                f.write(r.content)
            return True, len(r.content)
    except Exception as e:
        print(f"    Image download failed: {e}")
    return False, 0

def score_img_url(url):
    """Higher = better. Prefer SVG > PNG > other; prefer 'logo' in name."""
    score = 0
    u = url.lower()
    if ".svg" in u:   score += 50
    if ".png" in u:   score += 30
    if "logo" in u:   score += 20
    if "favicon" in u: score -= 10
    if "icon" in u:   score += 5
    if "-32" in u or "-16" in u: score -= 15   # tiny icon versions
    return score

# ── Candidate extractors ──────────────────────────────────────────────────────
def candidates_from_html(html, base_url):
    """Return list of (score, img_url) from page HTML."""
    if not html:
        return []
    soup   = BeautifulSoup(html, "lxml")
    found  = []

    # <link rel="icon|apple-touch-icon|mask-icon|...">
    for rel in ("apple-touch-icon", "apple-touch-icon-precomposed",
                "icon", "shortcut icon", "mask-icon"):
        for tag in soup.find_all("link", rel=lambda r, _rel=rel: r and _rel in " ".join(r).lower()):
            href = tag.get("href") or tag.get("content")
            if href:
                url = urljoin(base_url, href)
                found.append((score_img_url(url) + 10, url))

    # og:image
    og = soup.find("meta", property="og:image") or \
         soup.find("meta", attrs={"name": "og:image"})
    if og:
        content = og.get("content") or og.get("href")
        if content:
            found.append((score_img_url(content) + 5, urljoin(base_url, content)))

    # Twitter card image
    tw = soup.find("meta", attrs={"name": "twitter:image"})
    if tw:
        content = tw.get("content","")
        if content:
            found.append((score_img_url(content), urljoin(base_url, content)))

    # <img> tags with class or id containing "logo"
    for img in soup.find_all("img"):
        cls = " ".join(img.get("class", [])).lower()
        id_ = (img.get("id") or "").lower()
        src = img.get("src","")
        if src and ("logo" in cls or "logo" in id_ or "logo" in src.lower()):
            url = urljoin(base_url, src)
            found.append((score_img_url(url) + 40, url))

    # Explicit /favicon.ico fallback
    fav = urljoin(base_url, "/favicon.ico")
    found.append((-5, fav))

    # Also try /favicon.png and /logo.svg
    for path in ("/favicon.png", "/logo.svg", "/logo.png", "/images/logo.svg",
                 "/assets/logo.svg", "/assets/images/logo.png"):
        found.append((score_img_url(path), urljoin(base_url, path)))

    return found

# ── Main loop ─────────────────────────────────────────────────────────────────
def process_link(entry):
    name = entry["name"]
    url  = entry["url"]
    s    = slug(url)

    print(f"\n── {name}")
    print(f"   {url}")

    html, final_url = fetch_html(url)
    base = final_url or url
    time.sleep(DELAY)

    candidates = candidates_from_html(html, base)
    # Sort best first
    candidates.sort(key=lambda x: -x[0])
    # Deduplicate
    seen = set()
    candidates = [(sc, u) for sc, u in candidates if u not in seen and not seen.add(u)]

    for score, img_url in candidates:
        e = ext_from_url(img_url)
        if not e:
            e = ".png"   # assume PNG if no extension
        out_path = os.path.join(OUT, f"{s}{e}")
        print(f"   Trying (score={score:+d})  {img_url[:80]}")
        ok, size = download_image(img_url, out_path)
        if ok:
            print(f"   ✓  Saved {size:,} bytes → {out_path}")
            return {
                "name":  name,
                "url":   url,
                "logo":  img_url,
                "file":  out_path,
                "bytes": size,
                "ext":   e,
            }
        time.sleep(0.4)

    print(f"   ✗  No logo found for {name}")
    return {"name": name, "url": url, "logo": None, "file": None, "bytes": 0, "ext": None}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="from_file",
                        help="JSON file with [{name, url}] entries (e.g. sidebar_links.json)")
    args = parser.parse_args()

    if args.from_file:
        with open(args.from_file, encoding="utf-8") as f:
            links = json.load(f)
        # Normalise: accept both {name,url} and {text,href}
        links = [
            {"name": d.get("name") or d.get("text",""), "url": d.get("url") or d.get("href","")}
            for d in links if d.get("url") or d.get("href")
        ]
    else:
        links = DEFAULT_LINKS

    print(f"\nfetch_logos.py — fetching {len(links)} logos\n{'─'*60}")

    results = []
    for entry in links:
        result = process_link(entry)
        results.append(result)

    with open(os.path.join(OUT, "logos.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n{'─'*60}")
    print(f"Results saved to  {os.path.abspath(OUT)}/logos.json")
    print("\nSUMMARY:")
    for r in results:
        status = f"✓  {r['file']}" if r["file"] else "✗  not found"
        print(f"  {r['name']:<35} {status}")

    print(f"""
── Next steps ──────────────────────────────────────────
1. Copy the logos/ folder into your scn_repo/img/logos/
   cp -r logos/ ~/PATO/USACH/scn_repo/img/logos/

2. Paste logos.json back to Claude so the sidebar HTML
   can reference the correct filenames.
────────────────────────────────────────────────────────
""")

if __name__ == "__main__":
    main()
