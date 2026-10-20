#!/usr/bin/env bash
set -Eeuo pipefail

if [[ "$DEPLOY_ENV" == "prod" ]]; then
  export COMPOSE_PROJECT_NAME="step4_movie-app"
  export APP_PORT=8181
elif [[ "$DEPLOY_ENV" == "dev" ]]; then
  export COMPOSE_PROJECT_NAME="step4_movie-app-dev"
  export APP_PORT=8182
else
  echo "DEPLOY_ENV must be prod or dev." >&2
  exit 1
fi

export IMAGE_TAG="${GITHUB_REF_NAME}-${GITHUB_SHA}"
compose=(docker compose
  -f step4_movie-app/docker-compose.yml
  -f .github/compose.deploy.yaml)
proxy_name="${COMPOSE_PROJECT_NAME}-nginx-proxy-1"

if [[ -z "${DOCKERHUB_USERNAME:-}" || -z "${DOCKERHUB_TOKEN:-}" ||
      -z "${MONGO_USERNAME:-}" || -z "${MONGO_PASSWORD:-}" ]]; then
  echo "Docker Hub and MongoDB credentials must be configured in Actions secrets." >&2
  exit 1
fi

echo "$DOCKERHUB_TOKEN" | docker login \
  --username "$DOCKERHUB_USERNAME" \
  --password-stdin
trap 'docker logout >/dev/null 2>&1 || true' EXIT

active_slot=""
legacy_available=false
proxy_id="$("${compose[@]}" ps -q nginx-proxy)"
legacy_api_id="$("${compose[@]}" ps -q movie-api)"
legacy_ui_id="$("${compose[@]}" ps -q movie-ui)"
if [[ -n "$legacy_api_id" && -n "$legacy_ui_id" ]] &&
   docker inspect --format '{{.State.Running}}' "$legacy_api_id" | grep -qx true &&
   docker inspect --format '{{.State.Running}}' "$legacy_ui_id" | grep -qx true; then
  legacy_available=true
fi

if [[ -n "$proxy_id" ]] &&
   docker inspect --format '{{.State.Running}}' "$proxy_id" | grep -qx true; then
  proxy_name="$proxy_id"
  active_slot="$(docker exec "$proxy_name" sh -c \
    'grep -Eo "movie-api-(blue|green):5000" /etc/nginx/conf.d/default.conf || true' \
    | head -n 1 | sed 's/movie-api-//; s/:5000//')"
fi

if [[ "$active_slot" == "blue" ]]; then
  deploy_slot=green
else
  deploy_slot=blue
fi

echo "Deploying $IMAGE_TAG to $DEPLOY_ENV on port $APP_PORT using the $deploy_slot slot."
services=(movie-db "movie-api-$deploy_slot" "movie-ui-$deploy_slot" nginx-proxy)

"${compose[@]}" --profile "$deploy_slot" pull "${services[@]}"
"${compose[@]}" --profile "$deploy_slot" up \
  --detach --no-build --wait --wait-timeout 180 "${services[@]}"

proxy_name="$("${compose[@]}" ps -q nginx-proxy)"
if [[ -z "$proxy_name" ]]; then
  echo "The Nginx proxy container is not running after Compose startup." >&2
  exit 1
fi

if ! docker exec "$proxy_name" wget -qO- \
  "http://movie-api-$deploy_slot:5000/api/movies?category=comedy" \
  | python3 -c 'import json,sys; sys.exit(0 if json.load(sys.stdin).get("count") == 12 else 1)'; then
  echo "The inactive API slot failed its readiness check." >&2
  exit 1
fi

if ! docker exec "$proxy_name" wget -qO- \
  "http://movie-ui-$deploy_slot/" | grep -q "Find your next"; then
  echo "The inactive UI slot failed its readiness check." >&2
  exit 1
fi

render_proxy_config() {
  local slot="$1"
  if [[ "$slot" == "legacy" ]]; then
    cat step4_movie-app/nginx/default.conf
    return
  fi

  sed \
    -e "s/\${API_UPSTREAM}/movie-api-$slot/g" \
    -e "s/\${UI_UPSTREAM}/movie-ui-$slot/g" \
    step4_movie-app/nginx/bluegreen.conf.template
}

switch_traffic() {
  local slot="$1"
  local config_file
  config_file="$(mktemp)"
  render_proxy_config "$slot" >"$config_file"
  docker cp "$config_file" "$proxy_name:/etc/nginx/conf.d/default.conf.next" >/dev/null
  rm -f "$config_file"

  docker exec "$proxy_name" sh -eu -c '
    conf=/etc/nginx/conf.d/default.conf
    backup=/etc/nginx/conf.d/default.conf.previous
    mv "$conf" "$backup"
    mv "$conf.next" "$conf"
    if nginx -t && nginx -s reload; then
      rm -f "$backup"
    else
      mv "$backup" "$conf"
      nginx -t && nginx -s reload
      exit 1
    fi
  '
}

switch_traffic "$deploy_slot"

if ! curl --silent --show-error --fail "http://127.0.0.1:$APP_PORT/" \
    | grep -q "Find your next" ||
   ! curl --silent --show-error --fail \
    "http://127.0.0.1:$APP_PORT/api/movies?category=comedy" \
    | python3 -c 'import json,sys; sys.exit(0 if json.load(sys.stdin).get("count") == 12 else 1)'; then
  echo "Post-deployment smoke check failed." >&2
  if [[ -n "$active_slot" ]]; then
    echo "Restoring traffic to the previous $active_slot slot." >&2
    switch_traffic "$active_slot"
  elif [[ "$legacy_available" == true ]]; then
    echo "Restoring traffic to the pre-deployment app." >&2
    switch_traffic legacy
  fi
  exit 1
fi

echo "Deployment succeeded: http://localhost:$APP_PORT (slot $deploy_slot, $IMAGE_TAG)."
