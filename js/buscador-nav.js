/*
 * buscador-nav.js — buscador de noticias en el menú superior (todas las páginas).
 *
 * Agrega una lupa al menú. Al abrirla muestra un campo de búsqueda con los
 * primeros resultados del índice Pagefind (/pagefind/, generado en deploy.sh).
 * Enter o "Ver todos los resultados" lleva a /noticias.html?q=…
 * En noticias.html la lupa enfoca el buscador de la página.
 *
 * Se incluye en cada página con:
 *   <script src="/js/buscador-nav.js" defer></script>
 */
(function () {
  var nav = document.querySelector('nav.nav');
  var inner = nav && nav.querySelector('.nav-inner');
  if (!inner || inner.querySelector('.nav-buscar')) return;

  var MAX = 6;
  var css = [
    '.nav-buscar{display:flex;align-items:center;justify-content:center;width:36px;height:36px;margin-left:.6rem;flex-shrink:0;background:none;border:none;border-radius:4px;color:rgba(255,255,255,.78);cursor:pointer;transition:background .15s,color .15s}',
    '.nav-buscar:hover,.nav-buscar[aria-expanded="true"]{color:#fff;background:rgba(255,255,255,.1)}',
    '.nav-buscar:focus-visible,.bn-lista a:focus-visible,.bn-todos:focus-visible{outline:2px solid var(--teal,#0d9fa0);outline-offset:2px}',
    '.nav-buscar svg{width:18px;height:18px}',
    'nav.nav-movil .nav-buscar{margin-left:auto}',
    'nav.nav-movil .nav-burger{margin-left:.35rem}',
    '.bn-panel{position:absolute;top:100%;right:max(1rem,calc((100% - var(--max-w,1100px))/2 + 1rem));width:min(440px,calc(100% - 2rem));background:var(--navymd,#162e58);border-top:2px solid var(--teal,#0d9fa0);box-shadow:0 12px 32px rgba(0,0,0,.35);padding:1rem;font-family:Inter,system-ui,sans-serif;z-index:300}',
    'nav.nav-movil .bn-panel{left:0;right:0;width:auto}',
    '.bn-panel[hidden]{display:none}',
    '.bn-campo{display:flex;align-items:center;gap:.55rem;background:#fff;border-radius:6px;padding:0 .8rem}',
    '.bn-campo svg{width:16px;height:16px;color:#627286;flex-shrink:0}',
    '.bn-campo input{flex:1;min-width:0;border:none;outline:none;background:none;font:inherit;font-size:.95rem;color:#2d3748;padding:.7rem 0}',
    '.bn-campo:focus-within{box-shadow:0 0 0 2px var(--teal,#0d9fa0)}',
    '.bn-msg{font-size:.8rem;color:rgba(255,255,255,.55);margin:.8rem .1rem 0}',
    '.bn-lista{list-style:none;margin:.5rem 0 0;padding:0;max-height:min(60vh,420px);overflow-y:auto}',
    '.bn-lista a{display:block;padding:.6rem .5rem;border-radius:4px;color:rgba(255,255,255,.9);text-decoration:none}',
    '.bn-lista a:hover,.bn-lista a:focus{background:rgba(255,255,255,.08);outline:none}',
    '.bn-titulo{display:block;font-size:.88rem;font-weight:500;line-height:1.35}',
    '.bn-fecha{display:block;font-size:.74rem;color:rgba(255,255,255,.5);margin-top:.15rem}',
    '.bn-extracto{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;font-size:.78rem;line-height:1.45;color:rgba(255,255,255,.6);margin-top:.25rem}',
    '.bn-extracto mark{background:rgba(13,159,160,.35);color:#fff;border-radius:2px;padding:0 .1em}',
    '.bn-todos{display:block;margin-top:.6rem;padding:.55rem .5rem 0;border-top:1px solid rgba(255,255,255,.1);font-size:.82rem;font-weight:600;color:var(--teal,#0d9fa0);text-decoration:none}',
    '.bn-todos:hover{color:#fff}',
    '.bn-todos[hidden]{display:none}',
    '.bn-panel input:focus-visible{outline:none}',
    // El menú completo + la lupa no caben bajo ~1040px (antes ya se desbordaba
    // entre ~780 y ~920px): desde ahí se usa el menú ☰, igual que en móvil.
    '@media(max-width:1040px){' +
      '.nav-links{display:none;position:absolute;top:60px;left:0;right:0;background:var(--navy,#0c1e3f);flex-direction:column;padding:1rem;gap:.25rem;border-top:1px solid rgba(255,255,255,.1)}' +
      '.nav-links.open{display:flex}' +
      '.nav-has-drop .nav-drop{position:static;box-shadow:none;border:none;background:transparent;padding-left:1rem}' +
      '.nav-burger{display:block}' +
    '}'
  ].join('\n');
  var style = document.createElement('style');
  style.textContent = css;
  document.head.appendChild(style);

  var LUPA = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.6-3.6"/></svg>';

  // Botón en el menú (antes del ☰, visible en escritorio y móvil)
  var btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'nav-buscar';
  btn.setAttribute('aria-label', 'Buscar noticias');
  btn.setAttribute('aria-expanded', 'false');
  btn.setAttribute('aria-controls', 'bn-panel');
  btn.innerHTML = LUPA;
  var burger = inner.querySelector('.nav-burger');
  inner.insertBefore(btn, burger || null);

  // En noticias.html ya hay buscador en la página: la lupa lo enfoca
  var enPagina = document.getElementById('buscador');
  if (enPagina) {
    btn.addEventListener('click', function () {
      enPagina.scrollIntoView({ behavior: 'smooth', block: 'center' });
      var i = enPagina.querySelector('input');
      if (i) i.focus({ preventScroll: true });
    });
    return;
  }

  // Panel desplegable
  var panel = document.createElement('div');
  panel.className = 'bn-panel';
  panel.id = 'bn-panel';
  panel.hidden = true;
  panel.setAttribute('role', 'search');
  panel.innerHTML =
    '<form class="bn-campo" action="/noticias.html" method="get">' + LUPA +
    '<input type="search" name="q" autocomplete="off" aria-label="Buscar noticias" placeholder="Buscar noticias (2013–2026)"></form>' +
    '<p class="bn-msg" aria-live="polite"></p><ul class="bn-lista"></ul><a class="bn-todos" hidden></a>';
  nav.appendChild(panel);

  var form = panel.querySelector('form');
  var input = panel.querySelector('input');
  var msg = panel.querySelector('.bn-msg');
  var lista = panel.querySelector('.bn-lista');
  var todos = panel.querySelector('.bn-todos');
  var pagefind = null;

  function cargar() {
    if (!pagefind) {
      pagefind = import('/pagefind/pagefind.js').then(function (pf) {
        return pf.options({ excerptLength: 18 }).then(function () { return pf; });
      });
    }
    return pagefind;
  }

  function esMovil() {
    return !!burger && getComputedStyle(burger).display !== 'none';
  }
  function ajustar() { nav.classList.toggle('nav-movil', esMovil()); }
  ajustar();
  window.addEventListener('resize', ajustar);

  function abrir() {
    panel.hidden = false;
    btn.setAttribute('aria-expanded', 'true');
    // Cerrar el menú móvil si estaba abierto
    var links = document.getElementById('nav-links');
    if (links && links.classList.contains('open')) {
      links.classList.remove('open');
      if (burger) { burger.textContent = '☰'; burger.setAttribute('aria-expanded', 'false'); }
    }
    input.focus();
    cargar().catch(function () {});
  }
  function cerrar(devolverFoco) {
    panel.hidden = true;
    btn.setAttribute('aria-expanded', 'false');
    if (devolverFoco) btn.focus();
  }

  btn.addEventListener('click', function () { panel.hidden ? abrir() : cerrar(false); });
  if (burger) burger.addEventListener('click', function () { cerrar(false); });
  document.addEventListener('click', function (e) {
    if (!panel.hidden && !panel.contains(e.target) && !btn.contains(e.target)) cerrar(false);
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && !panel.hidden) cerrar(true);
  });

  function enlaceTodos(q) {
    return '/noticias.html?q=' + encodeURIComponent(q);
  }

  var ultima = 0;
  input.addEventListener('input', function () {
    var q = input.value.trim();
    var n = ++ultima;
    if (!q) { lista.innerHTML = ''; msg.textContent = ''; todos.hidden = true; return; }
    cargar().then(function (pf) {
      return pf.debouncedSearch(q, {}, 250).then(function (res) {
        if (res === null || n !== ultima) return; // búsqueda reemplazada por otra
        var total = res.results.length;
        return Promise.all(res.results.slice(0, MAX).map(function (r) { return r.data(); }))
          .then(function (datos) {
            if (n !== ultima) return;
            lista.innerHTML = '';
            todos.hidden = total <= MAX;
            todos.href = enlaceTodos(q);
            todos.textContent = 'Ver los ' + total + ' resultados';
            if (!total) {
              msg.textContent = 'Sin resultados para “' + q + '”.';
              return;
            }
            msg.textContent = total === 1 ? '1 resultado' : total + ' resultados';
            datos.forEach(function (d) {
              var li = document.createElement('li');
              var a = document.createElement('a');
              a.href = d.url;
              var t = document.createElement('span');
              t.className = 'bn-titulo';
              t.textContent = (d.meta && d.meta.title) || d.url;
              a.appendChild(t);
              if (d.meta && d.meta.fecha) {
                var f = document.createElement('span');
                f.className = 'bn-fecha';
                f.textContent = d.meta.fecha;
                a.appendChild(f);
              }
              if (d.excerpt) {
                var x = document.createElement('span');
                x.className = 'bn-extracto';
                x.innerHTML = d.excerpt; // Pagefind escapa el texto; solo agrega <mark>
                a.appendChild(x);
              }
              li.appendChild(a);
              lista.appendChild(li);
            });
          });
      });
    }).catch(function () {
      msg.textContent = 'El buscador no está disponible. Presiona Enter para buscar en Noticias.';
    });
  });

  // Enter: página completa de resultados
  form.addEventListener('submit', function (e) {
    e.preventDefault();
    var q = input.value.trim();
    if (q) location.href = enlaceTodos(q);
  });

  // Flecha abajo desde el campo: pasar a los resultados
  input.addEventListener('keydown', function (e) {
    if (e.key === 'ArrowDown') {
      var first = lista.querySelector('a');
      if (first) { e.preventDefault(); e.stopPropagation(); first.focus(); }
    }
  });
  panel.addEventListener('keydown', function (e) {
    var links = Array.prototype.slice.call(panel.querySelectorAll('.bn-lista a, .bn-todos:not([hidden])'));
    var i = links.indexOf(document.activeElement);
    if (i < 0) return;
    if (e.key === 'ArrowDown' && i < links.length - 1) { e.preventDefault(); links[i + 1].focus(); }
    if (e.key === 'ArrowUp') { e.preventDefault(); (i === 0 ? input : links[i - 1]).focus(); }
  });
})();
