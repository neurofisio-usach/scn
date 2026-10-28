#!/usr/bin/env python3
"""Investigación forense de los documentos perdidos del sitio SCN.

Para cada archivo de migration_report/documentos_perdidos.txt responde:
  ¿existió?   – el enlace está en la página original (no es un artefacto),
                el archivo está en la biblioteca de medios de WordPress,
                o algún archivo web lo capturó.
  ¿dónde está? – servidor actual (otra ruta/nombre, listado de carpeta),
                Wayback Machine, Common Crawl, otros archivos web (Memento).
y descarga lo que encuentre, verificando que sea un PDF/DOC/DOCX/PPTX real.

Solo usa fuentes públicas y de lectura (no prueba contraseñas ni explota nada).

Uso (raíz del repo):
  python3 forense_documentos.py                 # todo
  python3 forense_documentos.py --limit 5       # prueba rápida
  python3 forense_documentos.py --skip-cc --skip-memento
Salida en migration_report/forense/:
  forense.csv, resumen.txt, busquedas_manuales.txt, recuperados/…
"""
import argparse
import csv
import gzip
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

import requests

LIST = Path("migration_report/documentos_perdidos.txt")
OUT = Path("migration_report/forense")
REC = OUT / "recuperados"
CACHE = OUT / "cache.json"
WP = "https://socneurociencia.cl"
OWN = ("socneurociencia.cl",)
UA = {"User-Agent": "Mozilla/5.0 (SCN archive recovery; contacto sociedadchilenaneurociencia@gmail.com)"}

MAGIC = {
    ".pdf": [b"%PDF"],
    ".doc": [b"\xd0\xcf\x11\xe0"],
    ".docx": [b"PK\x03\x04"], ".pptx": [b"PK\x03\x04"], ".xlsx": [b"PK\x03\x04"],
    ".ppt": [b"\xd0\xcf\x11\xe0"], ".xls": [b"\xd0\xcf\x11\xe0"],
}

S = requests.Session()
S.headers.update(UA)


# ── utilidades ─────────────────────────────────────────────
def load_cache():
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_cache(c):
    CACHE.write_text(json.dumps(c, ensure_ascii=False), encoding="utf-8")


def get(url, *, tries=4, timeout=40, stream=False, **kw):
    """GET con reintentos y espera ante 429/5xx. Devuelve Response o None."""
    wait = 3
    for _ in range(tries):
        try:
            r = S.get(url, timeout=timeout, stream=stream, **kw)
        except requests.RequestException:
            time.sleep(wait); wait *= 2
            continue
        if r.status_code in (429, 502, 503, 504):
            time.sleep(int(r.headers.get("Retry-After", wait)) if
                       str(r.headers.get("Retry-After", "")).isdigit() else wait)
            wait *= 2
            continue
        return r
    return None


def norm(u):
    """Clave comparable: host sin www, ruta decodificada en minúsculas, sin query."""
    p = urlparse(u.strip())
    host = p.netloc.lower().split(":")[0]
    host = host[4:] if host.startswith("www.") else host
    return host + unquote(p.path).lower().rstrip("/")


def base(u):
    return unquote(urlparse(u).path.rsplit("/", 1)[-1]).lower()


def stem_variants(name):
    """nombre.pdf → nombre base sin sufijos -1, -2 de WordPress."""
    st, _, ext = name.rpartition(".")
    st = re.sub(r"-\d+$", "", st)
    return st, ext


def is_real(data, ext):
    if not data or len(data) < 200:
        return False
    head = data[:2048].lstrip()
    if head[:15].lower().startswith((b"<!doctype", b"<html", b"<?xml")) and ext != ".xml":
        return False
    sigs = MAGIC.get(ext)
    return True if sigs is None else any(data.startswith(s) for s in sigs)


def ext_of(u):
    e = Path(unquote(urlparse(u).path)).suffix.lower()
    return e if e else ".bin"


def save_file(u, data, source):
    p = urlparse(u)
    dest = REC / (p.netloc.lower().removeprefix("www.")) / unquote(p.path).lstrip("/")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return dest.as_posix()


