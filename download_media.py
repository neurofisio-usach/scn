#!/usr/bin/env python3
"""
download_media.py — descarga los PDFs de la biblioteca de medios de WordPress
que no están enlazados desde ninguna página y no fueron exportados.

Estrategia:
  1. REST API de WP (/wp/v2/media?search=…) para obtener la URL original.
  2. Si la API no responde o no encuentra el archivo, busca en wayback_index.json.
  3. Guarda en docs/ (directamente, sin subdirectorio de año).

Ejecutar desde la raíz del repo:
    python3 download_media.py
"""

import json, os, time
from pathlib import Path
from urllib.parse import unquote, quote
import requests

OLD_SITE = "https://socneurociencia.cl"
OUT_DIR  = "docs"
TIMEOUT  = 40
SLEEP    = 1.0          # segundos entre llamadas a la API
CDX_FILE = "migration_report/wayback_index.json"

# (término de búsqueda en la API, nombre de archivo esperado)
TARGETS = [
    ("formulario patrocinio SCN",
     "formulario-solicitud-de-patrocinio-SCN-2-2.pdf"),
    ("Relato Año del Cerebro 2026",
     "Relato-Ano-del-Cerebro-2026_v-11.2025(-1).pdf"),
    ("Horario XXI Reunión Anual SCN",
     "Horario-XXI-Reunion-Anual-SCN-27082025.pdf"),
    ("Postdoc PhD Neuroscience UK",
     "Postdoc-PhD-position-in-Neuroscience-UK.pdf"),
    ("Boletín Doctorado Ciencias UACh",
     "Boletin-Doct-CsMedicas_UACh.pdf"),
]


# ── helpers ───────────────────────────────────────────────────────────────────

def load_cdx():
    try:
        data = json.loads(Path(CDX_FILE).read_text("utf-8"))
        # puede ser lista de [url, timestamp, ...] o dict
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def find_in_cdx(index, filename):
    """Devuelve URL del snapshot más reciente para ese filename, o None."""
    fn_lower = filename.lower()
    hits = []
    for entry in index:
        if isinstance(entry, list) and len(entry) >= 2:
            url, ts = entry[0], entry[1]
        elif isinstance(entry, dict):
            url, ts = entry.get("url", ""), entry.get("timestamp", "")
        else:
            continue
        if fn_lower in unquote(url).lower():
            hits.append((ts, url))
    if not hits:
        return None
    ts, orig = sorted(hits, reverse=True)[0]
    return f"https://web.archive.org/web/{ts}/{orig}"


def lenient_json(text):
    """Acepta respuestas con junk HTML antes del JSON (mismo problema que la API general)."""
    for i, c in enumerate(text):
        if c in ("{", "["):
            try:
                return json.loads(text[i:])
            except ValueError:
                continue
    raise ValueError("no JSON found")


def api_search(term):
    """Llama al endpoint media de WP y devuelve lista de resultados."""
    url = (f"{OLD_SITE}/wp-json/wp/v2/media"
           f"?per_page=5&media_type=application&search={quote(term)}")
    try:
        r = requests.get(url, timeout=TIMEOUT)
        result = lenient_json(r.text)
        return result if isinstance(result, list) else []
    except Exception as e:
        print(f"  ⚠  API error: {e}")
        return []


def download_file(src_url, dest_path):
    """Descarga src_url a dest_path; devuelve True si éxito."""
    try:
        r = requests.get(src_url, timeout=TIMEOUT, stream=True)
        if r.status_code == 200 and len(r.content) > 200:
            Path(dest_path).parent.mkdir(parents=True, exist_ok=True)
            Path(dest_path).write_bytes(r.content)
            return True
        print(f"  ⚠  HTTP {r.status_code}")
        return False
    except Exception as e:
        print(f"  ⚠  {e}")
        return False


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    cdx = load_cdx()
    if cdx:
        print(f"CDX index cargado: {len(cdx)} entradas\n")
    else:
        print("⚠  wayback_index.json no disponible — solo se usará la API\n")

    ok = fail = 0

    for search_term, filename in TARGETS:
        dest = os.path.join(OUT_DIR, filename)
        if Path(dest).exists():
            print(f"⏭  ya existe: {dest}")
            ok += 1
            continue

        print(f"→ {filename}")
        src_url = None

        # 1. WP REST API
        time.sleep(SLEEP)
        results = api_search(search_term)
        for item in results:
            if isinstance(item, dict) and item.get("source_url"):
                src_url = item["source_url"]
                print(f"  API → {src_url}")
                break

        # 2. CDX / archive.org
        if not src_url:
            src_url = find_in_cdx(cdx, filename)
            if src_url:
                print(f"  archive.org → {src_url}")

        # 3. Descargar
        if src_url:
            if download_file(src_url, dest):
                print(f"  ✔  {dest}")
                ok += 1
            else:
                print(f"  ✘  descarga fallida")
                fail += 1
        else:
            print(f"  ✘  no encontrado en API ni en archive.org")
            fail += 1

    print(f"\n{'─'*60}")
    print(f"  {ok} descargado(s)  ·  {fail} no disponible(s)")
    if fail:
        print("  Los no disponibles deberán buscarse manualmente"
              " (WordPress admin → Biblioteca de medios).")


if __name__ == "__main__":
    main()
