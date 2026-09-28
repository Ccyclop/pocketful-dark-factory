#!/usr/bin/env bash
# Factory heartbeat: is anyone actually doing work right now?
# Usage: ./factory/status.sh [minutes]    (activity window, default 15)
set -uo pipefail
WIN="${1:-15}"
SEATS_DIR="${SEATS_DIR:-$HOME/Developer/hackathon/seats}"
ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || { echo "Run inside the repository."; exit 1; }

echo "== $(date '+%a %d %b %H:%M')   activity window: last ${WIN} min"
echo; echo "== Latest commits on origin/main (author = seat)"
git -C "$ROOT" fetch -q origin
git -C "$ROOT" log origin/main -12 --date=format:'%d %H:%M' --format='  %h  %ad  %<(12,trunc)%an  %s'

echo; echo "== Files changed in the last ${WIN} min, per seat clone"
for seat in planner implementer verifier adversary integrator; do
  d="$SEATS_DIR/$seat"; [ -d "$d" ] || continue
  files=$(find "$d" -path "$d/.git" -prune -o -path '*/node_modules' -prune -o -path '*/.venv' -prune -o -type f -mmin "-$WIN" -print 2>/dev/null)
  n=$(printf '%s' "$files" | grep -c . || true)
  printf '  %-12s %s file(s)\n' "$seat" "$n"
  printf '%s\n' "$files" | grep . | head -3 | sed "s|$d/|      |"
done

echo; echo "== Containers running now"
docker ps --format '  {{.Names}}\t{{.Image}}\t{{.Status}}' 2>/dev/null || echo "  docker not reachable"
echo; echo "Also look at: Featherless > Subscription (latest Kimi / GLM request) and the room's last tagged message."