# ── 1. lista ───────────────────────────────────────────────
def parse_list():
    items, page, title, new = [], "", "", ""
    for ln in LIST.read_text(encoding="utf-8").splitlines():
        if ln.startswith("■ "):
            title, page, new = ln[2:].strip(), "", ""
        elif ln.strip().startswith("original:"):
            page = ln.split("original:", 1)[1].strip()
        elif ln.strip().startswith("sitio nuevo:"):
            new = ln.split("sitio nuevo:", 1)[1].strip()
        elif ln.startswith("  - "):
            items.append({"url": ln[4:].strip(), "pagina": page, "titulo": title, "nuevo": new})
    return items


# ── 2. servidor actual ─────────────────────────────────────
def wp_media_census(cache):
    """Cuántos adjuntos tiene la biblioteca de medios, por año (prueba de la reconstrucción 2018)."""
    if "census" in cache:
        return cache["census"]
    res = {}
    for y in range(2012, 2027):
        r = get(f"{WP}/wp-json/wp/v2/media?per_page=1&after={y}-01-01T00:00:00"
                f"&before={y + 1}-01-01T00:00:00")
        res[y] = int(r.headers.get("X-WP-Total", -1)) if r is not None and r.ok else None
    cache["census"] = res
    return res


def wp_media_search(stem, cache):
    key = "media:" + stem
    if key not in cache:
        urls = []
        r = get(f"{WP}/wp-json/wp/v2/media?per_page=100&search={quote(stem)}")
        if r is not None and r.ok:
            try:
                urls = [m.get("source_url", "") for m in r.json() if isinstance(m, dict)]
            except ValueError:
                pass
        cache[key] = urls
    return cache[key]


def dir_listing(folder_url, cache):
    key = "dir:" + folder_url
    if key not in cache:
        r = get(folder_url)
        names = []
        if r is not None and r.ok and "Index of" in r.text[:3000]:
            names = [unquote(h).lower() for h in re.findall(r'href="([^"?/][^"]*)"', r.text)]
        cache[key] = {"status": None if r is None else r.status_code, "names": names}
    return cache[key]


def live_check(u):
    """Prueba el URL y sus variantes http/https y www/sin-www."""
    p = urlparse(u)
    host = p.netloc.removeprefix("www.")
    tried, last = [], None
    for sch in ("https", "http"):
        for h in (host, "www." + host):
            v = f"{sch}://{h}{p.path}" + (f"?{p.query}" if p.query else "")
            if v in tried:
                continue
            tried.append(v)
            r = get(v, tries=2, timeout=25)
            if r is None:
                continue
            if r.ok and is_real(r.content, ext_of(u)):
                return v, r.status_code, r.content
            last = r.status_code
    return None, last, None


def page_has_link(page_url, fname, cache):
    key = "page:" + page_url
    if key not in cache:
        r = get(page_url, tries=2)
        cache[key] = unquote(r.text).lower() if (r is not None and r.ok) else None
    html = cache[key]
    if html is None:
        return "página no disponible"
    return "sí" if fname in html else "no"


# ── 3. Wayback Machine ─────────────────────────────────────
def wayback_prefix(host, cache):
    """Todas las capturas no-imagen bajo /wp-content/uploads/ del dominio."""
    key = "wb:" + host
    if key in cache:
        return cache[key]
    url = ("https://web.archive.org/cdx/search/cdx?url=" + host + "/wp-content/uploads/"
           "&matchType=prefix&output=json&fl=original,timestamp,statuscode,mimetype"
           "&filter=!mimetype:image/.*&limit=200000")
    r = get(url, timeout=180)
    rows = []
    if r is not None and r.ok and r.text.strip():
        try:
            rows = r.json()[1:]
        except ValueError:
            pass
    cache[key] = rows
    print(f"  Wayback {host}/wp-content/uploads/: {len(rows)} capturas")
    return rows


def wayback_url(u, cache):
    key = "wbu:" + u
    if key not in cache:
        url = ("https://web.archive.org/cdx/search/cdx?url=" + quote(u.split("?")[0], safe=":/%")
               + "&output=json&fl=original,timestamp,statuscode,mimetype")
        r = get(url, timeout=60)
        rows = []
        if r is not None and r.ok and r.text.strip():
            try:
                rows = r.json()[1:]
            except ValueError:
                pass
        cache[key] = rows
        time.sleep(1)
    return cache[key]


