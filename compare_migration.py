#!/usr/bin/env python3
"""
compare_migration.py — ¿Cuánta información perdemos al migrar?
================================================================
Compares the live WordPress site (socneurociencia.cl) with the new static
site in this repo, and reports what is migrated, partial, or missing.

Old site inventory (most complete source first):
  1. WordPress REST API  /wp-json/wp/v2/{posts,pages,media}  → every post,
     page and uploaded file, even ones no menu links to
  2. Fallback: crawl from the homepage (if the API is disabled)

New site inventory: the local HTML files of this repo (no network needed).

Run from the repo root:
    pip install requests beautifulsoup4 lxml
    python3 compare_migration.py

Outputs (folder migration_report/, NOT meant to be committed):
    report.md        ← summary to read / paste back to Claude
    pages.csv        ← every old post/page: coverage %, best new match
    documents.csv    ← every PDF/DOC referenced: found locally or not
    images.csv       ← every content image: found locally or not
    redirects.csv    ← old URL → new file (for redirect stubs after DNS switch)
Fetched HTML/JSON is cached in migration_report/cache/ so re-runs are fast.
"""

import csv, glob, hashlib, json, os, re, sys, time, unicodedata
from urllib.parse import urljoin, urlparse, unquote

import requests
from bs4 import BeautifulSoup

# ── Config ────────────────────────────────────────────────────────────────────
OLD_SITE   = "https://socneurociencia.cl"
REPO_ROOT  = "."
OUT        = "migration_report"
DELAY      = 0.6            # seconds between live requests
MAX_CRAWL  = 400            # fallback crawler page limit

