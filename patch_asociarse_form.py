#!/usr/bin/env python3
"""Reemplaza el formulario antiguo (FormSubmit, con archivos adjuntos) de
asociarse.html por un botón que lleva a formulario.html.

- Respaldo: migration_report/asociarse.html.bak-form
- Avisa si algún script de la página usa ids del formulario eliminado.
- Muestra la sección resultante para revisión e indica restos de texto
  sobre adjuntos.
Uso (raíz del repo):  python3 patch_asociarse_form.py [--dry-run]
"""
import re
import shutil
import sys
from pathlib import Path

PAGE = Path("asociarse.html")
BACKUP = Path("migration_report/asociarse.html.bak-form")
EMAIL = "sociedadchilenaneurociencia@gmail.com"

CSS = """
/* CTA hacia formulario.html (patch_asociarse_form.py) */
.inc-cta{margin:1.25rem 0 .5rem}
.inc-cta p{margin:0 0 1rem;line-height:1.6}
.inc-cta p a{color:inherit;text-decoration:underline}
.inc-cta-btn{display:inline-block;padding:.75rem 1.4rem;border-radius:6px;
  background:#14a39b;color:#fff;font-weight:600;text-decoration:none}
.inc-cta-btn:hover,.inc-cta-btn:focus{background:#0f857e;color:#fff}
"""


def cta(indent):
    lines = [
        '<div class="inc-cta">',
        '  <p>Completa la postulación en línea. Después de enviarla, envía tus '
        'documentos en PDF (CV, carta de intención y, si eres estudiante, '
        'certificado de alumno regular) a '
        f'<a href="mailto:{EMAIL}">{EMAIL}</a>.</p>',
        '  <a class="inc-cta-btn" href="formulario.html">'
        'Ir al formulario de postulación &rarr;</a>',
        '</div>',
    ]
    return "\n".join(indent + ln for ln in lines) + "\n"


def main():
    dry = "--dry-run" in sys.argv
    if not PAGE.exists():
        sys.exit("No encuentro asociarse.html — ejecuta desde la raíz del repo.")
    s = PAGE.read_text(encoding="utf-8")

    if 'class="inc-cta"' in s:
        print("asociarse.html ya está parchado. Nada que hacer.")
        return
    if s.count('<form class="inc-form"') != 1:
        sys.exit('No se aplicó nada: se esperaba exactamente 1 <form class="inc-form".')

    k = s.find('<form class="inc-form"')
    start = s.rfind("\n", 0, k) + 1                 # inicio de la línea
    indent = s[start:k]
    end = s.find("</form>", k)
    if end < 0:
        sys.exit("No se aplicó nada: no encuentro </form>.")
    end += len("</form>")
    if s[end:end + 1] == "\n":
        end += 1
    block = s[start:end]
    if "formsubmit" not in block:
        sys.exit("No se aplicó nada: el bloque no parece el formulario FormSubmit.")

    new = s[:start] + cta(indent) + s[end:]
    i = new.find("</style>")
    if i < 0:
        sys.exit("No se aplicó nada: no hay </style> para el CSS.")
    new = new[:i] + CSS + new[i:]

    # ¿Scripts que dependen del formulario eliminado?
    ids = set(re.findall(r'\bid="([^"]+)"', block)) | {"inc-form"}
    scripts = "\n".join(re.findall(r"<script\b[^>]*>(.*?)</script>", new, re.S))
    used = sorted(x for x in ids if x in scripts)
    if used:
        print("AVISO: el <script> menciona elementos eliminados:", ", ".join(used))
        print("       (revisa que use 'if(el)' o pega esas líneas para ajustarlo)")

    # Mostrar la sección resultante y restos de texto sobre adjuntos
    a = new.find('<section class="section-dark mem-section">')
    b = new.find("</section>", a) + len("</section>")
    sec = new[a:b]
    first = new.count("\n", 0, a) + 1
    print(f"\n--- sección resultante (desde línea {first}) ---")
    for n, ln in enumerate(sec.splitlines(), first):
        flag = "  <<< revisar" if re.search(r"adjunt|archivo|upload|Browse|10 ?MB",
                                              ln, re.I) and "inc-cta" not in ln and \
            "envía tus documentos" not in ln else ""
        print(f"{n:4d}: {ln}{flag}")
    print("--- fin ---\n")

    removed = block.count("\n")
    if dry:
        print(f"--dry-run: se eliminarían {removed} líneas del formulario; nada escrito.")
        return
    BACKUP.parent.mkdir(exist_ok=True)
    shutil.copy2(PAGE, BACKUP)
    PAGE.write_text(new, encoding="utf-8")
    print(f"OK: formulario antiguo eliminado ({removed} líneas). Respaldo: {BACKUP}")


if __name__ == "__main__":
    main()
