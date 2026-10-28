#!/usr/bin/env python3
"""Reincorpora al sitio los documentos recuperados del respaldo de 4ID.

- Lee <respaldo>/coincidencias.csv y los archivos en <respaldo>/extraidos/.
- Acepta: coincidencias con RUTA EXACTA (archivos del propio sitio) y, para
  enlaces externos, coincidencias por nombre si el nombre no es genérico.
- Copia cada archivo a docs/archivo/<año>/<nombre-normalizado> (mismo esquema
  que los documentos ya migrados).
- En todas las páginas .html: los <a> que apuntan a esos URL pasan a la ruta
  local relativa y pierden data-estado="no-disponible".
- Escribe migration_report/documentos_perdidos_restantes.txt con lo que sigue
  sin recuperar.

Uso (raíz del repo):
  python3 restaurar_documentos.py --dry-run
  python3 restaurar_documentos.py
"""
import argparse
import csv
import filecmp
import os
import re
import shutil
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path
from urllib.parse import unquote, urlparse

BK = Path("~/PATO/USACH/scn_privado/respaldo_4id").expanduser()
DOCS = Path("docs/archivo")
SKIP = ("migration_report", ".git", "node_modules")
GENERIC = {"program.pdf", "poster.pdf", "schedule.pdf", "programa.pdf", "triptico.pdf",
           "afiche.pdf", "flyer.pdf", "basic-information.pdf"}
A_TAG = re.compile(r"<a\b[^>]*>", re.I)
HREF = re.compile(r'\bhref="([^"]+)"', re.I)
ESTADO = re.compile(r'\s*\bdata-estado="no-disponible"', re.I)


def norm(u):
    p = urlparse(u.strip())
    h = p.netloc.lower().split(":")[0].removeprefix("www.")
    return h + unquote(p.path).lower()


def slug(name):
    st, dot, ext = unquote(name).rpartition(".")
    if not dot:
        st, ext = name, ""
    st = unicodedata.normalize("NFKD", st).encode("ascii", "ignore").decode().lower()
    st = re.sub(r"[^a-z0-9]+", "-", st).strip("-") or "documento"
    return st + ("." + ext.lower() if ext else "")


def html_files():
    for f in sorted(Path(".").rglob("*.html")):
        if not any(p in f.parts for p in SKIP):
            yield f


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--respaldo", default=str(BK))
    a = ap.parse_args()
    bk = Path(a.respaldo).expanduser()
    csvf, ext_dir = bk / "coincidencias.csv", bk / "extraidos"
    if not Path("index.html").exists():
        sys.exit("Ejecuta desde la raíz del repo.")
    if not csvf.exists() or not ext_dir.exists():
        sys.exit(f"Falta {csvf} o {ext_dir} (ejecuta antes buscar_en_respaldo.py --extract).")

    # 1. elegir una fuente por URL
    chosen, notes = {}, []
    rows = list(csv.DictReader(open(csvf, encoding="utf-8")))
    by_url = defaultdict(list)
    for r in rows:
        by_url[r["url"]].append(r)
    for url, rs in by_url.items():
        own = urlparse(url).netloc.lower().removeprefix("www.") == "socneurociencia.cl"
        exact = [r for r in rs if r["tipo"] == "RUTA EXACTA"]
        if exact:
            pick = exact[0]
        elif not own:
            fname = unquote(urlparse(url).path).rsplit("/", 1)[-1].lower()
            if fname in GENERIC or len({r["ruta_en_respaldo"] for r in rs}) > 1:
                notes.append(f"  omitido (nombre ambiguo): {url}")
                continue
            pick = rs[0]
            notes.append(f"  externo, por nombre: {url}\n      ← {pick['ruta_en_respaldo']}")
        else:
            notes.append(f"  omitido (solo mismo nombre en otra carpeta): {url}")
            continue
        src = ext_dir / pick["ruta_en_respaldo"]
        if not src.is_file():
            notes.append(f"  falta extraído: {src}")
            continue
        chosen[url] = src

    # 2. destino en docs/archivo/<año>/
    dest_of, used = {}, {}
    for url, src in sorted(chosen.items()):
        m = re.search(r"/uploads/(\d{4})/(\d{2})/", str(src))
        year, month = (m.group(1), m.group(2)) if m else ("externos", "")
        d = DOCS / year / slug(src.name)
        if d in used and not filecmp.cmp(used[d], src, shallow=False):
            d = d.with_name(f"{d.stem}-{month}{d.suffix}")
        if d.exists() and d not in used and not filecmp.cmp(d, src, shallow=False):
            d = d.with_name(f"{d.stem}-rec{d.suffix}")
        used[d] = src
        dest_of[norm(url)] = d

    big = [(d, s.stat().st_size) for d, s in used.items() if s.stat().st_size > 25 * 2**20]
    total = sum(s.stat().st_size for s in used.values())
    print(f"Documentos a reincorporar: {len(chosen)} URL → {len(used)} archivos "
          f"({total / 2**20:.0f} MB)")
    for d, sz in big:
        print(f"  AVISO archivo grande ({sz / 2**20:.0f} MB): {d}")
    if notes:
        print("Notas:\n" + "\n".join(notes))

    # 3. reenlazar
    changed_files, n_links, example = 0, 0, None
    remaining = defaultdict(set)
    for f in html_files():
        txt = f.read_text(encoding="utf-8", errors="replace")

        def fix(m):
            nonlocal n_links, example
            tag = m.group(0)
            h = HREF.search(tag)
            if not h:
                return tag
            d = dest_of.get(norm(h.group(1)))
            if d is None:
                return tag
            rel = os.path.relpath(d, f.parent).replace(os.sep, "/")
            new = ESTADO.sub("", tag.replace(h.group(0), f'href="{rel}"'))
            n_links += 1
            if example is None:
                example = (f, tag, new)
            return new

        new_txt = A_TAG.sub(fix, txt)
        for tag in A_TAG.findall(new_txt):
            if ESTADO.search(tag) and (h := HREF.search(tag)):
                remaining[h.group(1)].add(f.as_posix())
        if new_txt != txt:
            changed_files += 1
            if not a.dry_run:
                f.write_text(new_txt, encoding="utf-8")

    print(f"Enlaces reemplazados: {n_links} en {changed_files} páginas")
    if example:
        print(f"Ejemplo ({example[0]}):\n  antes:   {example[1]}\n  después: {example[2]}")

    # 4. copiar y lista de restantes
    if not a.dry_run:
        for d, src in used.items():
            d.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, d)
        out = Path("migration_report/documentos_perdidos_restantes.txt")
        out.parent.mkdir(exist_ok=True)
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(f"Documentos aún no recuperados: {len(remaining)}\n\n")
            for u in sorted(remaining):
                fh.write(f"- {u}\n    en: {', '.join(sorted(remaining[u]))}\n")
        print(f"Copiados {len(used)} archivos a {DOCS}/")
        print(f"Siguen sin recuperar: {len(remaining)} → {out}")
    else:
        print(f"Seguirían marcados no-disponible: {len(remaining)} URL")
        print("--dry-run: nada escrito.")


if __name__ == "__main__":
    main()