def wayback_fetch(rows, ext):
    """Prueba capturas (200 primero, más recientes primero) y devuelve (bytes, url_captura)."""
    def score(rw):
        st = rw[2]
        return (0 if st == "200" else 1 if st.startswith("3") else 2, -int(rw[1]))
    for orig, ts, st, _mime in sorted(rows, key=score)[:6]:
        if st not in ("200", "301", "302", "-"):
            continue
        cap = f"https://web.archive.org/web/{ts}id_/{orig}"
        r = get(cap, timeout=90)
        time.sleep(1)
        if r is not None and r.ok and is_real(r.content, ext):
            return r.content, cap
    return None, None


# ── 4. Common Crawl ────────────────────────────────────────
def cc_collections(cache, years):
    if "cc_coll" not in cache:
        r = get("https://index.commoncrawl.org/collinfo.json", timeout=60)
        cache["cc_coll"] = r.json() if (r is not None and r.ok) else []
    return [c for c in cache["cc_coll"]
            if any(f"-{y}-" in c.get("id", "") for y in years)]


def cc_prefix(coll, cache):
    key = "cc:" + coll["id"]
    if key in cache:
        return cache[key]
    api = coll["cdx-api"]
    q = "?url=socneurociencia.cl/wp-content/uploads/&matchType=prefix&output=json"
    rows = []
    r = get(api + q + "&showNumPages=true", timeout=90)
    try:
        pages = int(r.json().get("pages", 1)) if (r is not None and r.ok) else 0
    except (ValueError, AttributeError):
        pages = 0
    for pg in range(pages):
        r = get(api + q + f"&page={pg}", timeout=120)
        if r is None or not r.ok:
            continue
        for ln in r.text.splitlines():
            try:
                d = json.loads(ln)
            except ValueError:
                continue
            if not str(d.get("mime", "")).startswith("image"):
                rows.append({k: d.get(k) for k in
                             ("url", "status", "filename", "offset", "length", "mime")})
    cache[key] = rows
    print(f"  Common Crawl {coll['id']}: {len(rows)} capturas")
    return rows


def cc_fetch(rec, ext):
    off, ln = int(rec["offset"]), int(rec["length"])
    r = get("https://data.commoncrawl.org/" + rec["filename"], timeout=120,
            headers={"Range": f"bytes={off}-{off + ln - 1}"})
    if r is None or r.status_code not in (200, 206):
        return None, "descarga fallida"
    try:
        raw = gzip.decompress(r.content)
    except OSError:
        return None, "gzip inválido"
    warc_h, _, rest = raw.partition(b"\r\n\r\n")
    http_h, _, body = rest.partition(b"\r\n\r\n")
    if b"WARC-Truncated" in warc_h:
        return None, "truncado por Common Crawl"
    if b"transfer-encoding: chunked" in http_h.lower():
        out, i = b"", 0
        while True:
            j = body.find(b"\r\n", i)
            if j < 0:
                break
            try:
                size = int(body[i:j].split(b";")[0], 16)
            except ValueError:
                break
            if size == 0:
                break
            out += body[j + 2:j + 2 + size]
            i = j + 2 + size + 2
        body = out
    return (body, "ok") if is_real(body, ext) else (None, "no es el archivo")


# ── 5. Memento (otros archivos web) ────────────────────────
def memento(u, year):
    api = f"https://timetravel.mementoweb.org/api/json/{year}0101/{u}"
    r = get(api, tries=2, timeout=60)
    if r is None or not r.ok:
        return []
    try:
        d = r.json()
    except ValueError:
        return []
    ms = d.get("mementos", {})
    cand = [x.get("uri") for x in (ms.get("closest"), ms.get("first"), ms.get("last")) if x]
    out = []
    for c in cand:
        uri = c[0] if isinstance(c, list) else c
        if uri and uri not in out:
            out.append(uri)
    return out


def memento_fetch(uris, ext):
    for m in uris:
        raw = re.sub(r"/(\d{14})/", r"/\1id_/", m, count=1)
        for v in (raw, m):
            r = get(v, tries=2, timeout=90)
            if r is not None and r.ok and is_real(r.content, ext):
                return r.content, v
    return None, None


