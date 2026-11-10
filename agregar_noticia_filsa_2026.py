#!/usr/bin/env python3
"""
agregar_noticia_filsa_2026.py — enlaza la noticia FILSA 2026 en el sitio.

  • index.html          → primera entrada de "Noticias y convocatorias" (se mantienen 6)
  • noticias.html       → primera tarjeta + contador de publicaciones
  • noticias.html, asociarse.html, quienes-somos.html
                        → primera línea de "Entradas recientes" (se mantienen 5)

Idempotente: si la noticia ya está enlazada en una página, no la toca.
Uso (desde la raíz del repo):  python3 agregar_noticia_filsa_2026.py
"""
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
SLUG = "noticias/scn-en-filsa-2026.html"
TITULO = "La SCN participa en la 45ª Feria Internacional del Libro de Santiago (FILSA 2026)"
IMG = "img/filsa-2026-programa-scn.jpg"

HOME_ITEM = f"""      <li class="news-item">
        <div class="news-thumb"><img src="/{IMG}" alt="Programa SCN en FILSA 2026" loading="lazy"></div>
        <div class="news-date"><strong>10</strong>Nov 2026</div>
        <div>
          <span class="news-cat cat-divul">Divulgación</span>
          <a class="news-title" href="{SLUG}">{TITULO}</a>
          <p class="news-excpt">19 actividades de divulgación entre el 13 y el 22 de noviembre en el Centro Cultural Estación Mapocho: charla magistral, presentaciones de libros, talleres y conversatorios.</p>
        </div>
      </li>
"""

CARD = f"""    <a href="{SLUG}" class="card">
      <div class="card-img"><img src="{IMG}" alt="" loading="lazy"></div>
      <div class="card-body">
        <span class="badge b-dest">Destacado</span>
        <span class="card-title">{TITULO}</span>
        <p class="card-date">Noviembre 10, 2026</p>
        <p class="card-excerpt">La SCN presenta 19 actividades en FILSA 2026, del 13 al 22 de noviembre en el Centro Cultural Estación Mapocho: una charla magistral, presentaciones de libros, talleres y conversatorios. Programa completo en la noticia.</p>
        <span class="card-more">Leer artículo completo</span>
      </div>
    </a>
"""


def leer(nombre):
    return (RAIZ / nombre).read_text(encoding="utf-8")


def escribir(nombre, texto):
    (RAIZ / nombre).write_text(texto, encoding="utf-8")
    print(f"✓  {nombre}")


def agregar_reciente(texto):
    """Inserta la noticia al inicio de cada <ul class="sb-news-list"> y deja 5."""
    def repl(m):
        abre, items, cierra = m.group(1), m.group(2), m.group(3)
        indent = re.search(r"\n([ \t]*)<li>", items).group(1)
        lis = re.findall(r"[ \t]*<li>.*?</li>\n", items, flags=re.S)
        nuevo = f'{indent}<li><a href="{SLUG}">{TITULO}</a></li>\n'
        return abre + "".join([nuevo] + lis[:4]) + cierra
    return re.sub(r'(<ul class="sb-news-list">\n)(.*?)([ \t]*</ul>)', repl, texto,
                  count=1, flags=re.S)


# ── index.html ───────────────────────────────────────────────
t = leer("index.html")
if SLUG not in t:
    m = re.search(r'(<ul class="news-list">\n)(.*?)([ \t]*</ul>)', t, flags=re.S)
    items = re.findall(r'[ \t]*<li class="news-item">.*?</li>\n', m.group(2), flags=re.S)
    t = t[:m.start()] + m.group(1) + HOME_ITEM + "".join(items[:len(items) - 1]) + m.group(3) + t[m.end():]
    escribir("index.html", t)
else:
    print("·  index.html ya tenía la noticia")

# ── noticias.html ────────────────────────────────────────────
t = leer("noticias.html")
if SLUG not in t:
    marca = '<div class="card-grid" style="padding-top:0">\n'
    assert marca in t, "No se encontró la grilla de tarjetas en noticias.html"
    t = t.replace(marca, marca + CARD, 1)
    t = re.sub(r"<p>(\d+) publicaciones</p>",
               lambda m: f"<p>{int(m.group(1)) + 1} publicaciones</p>", t, count=1)
    t = agregar_reciente(t)
    escribir("noticias.html", t)
else:
    print("·  noticias.html ya tenía la noticia")

# ── sidebars "Entradas recientes" ────────────────────────────
for pagina in ("asociarse.html", "quienes-somos.html"):
    t = leer(pagina)
    if SLUG not in t:
        escribir(pagina, agregar_reciente(t))
    else:
        print(f"·  {pagina} ya tenía la noticia")
