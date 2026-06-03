#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

source "$ROOT_DIR/.env"
source "$ROOT_DIR/common.sh"

kubectl create secret generic grafana-secrets \
  -n istio-system \
  --from-literal=irm-webhook-url=${GF_IRM_WEBHOOK_URL} \
  --from-literal=discord-webhook-url=${GF_DISCORD_WEBHOOK_URL}

kubectl apply -f grafana-custom-provisioning.yaml

kubectl patch deployment grafana \
  -n istio-system \
  --patch-file grafana-patch.yaml

kubectl rollout restart deployment/grafana -n istio-system
kubectl rollout status deployment/grafana -n istio-system --timeout=120s

wait_for_pods "istio-system" 60
