#!/usr/bin/env python3
"""congresos/2014.html: quita los enlaces-imagen con el logo de reemplazo
(imágenes no recuperadas) y deja solo el del Libro de resúmenes, convertido en
botón de texto.

Uso (raíz del repo):
  python3 limpiar_2014.py --dry-run
  python3 limpiar_2014.py
Respaldo: migration_report/2014.html.bak-limpieza
"""
import argparse
import shutil
import sys
from collections import Counter
from pathlib import Path

from bs4 import BeautifulSoup

PAGE = Path("congresos/2014.html")
BACKUP = Path("migration_report/2014.html.bak-limpieza")
KEEP = "libro-de-resumenes"
CSS = """
/* limpiar_2014.py */
.doc-btn-wrap{text-align:center;margin:1.5rem 0}
.doc-btn{display:inline-block;padding:.8rem 1.6rem;border-radius:6px;background:#14a39b;
  color:#fff !important;font-weight:600;text-decoration:none}
.doc-btn:hover,.doc-btn:focus{background:#0f857e}
"""


def image_links(soup):
    """<a> sin texto que contienen exactamente una <img>."""
    out = []
    for a in soup.find_all("a"):
        imgs = a.find_all("img")
        if len(imgs) == 1 and not a.get_text(strip=True):
            out.append((a, imgs[0].get("src", "")))
    return out


def remove_empty_parents(tag):
    p = tag.parent
    tag.decompose()
    while p is not None and p.name not in ("body", "main", "article", "section") \
            and not p.get_text(strip=True) and not p.find(["img", "iframe", "video", "a"]):
        q = p.parent
        p.decompose()
        p = q


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if not PAGE.exists():
        sys.exit(f"No encuentro {PAGE} — ejecuta desde la raíz del repo.")
    soup = BeautifulSoup(PAGE.read_text(encoding="utf-8"), "html.parser")

    links = image_links(soup)
    counts = Counter(src for _, src in links)
    print("Enlaces-imagen en la página (src de la imagen → cantidad):")
    for src, c in counts.most_common():
        print(f"  {c:3d}  {src}")
    if not counts:
        sys.exit("No hay enlaces-imagen; nada que hacer.")
    placeholder = counts.most_common(1)[0][0]
    if counts[placeholder] < 3:
        sys.exit("No identifico con seguridad la imagen de reemplazo; pega la lista de arriba.")
    print(f"\nImagen de reemplazo: {placeholder}\n")

    keep, drop = [], []
    for el, src in links:
        if src != placeholder:
            continue
        (keep if KEEP in el.get("href", "").lower() else drop).append(el)
    for el in drop:
        print(f"  quitar   {el.get('href', '')}")
    for el in keep:
        print(f"  CONSERVAR (como botón) {el.get('href', '')}")
    if not keep:
        print("AVISO: no encontré el enlace al Libro de resúmenes entre las imágenes.")
    if a.dry_run:
        print(f"\n--dry-run: se quitarían {len(drop)} y se convertiría {len(keep)}; nada escrito.")
        return

    for el in keep:
        new = soup.new_tag("a", href=el["href"], target="_blank", rel="noopener")
        new["class"] = "doc-btn"
        new.string = "Libro de resúmenes 2014 (PDF)"
        wrap = soup.new_tag("p")
        wrap["class"] = "doc-btn-wrap"
        wrap.append(new)
        el.replace_with(wrap)
    for el in drop:
        remove_empty_parents(el)
    if keep:
        st = soup.new_tag("style")
        st.string = CSS
        (soup.head or soup).append(st)

    BACKUP.parent.mkdir(exist_ok=True)
    shutil.copy2(PAGE, BACKUP)
    PAGE.write_text(str(soup), encoding="utf-8")
    print(f"\nOK: {len(drop)} enlaces quitados, {len(keep)} convertido en botón. Respaldo: {BACKUP}")


if __name__ == "__main__":
    main()
