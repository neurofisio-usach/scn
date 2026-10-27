#!/usr/bin/env python3
"""
patch_archivo_css.py — añade estilos para .img-reemplazo-logo, .nota-archivo,
.lista-archivo y .btn-archivo a todos los archivos HTML creados por
export_wp_archive.py (listados en export_manifest.json).

Idempotente: omite archivos que ya tienen el parche.

Ejecutar desde la raíz del repo:
    python3 patch_archivo_css.py
"""

import json
from pathlib import Path

MANIFEST     = "migration_report/export_manifest.json"
PATCH_MARKER = "/* archivo-css-patch */"

CSS = """\
<style id="archivo-css">/* archivo-css-patch */
/* img-reemplazo-logo — logo SCN usado como imagen de reemplazo */
img.img-reemplazo-logo{max-width:160px;height:auto;opacity:.28;display:block;
  margin:1.25rem auto;filter:grayscale(1)}
/* nota-archivo — pie de página con enlace al original */
.nota-archivo{margin-top:2.5rem;padding:.65rem 1rem;background:#f4f7fb;
  border-left:3px solid #0d9fa0;border-radius:0 4px 4px 0;
  font-size:.78rem;color:#627286;line-height:1.6}
.nota-archivo a{color:#0d9fa0;text-decoration:underline;text-underline-offset:2px}
/* lista-archivo — listado de noticias por año (noticias/archivo.html) */
.lista-archivo{list-style:none;margin:.25rem 0 1rem;padding:0}
.lista-archivo li{display:flex;gap:.75rem;align-items:baseline;
  padding:.38rem 0;border-bottom:1px solid #e2e8f0;
  font-size:.88rem;line-height:1.45}
.lista-archivo li:last-child{border-bottom:none}
.lista-archivo time{color:#627286;font-size:.76rem;white-space:nowrap;flex-shrink:0}
.lista-archivo a{color:#0c1e3f;font-weight:500;text-decoration:none}
.lista-archivo a:hover{color:#0d9fa0;text-decoration:underline}
/* btn-archivo — botón teal de WPBakery vc_btn (el resto es inline) */
a.btn-archivo:hover{opacity:.82}
</style>"""


def main():
    try:
        manifest = json.loads(Path(MANIFEST).read_text("utf-8"))
    except (OSError, ValueError) as e:
        print(f"✘  no se pudo leer {MANIFEST}: {e}")
        return

    # el manifest es {key: {"new_file": "noticias/xxx.html", ...}}
    # más noticias/archivo.html que el script escribe aparte
    html_files = set()
    for v in manifest.values():
        if isinstance(v, dict) and v.get("new_file", "").endswith(".html"):
            html_files.add(v["new_file"])
    # incluir el índice del archivo si existe
    html_files.add("noticias/archivo.html")

    patched = skipped = missing = 0

    for path_str in sorted(html_files):
        p = Path(path_str)
        if not p.exists():
            missing += 1
            continue
        text = p.read_text("utf-8")
        if PATCH_MARKER in text:
            skipped += 1
            continue
        new_text = text.replace("</head>", CSS + "\n</head>", 1)
        if new_text == text:
            print(f"⚠  sin </head>: {path_str}")
            continue
        p.write_text(new_text, "utf-8")
        patched += 1

    print(f"✔  {patched} archivos parcheados"
          f"  ·  {skipped} ya tenían el parche"
          f"  ·  {missing} no encontrados")


if __name__ == "__main__":
    main()
