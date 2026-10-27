#!/usr/bin/env python3
"""Crea acceso-memberships.html (clon de socneurociencia.cl/acceso-memberships/).

- Plantilla: formulario.html (mismo nav, footer y estilos).
- Lee del sitio antiguo el enlace "INGRESE AQUÍ" y la imagen del banner
  (o usa --link URL / --img archivo si no hay conexión).
- Guarda la imagen junto al logo del sitio (misma carpeta que el logo del nav).
- --relink: cambia los enlaces a .../acceso-memberships/ del sitio antiguo
  en todas las páginas del repo por el nuevo archivo (ruta relativa).

Uso (raíz del repo):
  python3 build_memberships_page.py --dry-run
  python3 build_memberships_page.py [--relink] [--link URL] [--img RUTA] [--force]
"""
import argparse
import os
import re
import sys
from pathlib import Path
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

OLD_URL = "https://socneurociencia.cl/acceso-memberships/"
TEMPLATE = Path("formulario.html")
OUT = Path("acceso-memberships.html")
IMG_NAME = "banner-cuotas.png"
EMAIL = "sociedadchilenaneurociencia@gmail.com"
OLD_HOSTS = {"socneurociencia.cl", "www.socneurociencia.cl"}

CSS = """
/* acceso-memberships.html (build_memberships_page.py) */
.mem-access{max-width:500px;margin:0 auto;text-align:center}
.mem-access .mem-banner{display:block;border-radius:8px;overflow:hidden;
  box-shadow:0 4px 18px rgba(0,0,0,.12);transition:transform .15s}
.mem-access .mem-banner:hover,.mem-access .mem-banner:focus{transform:translateY(-2px)}
.mem-access .mem-banner img{display:block;width:100%;height:auto}
.mem-access .mem-btn{display:inline-block;margin:1.4rem 0 .4rem;padding:.8rem 1.6rem;
  border-radius:6px;background:#14a39b;color:#fff;font-weight:600;text-decoration:none}
.mem-access .mem-btn:hover,.mem-access .mem-btn:focus{background:#0f857e;color:#fff}
.mem-access .mem-note{font-size:.92rem;line-height:1.6;opacity:.85;margin-top:1rem}
"""

ALT = ("Pague sus cuotas societarias en línea a través de Memberships. "
       "También podrá actualizar su información personal y académica. "
       "Ingrese aquí. Pago con Webpay Plus.")


def fetch_old():
    """Devuelve (link, img_url) desde la página antigua, o (None, None)."""
    try:
        import requests
        r = requests.get(OLD_URL, timeout=25,
                         headers={"User-Agent": "Mozilla/5.0 (SCN migration)"})
        r.raise_for_status()
    except Exception as ex:
        print(f"  (no pude leer {OLD_URL}: {ex})")
        return None, None
    s = BeautifulSoup(r.text, "html.parser")
    body = s.select_one(".entry-content") or s.find("main") or s.body
    cands = []
    for a in body.find_all("a", href=True):
        img = a.find("img")
        href = urljoin(OLD_URL, a["href"])
        if img is not None:
            src = img.get("data-src") or img.get("src") or ""
            cands.append((href, urljoin(OLD_URL, src)))
    if not cands:
        print("  (no encontré un enlace con imagen en la página antigua)")
        return None, None
    pref = [c for c in cands if "cuota" in c[1].lower()] or cands
    print("  candidatos encontrados:")
    for h, i in cands:
        print(f"    enlace={h}\n    imagen={i}")
    return pref[0]


def img_dir_from(soup):
    """Carpeta del logo del nav (para guardar la imagen al lado)."""
    for img in soup.find_all("img", src=True):
        src = img["src"]
        if not urlparse(src).scheme and "logo" in src.lower():
            return Path(os.path.dirname(src) or ".")
    return Path("img")


