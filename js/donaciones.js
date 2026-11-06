/*
 * donaciones.js — ventana con los datos para donar (botón "Donaciones" del menú).
 *
 * Funciona en todas las páginas: busca los enlaces del menú cuyo texto es
 * "Donaciones" y al hacer clic abre la ventana. También se abre si la
 * dirección termina en #donaciones (útil para compartir el enlace).
 * Para cambiar los datos de la cuenta o el texto, editar solo este archivo.
 *
 * Se incluye en cada página con:
 *   <script src="/js/donaciones.js" defer></script>
 */
(function () {
  var EMAIL = 'sociedadchilenaneurociencia@gmail.com';

  var enlaces = Array.prototype.filter.call(
    document.querySelectorAll('nav a'),
    function (a) { return a.textContent.trim() === 'Donaciones'; }
  );
  if (!enlaces.length || document.getElementById('modal-donaciones')) return;

  var css = [
    '.don-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:1000;align-items:center;justify-content:center;padding:1rem}',
    '.don-overlay.open{display:flex}',
    '.don-box{background:#fff;color:#2d3748;border-radius:8px;max-width:580px;width:100%;padding:2.5rem 2rem 2rem;position:relative;box-shadow:0 20px 60px rgba(0,0,0,.4);max-height:90vh;overflow-y:auto;font-family:Inter,system-ui,sans-serif}',
    '.don-close{position:absolute;top:.75rem;right:.75rem;background:var(--navy,#0c1e3f);color:#fff;border:none;border-radius:4px;width:28px;height:28px;font-size:.9rem;font-weight:700;cursor:pointer;line-height:1;display:flex;align-items:center;justify-content:center}',
    '.don-close:hover{background:var(--teal,#0d9fa0)}',
    '.don-close:focus-visible,.don-box a:focus-visible{outline:2px solid var(--teal,#0d9fa0);outline-offset:2px}',
    '.don-title{font-family:var(--f-display,var(--f-serif,Georgia,serif));font-size:clamp(1.3rem,3vw,1.75rem);font-weight:500;color:var(--navy,#0c1e3f);text-align:center;line-height:1.25;margin:0 0 1.25rem}',
    '.don-body{font-size:.9rem;line-height:1.75;color:#4a5568;text-align:center;margin:0}',
    '.don-divider{border:none;border-top:1px solid #e2e8f0;margin:1.5rem 0}',
    '.don-account{text-align:center;font-size:.92rem;line-height:2;color:#2d3748}',
    '.don-account strong{display:block;font-size:.72rem;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--teal,#0d9fa0);margin-bottom:.5rem}',
    '.don-box a{color:var(--teal,#0d9fa0);text-decoration:none;overflow-wrap:anywhere}',
    '.don-box a:hover{text-decoration:underline}',
    '.don-note{margin:1.25rem 0 0;font-size:.85rem;color:#718096;text-align:center;line-height:1.75}',
    '.don-thanks{margin:1.25rem 0 0;font-size:.9rem;font-weight:600;color:var(--navy,#0c1e3f);text-align:center}'
  ].join('\n');
  var style = document.createElement('style');
  style.textContent = css;
  document.head.appendChild(style);

  var mail = '<a href="mailto:' + EMAIL + '">' + EMAIL + '</a>';
  var overlay = document.createElement('div');
  overlay.className = 'don-overlay';
  overlay.id = 'modal-donaciones';
  overlay.innerHTML =
    '<div class="don-box" role="dialog" aria-modal="true" aria-labelledby="don-titulo">' +
      '<button type="button" class="don-close" aria-label="Cerrar">✕</button>' +
      '<h2 class="don-title" id="don-titulo">Apoya a la Sociedad<br>Chilena de Neurociencia</h2>' +
      '<p class="don-body">La SCN es una comunidad que crece gracias al compromiso de quienes creen en la ciencia como bien público. Si deseas contribuir a nuestros proyectos, este año tus donaciones se destinarán a financiar actividades de extensión en el marco del Año del Cerebro en todas las regiones de Chile.</p>' +
      '<hr class="don-divider">' +
      '<div class="don-account">' +
        '<strong>Para donar, haz una transferencia a</strong>' +
        'Nombre: Sociedad Chilena de Neurociencia<br>' +
        'RUT: 65.020.367-4<br>' +
        'Banco: Santander<br>' +
        'Cuenta corriente Nº: 64981706<br>' +
        'Email: ' + mail +
      '</div>' +
      '<p class="don-note">Una vez realizada la transferencia, envía el comprobante a ' + mail +
        ' indicando tu nombre y apellido para recibir el certificado de donación.</p>' +
      '<p class="don-thanks">¡Gracias por ser parte de este esfuerzo!</p>' +
    '</div>';
  document.body.appendChild(overlay);

  var cerrarBtn = overlay.querySelector('.don-close');
  var origen = null;

  function abrir(e) {
    if (e) e.preventDefault();
    origen = document.activeElement;
    // Cerrar el menú móvil si estaba abierto
    var links = document.getElementById('nav-links');
    var burger = document.getElementById('burger');
    if (links && links.classList.contains('open')) {
      links.classList.remove('open');
      if (burger) burger.textContent = '☰';
    }
    overlay.classList.add('open');
    document.body.style.overflow = 'hidden';
    cerrarBtn.focus();
  }
  function cerrar() {
    if (!overlay.classList.contains('open')) return;
    overlay.classList.remove('open');
    document.body.style.overflow = '';
    if (location.hash === '#donaciones') {
      history.replaceState(null, '', location.pathname + location.search);
    }
    if (origen && origen.focus) origen.focus();
  }

  enlaces.forEach(function (a) {
    a.setAttribute('href', '#donaciones');
    a.setAttribute('aria-haspopup', 'dialog');
    a.addEventListener('click', abrir);
  });
  cerrarBtn.addEventListener('click', cerrar);
  overlay.addEventListener('click', function (e) { if (e.target === overlay) cerrar(); });
  document.addEventListener('keydown', function (e) {
    if (!overlay.classList.contains('open')) return;
    if (e.key === 'Escape') cerrar();
    // Mantener el foco dentro de la ventana
    if (e.key === 'Tab') {
      var f = overlay.querySelectorAll('button, a[href]');
      var primero = f[0], ultimo = f[f.length - 1];
      if (e.shiftKey && document.activeElement === primero) { e.preventDefault(); ultimo.focus(); }
      else if (!e.shiftKey && document.activeElement === ultimo) { e.preventDefault(); primero.focus(); }
    }
  });
  if (location.hash === '#donaciones') abrir();
})();
