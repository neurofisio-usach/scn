#!/usr/bin/env python3
"""
export_wp_archive.py — rescata del sitio WordPress antiguo (socneurociencia.cl)
todo lo que compare_migration.py marcó como FALTA / parcial / sin texto, y lo
convierte en páginas estáticas con el mismo diseño del sitio nuevo.

Qué hace
  1. Lee migration_report/pages.csv (generado por compare_migration.py).
  2. Descarga todos los posts y páginas por la REST API (con caché que nunca
     guarda respuestas inválidas).
  3. Por cada post/página pendiente:
       - limpia el HTML de WordPress (scripts, botones de compartir, etc.)
       - imágenes: intenta descargar el original; si no se puede, pone el logo SCN
       - documentos (pdf, doc, ppt, xls, mp4, zip…): los descarga al repo;
         si fallan, deja el enlace original y lo anota en el log
       - enlaces internos a socneurociencia.cl: los reescribe a la página nueva
         (exportada aquí o ya migrada antes)
       - inserta el contenido en una copia de la plantilla (una noticia existente)
  4. Escribe noticias/archivo.html (índice por año) y un log por post.

Salida (rutas relativas a la raíz del repo)
  noticias/<slug>.html          posts
  archivo/<slug>.html           páginas estáticas de WordPress
  img/archivo/<año>/...         imágenes descargadas
  docs/archivo/<año>/...        documentos descargados
  noticias/archivo.html         índice del archivo
  migration_report/export_log.csv, export_manifest.json

Uso (desde la raíz del repo)
  python3 export_wp_archive.py --limit 5          # prueba con 5 posts
  python3 export_wp_archive.py                    # todo
  python3 export_wp_archive.py --images logo      # logo en todas las imágenes
  python3 export_wp_archive.py --only asamblea    # solo títulos/URLs que contengan "asamblea"

Nunca sobrescribe un archivo que no haya creado este mismo script (usa el manifest).
Re-ejecutar es seguro y rápido: API y descargas quedan en caché.
Si un archivo del sitio antiguo ya no existe (404), se busca en web.archive.org
(desactivar con --no-wayback); lo recuperado así queda en migration_report/export_wayback.json.
"""

import argparse, copy, csv, hashlib, html, json, os, re, sys, time, unicodedata
from urllib.parse import urlparse, unquote, urljoin

import requests
from bs4 import BeautifulSoup, Comment

# ───────────────────────── configuración ─────────────────────────
OLD_SITE      = "https://socneurociencia.cl"
OWN_HOSTS     = {"socneurociencia.cl", "www.socneurociencia.cl"}
PAGES_CSV     = "migration_report/pages.csv"
TEMPLATE      = "noticias/semblanza-dra-katia-gysling-caselli.html"   # una noticia ya migrada
CONTENT_SELECTORS = ["article", "main .container", "main"]           # dónde va el contenido;
                                                                     # si no hay ninguno se detecta por el <h1>
# bloques de una noticia del sitio nuevo (si existen en la plantilla se rellenan uno a uno)
SLOT_TITLE    = ".art-header h1"
SLOT_META     = ".art-header .meta"
SLOT_PILL     = ".cat-pill"
SLOT_FEAT     = "img.feat-img"
SLOT_BODY     = ".art-body"
SLOT_KEEP     = ".back-btn"          # elementos del cuerpo que se conservan (botón volver)
POST_DIR      = "noticias"
PAGE_DIR      = "archivo"
IMG_DIR       = "img/archivo"
DOC_DIR       = "docs/archivo"
LOGO          = None      # p.ej. "img/logo-scn.png"; None = detectar en la plantilla
EXPORT_STATUS = {"FALTA", "parcial", "sin texto"}
ARCH_LABEL    = {"post": "Noticias · Archivo", "page": "Archivo"}  # reemplaza el span.label de la plantilla
BACK_TO       = ("noticias/archivo.html", "Volver al archivo")       # botón volver de lo exportado
EXTRA_PAGES   = ["congreso-2018"]   # páginas de WordPress que no están en pages.csv y se exportan igual
WAYBACK_LOG   = "migration_report/export_wayback.json"   # qué archivos vinieron de archive.org
CACHE_DIR     = "migration_report/cache_export"
JUNK_DIR      = "migration_report/api_basura"   # HTML que el sitio antiguo mete antes del JSON
LOG_CSV       = "migration_report/export_log.csv"
MANIFEST      = "migration_report/export_manifest.json"
SLEEP         = 0.3       # segundos entre peticiones al sitio antiguo
TIMEOUT       = 40

DOC_EXT = {".pdf", ".doc", ".docx", ".ppt", ".pptx", ".pps", ".ppsx", ".xls", ".xlsx",
           ".odt", ".ods", ".odp", ".rtf", ".txt", ".zip", ".rar", ".mp4", ".mov",
           ".mp3", ".m4a", ".wav", ".avi", ".wmv"}
IMG_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg"}
MONTHS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
          "septiembre", "octubre", "noviembre", "diciembre"]

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 SCN-migration",
    "Accept-Language": "es-CL,es;q=0.9,en;q=0.8",
})


# ───────────────────────── utilidades ─────────────────────────
def norm_url(u):
    """Clave comparable para una URL: host sin www + ruta decodificada, sin / final."""
    p = urlparse((u or "").strip())
    host = p.netloc.lower()
    host = host[4:] if host.startswith("www.") else host
    return host + unquote(p.path).rstrip("/").lower()


def is_own(u):
    return urlparse(u).netloc.lower() in OWN_HOSTS


def ext_of(u):
    return os.path.splitext(unquote(urlparse(u).path).lower())[1]


def slugify(text, fallback):
    t = unicodedata.normalize("NFKD", unquote(text or "")).encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")
    return t[:90].rstrip("-") or fallback


def safe_filename(u):
    name = os.path.basename(unquote(urlparse(u).path)) or "archivo"
    base, ext = os.path.splitext(name)
    return slugify(base, "archivo") + ext.lower()


