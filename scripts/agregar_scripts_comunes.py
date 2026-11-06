#!/usr/bin/env python3
"""
agregar_scripts_comunes.py — agrega los scripts compartidos a todas las páginas.

Inserta antes de </body>, en cada .html del sitio que tenga el menú superior
(id="nav-links"), los <script> de la lista SCRIPTS que todavía no tenga:
  • /js/buscador-nav.js  — lupa de búsqueda de noticias en el menú
  • /js/donaciones.js    — ventana con los datos para donar (botón Donaciones)

Además deja el botón "Año del Cerebro" del menú apuntando al sitio oficial
de Minciencia (pestaña nueva), en todas las páginas.

Es idempotente; deploy.sh lo ejecuta en cada publicación para cubrir páginas
nuevas. Para agregar otro script común a todo el sitio, súmalo a SCRIPTS.

Uso:  python3 scripts/agregar_scripts_comunes.py   (desde la raíz del repo)
"""
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SCRIPTS = ["/js/buscador-nav.js", "/js/donaciones.js"]
URL_CEREBRO = "https://añodelcerebro.minciencia.gob.cl/"
BOTON_CEREBRO = re.compile(r'(<li class="nav-hl">)<a [^>]*>(Año del Cerebro</a>)')
LINK_CEREBRO = f'<a href="{URL_CEREBRO}" target="_blank" rel="noopener">'
OMITIR = {".git", "pagefind", "migration_report", "node_modules"}


def main():
    revisadas = cambiadas = 0
    for p in sorted(RAIZ.rglob("*.html")):
        if OMITIR & set(p.relative_to(RAIZ).parts):
            continue
        html = p.read_text(encoding="utf-8")
        if 'id="nav-links"' not in html or "</body>" not in html:
            continue
        revisadas += 1
        original = html
        html = BOTON_CEREBRO.sub(lambda m: m.group(1) + LINK_CEREBRO + m.group(2), html)
        faltan = [s for s in SCRIPTS if s not in html]
        if faltan:
            tags = "".join(f'<script src="{s}" defer></script>\n' for s in faltan)
            i = html.rfind("</body>")
            html = html[:i] + tags + html[i:]
        if html != original:
            p.write_text(html, encoding="utf-8")
            cambiadas += 1
    print(f"Scripts comunes: {revisadas} páginas con menú, {cambiadas} actualizadas.")


if __name__ == "__main__":
    main()
