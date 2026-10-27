#!/usr/bin/env python3
"""
build_congress_pages.py — crea congresos/<AÑO>.html para los congresos que solo
existen como posts en WordPress (categoría 74, "congresos-anteriores"), usando
una página de congreso ya migrada como plantilla, y los agrega al índice
congresos-anteriores.html.

Reutiliza export_wp_archive.py (debe estar en la misma carpeta): misma caché de
la API, misma descarga de imágenes/documentos (con archive.org), mismos logs.

Qué hace
  1. Lee todos los posts de la categoría 74 por la REST API.
  2. Por cada año pedido busca el post cuyo título contiene el año y
     "congreso" o "reunión" (principal). Otros posts de la categoría con ese
     año en el título se agregan debajo como secciones adicionales.
     Para 2016 (no está en la cat. 74) busca además en todas las páginas/posts.
  3. Limpia el contenido (Exporter de export_wp_archive.py), lo inserta en una
     copia de congresos/2013.html y escribe congresos/<AÑO>.html.
  4. Agrega una tarjeta/enlace por año nuevo en congresos-anteriores.html
     (copia una tarjeta existente; respaldo en migration_report/).

Uso (desde la raíz del repo)
  python3 build_congress_pages.py --dry-run          # solo muestra qué haría
  python3 build_congress_pages.py                    # todos los años pendientes
  python3 build_congress_pages.py --years 2014 2009  # solo esos años
  python3 build_congress_pages.py --pick 2016=1234   # forzar el post/página id 1234 para 2016
  python3 build_congress_pages.py --no-index         # no tocar congresos-anteriores.html
  python3 build_congress_pages.py --remove 2016      # borra una página creada por este script
                                                     # (archivo, tarjeta del índice y manifest)

Nunca sobrescribe un congresos/<AÑO>.html que no haya creado este script
(salvo --force). Re-ejecutar es seguro.
"""

import argparse, copy, csv, html, json, os, re, shutil, sys, time
from types import SimpleNamespace

from bs4 import BeautifulSoup

try:
    import export_wp_archive as ew
except ImportError:
    sys.exit("No encuentro export_wp_archive.py. Corre este script desde la raíz del repo.")

# ───────────────────────── configuración ─────────────────────────
CATEGORY_ID = 74
YEARS       = [2005, 2006, 2007, 2008, 2009, 2010, 2014, 2016]
# años cuyo contenido se elige a mano: principal primero, luego secciones adicionales
PICKS       = {2016: [2100, 2133]}      # Congreso FALAN 2016 (+ plazo de resúmenes); NO Solcema (2035)
# nota destacada al inicio de la página
NOTES       = {2016: "En 2016 la Reunión Anual de la Sociedad Chilena de Neurociencia "
                     "fue reemplazada por el Congreso FALAN 2016."}
TEMPLATE    = "congresos/2013.html"
OUT_DIR     = "congresos"
INDEX_PAGE  = "congresos-anteriores.html"
MANIFEST    = "migration_report/congress_manifest.json"
LOG_CSV     = "migration_report/congress_log.csv"
KEY_RE      = re.compile(r"congreso|reuni[oó]n", re.I)
# fuera de la cat. 74 solo cuenta lo que es claramente de la SCN (no Solcema, FALAN, etc.)
SCN_RE      = re.compile(r"reuni[oó]n\s+anual|sociedad\s+chilena\s+de\s+neurociencia|\bscn\b", re.I)
YEAR_LINK   = re.compile(r"(?:^|/)congresos/(\d{4})\.html$")

# CSS de lo exportado (por si la plantilla no lo trae)
EXTRA_CSS = """
/* archivo (build_congress_pages.py) */
.img-reemplazo-logo{max-width:180px!important;opacity:.35;margin:1.25rem auto!important;border-radius:0!important}
.nota-archivo{margin-top:2rem;color:var(--muted);font-size:.85rem}
.nota-archivo code{font-size:.78rem;word-break:break-all}
.lista-archivo{list-style:none;margin-left:0!important}
.btn-archivo{text-decoration:none!important}
.cong-body a[data-estado="no-disponible"]{color:var(--muted);text-decoration:line-through}
.cong-body a[data-estado="no-disponible"]::after{content:' (no disponible)';font-size:.8em;text-decoration:none;display:inline-block;margin-left:.2em}
"""


