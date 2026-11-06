#!/bin/bash
# actualizar.sh — trae al repo local los cambios hechos en GitHub
#                 (por ejemplo, ediciones en la web de github.com)
# Uso:  ./actualizar.sh
#
# Si tienes cambios locales sin publicar, se guardan temporalmente,
# se baja lo nuevo de GitHub y se vuelven a aplicar encima.

set -euo pipefail

# ── Verificar repo ────────────────────────────────────────
if ! git rev-parse --show-toplevel &>/dev/null; then
  echo "❌  No estás dentro de un repositorio git."
  exit 1
fi
cd "$(git rev-parse --show-toplevel)"

if [ -d .git/rebase-merge ] || [ -d .git/rebase-apply ] || [ -f .git/MERGE_HEAD ]; then
  echo "❌  Hay una sincronización anterior sin terminar."
  echo "    Revisa con:  git status"
  exit 1
fi

# ── Consultar GitHub ──────────────────────────────────────
echo "Consultando GitHub..."
git fetch origin main --quiet

NUEVOS=$(git rev-list --count HEAD..origin/main)
if [ "$NUEVOS" -eq 0 ]; then
  echo "✓  Sin cambios nuevos en GitHub — el repo local está al día."
  exit 0
fi

echo ""
echo "Cambios nuevos en GitHub ($NUEVOS):"
echo "───────────────────────────────────────────────"
git log --format='  %h  %ad  %s' --date=format:'%Y-%m-%d %H:%M' HEAD..origin/main
echo "───────────────────────────────────────────────"
git diff --stat HEAD...origin/main | tail -n 15
echo ""

# ── Guardar cambios locales sin publicar ──────────────────
GUARDADO=0
if ! git diff --quiet || ! git diff --cached --quiet \
   || [ -n "$(git ls-files --others --exclude-standard)" ]; then
  echo "→ Tienes cambios locales sin publicar; se guardan temporalmente..."
  git stash push --include-untracked --quiet -m "actualizar.sh $(date '+%Y-%m-%d %H:%M')"
  GUARDADO=1
fi

# ── Traer lo nuevo ────────────────────────────────────────
if ! git pull --rebase --quiet origin main; then
  git rebase --abort 2>/dev/null || true
  [ "$GUARDADO" -eq 1 ] && git stash pop --quiet || true
  echo ""
  echo "❌  Tus commits locales chocan con los cambios de GitHub (mismas líneas)."
  echo "    No se modificó nada. Revisa con:  git status"
  exit 1
fi

# ── Recuperar cambios locales ─────────────────────────────
if [ "$GUARDADO" -eq 1 ]; then
  if git stash pop --quiet; then
    echo "→ Cambios locales recuperados."
  else
    echo ""
    echo "⚠️   Tus cambios locales tocan las mismas líneas que el cambio de GitHub."
    echo "    Los archivos con conflicto (marcados <<<<<<< / >>>>>>>) son:"
    git diff --name-only --diff-filter=U | sed 's/^/      /'
    echo "    Edítalos, quita las marcas y luego ejecuta:  git stash drop"
    echo "    (tu versión sigue guardada en  git stash list  hasta entonces)"
    exit 1
  fi
fi

echo ""
echo "───────────────────────────────────────────────"
echo "✓  Repo local actualizado con lo último de GitHub."
echo "───────────────────────────────────────────────"