# Known, accepted losses → reported separately, not counted as "missing"
KNOWN_LOSSES = [
    r"/socios/?$",                 # Lista de socios (decided not to migrate)
]
# Paths that are WordPress machinery, not content
SKIP_OLD = [
    r"/wp-admin", r"/wp-login", r"/feed", r"/tag/", r"/author/", r"/page/\d+",
    r"/category/", r"\?", r"/wp-json", r"/xmlrpc",
]
COVERAGE_OK      = 0.80     # ≥ 80 % of sentences found → migrated
COVERAGE_PARTIAL = 0.20     # 20–80 % → partial ; < 20 % → missing
MIN_CHUNK        = 40       # ignore sentences shorter than this (menus, dates)

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"),
    "Accept-Language": "es-CL,es;q=0.9,en;q=0.8",
}
DOC_EXT = {".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".zip", ".mp4"}
IMG_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"}

os.makedirs(os.path.join(OUT, "cache"), exist_ok=True)
session = requests.Session()
session.headers.update(HEADERS)

# ── Helpers ───────────────────────────────────────────────────────────────────
def norm_text(t):
    t = unicodedata.normalize("NFKC", t or "").lower()
    t = re.sub(r"[“”«»\"'’`´]", "", t)
    return re.sub(r"\s+", " ", t).strip()

def chunks(text):
    """Split text into sentence-sized pieces worth checking."""
    parts = re.split(r"(?<=[.!?;:])\s+|\n+| \d\)\s", text)
    out = []
    for p in parts:
        p = norm_text(p)
        p = re.sub(r"^[\W\d]+|[\W]+$", "", p)
        if len(p) >= MIN_CHUNK:
            out.append(p[:160])          # long sentences: first 160 chars is enough
    return out

def file_key(name):
    """Loose key for matching an uploaded file to a local copy."""
    name = unquote(os.path.basename(urlparse(name).path)).lower()
    stem, ext = os.path.splitext(name)
    stem = re.sub(r"-\d+x\d+$", "", stem)            # WP size suffix -300x200
    stem = re.sub(r"-scaled$|-e\d{10,}$", "", stem)  # WP scaled / edited suffix
    stem = unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", stem) + ext

def skip_old(url):
    return any(re.search(p, url) for p in SKIP_OLD)

def known_loss(url):
    return any(re.search(p, urlparse(url).path) for p in KNOWN_LOSSES)

def cached_get(url, as_json=False):
    key = hashlib.md5(url.encode()).hexdigest()
    path = os.path.join(OUT, "cache", key + (".json" if as_json else ".html"))
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            data = f.read()
        return (json.loads(data), {}) if as_json else (data, {})
    time.sleep(DELAY)
    try:
        r = session.get(url, timeout=25)
    except Exception as e:
        print(f"   [FAIL] {url}: {e}")
        return None, {}
    if r.status_code != 200:
        print(f"   [{r.status_code}] {url}")
        return None, {}
    if as_json:
        try:
            data = r.json()
        except ValueError:
            ctype = r.headers.get("content-type", "?")
            print(f"   [no-JSON, {ctype}, {len(r.text)} bytes] {url}")
            return None, {}
        with open(path, "w", encoding="utf-8") as f:
            f.write(r.text)
        return data, r.headers
    with open(path, "w", encoding="utf-8") as f:
        f.write(r.text)
    return r.text, r.headers

def content_from_html(html, base):
    """Return (text, image urls, doc urls, external links) for a content block."""
    soup = BeautifulSoup(html, "lxml")
    for t in soup(["script", "style", "noscript"]):
        t.decompose()
    imgs, docs, ext = set(), set(), set()
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or ""
        if src:
            imgs.add(urljoin(base, src))
    for a in soup.find_all("a", href=True):
        u = urljoin(base, a["href"])
        e = os.path.splitext(urlparse(u).path)[1].lower()
        if e in DOC_EXT:
            docs.add(u)
        elif e in IMG_EXT and "/wp-content/uploads/" in u:
            imgs.add(u)
        elif u.startswith("http") and "socneurociencia" not in urlparse(u).netloc:
            ext.add(u.split("#")[0])
    for s in soup.find_all(["source", "video"]):
        if s.get("src"):
            docs.add(urljoin(base, s["src"]))
    return soup.get_text(" "), imgs, docs, ext

# ── 1. Old site inventory ─────────────────────────────────────────────────────
def wp_api_collection(kind):
    """Fetch every item of a REST collection; retries with smaller batches
    if the server refuses big ones. Returns (items, ok)."""
    for per_page in (100, 20):
        items, page, ok = [], 1, True
        while True:
            url = f"{OLD_SITE}/wp-json/wp/v2/{kind}?per_page={per_page}&page={page}"
            data, hdr = cached_get(url, as_json=True)
            if data is None:
                ok = page > 1          # failing after page 1 = simply no more pages
                break
            if not isinstance(data, list):
                ok = False
                break
            items += data
            total = int(hdr.get("X-WP-TotalPages", 0) or 0)
            print(f"   {kind}: page {page} → {len(data)} items")
            if len(data) < per_page or (total and page >= total):
                break
            page += 1
        if ok:
            return items, True
        print(f"   {kind}: API rechazó per_page={per_page}")
    return [], False

def old_from_api():
    posts, posts_ok = wp_api_collection("posts")
    pages, pages_ok = wp_api_collection("pages")
    if not posts_ok and not pages_ok:
        return None, []
    records = []
    if not pages_ok:
        print("   pages: API bloqueada → crawling solo páginas (no posts)")
        records += old_from_crawl(pages_only=True)
    for kind, lst in (("post", posts), ("page", pages)):
        for it in lst:
            link = it.get("link", "")
            html = (it.get("content") or {}).get("rendered", "")
            title = BeautifulSoup((it.get("title") or {}).get("rendered", ""), "lxml").get_text()
            text, imgs, docs, ext = content_from_html(html, link)
            feat = it.get("jetpack_featured_media_url") or ""
            if feat:
                imgs.add(feat)
            records.append({
                "url": link, "kind": kind, "title": title.strip(),
                "date": (it.get("date") or "")[:10], "slug": it.get("slug", ""),
                "status": it.get("status", ""), "text": text,
                "imgs": imgs, "docs": docs, "ext": ext,
            })
    media, _ = wp_api_collection("media")
    return records, media

def old_from_crawl(pages_only=False):
    """Fallback when the REST API is disabled. pages_only: skip /YYYY/MM/DD/ posts."""
    seen, queue, records = set(), [OLD_SITE + "/"], []
    while queue and len(seen) < MAX_CRAWL:
        url = queue.pop(0).split("#")[0]
        if url in seen or skip_old(url):
            continue
        seen.add(url)
        html, _ = cached_get(url)
        if not html:
            continue
        soup = BeautifulSoup(html, "lxml")
        main = (soup.select_one(".entry__article") or soup.select_one(".entry-content")
                or soup.find("article") or soup.find("main") or soup.body)
        text, imgs, docs, ext = content_from_html(str(main), url)
        title = soup.title.get_text(strip=True) if soup.title else ""
        path = urlparse(url).path
        kind = "post" if re.match(r"^/\d{4}/\d{2}/\d{2}/", path) else "page"
        slug = path.rstrip("/").rsplit("/", 1)[-1]
        records.append({"url": url, "kind": kind, "title": title, "date": "",
                        "slug": slug, "status": "crawled", "text": text,
                        "imgs": imgs, "docs": docs, "ext": ext})
        print(f"   crawled {len(seen):3d}  {url}")
        for a in soup.find_all("a", href=True):
            u = urljoin(url, a["href"]).split("#")[0]
            if urlparse(u).netloc.replace("www.", "") == "socneurociencia.cl":
                e = os.path.splitext(urlparse(u).path)[1].lower()
                is_post = re.match(r"^/\d{4}/\d{2}/", urlparse(u).path)
                if e not in DOC_EXT | IMG_EXT and u not in seen and not (pages_only and is_post):
                    queue.append(u)
    return records

# ── 2. New site inventory (local files) ───────────────────────────────────────
def new_inventory():
    html_files = [f for f in glob.glob(os.path.join(REPO_ROOT, "**/*.html"), recursive=True)
                  if "/migration_report/" not in f and "/scn_quienes/" not in f]
    pages, corpus = {}, []
    for f in html_files:
        with open(f, encoding="utf-8", errors="ignore") as fh:
            soup = BeautifulSoup(fh.read(), "lxml")
        for t in soup(["script", "style", "noscript", "nav", "footer"]):
            t.decompose()
        txt = norm_text(soup.get_text(" "))
        rel = os.path.relpath(f, REPO_ROOT)
        pages[rel] = txt
        corpus.append(txt)
    local_files = {}
    for p in glob.glob(os.path.join(REPO_ROOT, "**/*"), recursive=True):
        if os.path.isfile(p) and "/.git/" not in p and "/migration_report/" not in p:
            local_files.setdefault(file_key(p), os.path.relpath(p, REPO_ROOT))
    hrefs = set()
    for f in html_files:
        with open(f, encoding="utf-8", errors="ignore") as fh:
            for m in re.finditer(r'href="(https?://[^"#]+)', fh.read()):
                hrefs.add(m.group(1).rstrip("/"))
    return pages, " \n ".join(corpus), local_files, hrefs

# ── 3. Compare ────────────────────────────────────────────────────────────────
def best_match(rec, new_pages):
    slug = rec["slug"]
    for cand in (f"noticias/{slug}.html", f"{slug}.html"):
        if cand in new_pages:
            return cand
    m = re.search(r"congreso-?(\d{4})", slug) or re.search(r"(\d{4})", slug)
    if m and f"congresos/{m.group(1)}.html" in new_pages and "congreso" in slug:
        return f"congresos/{m.group(1)}.html"
    cks = chunks(rec["text"])[:25]
    if not cks:
        return ""
    scores = {p: sum(c in t for c in cks) for p, t in new_pages.items()}
    p, s = max(scores.items(), key=lambda x: x[1])
    return p if s else ""

def main():
    print(f"\n── 1. Inventario sitio antiguo ({OLD_SITE})")
    records, media = old_from_api()
    source = "REST API"
    if records is None:
        print("   REST API no disponible → crawling")
        records, media, source = old_from_crawl(), [], "crawler"
    records = [r for r in records if not skip_old(r["url"])]
    print(f"   {len(records)} posts/páginas, {len(media)} archivos en biblioteca de medios")

    print("\n── 2. Inventario sitio nuevo (repo local)")
    new_pages, corpus, local_files, new_hrefs = new_inventory()
    print(f"   {len(new_pages)} páginas HTML, {len(local_files)} archivos locales")

    print("\n── 3. Comparando…")
    page_rows, all_imgs, all_docs, all_ext = [], {}, {}, {}
    for r in records:
        cks = chunks(r["text"])
        found = sum(c in corpus for c in cks)
        cov = found / len(cks) if cks else None
        if known_loss(r["url"]):
            status = "pérdida aceptada"
        elif cov is None:
            status = "sin texto"
        elif cov >= COVERAGE_OK:
            status = "migrado"
        elif cov >= COVERAGE_PARTIAL:
            status = "parcial"
        else:
            status = "FALTA"
        match = best_match(r, new_pages)
        page_rows.append({
            "status": status, "coverage": "" if cov is None else f"{cov:.0%}",
            "kind": r["kind"], "date": r["date"], "title": r["title"][:90],
            "old_url": r["url"], "new_file": match,
            "sentences": len(cks), "found": found,
            "missing_example": next((c for c in cks if c not in corpus), "")[:120],
        })
        for i in r["imgs"]:
            all_imgs.setdefault(i, set()).add(r["url"])
        for d in r["docs"]:
            all_docs.setdefault(d, set()).add(r["url"])
        for e in r["ext"]:
            all_ext.setdefault(e.rstrip("/"), set()).add(r["url"])

    def asset_rows(d, only_uploads):
        rows = []
        for u, srcs in sorted(d.items()):
            if only_uploads and "/wp-content/uploads/" not in u:
                continue
            k = file_key(u)
            local = local_files.get(k, "")
            if not local and only_uploads:                       # try without -1/-2 dup suffix
                k2 = re.sub(r"\d(\.\w+)$", r"\1", k)
                local = next((v for kk, v in local_files.items()
                              if re.sub(r"\d(\.\w+)$", r"\1", kk) == k2), "")
            accepted = all(known_loss(s) for s in srcs)
            rows.append({"status": "ok" if local else ("pérdida aceptada" if accepted else "FALTA"),
                         "file": unquote(os.path.basename(urlparse(u).path)),
                         "local": local, "url": u, "used_on": " ; ".join(sorted(srcs))[:300]})
        return rows

    img_rows = asset_rows(all_imgs, only_uploads=True)
    doc_rows = asset_rows(all_docs, only_uploads=False)
    ext_missing = sorted(e for e in all_ext if e not in new_hrefs
                         and not e.startswith(("https://www.facebook", "https://twitter")))

    # Media library: anything uploaded but never referenced in content
    lib_docs = [m for m in media if os.path.splitext(urlparse(m.get("source_url", "")).path)[1].lower() in DOC_EXT]
    lib_docs_missing = [m["source_url"] for m in lib_docs if file_key(m["source_url"]) not in local_files]

    # ── Write CSVs ────────────────────────────────────────────────────────────
    def write(name, rows):
        if not rows:
            return
        with open(os.path.join(OUT, name), "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
    order = {"FALTA": 0, "parcial": 1, "sin texto": 2, "pérdida aceptada": 3, "migrado": 4, "ok": 4}
    page_rows.sort(key=lambda r: (order[r["status"]], r["date"]), reverse=False)
    write("pages.csv", page_rows)
    write("images.csv", sorted(img_rows, key=lambda r: order[r["status"]]))
    write("documents.csv", sorted(doc_rows, key=lambda r: order[r["status"]]))
    write("redirects.csv", [{"old_path": urlparse(r["old_url"]).path, "new_file": r["new_file"]}
                            for r in page_rows if r["new_file"]])

    # ── Report ────────────────────────────────────────────────────────────────
    def count(rows, s):
        return sum(r["status"] == s for r in rows)
    tot_s = sum(r["sentences"] for r in page_rows if r["status"] != "pérdida aceptada")
    tot_f = sum(r["found"] for r in page_rows if r["status"] != "pérdida aceptada")
    L = [
        "# Informe de migración — socneurociencia.cl → sitio estático",
        f"Fecha: {time.strftime('%Y-%m-%d %H:%M')}   ·   Fuente sitio antiguo: {source}", "",
        "## Resumen", "",
        f"- **Texto**: {tot_f}/{tot_s} oraciones del sitio antiguo están en el nuevo "
        f"(**{(tot_f / tot_s if tot_s else 0):.0%}**)",
        f"- **Posts/páginas** ({len(page_rows)}): {count(page_rows,'migrado')} migrados · "
        f"{count(page_rows,'parcial')} parciales · **{count(page_rows,'FALTA')} faltan** · "
        f"{count(page_rows,'sin texto')} sin texto · {count(page_rows,'pérdida aceptada')} pérdida aceptada",
        f"- **Imágenes de contenido** ({len(img_rows)}): {count(img_rows,'ok')} locales · "
        f"**{count(img_rows,'FALTA')} faltan** · {count(img_rows,'pérdida aceptada')} aceptadas",
        f"- **Documentos** ({len(doc_rows)}): {count(doc_rows,'ok')} locales · "
        f"**{count(doc_rows,'FALTA')} faltan**",
        f"- **Enlaces externos** del sitio antiguo ausentes en el nuevo: {len(ext_missing)}",
    ]
    if media:
        L.append(f"- **Biblioteca de medios**: {len(media)} archivos subidos; "
                 f"{len(lib_docs)} documentos, {len(lib_docs_missing)} no están en el repo "
                 f"(pueden no estar enlazados en ninguna página)")
    L += ["", "## Posts/páginas que FALTAN o están parciales", "",
          "| Estado | Cob. | Fecha | Título | URL antigua |", "|---|---|---|---|---|"]
    for r in page_rows:
        if r["status"] in ("FALTA", "parcial"):
            L.append(f"| {r['status']} | {r['coverage']} | {r['date']} | {r['title']} | {r['old_url']} |")
    L += ["", "## Documentos que faltan", ""]
    L += [f"- {r['file']}  ←  {r['used_on'][:120]}" for r in doc_rows if r["status"] == "FALTA"] or ["- (ninguno)"]
    L += ["", "## Imágenes que faltan (primeras 40)", ""]
    miss_img = [r for r in img_rows if r["status"] == "FALTA"]
    L += [f"- {r['file']}  ←  {r['used_on'][:100]}" for r in miss_img[:40]] or ["- (ninguna)"]
    if len(miss_img) > 40:
        L.append(f"- … +{len(miss_img) - 40} más (ver images.csv)")
    L += ["", "## Enlaces externos ausentes (primeros 40)", ""]
    L += [f"- {e}" for e in ext_missing[:40]] or ["- (ninguno)"]
    L += ["", "## Pérdidas aceptadas", ""]
    L += [f"- {r['old_url']}" for r in page_rows if r["status"] == "pérdida aceptada"] or ["- (ninguna)"]
    if lib_docs_missing:
        L += ["", "## Documentos en la biblioteca de medios sin copia local (primeros 30)", ""]
        L += [f"- {u}" for u in lib_docs_missing[:30]]

    report = "\n".join(L)
    with open(os.path.join(OUT, "report.md"), "w", encoding="utf-8") as f:
        f.write(report)
    print("\n" + report[:3000])
    print(f"\n✓ Archivos en {os.path.abspath(OUT)}/  →  envía report.md (y pages.csv si quieres detalle)")

if __name__ == "__main__":
    main()
