#!/usr/bin/env python3
"""
marcar_pagefind.py — prepara las noticias para el buscador Pagefind.

Recorre noticias/*.html y, en cada artículo:
  • marca .art-header y .art-body con data-pagefind-body (solo eso se indexa;
    menú, footer y sidebar quedan fuera),
  • ignora textos que no aportan a la búsqueda (etiqueta y línea de
    fecha/categorías del encabezado, botón "Volver…", nota de archivo con la
    URL antigua),
  • agrega la fecha como metadato (se muestra en los resultados) y como
    criterio de orden (data-pagefind-sort="date:AAAA-MM-DD").

Es idempotente: se puede correr en cada deploy. deploy.sh lo ejecuta antes de
generar el índice, así las noticias nuevas quedan marcadas automáticamente.

Uso:  python3 scripts/marcar_pagefind.py   (desde la raíz del repo)
"""
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
NOTICIAS = RAIZ / "noticias"

# Páginas que NO deben indexarse
EXCLUIR = {
    "archivo.html",  # listado de enlaces: coincidiría con casi cualquier búsqueda
    # copia de archivo de la noticia vigente postulaciones-abiertas-doctorado-en-ciencias-bmcn.html
    "postulaciones-abiertas-doctorado-en-ciencias-bmcn-2026-6485.html",
}

MESES = {m: i for i, m in enumerate(
    "enero febrero marzo abril mayo junio julio agosto septiembre "
    "octubre noviembre diciembre".split(), start=1)}
MESES["setiembre"] = 9
NOMBRES = {v: k for k, v in MESES.items() if k != "setiembre"}


def fecha_iso(texto):
    """'21 de octubre de 2024' o 'Julio 15, 2026' -> '2024-10-21'."""
    t = texto.strip().lower()
    m = re.fullmatch(r"(\d{1,2}) de (\w+) de (\d{4})", t)
    if m:
        d, mes, a = m.groups()
    else:
        m = re.fullmatch(r"(\w+) (\d{1,2}), (\d{4})", t)
        if not m:
            return None
        mes, d, a = m.groups()
    if mes not in MESES:
        return None
    return f"{a}-{MESES[mes]:02d}-{int(d):02d}"


def agregar_attr(html, patron, attr):
    """Agrega attr a la primera etiqueta que calce con patron, si aún no lo tiene."""
    m = re.search(patron, html)
    if not m or attr.split("=")[0] in m.group(0):
        return html
    etiqueta = m.group(0)
    nueva = etiqueta[:-1] + " " + attr + ">"
    return html[:m.start()] + nueva + html[m.end():]


def marcar(path):
    html = original = path.read_text(encoding="utf-8")

    if path.name in EXCLUIR:
        # Quitar marcas si alguna vez se agregaron
        html = html.replace(" data-pagefind-body", "")
    else:
        html = agregar_attr(html, r'<div class="art-header"[^>]*>', "data-pagefind-body")
        html = agregar_attr(html, r'<div class="art-body"[^>]*>', "data-pagefind-body")

        # Etiqueta del encabezado ("Noticias · Archivo", etc.)
        html = re.sub(r'<span class="label"(?![^>]*data-pagefind-ignore)',
                      '<span class="label" data-pagefind-ignore', html, count=1)
        # Botón Volver… (cualquier orden de atributos)
        html = re.sub(r'<a (?=[^>]*class="back-btn")(?![^>]*data-pagefind-ignore)',
                      '<a data-pagefind-ignore ', html)
        # Línea de fecha y categorías del encabezado (la fecha ya va como metadato)
        html = re.sub(r'<div class="meta"(?![^>]*data-pagefind-ignore)',
                      '<div class="meta" data-pagefind-ignore', html, count=1)
        # Nota con la URL del sitio anterior
        html = re.sub(r'<p class="nota-archivo"(?![^>]*data-pagefind-ignore)',
                      '<p class="nota-archivo" data-pagefind-ignore', html)

        # Fecha: metadato visible + orden
        m = re.search(r'<div class="meta"[^>]*><span>([^<]*)</span>', html)
        if m:
            visible = m.group(1).strip()
            iso = fecha_iso(visible)
            if iso:  # formato uniforme en los resultados: "10 de abril de 2025"
                a, mes, d = iso.split("-")
                visible = f"{int(d)} de {NOMBRES[int(mes)]} de {a}"
            # Primer <h1> dentro del encabezado (sin cruzar a otros h1 del cuerpo)
            h1 = re.search(r'<div class="art-header"[^>]*>\s*<div class="wrap">.*?<h1', html, re.S)
            if h1:
                resto = html[h1.end():html.index(">", h1.end())]
                if "data-pagefind-meta" not in resto:
                    attrs = f' data-pagefind-meta="fecha:{visible}"'
                    if iso:
                        attrs += f' data-pagefind-sort="date:{iso}"'
                    html = html[:h1.end()] + attrs + html[h1.end():]

    if html != original:
        path.write_text(html, encoding="utf-8")
        return True
    return False


def main():
    if not NOTICIAS.is_dir():
        sys.exit(f"No encuentro la carpeta {NOTICIAS}")
    archivos = sorted(NOTICIAS.glob("*.html"))
    cambiados = sum(marcar(p) for p in archivos)
    print(f"Pagefind: {len(archivos)} páginas revisadas, {cambiados} actualizadas.")


if __name__ == "__main__":
    main()
