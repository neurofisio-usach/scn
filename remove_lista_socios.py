#!/usr/bin/env python3
"""Lista de Socios: guardar una copia privada y quitarla del sitio.

1. Descarga https://socneurociencia.cl/socios/ (mientras siga en línea) y la
   guarda FUERA del repo: HTML original + texto + tablas en CSV.
2. Si el repo tiene páginas que son la lista (p.ej. archivo/socios.html),
   copia cada una al respaldo y la quita del repo (git rm).
3. Elimina del menú/pie los <li> con "Lista de Socios" en todas las páginas.
4. Informa cualquier otra mención o enlace para revisión manual.

Uso (raíz del repo):
  python3 remove_lista_socios.py --dry-run
  python3 remove_lista_socios.py [--dest ~/PATO/USACH/scn_privado/lista_socios]
"""
import argparse
import csv
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

from bs4 import BeautifulSoup

OLD_URL = "https://socneurociencia.cl/socios/"
DEFAULT_DEST = "~/PATO/USACH/scn_privado/lista_socios"
SKIP = ("migration_report", ".git", "node_modules")
LIST_STEMS = {"socios", "lista-de-socios", "lista-socios", "listado-de-socios"}

LI_RE = re.compile(r'^[ \t]*<li\b[^\n]*?Lista de Socios[^\n]*?</li>[ \t]*\n?',
                   re.I | re.M)
MENTION_RE = re.compile(r'Lista de Socios|socneurociencia\.cl/socios/?["#?]', re.I)


def html_files():
    for f in sorted(Path(".").rglob("*.html")):
        if not any(p in f.parts for p in SKIP):
            yield f


def save_old_page(url, dest, dry):
    try:
        import requests
        r = requests.get(url, timeout=30,
                         headers={"User-Agent": "Mozilla/5.0 (SCN migration)"})
    except Exception as ex:
        print(f"  ✗ no pude descargar {url}: {ex}")
        return False
    print(f"  HTTP {r.status_code}  ({len(r.content)//1024} kB)  {r.url}")
    if r.status_code != 200:
        print("  ✗ la página no está disponible públicamente; nada guardado.")
        return False
    s = BeautifulSoup(r.text, "html.parser")
    body = s.select_one(".entry-content") or s.find("main") or s.body
    if "wp-login" in r.url or (body and body.find("input", {"type": "password"})):
        print("  ✗ la página pide inicio de sesión; nada guardado.")
        return False
    tables = body.find_all("table") if body else []
    text = body.get_text("\n", strip=True) if body else ""
    print(f"  contenido: {len(tables)} tabla(s), {len(text.splitlines())} líneas de texto")
    if dry:
        return True
    tag = date.today().isoformat()
    dest.mkdir(parents=True, exist_ok=True)
    (dest / f"socios_wp_{tag}.html").write_text(r.text, encoding="utf-8")
    (dest / f"socios_wp_{tag}.txt").write_text(text + "\n", encoding="utf-8")
    for k, t in enumerate(tables, 1):
        with open(dest / f"socios_wp_{tag}_tabla{k}.csv", "w", newline="",
                  encoding="utf-8") as fh:
            w = csv.writer(fh)
            for tr in t.find_all("tr"):
                w.writerow([c.get_text(" ", strip=True)
                            for c in tr.find_all(["th", "td"])])
    print(f"  ✓ guardado en {dest}")
    return True


def is_list_page(f):
    if f.stem.lower() in LIST_STEMS:
        return True
    head = f.read_text(encoding="utf-8", errors="replace")[:6000]
    m = re.search(r"<title>(.*?)</title>", head, re.I | re.S)
    h = re.search(r"<h1[^>]*>(.*?)</h1>", head, re.I | re.S)
    return any(x and re.search(r"lista de socios", x.group(1), re.I) for x in (m, h))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--dest", default=DEFAULT_DEST)
    ap.add_argument("--url", default=OLD_URL)
    a = ap.parse_args()
    dry = a.dry_run
    dest = Path(a.dest).expanduser().resolve()
    repo = Path(".").resolve()
    if not Path("index.html").exists():
        sys.exit("Ejecuta desde la raíz del repo.")
    if repo in dest.parents or dest == repo:
        sys.exit(f"--dest está dentro del repo ({dest}); elige una carpeta fuera.")

    print(f"1) Copia privada de {a.url}")
    save_old_page(a.url, dest, dry)

    print("\n2) Páginas de la lista dentro del repo")
    pages = [f for f in html_files() if is_list_page(f)]
    if not pages:
        print("  (ninguna)")
    for f in pages:
        print(f"  {f}")
        if not dry:
            target = dest / "repo" / f
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, target)
            r = subprocess.run(["git", "rm", "-q", str(f)], capture_output=True, text=True)
            if r.returncode:            # no versionado: borrar directamente
                f.unlink()
            print(f"    → copiado a {target} y quitado del repo")

    print("\n3) <li> 'Lista de Socios' en menús")
    total = 0
    for f in html_files():
        if not f.exists():
            continue
        txt = f.read_text(encoding="utf-8", errors="replace")
        new, n = LI_RE.subn("", txt)
        if n:
            total += n
            if not dry:
                f.write_text(new, encoding="utf-8")
    print(f"  {total} elemento(s) {'se quitarían' if dry else 'quitados'}")

    print("\n4) Menciones o enlaces restantes (revisar a mano)")
    removed = {p.as_posix() for p in pages}
    left = 0
    for f in html_files():
        if not f.exists():
            continue
        txt = f.read_text(encoding="utf-8", errors="replace")
        if dry:
            txt = LI_RE.sub("", txt)
        for n, ln in enumerate(txt.splitlines(), 1):
            hit = MENTION_RE.search(ln) or any(
                re.search(r'href="[^"]*' + re.escape(Path(r).name) + '"', ln)
                for r in removed)
            if hit:
                left += 1
                if left <= 40:
                    print(f"  {f}:{n}: {ln.strip()[:150]}")
    print(f"  total: {left}" + ("  (solo se muestran 40)" if left > 40 else ""))

    if dry:
        print("\n--dry-run: nada escrito.")


if __name__ == "__main__":
    main()
