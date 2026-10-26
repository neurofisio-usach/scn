#!/usr/bin/env python3
"""
fix_internal_links.py — corrige los 4 enlaces internos sin destino
que quedaron en los archivos exportados por export_wp_archive.py.

Ejecutar desde la raíz del repo:
    python3 fix_internal_links.py
"""

from pathlib import Path
from bs4 import BeautifulSoup

# (archivo, href_exacto_en_el_html, acción, nuevo_href_o_None)
# acción "unwrap": elimina el <a> y deja el texto; "fix": corrige el href.
FIXES = [
    (
        "noticias/x-reunion-anual-de-la-sociedad-chilena-de-neurociencias-"
        "2-al-4-de-octubre-de-2014-hotel-villa-del-rio-valdivia.html",
        "https://www.socneurociencia.cl/sugerencia-de-hoteles/",
        "unwrap",
        None,
    ),
    (
        "noticias/herramientas-de-analisis-espectral-en-eeg-seminario-workshop.html",
        "https://socneurociencia.cl/www.bni.cl",
        "fix",
        "https://www.bni.cl",
    ),
    (
        "noticias/phd-position-at-the-instituto-de-neurociencias-umh-csic.html",
        "https://socneurociencia.cl/_wp_link_placeholder",
        "unwrap",
        None,
    ),
    (
        "noticias/latin-american-school-molecular-and-cellular-mechanisms-"
        "of-sensory-transduction.html",
        "https://socneurociencia.cl/_wp_link_placeholder",
        "unwrap",
        None,
    ),
]


def main():
    ok = warn = 0
    for path_str, bad_href, action, new_href in FIXES:
        p = Path(path_str)
        if not p.exists():
            print(f"⚠  archivo no encontrado: {path_str}")
            warn += 1
            continue

        soup = BeautifulSoup(p.read_text("utf-8"), "html.parser")
        changed = 0

        for a in soup.find_all("a", href=bad_href):
            if action == "unwrap":
                a.unwrap()
            else:  # "fix"
                a["href"] = new_href
                a["target"] = "_blank"
                a["rel"] = "noopener"
            changed += 1

        if changed:
            p.write_text(str(soup), "utf-8")
            verb = "desvinculado(s)" if action == "unwrap" else "corregido(s)"
            print(f"✔  {path_str}\n   {changed} enlace(s) {verb}  [{bad_href}]")
            ok += 1
        else:
            print(f"⚠  href no encontrado en {path_str}\n   [{bad_href}]")
            warn += 1

    print(f"\n{'─'*60}")
    print(f"  {ok} archivo(s) corregido(s)  ·  {warn} advertencia(s)")


if __name__ == "__main__":
    main()
