#!/usr/bin/env python3
"""
agregar_buscador_nav.py — agrega la lupa de búsqueda al menú de todas las páginas.

Inserta antes de </body>:
    <script src="/js/buscador-nav.js" defer></script>
en cada .html del sitio que tenga el menú superior (id="nav-links").
Es idempotente; deploy.sh lo ejecuta en cada publicación para cubrir
páginas nuevas.

Uso:  python3 scripts/agregar_buscador_nav.py   (desde la raíz del repo)
"""
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
TAG = '<script src="/js/buscador-nav.js" defer></script>'
OMITIR = {".git", "pagefind", "migration_report", "node_modules"}


def main():
    revisadas = cambiadas = 0
    for p in sorted(RAIZ.rglob("*.html")):
        if OMITIR & set(p.relative_to(RAIZ).parts):
            continue
        html = p.read_text(encoding="utf-8")
        if 'id="nav-links"' not in html:
            continue
        revisadas += 1
        if "/js/buscador-nav.js" in html or "</body>" not in html:
            continue
        i = html.rfind("</body>")
        html = html[:i] + TAG + "\n" + html[i:]
        p.write_text(encoding="utf-8", data=html)
        cambiadas += 1
    print(f"Buscador en menú: {revisadas} páginas con menú, {cambiadas} actualizadas.")


if __name__ == "__main__":
    main()
