#!/usr/bin/env python3
"""Busca los documentos perdidos dentro del respaldo cPanel de 4ID (.tar.gz).

Paso 1 (sin --extract): recorre el respaldo SIN descomprimirlo a disco y escribe
  inventario.txt  – carpetas raíz, carpetas wp-content/uploads por año,
                    archivos comprimidos y volcados SQL dentro del respaldo
  coincidencias.csv – cada documento perdido hallado (ruta exacta o mismo nombre)
Paso 2 (--extract): extrae solo las coincidencias a <respaldo>/extraidos/.

Uso (desde la raíz del repo):
  python3 buscar_en_respaldo.py ~/PATO/USACH/scn_privado/respaldo_4id/backup-*.tar.gz
  python3 buscar_en_respaldo.py <respaldo> --extract
"""
import argparse
import csv
import re
import sys
import tarfile
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlparse

LIST = Path("migration_report/documentos_perdidos.txt")
ARCH = re.compile(r"\.(zip|tar|tgz|gz|bz2|xz|7z|rar|wpress|jpa|daf)$", re.I)
SQL = re.compile(r"\.sql(\.gz)?$", re.I)
UP = re.compile(r"wp-content/uploads/(\d{4})/(\d{2})/([^/]+)$")


def wanted():
    """basename (minúsculas) → lista de (url, 'AAAA/MM/archivo' o None)."""
    w = defaultdict(list)
    for ln in LIST.read_text(encoding="utf-8").splitlines():
        if not ln.startswith("  - "):
            continue
        u = ln[4:].strip()
        path = unquote(urlparse(u).path)
        m = UP.search(path)
        rel = f"{m.group(1)}/{m.group(2)}/{m.group(3)}" if m else None
        w[PurePosixPath(path).name.lower()].append((u, rel))
    return w


def strip_suffix(name):
    """foo-1.pdf → foo.pdf (sufijo de duplicado de WordPress)."""
    st, dot, ext = name.rpartition(".")
    return re.sub(r"-\d{1,2}$", "", st) + dot + ext if dot else name


def human(n):
    for u in ("B", "kB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {u}"
        n /= 1024
    return f"{n:.1f} TB"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("backup")
    ap.add_argument("--extract", action="store_true")
    a = ap.parse_args()
    bk = Path(a.backup).expanduser()
    if not bk.exists():
        sys.exit(f"No existe {bk}")
    if not LIST.exists():
        sys.exit(f"No encuentro {LIST} — ejecuta desde la raíz del repo.")
    out = bk.parent
    W = wanted()
    print(f"{sum(len(v) for v in W.values())} documentos buscados · leyendo {bk.name} "
          f"({human(bk.stat().st_size)}), tarda unos minutos…")

    roots, up_years, archives, sqls = Counter(), Counter(), [], []
    hits, n = [], 0
    with tarfile.open(bk, "r|gz") as tf:
        for m in tf:
            n += 1
            if n % 50000 == 0:
                print(f"  {n} entradas…")
            if not m.isfile():
                continue
            p = m.name.lstrip("./")
            parts = p.split("/")
            roots["/".join(parts[:2]) if len(parts) > 2 else parts[0]] += 1
            mu = UP.search(p)
            if mu:
                base_dir = p[: p.index("wp-content/uploads/")]
                up_years[(base_dir or "(raíz)", mu.group(1))] += 1
            if ARCH.search(p):
                archives.append((p, m.size))
            elif SQL.search(p):
                sqls.append((p, m.size))
            name = parts[-1].lower()
            for key, kind in ((name, "nombre"), (strip_suffix(name), "nombre sin sufijo -N")):
                for url, rel in W.get(key, []):
                    exact = rel is not None and p.lower().endswith(
                        "wp-content/uploads/" + rel.lower())
                    hits.append({"url": url, "ruta_en_respaldo": p, "tamano": m.size,
                                 "tipo": "RUTA EXACTA" if exact else kind})
                if W.get(key):
                    break

    # inventario
    L = [f"Respaldo: {bk.name}", f"Entradas: {n}", "", "Carpetas principales (archivos):"]
    L += [f"  {c:7d}  {r}" for r, c in roots.most_common(40)]
    L += ["", "wp-content/uploads por instalación y año (archivos):"]
    for (d, y), c in sorted(up_years.items()):
        L.append(f"  {d or '(raíz)':60s} {y}: {c}")
    L += ["", f"Archivos comprimidos dentro del respaldo ({len(archives)}):"]
    L += [f"  {human(s):>9}  {p}" for p, s in sorted(archives, key=lambda x: -x[1])[:60]]
    L += ["", f"Volcados SQL ({len(sqls)}):"]
    L += [f"  {human(s):>9}  {p}" for p, s in sqls]
    (out / "inventario.txt").write_text("\n".join(L) + "\n", encoding="utf-8")

    with open(out / "coincidencias.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["url", "tipo", "ruta_en_respaldo", "tamano"])
        w.writeheader()
        w.writerows(hits)

    found = {h["url"] for h in hits}
    exact = {h["url"] for h in hits if h["tipo"] == "RUTA EXACTA"}
    total = sum(len(v) for v in W.values())
    print("\n" + "\n".join(L[:3]))
    print("wp-content/uploads por instalación y año:")
    for (d, y), c in sorted(up_years.items()):
        print(f"  {d or '(raíz)':50s} {y}: {c}")
    print(f"Comprimidos dentro: {len(archives)} · volcados SQL: {len(sqls)}")
    print(f"\nDocumentos perdidos hallados: {len(found)}/{total}  "
          f"(ruta exacta: {len(exact)}, solo mismo nombre: {len(found - exact)})")
    print(f"Informes: {out}/inventario.txt, {out}/coincidencias.csv")

    if a.extract and hits:
        dest = out / "extraidos"
        targets = {h["ruta_en_respaldo"] for h in hits}
        print(f"\nExtrayendo {len(targets)} archivos a {dest} …")
        with tarfile.open(bk, "r|gz") as tf:
            for m in tf:
                p = m.name.lstrip("./")
                if p in targets and m.isfile():
                    m.name = p
                    tf.extract(m, dest, filter="data") if hasattr(tarfile, "data_filter") \
                        else tf.extract(m, dest)
                    targets.discard(p)
                    if not targets:
                        break
        print("OK" + (f" (faltaron {len(targets)})" if targets else ""))
    elif a.extract:
        print("Nada que extraer.")


if __name__ == "__main__":
    main()
