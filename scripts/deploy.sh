#!/usr/bin/env bash
# Executar na VPS: bash scripts/deploy.sh
set -euo pipefail
cd "$(dirname "$0")/.."
exec 9>/tmp/escola-agenda-deploy.lock
flock -n 9 || { echo 'Outro deploy está em andamento.' >&2; exit 1; }
test "$(git branch --show-current)" = main
test -z "$(git status --porcelain)" || { echo 'Checkout possui alterações; deploy cancelado.' >&2; exit 1; }
before=$(git rev-parse HEAD)
git fetch origin main
target=$(git rev-parse origin/main)
git merge-base --is-ancestor "$before" "$target" || { echo 'Histórico divergente; revisar manualmente.' >&2; exit 1; }
build=0
runtime=0
compose=0
while IFS= read -r path; do
  case "$path" in
    Dockerfile|requirements*.txt|pyproject.toml|poetry.lock|uv.lock|setup.py|setup.cfg|.dockerignore) build=1 ;;
    docker-compose.yml) compose=1 ;;
    AGENTS.md|README*|docs/*|scripts/*|tests/*|.gitignore|.github/*) ;;
    *) runtime=1 ;;
  esac
done < <(git diff --name-only "$before" "$target")
paused=0
resume_worker() {
  if test "$paused" = 1; then docker compose start worker; fi
}
trap resume_worker EXIT
if test "$build" = 1; then
  # Não interromper restauração: exigir respostas válidas e nenhum trabalho ativo/reservado.
  for state in active reserved scheduled; do
    docker compose exec -T worker celery -A app.celery inspect "$state" --json --timeout=5 |
      python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0 if isinstance(d,dict) and d and all(isinstance(v,list) and not v for v in d.values()) else 1)'
  done
  docker compose stop --timeout -1 worker
  paused=1
fi
git merge --ff-only "$target"
if test "$build" = 1; then
  docker compose --parallel 1 build app
  docker compose up -d --no-build
  paused=0
elif test "$compose" = 1; then
  docker compose up -d --no-build
  if test "$runtime" = 1; then docker compose restart app worker; fi
elif test "$runtime" = 1; then
  docker compose restart app worker
else
  echo 'Somente documentação/scripts/testes: sem build ou reinício.'
fi
if test "$build$compose$runtime" != 000; then
  for attempt in $(seq 1 30); do
    if curl --fail --silent --max-time 5 http://localhost:5000/health; then break; fi
    if test "$attempt" = 30; then echo 'Healthcheck não recuperou.' >&2; exit 1; fi
    sleep 2
  done
  docker compose exec -T worker celery -A app.celery inspect ping --json --timeout=10 |
    python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0 if isinstance(d,dict) and d and all(isinstance(v,dict) and v.get("ok")=="pong" for v in d.values()) else 1)'
fi
git rev-parse HEAD
docker compose ps
curl --fail --silent --max-time 15 https://agendaricardo.com.br/health
echo