FILES_LOG = "migration_report/export_files.json"   # archivo local → URL original
_files = None


def dest_for(url, folder):
    """Ruta local para url dentro de folder; si el nombre ya es de otra URL, agrega un hash corto."""
    global _files
    if _files is None:
        try:
            with open(FILES_LOG, encoding="utf-8") as f:
                _files = json.load(f)
        except (OSError, ValueError):
            _files = {}
    dest = os.path.join(folder, safe_filename(url))
    owner = _files.get(dest)
    if owner not in (None, url):
        base, ext = os.path.splitext(dest)
        dest = f"{base}-{hashlib.sha1(url.encode()).hexdigest()[:6]}{ext}"
    if _files.get(dest) != url:
        _files[dest] = url
        os.makedirs(os.path.dirname(FILES_LOG) or ".", exist_ok=True)
        with open(FILES_LOG, "w", encoding="utf-8") as f:
            json.dump(_files, f, indent=0)
    return dest


def rel(target, page_dir):
    """Ruta relativa de un archivo del repo, vista desde una página en page_dir."""
    return os.path.relpath(target, start=page_dir).replace(os.sep, "/")


def fecha_larga(iso):
    y, m, d = iso[:10].split("-")
    return f"{int(d)} de {MONTHS[int(m) - 1]} de {y}"


def text_of(html_fragment):
    return " ".join(BeautifulSoup(html_fragment or "", "html.parser").get_text(" ").split())


# ───────────────────────── red + caché ─────────────────────────
def parse_json_lenient(text, url):
    """JSON aunque venga con BOM o con avisos PHP antes (p.ej. 'Warning: ... <br>[{...}]')."""
    txt = text.lstrip("\ufeff").rstrip()
    dec = json.JSONDecoder()
    for m in re.finditer(r"[\[{]", txt):
        i = m.start()
        try:
            data, end = dec.raw_decode(txt, i)
        except ValueError:
            continue
        if end != len(txt):                 # el JSON real de la API llega hasta el final
            continue
        if i == 0:
            return data
        ok = (isinstance(data, list) and all(isinstance(x, dict) and "id" in x for x in data)) \
            or (isinstance(data, dict) and "id" in data)
        if ok:
            os.makedirs(JUNK_DIR, exist_ok=True)
            jp = os.path.join(JUNK_DIR, hashlib.sha1(url.encode()).hexdigest()[:10] + ".html")
            with open(jp, "w", encoding="utf-8") as f:
                f.write(f"<!-- {url} -->\n" + txt[:i])
            print(f"   ⚠ texto basura antes del JSON ({i} caracteres) en {url}\n"
                  f"     guardado en {jp}: {txt[:80]!r}")
            return data
    raise RuntimeError(f"{url}\n  → respuesta 200 sin JSON válido ({len(txt)} caracteres): {txt[:300]!r}")