# ───────────────────────── API ─────────────────────────
def get_list(url_base):
    """Lista paginada desde la API; prueba con y sin _embed."""
    for extra in ("&_embed=wp:featuredmedia,wp:term", ""):
        items, page = [], 1
        try:
            while True:
                data, hdr = ew.get_json(f"{url_base}{extra}&page={page}")
                if not isinstance(data, list):
                    raise RuntimeError(f"se esperaba una lista: {str(data)[:150]}")
                items += data
                total = int(hdr.get("X-WP-TotalPages", 1) or 1)
                if not data or page >= total:
                    return items
                page += 1
        except (RuntimeError, ew.requests.RequestException) as e:
            if page > 1 and "rest_post_invalid_page_number" in str(e):
                return items
            print(f"   ⚠ {url_base}{extra}: {str(e).splitlines()[-1][:150]}")
    return []


def title_of(it):
    return html.unescape(ew.text_of(it["title"]["rendered"])).strip()


def years_in(text):
    return {int(y) for y in re.findall(r"\b(20[0-2]\d)\b", text)}


def search_year(year):
    """Para años fuera de la cat. 74: páginas y posts con el año y congreso/reunión en el título."""
    found = {}
    S = ew.OLD_SITE + "/wp-json/wp/v2"
    queries = [f"{S}/pages?slug=congreso-{year}&per_page=10",
               f"{S}/pages?search={year}&per_page=50",
               f"{S}/posts?search=congreso%20{year}&per_page=50",
               f"{S}/posts?search=reuni%C3%B3n%20{year}&per_page=50"]
    for q in queries:
        for it in get_list(q):
            t = title_of(it)
            key = t + " " + it.get("slug", "").replace("-", " ")
            if year in years_in(key) and SCN_RE.search(key):
                found[it["id"]] = it
    return list(found.values())


def get_by_id(pid):
    for kind in ("posts", "pages"):
        try:
            data, _ = ew.get_json(f"{ew.OLD_SITE}/wp-json/wp/v2/{kind}/{pid}?_embed=wp:featuredmedia,wp:term")
            if isinstance(data, dict) and data.get("id"):
                return data
        except (RuntimeError, ew.requests.RequestException):
            continue
    return None


def choose(year, cat_items, picks):
    """(principal, [adicionales], candidatos) para un año."""
    if year in picks:
        by_id = {it["id"]: it for it in cat_items}
        got = []
        for pid in picks[year]:
            it = by_id.get(pid) or get_by_id(pid)
            if it:
                got.append(it)
            else:
                print(f"   ⚠ {year}: no encuentro el id {pid} en posts ni páginas")
        return (got[0] if got else None), got[1:], got
    same = [it for it in cat_items if year in years_in(title_of(it))]
    main = [it for it in same if KEY_RE.search(title_of(it)) and "simposio" not in title_of(it).lower()]
    if not main:
        main = search_year(year)
        same = main
    if not main:
        return None, [], same
    main.sort(key=lambda it: (len(years_in(title_of(it))), it["date"]))   # el más específico y antiguo
    primary = main[0]
    extras = sorted((it for it in same if it["id"] != primary["id"]), key=lambda it: it["date"])
    return primary, extras, same