# ── principal ──────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    ap.add_argument("--skip-cc", action="store_true")
    ap.add_argument("--skip-memento", action="store_true")
    a = ap.parse_args()
    if not LIST.exists():
        sys.exit(f"No encuentro {LIST}.")
    REC.mkdir(parents=True, exist_ok=True)
    cache = load_cache()
    items = parse_list()[: a.limit] if a.limit else parse_list()
    print(f"{len(items)} archivos a investigar\n")

    print("A) Censo de la biblioteca de medios de WordPress (adjuntos por año)")
    census = wp_media_census(cache)
    print("  " + "  ".join(f"{y}:{n}" for y, n in census.items()))
    save_cache(cache)

    print("\nB) Índices de archivos web del dominio")
    wb = wayback_prefix("socneurociencia.cl", cache)
    save_cache(cache)
    wb_by_key, wb_by_name = defaultdict(list), defaultdict(list)
    for row in wb:
        wb_by_key[norm(row[0])].append(row)
        wb_by_name[base(row[0])].append(row)

    cc_by_key, cc_by_name = defaultdict(list), defaultdict(list)
    if not a.skip_cc:
        for coll in cc_collections(cache, range(2013, 2021)):
            for rec in cc_prefix(coll, cache):
                cc_by_key[norm(rec["url"])].append(rec)
                cc_by_name[base(rec["url"])].append(rec)
            save_cache(cache)

    print("\nC) Archivo por archivo")
    rows = []
    for n, it in enumerate(items, 1):
        u = it["url"]
        ext = ext_of(u)
        fname = base(u)
        own = urlparse(u).netloc.lower().removeprefix("www.") in OWN
        ev = {"url": u, "archivo": fname, "pagina": it["pagina"], "titulo": it["titulo"],
              "pagina_nueva": it["nuevo"], "enlace_en_pagina": "", "servidor": "",
              "biblioteca_medios": "", "listado_carpeta": "", "wayback": "",
              "commoncrawl": "", "memento": "", "resultado": "PERDIDO",
              "fuente": "", "archivo_local": ""}
        found = None

        ev["enlace_en_pagina"] = page_has_link(it["pagina"], fname, cache) if it["pagina"] else ""

        # servidor actual
        v, st, data = live_check(u)
        ev["servidor"] = f"OK {v}" if data else f"HTTP {st}"
        if data:
            found = (data, v, "servidor actual (misma ruta/variante)")

        if own and not found:
            stem, _ = stem_variants(fname)
            words = [w for w in re.split(r"[-_ .%]+", stem) if len(w) >= 3][:4]
            same = re.compile(re.escape(stem) + r"(-\d{1,2})?" + re.escape(ext) + "$")
            cands = [c for c in wp_media_search(" ".join(words) or stem, cache)
                     if same.match(base(c))]
            ev["biblioteca_medios"] = " | ".join(cands) if cands else "no"
            for c in cands:
                r = get(c, tries=2)
                if r is not None and r.ok and is_real(r.content, ext):
                    same_dir = c.rsplit("/", 1)[0].split("/uploads/")[-1] == \
                        u.rsplit("/", 1)[0].split("/uploads/")[-1]
                    found = (r.content, c, "servidor actual (biblioteca de medios)" if same_dir
                             else "servidor actual, OTRA CARPETA (verificar: puede ser otro documento)")
                    break
            folder = u.rsplit("/", 1)[0] + "/"
            dl = dir_listing(folder, cache)
            if dl["names"]:
                hits = [x for x in dl["names"] if same.match(x)]
                ev["listado_carpeta"] = ("; ".join(hits) or "carpeta listada, sin el archivo")
                for h in hits:
                    if found:
                        break
                    r = get(folder + quote(h))
                    if r is not None and r.ok and is_real(r.content, ext):
                        found = (r.content, folder + h, "servidor actual (listado de carpeta)")
            else:
                ev["listado_carpeta"] = f"sin listado (HTTP {dl['status']})"

        # Wayback
        if not found:
            caps = list(wb_by_key.get(norm(u), [])) if (own and wb) else wayback_url(u, cache)
            alt = [] if not own else [r for r in wb_by_name.get(fname, []) if r not in caps]
            ev["wayback"] = (f"{len(caps)} capturas exactas"
                             + (f", {len(alt)} con el mismo nombre en otra ruta" if alt else "")
                             if (caps or alt) else "sin capturas")
            data, cap = wayback_fetch(caps, ext)
            if data:
                found = (data, cap, "Wayback Machine")
            elif alt:
                data, cap = wayback_fetch(alt, ext)
                if data:
                    found = (data, cap, "Wayback Machine, MISMO NOMBRE EN OTRA RUTA (verificar)")
            elif caps or alt:
                ev["wayback"] += " (ninguna válida)"

        # Common Crawl
        if not found and own and not a.skip_cc:
            recs = cc_by_key.get(norm(u), []) + [r for r in cc_by_name.get(fname, [])
                                                 if norm(r["url"]) != norm(u)]
            notes = []
            for rec in recs[:5]:
                data, why = cc_fetch(rec, ext)
                notes.append(why)
                if data:
                    tag = ("Common Crawl" if norm(rec["url"]) == norm(u) else
                           "Common Crawl, MISMO NOMBRE EN OTRA RUTA (verificar)")
                    found = (data, rec["url"] + " @" + rec["filename"].split("/")[1], tag)
                    break
            ev["commoncrawl"] = f"{len(recs)} capturas: {', '.join(notes)}" if recs else "sin capturas"

        # Memento
        if not found and not a.skip_memento:
            yr = re.search(r"/uploads/(\d{4})/", u)
            ms = memento(u, yr.group(1) if yr else "2015")
            ev["memento"] = f"{len(ms)} mementos" if ms else "sin mementos"
            data, m = memento_fetch(ms, ext)
            if data:
                found = (data, m, "otro archivo web (Memento)")

        if found:
            ev["resultado"] = "RECUPERADO"
            ev["fuente"] = f"{found[2]}: {found[1]}"
            ev["archivo_local"] = save_file(u, found[0], found[2])
        elif ev["enlace_en_pagina"] == "no":
            ev["resultado"] = "PERDIDO (enlace no hallado en la página original: revisar)"
        rows.append(ev)
        print(f"  [{n:3d}/{len(items)}] {ev['resultado'][:10]:10s} {fname[:60]}"
              + (f"  ← {found[2]}" if found else ""))
        if n % 10 == 0:
            save_cache(cache)
    save_cache(cache)

    # informes
    with open(OUT / "forense.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    rec = [r for r in rows if r["resultado"] == "RECUPERADO"]
    lost = [r for r in rows if r["resultado"] != "RECUPERADO"]
    linked = sum(r["enlace_en_pagina"] == "sí" for r in rows)
    by_src = defaultdict(int)
    for r in rec:
        by_src[r["fuente"].split(":")[0]] += 1
    lines = [
        "Investigación forense — documentos perdidos del sitio SCN",
        f"Archivos investigados: {len(rows)}",
        f"Enlace confirmado en la página original publicada: {linked}/{len(rows)}",
        f"Recuperados: {len(rec)}  ·  Siguen perdidos: {len(lost)}",
        *(f"  - {k}: {v}" for k, v in sorted(by_src.items())),
        "",
        "Biblioteca de medios de WordPress, adjuntos por año:",
        "  " + "  ".join(f"{y}:{n}" for y, n in census.items()),
        "",
        "Siguen perdidos (por qué no se hallaron):",
        *(f"  - {r['archivo']}  [{r['servidor']}; wayback: {r['wayback'] or '-'}; "
          f"cc: {r['commoncrawl'] or '-'}]" for r in lost),
    ]
    (OUT / "resumen.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    with open(OUT / "busquedas_manuales.txt", "w", encoding="utf-8") as fh:
        fh.write("Búsquedas manuales para los archivos no recuperados\n\n")
        for r in lost:
            q = quote(f'"{r["archivo"]}"')
            fh.write(f"{r['archivo']}\n  https://www.google.com/search?q={q}\n"
                     f"  https://duckduckgo.com/?q={q}\n  (página: {r['titulo']})\n\n")

    print("\n" + "\n".join(lines[:lines.index("")] + lines[lines.index("") + 1:lines.index("") + 3]))
    print(f"\nInformes en {OUT}/  (forense.csv, resumen.txt, busquedas_manuales.txt)")


if __name__ == "__main__":
    main()