def relink(dry, target):
    pat = re.compile(r'href="https?://(?:www\.)?socneurociencia\.cl/acceso-memberships/?"')
    total = 0
    for f in sorted(Path(".").rglob("*.html")):
        if any(p in f.parts for p in ("migration_report", ".git", "node_modules")):
            continue
        txt = f.read_text(encoding="utf-8", errors="replace")
        n = len(pat.findall(txt))
        if not n:
            continue
        rel = os.path.relpath(target, f.parent)
        total += n
        print(f"  {f}: {n} enlace(s) -> {rel}")
        if not dry:
            f.write_text(pat.sub(f'href="{rel}"', txt), encoding="utf-8")
    print(f"  total: {total} enlace(s){' (dry-run, sin escribir)' if dry else ''}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="sobrescribir si existe")
    ap.add_argument("--relink", action="store_true")
    ap.add_argument("--link", help="URL del botón INGRESE AQUÍ (si no hay conexión)")
    ap.add_argument("--img", help="archivo local del banner (si no hay conexión)")
    a = ap.parse_args()

    if not TEMPLATE.exists():
        sys.exit("No encuentro formulario.html — ejecuta desde la raíz del repo.")
    if OUT.exists() and not a.force:
        print(f"{OUT} ya existe (usa --force para regenerarlo).")
        if a.relink:
            relink(a.dry_run, OUT)
        return

    print("Leyendo página antigua…")
    link, img_url = fetch_old()
    link = a.link or link
    if not link:
        sys.exit("Sin enlace del botón. Vuelve a ejecutar con --link URL.")
    host = urlparse(link).netloc.lower()
    print(f"Enlace del botón: {link}")
    if host in OLD_HOSTS:
        print("AVISO: el enlace apunta al WordPress antiguo; dejará de funcionar "
              "cuando se apague socneurociencia.cl. Hay que conseguir la URL "
              "directa de la plataforma Memberships.")

    soup = BeautifulSoup(TEMPLATE.read_text(encoding="utf-8"), "html.parser")

    # Imagen
    idir = img_dir_from(soup)
    img_path = idir / IMG_NAME
    if a.img:
        src_file = Path(a.img).expanduser()
        if not src_file.exists():
            sys.exit(f"No existe {src_file}")
        data = src_file.read_bytes()
    elif img_url:
        import requests
        rr = requests.get(img_url, timeout=25,
                          headers={"User-Agent": "Mozilla/5.0 (SCN migration)"})
        rr.raise_for_status()
        data = rr.content
    else:
        sys.exit("Sin imagen. Vuelve a ejecutar con --img ~/Downloads/banner-cuotas-2-2.png")
    print(f"Imagen: {img_path} ({len(data)//1024} kB)")

    # Cabecera
    if soup.title:
        soup.title.string = "Acceso Memberships — Sociedad Chilena de Neurociencia"
    h1 = soup.find("h1")
    if h1 is None:
        sys.exit("La plantilla no tiene <h1>.")
    h1.string = "Acceso Memberships"
    lab = h1.find_previous_sibling()
    if lab is not None and "asociarse" in lab.get_text().lower():
        lab.string = "Socios · Cuotas"
    sub = h1.find_next_sibling()
    if sub is not None and sub.name in ("p", "div", "span"):
        sub.string = ("Pague sus cuotas societarias en línea y actualice "
                      "su información personal y académica")

    # Contenido: reemplaza el contenedor del formulario
    form = soup.find("form", id="form-socio")
    if form is None:
        sys.exit("No encuentro <form id=\"form-socio\"> en la plantilla.")
    box = form.parent
    box.clear()
    frag = BeautifulSoup(f"""
<div class="mem-access">
  <a class="mem-banner" href="{link}" target="_blank" rel="noopener">
    <img src="{img_path.as_posix()}" alt="{ALT}" width="500" height="500">
  </a>
  <a class="mem-btn" href="{link}" target="_blank" rel="noopener">Ingresar a Memberships &#8599;</a>
  <p class="mem-note">El pago se realiza en la plataforma externa Memberships, con Webpay Plus (Transbank).
  Si tienes dudas sobre tus cuotas, escríbenos a <a href="mailto:{EMAIL}">{EMAIL}</a>.</p>
</div>
""", "html.parser")
    box.append(frag)

    # Quitar el script del formulario; conservar los demás
    removed = 0
    for sc in soup.find_all("script"):
        t = sc.string or ""
        if "form-socio" in t or "rutOk" in t or "formspree" in t:
            sc.decompose()
            removed += 1
    print(f"Scripts del formulario quitados: {removed}")

    st = soup.new_tag("style")
    st.string = CSS
    (soup.head or soup).append(st)

    leftovers = [w for w in ("form-socio", "formspree", "Volver a Asociarse")
                 if w in str(soup)]
    if leftovers:
        print("AVISO: quedan restos de la plantilla:", ", ".join(leftovers))

    if a.dry_run:
        print(f"--dry-run: se escribirían {OUT} y {img_path}; nada escrito.")
    else:
        img_path.parent.mkdir(parents=True, exist_ok=True)
        img_path.write_bytes(data)
        OUT.write_text(str(soup), encoding="utf-8")
        print(f"OK: {OUT} creado.")

    if a.relink:
        print("Reenlazando páginas:")
        relink(a.dry_run, OUT)


if __name__ == "__main__":
    main()
