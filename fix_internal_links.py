#!/usr/bin/env python3
"""
fix_internal_links.py — corrige los 4 enlaces internos sin destino.
Ejecutar desde la raíz del repo: python3 fix_internal_links.py
"""
import glob, re
from pathlib import Path
from bs4 import BeautifulSoup, NavigableString


def load(path_str):
    """Carga el archivo; si el nombre está truncado busca con glob."""
    p = Path(path_str)
    if p.exists():
        return p
    # el export trunca slugs muy largos — buscar por prefijo de 60 chars
    parent = p.parent
    prefix = p.stem[:60]
    candidates = sorted(parent.glob(prefix + "*.html"))
    if len(candidates) == 1:
        print(f"  (nombre truncado → {candidates[0].name})")
        return candidates[0]
    if candidates:
        print(f"⚠  varios candidatos para {path_str}:")
        for c in candidates:
            print(f"     {c}")
    else:
        print(f"⚠  archivo no encontrado: {path_str}")
    return None


def apply(p, finder, action):
    soup = BeautifulSoup(p.read_text("utf-8"), "html.parser")
    n = 0
    for a in soup.find_all("a", href=True):
        if finder(a):
            action(a)
            n += 1
    if n:
        p.write_text(str(soup), "utf-8")
    return n


# ── acciones ─────────────────────────────────────────────────────────────────

def unwrap(a):
    """Elimina el <a> conservando el texto."""
    a.unwrap()

def fix_bni(a):
    """href era markdown crudo → enlace externo limpio."""
    a["href"] = "https://www.bni.cl"
    a["target"] = "_blank"
    a["rel"] = "noopener"
    # limpiar texto de formato markdown [label](url) → label
    raw = a.get_text()
    m = re.match(r"\[(.+?)\]\(.+?\)", raw)
    if m:
        a.clear()
        a.append(NavigableString(m.group(1)))

def fix_placeholder_with_url(a):
    """_wp_link_placeholder cuyo texto es la URL real → la rescata."""
    text = a.get_text(strip=True)
    if text.startswith("http"):
        a["href"] = text
        a["target"] = "_blank"
        a["rel"] = "noopener"
    else:
        a.unwrap()

def remove_empty(a):
    """_wp_link_placeholder vacío → eliminar el <a> por completo."""
    a.decompose()


# ── tabla de fixes ────────────────────────────────────────────────────────────

TASKS = [
    (
        "noticias/x-reunion-anual-de-la-sociedad-chilena-de-neurociencias-"
        "2-al-4-de-octubre-de-2014-hotel-villa-del-rio-valdivia.html",
        lambda a: "sugerencia-de-hoteles" in a["href"],
        unwrap,
        "2014 · sugerencia-de-hoteles (página perdida) → desvinculado",
    ),
    (
        "noticias/herramientas-de-analisis-espectral-en-eeg-seminario-workshop.html",
        lambda a: "bni.cl" in a["href"],
        fix_bni,
        "EEG workshop · href markdown de bni.cl → https://www.bni.cl",
    ),
    (
        "noticias/phd-position-at-the-instituto-de-neurociencias-umh-csic.html",
        lambda a: a["href"] == "_wp_link_placeholder"
                  and a.get_text(strip=True).startswith("http"),
        fix_placeholder_with_url,
        "PhD UMH-CSIC · _wp_link_placeholder → URL rescatada del texto del enlace",
    ),
    (
        "noticias/latin-american-school-molecular-and-cellular-mechanisms-"
        "of-sensory-transduction.html",
        lambda a: a["href"] == "_wp_link_placeholder"
                  and not a.get_text(strip=True),
        remove_empty,
        "Latin American school · _wp_link_placeholder vacío → eliminado",
    ),
]


def main():
    ok = warn = 0
    for path_str, finder, action, desc in TASKS:
        p = load(path_str)
        if p is None:
            warn += 1
            continue
        n = apply(p, finder, action)
        if n:
            print(f"✔  {p}  ({n} enlace(s))\n   {desc}")
            ok += 1
        else:
            print(f"⚠  patrón no encontrado en {p}\n   {desc}")
            warn += 1

    print(f"\n{'─'*60}")
    print(f"  {ok} archivo(s) corregido(s)  ·  {warn} advertencia(s)")


if __name__ == "__main__":
    main()