def get_json(url):
    """GET JSON con caché. Solo guarda respuestas 200 que sean JSON válido."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, hashlib.sha1(url.encode()).hexdigest() + ".json")
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                c = json.load(f)
            return c["data"], c["headers"]
        except Exception:
            os.remove(path)
    time.sleep(SLEEP)
    r = session.get(url, timeout=TIMEOUT)
    if r.status_code != 200 or "json" not in r.headers.get("Content-Type", ""):
        raise RuntimeError(f"{url}\n  → HTTP {r.status_code} {r.headers.get('Content-Type')}\n"
                           f"  {r.text[:300]!r}")
    data = parse_json_lenient(r.text, url)
    hdr = {k: r.headers[k] for k in ("X-WP-Total", "X-WP-TotalPages") if k in r.headers}
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"data": data, "headers": hdr}, f)
    return data, hdr


FAILED = {}             # URL → motivo del fallo (en esta ejecución)
DEAD_FILE = "migration_report/export_dead.json"   # URLs originales con 404/410: no se reintentan
DEAD = None
RETRY_DEAD = False
WB_PACE   = 5.0         # segundos mínimos entre peticiones a archive.org (límite: ~15/min)
WB_BACKOFF = (30, 60, 120, 240)
_wb_last = [0.0]


def _dead():
    global DEAD
    if DEAD is None:
        try:
            with open(DEAD_FILE, encoding="utf-8") as f:
                DEAD = json.load(f)
        except (OSError, ValueError):
            DEAD = {}
    return DEAD


def is_wb(u):
    return urlparse(u).netloc.lower().endswith("archive.org")


def wb_get(url, **kw):
    """GET a archive.org respetando su límite de velocidad; reintenta ante 429/5xx."""
    r = None
    for wait in (0,) + WB_BACKOFF:
        if wait:
            ra = r.headers.get("Retry-After", "") if r is not None else ""
            wait = int(ra) if ra.isdigit() and int(ra) < 600 else wait
            print(f"     ⏳ archive.org respondió {r.status_code if r is not None else 'error'}; esperando {wait} s…")
            time.sleep(wait)
        gap = WB_PACE - (time.time() - _wb_last[0])
        if gap > 0:
            time.sleep(gap)
        try:
            r = session.get(url, **kw)
        except (requests.ConnectionError, requests.Timeout):
            r = None
            _wb_last[0] = time.time()
            continue
        _wb_last[0] = time.time()
        if r.status_code not in (429, 502, 503, 504):
            return r
    if r is None:
        raise requests.ConnectionError(f"archive.org no responde: {url}")
    return r


def download(url, dest, kind):
    """Descarga url → dest. Devuelve True si quedó un archivo válido en dest."""
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        return True
    if url in FAILED:
        return False
    dead = _dead()
    if url in dead and not RETRY_DEAD:
        FAILED[url] = dead[url]
        return False
    try:
        if is_wb(url):
            r = wb_get(url, timeout=max(TIMEOUT, 120), stream=True, allow_redirects=True)
        else:
            if is_own(url):
                time.sleep(SLEEP)
            r = session.get(url, timeout=TIMEOUT, stream=True, allow_redirects=True)
        ctype = r.headers.get("Content-Type", "").lower()
        ok = r.status_code == 200 and "text/html" not in ctype
        if kind == "img":
            ok = ok and (ctype.startswith("image/") or ext_of(url) in IMG_EXT)
        if not ok:
            FAILED[url] = f"HTTP {r.status_code} {ctype or 'sin content-type'}" + \
                          (f" (redirigido a {r.url})" if r.url != url else "")
            if r.status_code in (404, 410) and not is_wb(url):
                dead[url] = FAILED[url]
                with open(DEAD_FILE, "w", encoding="utf-8") as f:
                    json.dump(dead, f, indent=0)
            return False
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        tmp = dest + ".part"
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(65536):
                f.write(chunk)
        if os.path.getsize(tmp) == 0:
            os.remove(tmp)
            FAILED[url] = "archivo vacío"
            return False
        os.replace(tmp, dest)
        return True
    except requests.RequestException as e:
        FAILED[url] = f"{type(e).__name__}: {str(e)[:120]}"
        return False


WAYBACK_TRIED = {}      # URL → URL de descarga en archive.org (o None)
WB_INDEX      = None    # índice CDX del dominio: {"url": {...}, "name": {...}}
WB_INDEX_FILE = "migration_report/wayback_index.json"
WB_ERROR      = ""      # último error al consultar archive.org (va al log)
WB_URL_ERR    = {}      # URL → error al consultar archive.org por esa URL
WB_DOWN       = False   # archive.org no responde: no se vuelve a consultar en esta ejecución


def _wb_key(u):
    p = urlparse(u if "://" in u else "http://" + u)
    host = p.netloc.lower().split(":")[0]
    host = host[4:] if host.startswith("www.") else host
    return host + unquote(p.path).lower()


def wayback_index():
    """Lista (una vez, con caché) todos los archivos no-HTML que archive.org guardó del dominio."""
    global WB_INDEX, WB_ERROR, WB_DOWN
    if WB_INDEX is not None:
        return WB_INDEX
    rows = None
    if os.path.exists(WB_INDEX_FILE):
        try:
            with open(WB_INDEX_FILE, encoding="utf-8") as f:
                rows = json.load(f)
        except (OSError, ValueError):
            rows = None
    if rows is None:
        host = urlparse(OLD_SITE).netloc
        host = host[4:] if host.startswith("www.") else host
        print(f"   archive.org: descargando índice de archivos de {host} (puede tardar 1–3 min)…")
        try:
            r = wb_get("https://web.archive.org/cdx/search/cdx", timeout=600, params=[
                ("url", host), ("matchType", "domain"), ("output", "json"),
                ("fl", "original,timestamp,mimetype"), ("filter", "statuscode:200"),
                ("filter", "!mimetype:text/html"), ("collapse", "urlkey"), ("limit", "200000")])
            if r.status_code != 200:
                raise requests.RequestException(f"HTTP {r.status_code}: {r.text[:100]!r}")
            rows = json.loads(r.text)[1:] if r.text.strip() else []
            with open(WB_INDEX_FILE, "w", encoding="utf-8") as f:
                json.dump(rows, f)
            print(f"   archive.org: {len(rows)} archivos en el índice → {WB_INDEX_FILE}")
        except (requests.RequestException, ValueError) as e:
            WB_ERROR = f"índice CDX falló: {type(e).__name__}: {str(e)[:100]}"
            WB_DOWN = True
            print(f"   ⚠ archive.org: {WB_ERROR}\n"
                  f"     se omite archive.org en esta ejecución; vuelve a correr el script más tarde")
            rows = []
    by_url, by_name = {}, {}
    for orig, ts, mime in rows:
        by_url[_wb_key(orig)] = (orig, ts)
        name = os.path.basename(unquote(urlparse(orig).path)).lower()
        if name:
            by_name.setdefault(name, []).append((orig, ts))
    WB_INDEX = {"url": by_url, "name": by_name}
    return WB_INDEX


def wayback_raw(url):
    """URL 'cruda' (id_) de una copia en archive.org, o None.
    Orden: misma URL en el índice CDX → mismo nombre de archivo (en otra ruta) → consulta CDX de esa URL (solo externos)."""
    if url in WAYBACK_TRIED:
        return WAYBACK_TRIED[url]
    idx, hit = wayback_index(), None
    if WB_DOWN:
        return None
    hit = idx["url"].get(_wb_key(url))
    if not hit:
        cands = idx["name"].get(os.path.basename(unquote(urlparse(url).path)).lower(), [])
        if cands:
            hit = max(cands, key=lambda c: c[1])          # la copia más reciente
    found = f"https://web.archive.org/web/{hit[1]}id_/{hit[0]}" if hit else None
    if not found and not is_own(url):       # lo propio ya está cubierto por el índice del dominio
        try:
            r = wb_get("https://web.archive.org/cdx/search/cdx", timeout=120, params=[
                ("url", url), ("output", "json"), ("fl", "original,timestamp,mimetype"),
                ("filter", "statuscode:200"), ("filter", "!mimetype:text/html"), ("limit", "-1")])
            if r.status_code != 200:
                raise requests.RequestException(f"HTTP {r.status_code}")
            rows = json.loads(r.text)[1:] if r.text.strip() else []
            if rows:
                orig, ts, _ = rows[-1]                          # la copia más reciente
                found = f"https://web.archive.org/web/{ts}id_/{orig}"
        except (requests.RequestException, ValueError) as e:
            WB_URL_ERR[url] = f"consulta CDX falló: {type(e).__name__}: {str(e)[:80]}"
            return None                          # error ≠ "no hay copia": no se memoriza
    WAYBACK_TRIED[url] = found
    return found


def _wb_load():
    global WB_FILES
    if WB_FILES is None:
        try:
            with open(WAYBACK_LOG, encoding="utf-8") as f:
                WB_FILES = json.load(f)
        except (OSError, ValueError):
            WB_FILES = {}
    return WB_FILES


WB_FILES = None         # archivo local → URL de archive.org de donde vino


def fetch(url, dest, kind, use_wayback=True):
    """Descarga url → dest; si falla y el archivo es del sitio propio, prueba archive.org.
    Devuelve "local", "wayback" o None."""
    wbf = _wb_load()
    if download(url, dest, kind):
        return "wayback" if dest in wbf else "local"
    if not use_wayback or (kind == "img" and not is_own(url)):
        return None
    wb = wayback_raw(url)
    if wb and download(wb, dest, kind):
        wbf[dest] = wb
        with open(WAYBACK_LOG, "w", encoding="utf-8") as f:
            json.dump(wbf, f, indent=1)
        return "wayback"
    base = FAILED.get(url, "").split(" · ")[0]
    FAILED[url] = base + (f" · archive.org ({wb}): {FAILED.get(wb, 'falló')}" if wb
                          else f" · archive.org no respondió — {WB_URL_ERR[url]}" if url in WB_URL_ERR
                          else f" · archive.org no disponible — {WB_ERROR}" if WB_DOWN
                          else " · sin copia en archive.org")
    return None


# ───────────────────────── API WordPress ─────────────────────────
# Si una variante falla (algunos plugins rompen _embed o las respuestas grandes),
# se reintenta la colección completa con la siguiente. Lo ya descargado queda en caché.
API_VARIANTS = ["per_page=100&_embed=wp:featuredmedia,wp:term",
                "per_page=100",
                "per_page=20",
                "per_page=5"]


def wp_collection(kind):
    last_err = None
    for v in API_VARIANTS:
        items, page = [], 1
        try:
            while True:
                url = f"{OLD_SITE}/wp-json/wp/v2/{kind}?{v}&page={page}"
                try:
                    data, hdr = get_json(url)
                except RuntimeError as e:
                    if page > 1 and "rest_post_invalid_page_number" in str(e):
                        break
                    raise
                if not isinstance(data, list):
                    raise RuntimeError(f"{url}\n  → se esperaba una lista: {str(data)[:200]}")
                items += data
                total = int(hdr.get("X-WP-TotalPages", 0) or 0)
                print(f"   {kind}: página {page}/{total or '?'} → {len(data)}")
                if not data or (total and page >= total):
                    break
                page += 1
            return items
        except (RuntimeError, requests.RequestException) as e:
            last_err = e
            first = str(e).splitlines()
            print(f"   ⚠ {kind} falló con '{v}' (página {page}): "
                  f"{first[1].strip() if len(first) > 1 else first[0][:150]}")
            print("     reintentando con otra variante…")
    sys.exit(f"No pude descargar '{kind}' con ninguna variante. Último error:\n{last_err}")


_TERMS = {}


def term_names(taxonomy, ids):
    """Nombres de categorías/etiquetas cuando la respuesta no trae _embedded."""
    if taxonomy not in _TERMS:
        _TERMS[taxonomy] = {}
        try:
            page = 1
            while True:
                data, hdr = get_json(f"{OLD_SITE}/wp-json/wp/v2/{taxonomy}?per_page=100&page={page}")
                _TERMS[taxonomy].update({t["id"]: html.unescape(t["name"]) for t in data})
                if page >= int(hdr.get("X-WP-TotalPages", 1) or 1):
                    break
                page += 1
        except Exception as e:
            print(f"   ⚠ no pude leer {taxonomy}: {str(e)[:120]}")
    return [_TERMS[taxonomy][i] for i in ids if i in _TERMS[taxonomy]]


def terms_of(item):
    names = []
    groups = item.get("_embedded", {}).get("wp:term")
    if groups:
        for group in groups:
            for t in group or []:
                if isinstance(t, dict) and t.get("name"):
                    names.append(html.unescape(t["name"]))
    else:
        if item.get("categories"):
            names += term_names("categories", item["categories"])
        if item.get("tags"):
            names += term_names("tags", item["tags"])
    return [n for n in names if n not in ("Sin categoría", "Uncategorized")]


def featured_of(item):
    fm = item.get("_embedded", {}).get("wp:featuredmedia") or []
    if fm and isinstance(fm[0], dict) and fm[0].get("source_url"):
        return fm[0]["source_url"]
    mid = item.get("featured_media")
    if mid and not fm:
        try:
            data, _ = get_json(f"{OLD_SITE}/wp-json/wp/v2/media/{mid}")
            return data.get("source_url")
        except Exception:
            return None
    return None


# ───────────────────────── transformación ─────────────────────────
SIZE_RE = re.compile(r"-\d+x\d+(?=\.\w+$)")


def image_candidates(img, src):
    """URLs a intentar, de mayor a menor calidad."""
    c = []
    a = img.find_parent("a")
    if a and a.get("href") and ext_of(a["href"]) in IMG_EXT:
        c.append(a["href"])
    for attr in ("data-orig-file", "data-large-file"):
        if img.get(attr):
            c.append(img[attr])
    if is_own(src):
        c.append(SIZE_RE.sub("", src))       # original sin "-300x200"
    c.append(src)
    seen, out = set(), []
    for u in c:
        u = urljoin(OLD_SITE + "/", u.split("?")[0])
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def fetch_image(cands, year, use_wayback):
    """Prueba todas las URLs candidatas; si ninguna sirve, archive.org con las dos mejores.
    Devuelve (ruta local, "local"|"wayback") o (None, None)."""
    wbf = _wb_load()
    for c in cands:
        dest = dest_for(c, os.path.join(IMG_DIR, year))
        if download(c, dest, "img"):
            return dest, ("wayback" if dest in wbf else "local")
    if use_wayback:
        for c in [c for c in cands if is_own(c)][:2]:
            dest = dest_for(c, os.path.join(IMG_DIR, year))
            if fetch(c, dest, "img"):
                return dest, "wayback"
    return None, None


# ── shortcodes de WPBakery (Visual Composer) que la API deja como texto ──
SC_QUOTES = str.maketrans({"\u201d": '"', "\u201c": '"', "\u2033": '"', "\u2032": "'", "\u2019": "'", "\u2018": "'"})
SC_RE     = re.compile(r"\[(/?)((?:vc|vc_[a-z_]+|et_pb_[a-z_]+|fusion_[a-z_]+))((?:\s[^\]]*)?)\]")
SC_ATTR   = re.compile(r'([\w-]+)\s*=\s*"([^"]*)"')
BTN_STYLE = ("display:inline-block;margin:.4rem .4rem .4rem 0;padding:.6rem 1.2rem;background:#0d9fa0;"
             "color:#fff;border-radius:4px;text-decoration:none;font-weight:600")


def vc_link(v):
    """link="url:https%3A%2F%2F...||target:%20_blank|" → URL."""
    for part in v.split("|"):
        if part.startswith("url:"):
            return unquote(part[4:])
    return unquote(v) if v.startswith("http") else ""


def shortcodes_to_html(text, counter):
    """Convierte botones, imágenes y videos de WPBakery a HTML; borra el resto de shortcodes."""
    def sub(m):
        closing, name, raw = m.group(1), m.group(2), html.unescape(m.group(3)).translate(SC_QUOTES)
        counter["n"] += 1
        if closing:
            return ""
        a = dict(SC_ATTR.findall(raw))
        if name in ("vc_btn", "vc_button", "vc_button2", "vc_cta_button", "vc_cta_button2"):
            url = vc_link(a.get("link", "") or a.get("href", ""))
            title = html.escape(a.get("title", "") or url)
            return f'<a class="btn-archivo" style="{BTN_STYLE}" href="{html.escape(url)}">{title}</a>' if url else ""
        if name == "vc_single_image" and a.get("image", "").isdigit():
            try:
                data, _ = get_json(f"{OLD_SITE}/wp-json/wp/v2/media/{a['image']}")
                if data.get("source_url"):
                    return f'<img src="{html.escape(data["source_url"])}" alt="{html.escape(a.get("title", ""))}">'
            except Exception:
                pass
            return ""
        if name == "vc_video" and a.get("link"):
            u = html.escape(a["link"])
            return f'<p><a href="{u}">{u}</a></p>'
        if name in ("vc_custom_heading",) and a.get("text"):
            return f"<h3>{html.escape(a['text'])}</h3>"
        return ""
    return SC_RE.sub(sub, text)


class Exporter:
    def __init__(self, args, logo, page_map):
        self.args, self.logo, self.page_map = args, logo, page_map   # page_map: norm_url → repo path
        self.unresolved = []

    def process(self, item, out_path):
        year = item["date"][:4]
        page_dir = os.path.dirname(out_path)
        sc = {"n": 0}
        soup = BeautifulSoup(shortcodes_to_html(item["content"]["rendered"], sc), "html.parser")
        st = {"shortcodes": 0, "img_local": 0, "img_logo": 0, "doc_local": 0, "doc_failed": 0, "links_unresolved": 0,
              "img_wayback": 0, "doc_wayback": 0}
        wb = self.args.wayback
        st["shortcodes"] = sc["n"]

        # limpieza
        for t in soup.find_all(["script", "style", "noscript", "form"]):
            t.decompose()
        for c in soup.find_all(string=lambda s: isinstance(s, Comment)):
            c.extract()
        for sel in [".sharedaddy", "#jp-post-flair", ".jp-relatedposts", ".addtoany_share_save_container",
                    ".wpcnt", ".sd-sharing-enabled", ".wp-block-jetpack-sharing-buttons"]:
            for t in soup.select(sel):
                t.decompose()

        # imagen destacada (solo si no aparece ya dentro del contenido)
        feat_rel = None
        feat = featured_of(item)
        if feat:
            stem = os.path.splitext(SIZE_RE.sub("", os.path.basename(urlparse(feat).path)))[0]
            if stem not in str(soup):
                local = src_kind = None
                if self.args.images == "download":
                    local, src_kind = fetch_image(list(dict.fromkeys([SIZE_RE.sub("", feat), feat])), year, wb)
                if local:
                    feat_rel = rel(local, page_dir)
                    st["img_local"] += 1
                    st["img_wayback"] += src_kind == "wayback"
                else:
                    feat_rel = rel(self.logo, page_dir)
                    st["img_logo"] += 1

        # imágenes
        for img in soup.find_all("img"):
            src = img.get("data-src") or img.get("data-lazy-src") or img.get("src") or ""
            if not src or src.startswith("data:"):
                img.decompose()
                continue
            local = src_kind = None
            if self.args.images == "download":
                local, src_kind = fetch_image(image_candidates(img, src), year, wb)
            for attr in list(img.attrs):
                if attr.startswith("data-") or attr in ("srcset", "sizes", "width", "height", "decoding"):
                    del img[attr]
            img["loading"] = "lazy"
            a = img.find_parent("a")
            a_is_image_link = a is not None and a.get("href") and ext_of(a["href"]) in IMG_EXT
            if local:
                img["src"] = rel(local, page_dir)
                st["img_local"] += 1
                st["img_wayback"] += src_kind == "wayback"
                if a_is_image_link:
                    a["href"] = img["src"]
            else:
                img["data-original-src"] = urljoin(OLD_SITE + "/", src)
                img["src"] = rel(self.logo, page_dir)
                img["alt"] = img.get("alt") or "Sociedad Chilena de Neurociencia"
                img["class"] = (img.get("class") or []) + ["img-reemplazo-logo"]
                st["img_logo"] += 1
                if a_is_image_link:
                    a.unwrap()

        # video/audio con <source>
        for s in soup.select("video source[src], audio source[src], video[src], audio[src]"):
            u = urljoin(OLD_SITE + "/", s["src"])
            dest = dest_for(u, os.path.join(DOC_DIR, year))
            got = fetch(u, dest, "doc", wb)
            if got:
                s["src"] = rel(dest, page_dir)
                st["doc_local"] += 1
                st["doc_wayback"] += got == "wayback"
            else:
                st["doc_failed"] += 1
                self.unresolved.append((item["link"], "video/audio", u, FAILED.get(u, "")))

        # enlaces: documentos e internos
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if href.startswith(("#", "mailto:", "tel:", "javascript:")):
                continue
            absu = urljoin(OLD_SITE + "/", href)
            e = ext_of(absu)
            if e in DOC_EXT or (is_own(absu) and "/wp-content/uploads/" in absu and e not in IMG_EXT):
                dest = dest_for(absu, os.path.join(DOC_DIR, year))
                got = fetch(absu, dest, "doc", wb)
                if got:
                    a["href"] = rel(dest, page_dir)
                    st["doc_local"] += 1
                    st["doc_wayback"] += got == "wayback"
                else:
                    a["href"] = absu
                    a["data-estado"] = "no-disponible"
                    st["doc_failed"] += 1
                    self.unresolved.append((item["link"], "documento", absu, FAILED.get(absu, "")))
                continue
            if is_own(absu) and e not in IMG_EXT:
                target = self.page_map.get(norm_url(absu))
                if target:
                    a["href"] = rel(target, page_dir)
                elif norm_url(absu) in (norm_url(OLD_SITE), ):
                    a["href"] = rel("index.html", page_dir)
                else:
                    st["links_unresolved"] += 1
                    self.unresolved.append((item["link"], "enlace interno", absu, ""))
            elif urlparse(absu).scheme in ("http", "https") and not is_own(absu):
                a["target"] = "_blank"
                a["rel"] = "noopener"

        # párrafos vacíos
        for p in soup.find_all("p"):
            if not p.get_text(strip=True) and not p.find(["img", "iframe", "video", "embed", "object"]):
                p.decompose()
        return str(soup), st, feat_rel


# ───────────────────────── plantilla ─────────────────────────
CHROME_RE = re.compile(r"^(site-?header|header|nav|navbar|nav-.*|menu|menu-.*|footer|footer-.*|"
                       r"pie|cabecera|topbar|breadcrumbs?)$", re.I)


def is_chrome(el):
    """¿Es parte del 'marco' del sitio (encabezado, menú, pie)?"""
    if el.name in ("header", "nav", "footer"):
        return True
    return any(CHROME_RE.match(tok) for tok in [el.get("id") or ""] + (el.get("class") or []) if tok)


def contains_chrome(el):
    return is_chrome(el) or any(is_chrome(d) for d in el.find_all(True))


def find_container(soup, sel):
    """Contenedor del artículo. sel = selector CSS o 'auto:<n>' (n-ésimo h1 fuera del marco)."""
    if not sel.startswith("auto"):
        return soup.select_one(sel)
    h1s = [h for h in soup.find_all("h1") if not any(is_chrome(p) for p in h.parents if p.name)]
    if not h1s:
        return None
    el = h1s[0].parent
    # subir solo si el padre agrega texto del artículo (p.ej. el h1 está en su propio bloque),
    # sin cruzar a <body> ni a un bloque que contenga encabezado/menú/pie. Así se conserva el
    # contenedor más interno (y su CSS de ancho y márgenes).
    tlen = lambda e: len(e.get_text(" ", strip=True))
    while el.parent is not None and el.parent.name not in ("body", "html", "[document]") \
            and not contains_chrome(el.parent) and tlen(el.parent) > 1.3 * tlen(el):
        el = el.parent
    return el


def describe(el):
    ident = (f'#{el["id"]}' if el.get("id") else "") + "".join(f".{c}" for c in el.get("class") or [])
    return f"<{el.name}{ident}>"


def load_template():
    if not os.path.exists(TEMPLATE):
        sys.exit(f"No encuentro la plantilla {TEMPLATE}. Ajusta TEMPLATE en la configuración.")
    with open(TEMPLATE, encoding="utf-8") as f:
        tpl = f.read()
    soup = BeautifulSoup(tpl, "html.parser")
    if soup.select_one(SLOT_TITLE) and soup.select_one(SLOT_BODY):
        print(f"Plantilla con bloques del sitio nuevo: título '{SLOT_TITLE}', "
              f"imagen '{SLOT_FEAT}', cuerpo '{SLOT_BODY}'")
        sel = "slots"
        box = soup.select_one(SLOT_BODY)
    else:
        sel = next((s for s in CONTENT_SELECTORS if soup.select_one(s)), None) or "auto"
        box = find_container(soup, sel)
    if box is None:
        sys.exit(f"No encuentro el contenido en la plantilla (ni {CONTENT_SELECTORS} ni un <h1>). "
                 f"Ajusta CONTENT_SELECTORS con el selector CSS del bloque del artículo.")
    if sel != "slots":
        print(f"Contenedor del artículo en la plantilla: {describe(box)}  "
              f"({len(box.get_text(' ', strip=True))} caracteres de texto se reemplazarán)")
    suffix = ""
    if soup.title and soup.title.string:
        m = re.search(r"\s[|—–-]\s(?!.*\s[|—–-]\s).*$", soup.title.string)   # último separador
        suffix = m.group(0) if m else ""
    logo = LOGO
    if not logo:
        cand = [i for i in soup.find_all("img")
                if "logo" in (i.get("src", "") + i.get("alt", "") + " ".join(i.get("class", []))).lower()]
        if cand:
            src = cand[0]["src"]
            logo = (os.path.normpath(src.lstrip("/")) if src.startswith("/")
                    else os.path.normpath(os.path.join(os.path.dirname(TEMPLATE), src)))
    if not logo or not os.path.exists(logo):
        sys.exit(f"No encuentro el logo SCN (detectado: {logo}). Fija LOGO en la configuración.")
    return tpl, sel, suffix, logo


def nota_archivo(date_iso, old_url):
    return (f'<p class="nota-archivo"><small>Archivo: publicado originalmente el '
            f'{fecha_larga(date_iso)} en el sitio anterior de la Sociedad '
            f'(<code>{html.escape(old_url)}</code>).</small></p>')


def fill_slots(soup, title, date_iso, terms, feat_rel, body_html):
    """Rellena los bloques de una noticia del sitio nuevo (art-header / feat-img / art-body)."""
    soup.select_one(SLOT_TITLE).string = title
    meta = soup.select_one(SLOT_META)
    if meta:
        pills = meta.select(SLOT_PILL)
        proto = copy.copy(pills[0]) if pills else None
        for p in pills:
            p.decompose()
        others = [c for c in meta.find_all(recursive=False)]
        if others:                               # el primer <span> es la fecha
            if date_iso:
                others[0].string = fecha_larga(date_iso)
            else:
                others[0].decompose()
        if proto is not None:
            for t in terms:
                pill = copy.copy(proto)
                pill.string = t
                meta.append(pill)
        if not meta.get_text(strip=True):
            meta.decompose()
    feat = soup.select_one(SLOT_FEAT)
    if feat is not None:
        if feat_rel:
            feat["src"] = feat_rel
            feat["alt"] = title
            for a in ("srcset", "sizes", "width", "height"):
                if a in feat.attrs:
                    del feat[a]
        else:
            feat.decompose()
    body = soup.select_one(SLOT_BODY)
    keep = [k.extract() for k in body.select(SLOT_KEEP)]
    body.clear()
    for k in keep:
        body.append(k)
    body.append(BeautifulSoup(body_html, "html.parser"))


def render(tpl, sel, suffix, out_path, title, description, body_html,
           date_iso=None, terms=(), feat_rel=None, old_url=None, kind=None):
    soup = BeautifulSoup(tpl, "html.parser")
    note = nota_archivo(date_iso, old_url) if old_url else ""
    if sel == "slots":
        fill_slots(soup, title, date_iso, terms, feat_rel, body_html + note)
        lab = soup.select_one(".art-header .label")
        if lab is not None:
            lab.string = ARCH_LABEL.get(kind, "Archivo")
        if old_url:                                   # lo exportado vuelve al índice del archivo
            for b in soup.select(f"{SLOT_BODY} {SLOT_KEEP}"):
                b["href"] = rel(BACK_TO[0], os.path.dirname(out_path))
                b.string = BACK_TO[1]
    else:
        meta = ""
        if date_iso:
            meta = fecha_larga(date_iso) + "".join(" · " + html.escape(t) for t in terms)
            meta = f'<p class="post-meta">{meta}</p>\n'
        fig = f'<figure class="imagen-destacada"><img src="{feat_rel}" alt=""></figure>\n' if feat_rel else ""
        box = find_container(soup, sel)
        box.clear()
        box.append(BeautifulSoup(f"<h1>{html.escape(title)}</h1>\n{meta}{fig}"
                                 f'<div class="post-content">\n{body_html}\n</div>\n{note}', "html.parser"))
    if soup.title:
        soup.title.string = title + suffix
    m = soup.find("meta", attrs={"name": "description"})
    if m:
        m["content"] = description
    for prop, val in (("og:title", title), ("og:description", description)):
        m = soup.find("meta", attrs={"property": prop})
        if m:
            m["content"] = val
    for m in soup.find_all("meta", attrs={"property": "og:image"}):
        m.decompose()
    can = soup.find("link", rel="canonical")
    if can:
        can.decompose()
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(str(soup))


# ───────────────────────── principal ─────────────────────────
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=0, help="exportar solo N elementos (prueba)")
    ap.add_argument("--only", default="", help="solo títulos/URLs que contengan este texto")
    ap.add_argument("--images", choices=["download", "logo"], default="download",
                    help="download: descarga y usa el logo solo si falla · logo: logo siempre")
    ap.add_argument("--no-wayback", dest="wayback", action="store_false",
                    help="no buscar en archive.org los archivos que ya no están en el sitio antiguo")
    ap.add_argument("--retry-dead", action="store_true",
                    help=f"reintentar también las URLs que dieron 404/410 (guardadas en {DEAD_FILE})")
    args = ap.parse_args()
    global RETRY_DEAD
    RETRY_DEAD = args.retry_dead

    tpl, sel, suffix, logo = load_template()
    print(f"Plantilla: {TEMPLATE} (contenido en '{sel}')   Logo: {logo}")

    with open(PAGES_CSV, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    todo = {norm_url(r["old_url"]): r for r in rows if r["status"] in EXPORT_STATUS and is_own(r["old_url"])}
    migrated = {norm_url(r["old_url"]): r["new_file"] for r in rows
                if r["status"] == "migrado" and r.get("new_file")}
    print(f"Pendientes según {PAGES_CSV}: {len(todo)}   ya migrados: {len(migrated)}")

    print("\n── API del sitio antiguo")
    items = [("post", i) for i in wp_collection("posts")] + [("page", i) for i in wp_collection("pages")]
    by_url = {norm_url(i["link"]): (k, i) for k, i in items}
    for slug in EXTRA_PAGES:
        k = norm_url(f"{OLD_SITE}/{slug}/")
        if k in by_url and k not in todo:
            todo[k] = {"status": "no listado", "old_url": by_url[k][1]["link"]}
            print(f"   + {by_url[k][1]['link']} (EXTRA_PAGES)")
        elif k not in by_url:
            print(f"   ⚠ EXTRA_PAGES: {slug} no está en la API")
    listed = {norm_url(r["old_url"]) for r in rows} | set(todo)
    unlisted = [(k, i) for key, (k, i) in by_url.items() if key not in listed]
    print(f"   API: {sum(k == 'post' for k, _ in items)} posts, {sum(k == 'page' for k, _ in items)} páginas"
          f" · {len(unlisted)} no aparecen en {PAGES_CSV} (no se exportan; ver pendientes)")

    manifest = {}
    if os.path.exists(MANIFEST):
        with open(MANIFEST, encoding="utf-8") as f:
            manifest = json.load(f)
    ours = {v["new_file"] for v in manifest.values()}

    # 1) decidir nombres de archivo para todo lo pendiente (para poder enlazar entre ellos)
    plan, used = [], set(ours)
    for key, row in todo.items():
        if key not in by_url:
            print(f"   ⚠ no está en la API: {row['old_url']}")
            continue
        kind, it = by_url[key]
        if key in manifest:
            out = manifest[key]["new_file"]
        else:
            base = slugify(it.get("slug"), "")
            if not base or base.isdigit():      # WordPress a veces deja el slug como un número
                base = slugify(text_of(it["title"]["rendered"]), f"post-{it['id']}")
            d = POST_DIR if kind == "post" else PAGE_DIR
            out = f"{d}/{base}.html"
            if (os.path.exists(out) and out not in ours) or out in used:
                out = f"{d}/{base}-{it['date'][:4]}-{it['id']}.html"
        used.add(out)
        plan.append((key, kind, it, out))
    plan.sort(key=lambda x: x[2]["date"])

    page_map = dict(migrated)
    page_map.update({k: out for k, _, _, out in plan})
    page_map.update({norm_url(f"{OLD_SITE}/{p}"): f for p, f in
                     (("noticias", "noticias.html"), ("category/noticias", "noticias.html"))})

    if args.only:
        q = args.only.lower()
        plan = [p for p in plan if q in p[0] or q in text_of(p[2]["title"]["rendered"]).lower()]
    if args.limit:
        plan = plan[:args.limit]

    print(f"\n── Exportando {len(plan)} elementos (imágenes: {args.images})")
    ex = Exporter(args, logo, page_map)
    log = []
    for n, (key, kind, it, out) in enumerate(plan, 1):
        body, st, feat_rel = ex.process(it, out)
        title = html.unescape(text_of(it["title"]["rendered"])) or f"Publicación {it['id']}"
        desc = (text_of(it.get("excerpt", {}).get("rendered", "")) or text_of(body))[:160]
        render(tpl, sel, suffix, out, title, desc, body, date_iso=it["date"][:10],
               terms=terms_of(it), feat_rel=feat_rel, old_url=it["link"], kind=kind)
        manifest[key] = {"old_url": it["link"], "new_file": out, "title": title,
                         "date": it["date"][:10], "kind": kind}
        log.append({"date": it["date"][:10], "kind": kind, "title": title, "old_url": it["link"],
                    "new_file": out, "status_antes": todo[key]["status"], **st})
        print(f"   [{n}/{len(plan)}] {it['date'][:10]} {out}  "
              f"img {st['img_local']}+{st['img_logo']}logo  doc {st['doc_local']}/{st['doc_local']+st['doc_failed']}"
              + (f"  (archive.org: {st['img_wayback']} img, {st['doc_wayback']} doc)"
                 if st['img_wayback'] or st['doc_wayback'] else ""))
        with open(MANIFEST, "w", encoding="utf-8") as f:      # guardar a medida que avanza
            json.dump(manifest, f, ensure_ascii=False, indent=1)

    # 2) índice del archivo (todos los exportados, no solo los de esta ejecución)
    posts = sorted((v for v in manifest.values() if v["kind"] == "post"), key=lambda v: v["date"], reverse=True)
    pages = sorted((v for v in manifest.values() if v["kind"] == "page"), key=lambda v: v["title"].lower())
    parts = ['<p>Publicaciones del sitio anterior de la Sociedad Chilena de Neurociencia.</p>']
    year = None
    for v in posts:
        if v["date"][:4] != year:
            if year:
                parts.append("</ul>")
            year = v["date"][:4]
            parts.append(f'<h2 id="y{year}">{year}</h2>\n<ul class="lista-archivo">')
        parts.append(f'<li><time datetime="{v["date"]}">{fecha_larga(v["date"])}</time> — '
                     f'<a href="{rel(v["new_file"], POST_DIR)}">{html.escape(v["title"])}</a></li>')
    if year:
        parts.append("</ul>")
    if pages:
        parts.append('<h2>Otras páginas del sitio anterior</h2>\n<ul class="lista-archivo">')
        parts += [f'<li><a href="{rel(v["new_file"], POST_DIR)}">{html.escape(v["title"])}</a></li>' for v in pages]
        parts.append("</ul>")
    render(tpl, sel, suffix, f"{POST_DIR}/archivo.html", "Archivo de noticias",
           "Archivo de publicaciones de la Sociedad Chilena de Neurociencia.", "\n".join(parts))

    # 3) logs
    if log:
        with open(LOG_CSV, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(log[0]))
            w.writeheader()
            w.writerows(log)
    with open(LOG_CSV.replace(".csv", "_pendientes.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["pagina_antigua", "tipo", "url", "motivo"])
        w.writerows(ex.unresolved)
        w.writerows((i["link"], f"{k} no está en pages.csv", "", text_of(i["title"]["rendered"])[:100])
                    for k, i in unlisted)

    tot = {k: sum(r[k] for r in log) for k in ("img_local", "img_logo", "doc_local", "doc_failed", "links_unresolved",
                                               "img_wayback", "doc_wayback")}
    print(f"\n✔ {len(log)} páginas escritas · índice: {POST_DIR}/archivo.html")
    print(f"  imágenes: {tot['img_local']} descargadas ({tot['img_wayback']} de archive.org), "
          f"{tot['img_logo']} reemplazadas por el logo")
    print(f"  documentos: {tot['doc_local']} descargados ({tot['doc_wayback']} de archive.org), "
          f"{tot['doc_failed']} no disponibles (enlace original conservado)")
    print(f"  enlaces internos sin destino: {tot['links_unresolved']}")
    print(f"  detalle: {LOG_CSV}  ·  pendientes: {LOG_CSV.replace('.csv', '_pendientes.csv')}")


if __name__ == "__main__":
    main()
