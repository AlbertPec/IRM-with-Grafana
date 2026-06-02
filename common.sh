#!/bin/bash
# Common file implementing shared functions

wait_for_pods() {
  local namespace="$1"
  local timeout="${2:-600}"

  if ! kubectl get namespace "$namespace" &>/dev/null; then
    echo "Namespace '$namespace' does not exist yet. Skipping wait."
    return 0
  fi

  echo "Waiting for all pods in namespace '$namespace' to be ready (timeout: ${timeout}s)..."

  local pod_count
  pod_count=$(kubectl get pods -n "$namespace" --no-headers 2>/dev/null | wc -l)

  if [[ "$pod_count" -eq 0 ]]; then
    echo "No pods found in namespace '$namespace'. Skipping wait."
    return 0
  fi

  if kubectl wait --for=condition=ready pod --all -n "$namespace" --timeout="${timeout}s"; then
    echo "All pods in '$namespace' are ready"
  else
    echo "[ERROR]: Timeout waiting for pods in namespace '$namespace'."
    return 1
  fi
}

check_tool() {
  if ! command -v $1 &> /dev/null; then
    echo "[ERROR]: No $1 available."
    exit 1
  fi
}
