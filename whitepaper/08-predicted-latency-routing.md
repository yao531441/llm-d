# 2.2 Predicted Latency-Based Routing

## Overview

Hardware-agnostic at the routing layer; the GPU/TPU-specific model-server paths shown upstream do
not include an Intel XPU variant of their own — Intel XPU deployers reuse the Optimized Baseline
overlay exactly as the guide's "For other backends" note instructs.

Routes each inference request to the model server predicted to serve it fastest, using a
live-trained XGBoost latency-prediction model instead of heuristic queue-depth/KV-utilization
scoring — and, optionally, only to a server predicted to meet a per-request TTFT/TPOT SLO. Source:
`guides/predicted-latency-routing/README.md`.

**When to pick this path**: workloads with high variance in prompt/completion length where queue
depth alone is a poor load proxy, or where clients can express per-request latency SLOs you want
the gateway to enforce. **Skip it** for heterogeneous pools (mixed GPU types/model variants) —
the predictor assumes a single pod shape and will produce inaccurate predictions otherwise.

> [!NOTE] Upstream flags OpenShift support for this guide as "not reliable as-is" — the
> latency-predictor sidecars may need additional OpenShift-specific runtime adjustments. Prefer a
> vanilla Kubernetes distribution for your first Intel XPU validation pass.

## Prerequisites

- Chapter 0 (Common Installation) complete.
- No additional cluster prerequisites beyond Chapter 0.

## Deployment Steps

```bash
export REPO_ROOT=$(realpath $(git rev-parse --show-toplevel))
source ${REPO_ROOT}/guides/env.sh
export GUIDE_NAME="predicted-latency-routing"
export NAMESPACE=llm-d-predicted-latency
export MODEL_NAME="Qwen/Qwen3-32B"

kubectl create namespace ${NAMESPACE}
kubectl create secret generic llm-d-hf-token \
  --from-literal="HF_TOKEN=${HF_TOKEN}" \
  --namespace "${NAMESPACE}" --dry-run=client -o yaml | kubectl apply -f -

# 1. Deploy the Router — default values file trains the predictor on end-to-end latency
#    (routing only, no SLO headers). Swap in router/predicted-latency-slo.values.yaml
#    for SLO-aware scheduling.
helm install ${GUIDE_NAME} \
    ${ROUTER_STANDALONE_CHART} \
    -f ${REPO_ROOT}/guides/recipes/router/base.values.yaml \
    -f ${REPO_ROOT}/guides/${GUIDE_NAME}/router/predicted-latency.values.yaml \
    -n ${NAMESPACE} --version ${ROUTER_CHART_VERSION}

# 2. Deploy the Model Server — Intel XPU is not one of this guide's own model-server
#    variants (only GPU/vLLM base+gke, and a TPU variant for the agentic case exist under
#    guides/predicted-latency-routing/modelserver/). Per the guide's own instructions for
#    "other backends", reuse the Optimized Baseline Intel XPU overlay directly — both
#    values files already select pods labeled `llm-d.ai/guide=optimized-baseline`, so no
#    relabeling `sed` step is required here (unlike Flow Control in Chapter 2.1).
kubectl apply -n ${NAMESPACE} -k ${REPO_ROOT}/guides/optimized-baseline/modelserver/xpu/vllm/
```

## Verification

Confirm predictions are actually being produced in Prometheus (see
`docs/architecture/advanced/latency-predictor.md#observability` for the full metric reference):

```promql
inference_objective_request_ttft_prediction_duration_seconds
```

If this stays empty, the predictor sidecar isn't being called — tail the EPP logs for
`predicted-latency-producer` errors.

## Inference Test

```bash
export IP=$(kubectl get service ${GUIDE_NAME}-epp -n ${NAMESPACE} -o jsonpath='{.spec.clusterIP}')

kubectl run curl-debug --rm -it \
    --image=cfmanteiga/alpine-bash-curl-jq \
    --namespace="$NAMESPACE" \
    --env="IP=$IP" --env="NAMESPACE=$NAMESPACE" --env="MODEL_NAME=$MODEL_NAME" \
    -- /bin/bash

# from inside the debug pod — opt this request into SLO-aware routing:
curl -X POST http://${IP}/v1/completions \
    -H 'Content-Type: application/json' \
    -H 'x-llm-d-slo-ttft-ms: 200' \
    -H 'x-llm-d-slo-tpot-ms: 50' \
    -d '{
        "model": "'${MODEL_NAME}'",
        "prompt": "Explain the difference between prefill and decode.",
        "max_tokens": 200,
        "temperature": 0,
        "stream": true,
        "stream_options": {"include_usage": true}
    }'
```

No header changes are needed for plain latency-based routing — it applies to every request.
SLO headers (`x-llm-d-slo-ttft-ms`, `x-llm-d-slo-tpot-ms`) opt a request into SLO enforcement;
sheddable (negative-priority) requests are rejected at admission if no endpoint can meet the SLO,
rather than routed to a guaranteed miss.

## Troubleshooting

- **Empty prediction metrics**: predictor sidecar not being invoked — check EPP logs for
  `predicted-latency-producer` errors, and confirm the router values file actually enabled the
  predictor plugin (not just the base values file).
- **Predictions drifting from reality**: compare
  `inference_objective_request_predicted_ttft_seconds` against
  `inference_objective_request_ttft_seconds` over a rolling window — a healthy deployment
  converges within a few percent after warmup; if it doesn't, the pool is likely heterogeneous
  (mixed hardware/model shapes), which this guide explicitly does not support.
- **OpenShift**: known-unreliable per upstream notes — try a vanilla Kubernetes distro first if
  you hit sidecar runtime issues.

## Cleanup

```bash
helm uninstall ${GUIDE_NAME} -n ${NAMESPACE}
kubectl delete -n ${NAMESPACE} -k ${REPO_ROOT}/guides/optimized-baseline/modelserver/xpu/vllm/
kubectl delete namespace ${NAMESPACE}
```

## Config Reference

| Field | Value | Notes |
|---|---|---|
| Values file (default) | `router/predicted-latency.values.yaml` | routing-only, predictor trained on E2E latency |
| Values file (SLO-aware) | `router/predicted-latency-slo.values.yaml` | requires `"stream": true` on every request |
| SLO headers | `x-llm-d-slo-ttft-ms`, `x-llm-d-slo-tpot-ms` | opt-in per request |
| Model server (Intel XPU) | reuses `guides/optimized-baseline/modelserver/xpu/vllm/` directly | no relabeling needed, unlike Flow Control |
| Key metrics | `inference_objective_request_ttft_prediction_duration_seconds`, `..._predicted_ttft_seconds`, `..._ttft_slo_violation_total` | see architecture doc for full list |
