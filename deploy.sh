#!/bin/bash
# deploy.sh — detecta cambios, hace commit y sube al repo remoto
# Uso:  ./deploy.sh                  (pide mensaje interactivo)
#       ./deploy.sh "tu mensaje"     (mensaje directo)

set -euo pipefail

# ── Verificar repo ────────────────────────────────────────
if ! git rev-parse --show-toplevel &>/dev/null; then
  echo "❌  No estás dentro de un repositorio git."
  exit 1
fi

cd "$(git rev-parse --show-toplevel)"

# ── Revisar si hay cambios ────────────────────────────────
if git diff --quiet && git diff --cached --quiet \
   && [ -z "$(git ls-files --others --exclude-standard)" ]; then
  echo "✓  Sin cambios — el repositorio está al día."
  exit 0
fi

# ── Mostrar cambios ───────────────────────────────────────
echo ""
echo "Cambios detectados:"
echo "───────────────────────────────────────────────"
git status --short
echo "───────────────────────────────────────────────"
echo ""

# ── Mensaje de commit ─────────────────────────────────────
if [ -n "${1:-}" ]; then
  MSG="$1"
else
  read -rp "Mensaje de commit [Enter = fecha/hora automática]: " MSG
  [ -z "$MSG" ] && MSG="Actualización $(date '+%Y-%m-%d %H:%M')"
fi

# ── Stage + commit ────────────────────────────────────────
git add -A
git commit -m "$MSG"

# ── Sincronizar con remoto (rebase, con stash de respaldo) ─
echo ""
echo "Sincronizando con repositorio remoto..."
if ! git pull --rebase origin main 2>&1; then
  echo "→ Detectado conflicto — guardando cambios temporalmente..."
  git stash
  git pull --rebase origin main
  git stash pop
fi

# ── Push ──────────────────────────────────────────────────
echo "Subiendo cambios..."
git push origin main

echo ""
echo "───────────────────────────────────────────────"
echo "✓  Publicado en: https://neurofisio-usach.cl/scn/"
echo "───────────────────────────────────────────────"
