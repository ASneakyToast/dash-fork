set dotenv-load := false

default:
    @just --list

[arg('open', long='open', value='true')]
up open="" *args:
    docker compose up --build --detach {{ if open == "true" { "--wait" } else { "" } }} {{args}}
    {{ if open == "true" { "just browse" } else { "" } }}

down:
    docker compose down

nuke:
    docker compose down --volumes

[arg('follow', short='f', long='follow', value='--follow')]
[arg('tail', long='tail')]
logs follow="" tail="all" *services:
    docker compose logs {{follow}} --tail={{tail}} {{services}}

ps:
    docker compose ps

browse:
    open http://localhost:8000

kube_context := "rancher-desktop"
namespace := "dash"
chart := "charts/dash"
rd_socket := env("HOME") / ".rd/docker.sock"

k8s-build:
    @test -S {{rd_socket}} || { echo "start Rancher Desktop (dockerd runtime): {{rd_socket}} not found" >&2; exit 1; }
    DOCKER_HOST=unix://{{rd_socket}} docker build -t dash:local .

k8s-secrets:
    #!/usr/bin/env bash
    set -euo pipefail
    mkdir -p .local
    [ -f .local/id_ed25519 ] || ssh-keygen -q -t ed25519 -N '' -C dash-agent -f .local/id_ed25519
    set -a
    [ -f .env ] && . ./.env
    set +a
    jq -n \
      --rawfile private .local/id_ed25519 \
      --rawfile public .local/id_ed25519.pub \
      'def v($k; d): (env[$k] // "") | if . == "" then d else . end;
      {secrets: {values: {
        "dash-bedrock": ({
          AWS_REGION: v("AWS_REGION"; "us-east-1"),
          AWS_DEFAULT_REGION: v("AWS_DEFAULT_REGION"; v("AWS_REGION"; "us-east-1")),
          AWS_ACCESS_KEY_ID: v("AWS_ACCESS_KEY_ID"; null),
          AWS_SECRET_ACCESS_KEY: v("AWS_SECRET_ACCESS_KEY"; null),
          AWS_SESSION_TOKEN: v("AWS_SESSION_TOKEN"; null)
        } | with_entries(select(.value != null))),
        "dash-agent-ssh": {PRIVATE_KEY: $private},
        "dash-sandbox-ssh": {PUBLIC_KEY: $public}
      }}}' > .local/secrets.json

k8s-up: k8s-build k8s-secrets
    helm upgrade --install dash {{chart}} --kube-context {{kube_context}} --namespace {{namespace}} --create-namespace \
      --values {{chart}}/values-local.yaml --values .local/secrets.json --wait --timeout 10m
    @echo "open http://dash.localhost"

reload: k8s-build
    kubectl --context {{kube_context}} --namespace {{namespace}} rollout restart deploy/dash-api deploy/dash-worker
    kubectl --context {{kube_context}} --namespace {{namespace}} rollout status deploy/dash-api deploy/dash-worker --timeout 5m

k8s-down:
    helm uninstall dash --kube-context {{kube_context}} --namespace {{namespace}}

k8s-nuke:
    -helm uninstall dash --kube-context {{kube_context}} --namespace {{namespace}}
    kubectl --context {{kube_context}} delete namespace {{namespace}} --ignore-not-found

k8s-ps:
    kubectl --context {{kube_context}} --namespace {{namespace}} get pods,pvc,ingress

[arg('follow', short='f', long='follow', value='--follow')]
k8s-logs app follow="":
    kubectl --context {{kube_context}} --namespace {{namespace}} logs {{follow}} --all-containers --prefix deploy/{{app}}

chart-lint:
    helm lint {{chart}}
    helm lint {{chart}} --values {{chart}}/values-local.yaml
    helm template dash {{chart}} --namespace {{namespace}} > /dev/null
    helm template dash {{chart}} --namespace {{namespace}} --values {{chart}}/values-local.yaml > /dev/null
