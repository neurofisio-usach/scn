#!/usr/bin/env python3
"""Conecta el formulario de Contacto de index.html con Formspree.

- Reemplaza el <form> de #contacto (agrega name=, action, honeypot, _subject,
  zona de estado accesible).
- Reemplaza handleForm()/alert() por un envío fetch() con mensajes en español.
- Agrega un pequeño bloque CSS para los mensajes de estado.
- Respaldo en migration_report/index.html.bak-contacto. Idempotente.

Uso (desde la raíz del repo):  python3 patch_contacto_form.py [--dry-run]
"""
import shutil
import sys
from pathlib import Path

ENDPOINT = "https://formspree.io/f/xoeedyze"
SUBJECT = "Mensaje de contacto — sitio web SCN"
CONTACT_EMAIL = "sociedadchilenaneurociencia@gmail.com"

INDEX = Path("index.html")
BACKUP = Path("migration_report/index.html.bak-contacto")

OLD_FORM = """    <form class="contact-form" onsubmit="handleForm(event)">
      <div class="form-row">
        <input type="text" placeholder="Tu nombre (requerido)" required>
        <input type="email" placeholder="Tu correo (requerido)" required>
      </div>
      <input type="text" placeholder="Asunto">
      <textarea placeholder="Tu mensaje" rows="6"></textarea>
      <div><button type="submit" class="btn btn-primary">Enviar mensaje</button></div>
    </form>"""

NEW_FORM = f"""    <form class="contact-form" id="contact-form" action="{ENDPOINT}" method="POST">
      <input type="hidden" name="_subject" value="{SUBJECT}">
      <input type="text" name="_gotcha" tabindex="-1" autocomplete="off" aria-hidden="true" style="display:none">
      <div class="form-row">
        <input type="text" name="nombre" placeholder="Tu nombre (requerido)" aria-label="Tu nombre" autocomplete="name" required>
        <input type="email" name="email" placeholder="Tu correo (requerido)" aria-label="Tu correo" autocomplete="email" required>
      </div>
      <input type="text" name="asunto" placeholder="Asunto" aria-label="Asunto">
      <textarea name="mensaje" placeholder="Tu mensaje (requerido)" aria-label="Tu mensaje" rows="6" required></textarea>
      <div><button type="submit" class="btn btn-primary">Enviar mensaje</button></div>
      <p class="form-status" id="contact-status" role="status" aria-live="polite"></p>
    </form>"""

OLD_JS = """function handleForm(e){
  e.preventDefault();
  alert('Mensaje enviado. Esta funcionalidad se activará en la versión final del sitio.');
}"""

NEW_JS = f"""(function(){{
  const f=document.getElementById('contact-form');
  if(!f) return;
  const st=document.getElementById('contact-status');
  const btn=f.querySelector('button[type="submit"]');
  const BASE='{SUBJECT}';
  f.addEventListener('submit',async function(e){{
    e.preventDefault();
    const a=f.elements['asunto'].value.trim();
    f.elements['_subject'].value=a?BASE+': '+a:BASE;
    const label=btn.textContent;
    btn.disabled=true; btn.textContent='Enviando…';
    st.className='form-status'; st.textContent='';
    try{{
      const r=await fetch(f.action,{{method:'POST',body:new FormData(f),headers:{{'Accept':'application/json'}}}});
      if(!r.ok){{
        let msg='';
        try{{const d=await r.json(); if(d.errors) msg=d.errors.map(x=>x.message).join(' ');}}catch(_){{}}
        throw new Error(msg);
      }}
      f.reset();
      st.classList.add('ok');
      st.textContent='¡Gracias! Tu mensaje fue enviado. Te responderemos a la brevedad.';
    }}catch(err){{
      st.classList.add('err');
      st.textContent='No se pudo enviar el mensaje'+(err.message?' ('+err.message+')':'')+
        '. Inténtalo nuevamente o escríbenos a {CONTACT_EMAIL}.';
    }}finally{{
      btn.disabled=false; btn.textContent=label;
    }}
  }});
}})();"""

CSS = """
/* Contacto: mensajes de estado (patch_contacto_form.py) */
.contact-form .form-status{margin:.6rem 0 0;font-size:.95rem;min-height:1.2em}
.contact-form .form-status.ok{color:#1b6e3a}
.contact-form .form-status.err{color:#a12622}
"""


def main():
    dry = "--dry-run" in sys.argv
    if not INDEX.exists():
        sys.exit("No encuentro index.html — ejecuta desde la raíz del repo.")
    html = INDEX.read_text(encoding="utf-8")

    if 'id="contact-form"' in html:
        print("index.html ya está parchado (id=\"contact-form\" presente). Nada que hacer.")
        return

    problems = []
    for name, old in (("formulario", OLD_FORM), ("handleForm()", OLD_JS)):
        n = html.count(old)
        if n != 1:
            problems.append(f"  - bloque {name}: encontrado {n} veces (se esperaba 1)")
    if html.count("</style>") < 1:
        problems.append("  - no hay </style> donde insertar el CSS")
    if problems:
        sys.exit("No se aplicó nada:\n" + "\n".join(problems))

    new = html.replace(OLD_FORM, NEW_FORM).replace(OLD_JS, NEW_JS)
    i = new.find("</style>")  # primer bloque <style> (el CSS principal del head)
    new = new[:i] + CSS + new[i:]

    if "handleForm" in new:
        print("AVISO: aún queda una referencia a handleForm en index.html")

    if dry:
        print("--dry-run: los 3 cambios se aplicarían sin problemas; no se escribió nada.")
        return
    BACKUP.parent.mkdir(exist_ok=True)
    shutil.copy2(INDEX, BACKUP)
    INDEX.write_text(new, encoding="utf-8")
    print(f"OK: index.html parchado (respaldo: {BACKUP})")
    print(f"  formulario -> {ENDPOINT}")
    print(f"  asunto     -> '{SUBJECT}[: <asunto>]'")


if __name__ == "__main__":
    main()
