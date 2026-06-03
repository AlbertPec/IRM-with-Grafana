#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/.env"
source "$SCRIPT_DIR/common.sh"

check_tool kubectl
check_tool istioctl

echo "Installing Istio with demo profile..."
istioctl manifest apply --set profile=demo --skip-confirmation
wait_for_pods "istio-system" 600

echo "Labeling default namespace for Istio sidecar injection..."
kubectl label namespace default istio-injection=enabled --overwrite

echo "Applying application manifests..."
kubectl apply -f app/release/kubernetes/manifests.yaml
wait_for_pods "default" 600

echo "Deploying prometheus addon..."
kubectl apply -f https://raw.githubusercontent.com/istio/istio/release-1.21/samples/addons/prometheus.yaml
wait_for_pods "istio-system" 300

echo "Deploying Grafana addon..."
kubectl apply -f https://raw.githubusercontent.com/istio/istio/release-1.21/samples/addons/grafana.yaml
wait_for_pods "istio-system" 300

echo "Deploying frontend gateway"
kubectl -n default apply -f app/release/istio/frontend-gateway.yaml
kubectl -n default apply -f app/release/istio/frontend-ingress.yaml

echo "Running Grafana deployment script..."
if [[ -d "deployment" && -x "deployment/grafana_deploy.sh" ]]; then
  (cd deployment && ./grafana_deploy.sh)
else
  echo "[ERROR]: deployment/grafana_deploy.sh not found or not executable."
  exit 1
fi

wait_for_pods "default" 300
wait_for_pods "istio-system" 300

INGRESS_HOSTNAME=$(kubectl get svc istio-ingressgateway -n istio-system -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')
echo "All deployments completed successfully"

if [[ -n "$INGRESS_HOSTNAME" ]]; then
  echo "Istio Ingress Gateway Hostname: http://$INGRESS_HOSTNAME"
fi
echo "To open grafana dashboard run: 'istioctl dashboard grafana' in the terminal"