# ───────────────────────── páginas ─────────────────────────
def load_page_map():
    pm = {}
    try:
        with open(ew.PAGES_CSV, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r.get("status") == "migrado" and r.get("new_file"):
                    pm[ew.norm_url(r["old_url"])] = r["new_file"]
    except OSError:
        pass
    try:
        with open(ew.MANIFEST, encoding="utf-8") as f:
            pm.update({k: v["new_file"] for k, v in json.load(f).items()})
    except (OSError, ValueError):
        pass
    for y in range(2005, 2031):
        if os.path.exists(f"{OUT_DIR}/{y}.html"):
            pm[ew.norm_url(f"{ew.OLD_SITE}/congreso-{y}")] = f"{OUT_DIR}/{y}.html"
    pm[ew.norm_url(f"{ew.OLD_SITE}/congresos-anteriores")] = INDEX_PAGE
    return pm


def find_logo(soup):
    img = soup.select_one(".nav-logo img") or next(
        (i for i in soup.find_all("img") if "logo" in (i.get("src", "") + i.get("alt", "")).lower()), None)
    if img is None:
        return None
    return os.path.normpath(os.path.join(os.path.dirname(TEMPLATE), img["src"]))


def info_line(body_html):
    """'Lugar · Fecha' si el texto los trae ("Lugar: …", "Fecha: …")."""
    txt = BeautifulSoup(body_html, "html.parser").get_text("\n")
    out = []
    for key in ("Lugar", "Fecha"):
        m = re.search(rf"{key}\s*:\s*([^\n]+)", txt, re.I)
        if m:
            out.append(" ".join(m.group(1).split()).rstrip(" .,;"))
    return " · ".join(out)


def source_note(it):
    return (f'<p class="sub-source">Fuente: «{html.escape(title_of(it))}», publicado el '
            f'{ew.fecha_larga(it["date"])} en el sitio anterior de la Sociedad '
            f'(<code>{html.escape(it["link"])}</code>).</p>')


def build_page(tpl, year, primary, extras, ex, logo, out):
    stats = {"img_local": 0, "img_logo": 0, "doc_local": 0, "doc_failed": 0, "links_unresolved": 0}
    parts, notes, feat = [], [], None
    for n, it in enumerate([primary] + extras):
        body, st, feat_rel = ex.process(it, out)
        for k in stats:
            stats[k] += st[k]
        logo_rel = ew.rel(logo, OUT_DIR)
        if feat_rel and feat_rel != logo_rel:
            if n == 0:
                feat = feat_rel
            else:
                body = f'<img src="{feat_rel}" alt="{html.escape(title_of(it))}" loading="lazy">\n' + body
        if n:
            parts.append(f'<hr class="section-sep">\n<h2>{html.escape(title_of(it))}</h2>')
        parts.append(f"<div>\n{body}\n</div>")
        notes.append(source_note(it))
    body_html = "\n".join(parts) + "\n" + "\n".join(notes)
    if NOTES.get(year):
        body_html = f"<blockquote><p>{html.escape(NOTES[year])}</p></blockquote>\n" + body_html

    title = title_of(primary)
    soup = BeautifulSoup(tpl, "html.parser")
    if soup.title:
        soup.title.string = f"Congreso SCN {year} — Sociedad Chilena de Neurociencia"
    label = "Reunión Anual" if re.search(r"reuni", title, re.I) else "Congreso"
    soup.select_one(".cong-label").string = f"{label} · {year}"
    soup.select_one(".cong-header h1").string = title
    meta = soup.select_one(".cong-header .meta")
    info = info_line(body_html)
    if meta is not None:
        if info:
            meta.string = info
        else:
            meta.decompose()
    fimg = soup.select_one("img.feat-img")
    if fimg is not None:
        if feat:
            fimg["src"], fimg["alt"] = feat, f"Congreso {year}"
        else:
            fimg.decompose()
    box = soup.select_one(".cong-body")
    keep = [b.extract() for b in box.select(".back-btn")]
    box.clear()
    for b in keep:
        box.append(b)
    box.append(BeautifulSoup("\n" + body_html + "\n", "html.parser"))
    style = soup.find("style")
    if style is not None and ".img-reemplazo-logo" not in style.get_text():
        style.string = style.get_text() + EXTRA_CSS
    for m in soup.find_all("meta", attrs={"name": "description"}):
        m["content"] = ew.text_of(body_html)[:160]
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(str(soup))
    return stats, title, feat, info


# ───────────────────────── índice ─────────────────────────
def update_index(new, dry):
    """new: lista de dicts {year, file, title, feat (rel. a congresos/), info}."""
    if not os.path.exists(INDEX_PAGE):
        print(f"   ⚠ no existe {INDEX_PAGE}; agrega los enlaces a mano")
        return 0
    with open(INDEX_PAGE, encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")

    def unit_of(a):                       # bloque que representa un congreso en el índice
        if "card" in (a.get("class") or []):
            return a
        li = a.find_parent("li")
        return li if li is not None and len(li.find_all("a")) <= 2 else a

    units = {}
    for a in soup.find_all("a", href=True):
        if a.find_parent("nav") or a.find_parent("footer"):
            continue
        m = YEAR_LINK.search(a["href"].split("#")[0])
        if m:
            units.setdefault(int(m.group(1)), unit_of(a))
    if not units:
        print(f"   ⚠ {INDEX_PAGE}: no encontré enlaces a congresos/<año>.html; agrega los nuevos a mano")
        return 0
    desc = list(units) == sorted(units, reverse=True)
    added = 0
    for n in sorted(new, key=lambda d: d["year"]):
        y = n["year"]
        if y in units:
            u = units[y]
            if n.get("built") and u.select_one(".card-title") is not None:
                u.select_one(".card-title").string = n["title"]
                if u.select_one(".card-meta") is not None:
                    u.select_one(".card-meta").string = n["info"]
                added += 1
                print(f"   {INDEX_PAGE}: {y} ya enlazado → título actualizado")
            else:
                print(f"   {INDEX_PAGE}: {y} ya enlazado")
            continue
        near = min(units, key=lambda k: (abs(k - y), k))
        u = copy.copy(units[near])
        a = u if u.name == "a" else u.find("a", href=YEAR_LINK)
        a["href"] = f"{OUT_DIR}/{y}.html"
        # textos: reemplazar el año viejo por el nuevo
        for s in u.find_all(string=True):
            if str(near) in s:
                s.replace_with(s.replace(str(near), str(y)))
        t = u.select_one(".card-title")
        if t is not None:
            t.string = n["title"]
        mt = u.select_one(".card-meta")
        if mt is not None:
            mt.string = n["info"]
        tag = u.select_one(".card-tag")
        if tag is not None and not re.search(r"\b\d{4}\b", tag.get_text()):
            tag.string = "Reunión Anual" if re.search(r"reuni", n["title"], re.I) else "Congreso"
        ci = u.select_one(".card-img")
        if ci is not None:
            ci.clear()
            if n["feat"]:
                ci["class"] = [c for c in ci.get("class", []) if c != "no-img"]
                img = soup.new_tag("img", src=os.path.normpath(os.path.join(OUT_DIR, n["feat"])).replace(os.sep, "/"),
                                   alt=f"Congreso {y}", loading="lazy")
                ci.append(img)
            else:
                ci["class"] = list(dict.fromkeys(ci.get("class", []) + ["no-img"]))
                sp = soup.new_tag("span", attrs={"class": "yr"})
                sp.string = str(y)
                ci.append(sp)
        elif u.find("img") is not None:
            for i in u.find_all("img"):
                i.decompose()
        # posición: mantener el orden de los años
        ref = units[near]
        after = (y < near) if desc else (y > near)
        (ref.insert_after if after else ref.insert_before)(u)
        units[y] = u
        added += 1
        print(f"   {INDEX_PAGE}: + {y} (copiado de {near}, {'después' if after else 'antes'})")
    if added and not dry:
        os.makedirs("migration_report", exist_ok=True)
        bak = f"migration_report/{INDEX_PAGE}.{time.strftime('%Y%m%d-%H%M%S')}.bak"
        shutil.copy2(INDEX_PAGE, bak)
        with open(INDEX_PAGE, "w", encoding="utf-8") as f:
            f.write(str(soup))
        print(f"   respaldo: {bak}")
    return added


def remove_years(years, manifest):
    """Deshace lo que este script creó para esos años."""
    changed_index = False
    soup = None
    if os.path.exists(INDEX_PAGE):
        with open(INDEX_PAGE, encoding="utf-8") as f:
            soup = BeautifulSoup(f.read(), "html.parser")
    for y in years:
        ent = manifest.get(str(y))
        if not ent:
            print(f"   {y}: no lo creó este script (no está en {MANIFEST}); no se toca")
            continue
        if os.path.exists(ent["new_file"]):
            os.remove(ent["new_file"])
            print(f"   {y}: borrado {ent['new_file']}")
        if soup is not None:
            for a in soup.find_all("a", href=True):
                m = YEAR_LINK.search(a["href"].split("#")[0])
                if m and int(m.group(1)) == y and not (a.find_parent("nav") or a.find_parent("footer")):
                    u = a if "card" in (a.get("class") or []) else (a.find_parent("li") or a)
                    u.decompose()
                    changed_index = True
                    print(f"   {y}: quitado de {INDEX_PAGE}")
        del manifest[str(y)]
    with open(MANIFEST, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    if changed_index:
        bak = f"migration_report/{INDEX_PAGE}.{time.strftime('%Y%m%d-%H%M%S')}.bak"
        shutil.copy2(INDEX_PAGE, bak)
        with open(INDEX_PAGE, "w", encoding="utf-8") as f:
            f.write(str(soup))
        print(f"   respaldo: {bak}")


# ───────────────────────── principal ─────────────────────────
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--years", type=int, nargs="+", default=YEARS)
    ap.add_argument("--pick", nargs="+", default=[], metavar="AÑO=ID[,ID…]",
                    help="ids de posts/páginas de WordPress para ese año (el primero es el principal)")
    ap.add_argument("--dry-run", action="store_true", help="no escribe nada; muestra qué haría")
    ap.add_argument("--force", action="store_true", help="sobrescribir congresos/<año>.html aunque no sea de este script")
    ap.add_argument("--no-index", action="store_true", help=f"no modificar {INDEX_PAGE}")
    ap.add_argument("--images", choices=["download", "logo"], default="download")
    ap.add_argument("--no-wayback", dest="wayback", action="store_false")
    ap.add_argument("--remove", type=int, nargs="+", metavar="AÑO",
                    help="borrar las páginas de esos años creadas por este script (y su tarjeta del índice)")
    args = ap.parse_args()
    try:
        picks = dict(PICKS)
        picks.update({int(y): [int(x) for x in i.split(",")] for y, i in (p.split("=") for p in args.pick)})
    except ValueError:
        sys.exit("--pick espera AÑO=ID[,ID…], p.ej. --pick 2016=2100,2133")

    if not os.path.exists(TEMPLATE):
        sys.exit(f"No encuentro la plantilla {TEMPLATE}.")
    with open(TEMPLATE, encoding="utf-8") as f:
        tpl = f.read()
    tsoup = BeautifulSoup(tpl, "html.parser")
    for sel in (".cong-label", ".cong-header h1", ".cong-body"):
        if tsoup.select_one(sel) is None:
            sys.exit(f"La plantilla {TEMPLATE} no tiene '{sel}'.")
    logo = find_logo(tsoup)
    if not logo or not os.path.exists(logo):
        sys.exit(f"No encuentro el logo SCN (detectado: {logo}).")

    manifest = {}
    if os.path.exists(MANIFEST):
        with open(MANIFEST, encoding="utf-8") as f:
            manifest = json.load(f)

    if args.remove:
        print("── Eliminando")
        remove_years(args.remove, manifest)
        return

    print(f"── Posts de la categoría {CATEGORY_ID}")
    cat_items = get_list(f"{ew.OLD_SITE}/wp-json/wp/v2/posts?categories={CATEGORY_ID}&per_page=50")
    if not cat_items:
        sys.exit("La API no devolvió posts de la categoría; revisa la conexión.")
    for it in sorted(cat_items, key=lambda i: i["date"]):
        print(f"   {it['id']:>6}  {it['date'][:10]}  {title_of(it)}")

    plan = []
    print("\n── Selección por año")
    for y in sorted(args.years):
        out = f"{OUT_DIR}/{y}.html"
        primary, extras, cands = choose(y, cat_items, picks)
        if primary is None:
            print(f"   {y}: ✗ sin post/página en WordPress"
                  + (" (candidatos: " + ", ".join(f"{c['id']} «{title_of(c)}»" for c in cands) + ")" if cands else ""))
            continue
        if os.path.exists(out) and manifest.get(str(y), {}).get("new_file") != out and not args.force:
            print(f"   {y}: ⏭ {out} ya existe y no lo creó este script (usa --force)")
            continue
        print(f"   {y}: {primary['id']} «{title_of(primary)}»"
              + "".join(f"\n          + {e['id']} «{title_of(e)}»" for e in extras))
        if y in picks:
            print("          (elegido a mano: PICKS / --pick)")
        elif primary not in cat_items:
            print(f"          ⚠ no viene de la categoría {CATEGORY_ID}: revisa que sea un congreso de la SCN "
                  f"(si no, --remove {y})")
        plan.append((y, out, primary, extras))

    if args.dry_run:
        print("\n(dry-run: no se escribió nada)")
        return

    ew.RETRY_DEAD = False
    page_map = load_page_map()
    for y, out, primary, extras in plan:               # los posts usados apuntan ahora a la página del congreso
        for it in [primary] + extras:
            page_map[ew.norm_url(it["link"])] = out
    ex = ew.Exporter(SimpleNamespace(images=args.images, wayback=args.wayback), logo, page_map)

    print(f"\n── Escribiendo {len(plan)} páginas")
    log, new = [], []
    for y, out, primary, extras in plan:
        st, title, feat, info = build_page(tpl, y, primary, extras, ex, logo, out)
        manifest[str(y)] = {"new_file": out, "title": title, "posts": [i["id"] for i in [primary] + extras],
                            "old_urls": [i["link"] for i in [primary] + extras]}
        os.makedirs(os.path.dirname(MANIFEST), exist_ok=True)
        with open(MANIFEST, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=1)
        log.append({"year": y, "new_file": out, "title": title, "posts": len(extras) + 1, **st})
        new.append({"year": y, "file": out, "title": title, "feat": feat, "info": info, "built": True})
        print(f"   {out}  «{title}»  img {st['img_local']}+{st['img_logo']}logo  "
              f"doc {st['doc_local']}/{st['doc_local'] + st['doc_failed']}  "
              f"enlaces sin destino {st['links_unresolved']}")

    if log:
        with open(LOG_CSV, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(log[0]))
            w.writeheader()
            w.writerows(log)
        with open(LOG_CSV.replace(".csv", "_pendientes.csv"), "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["pagina_antigua", "tipo", "url", "motivo"])
            w.writerows(ex.unresolved)

    if not args.no_index:
        # incluye años ya construidos antes (por si el índice se regeneró)
        for k, v in manifest.items():
            if k.isdigit() and not any(n["year"] == int(k) for n in new) and os.path.exists(v["new_file"]):
                new.append({"year": int(k), "file": v["new_file"], "title": v["title"], "feat": None, "info": ""})
        print(f"\n── Índice {INDEX_PAGE}")
        update_index(new, dry=False)

    print(f"\n✔ {len(log)} páginas de congreso · detalle: {LOG_CSV}")
    if ex.unresolved:
        print(f"  {len(ex.unresolved)} documentos/enlaces sin resolver → {LOG_CSV.replace('.csv', '_pendientes.csv')}")


if __name__ == "__main__":
    main()
