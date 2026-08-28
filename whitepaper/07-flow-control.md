# 2.1 Flow Control

## Overview

Hardware-agnostic — same steps apply on Intel XPU as any other accelerator.

Flow Control adds intelligent request queuing at the llm-d Router (EPP) level. Traditional load
balancing falls short for LLM inference because resource consumption varies wildly per request;
shifting queuing into the Router enables **multi-tenant fairness** (prevent noisy neighbors from
starving other tenants) and **no-regret scheduling** (hold requests during saturation instead of
committing them to a server's local queue where they get stuck). Source:
`guides/flow-control/README.md`.

Requests are classified by a `FlowKey` (Fairness ID + Priority). The EPP maintains separate
in-memory queues per flow and dispatches by priority band, then fairness across tenants within a
band, then arrival order within a flow. Default policies (`global-strict-fairness-policy` +
`fcfs-ordering-policy` + `utilization-detector`) intentionally mimic legacy FCFS behavior for a
seamless transition — production deployments should switch the saturation detector to
`concurrency-detector` per the guide's `tuning.md` to avoid telemetry lag risk.

**Supported Hardware Backends**: Flow Control is a software-level EPP feature and is entirely
hardware-agnostic — it supports every accelerator the [Optimized Baseline](01-optimized-baseline.md)
guide supports, including Intel XPU. This guide dynamically reuses whichever model server overlay
you deploy from Optimized Baseline; there is no separate `modelserver/xpu/` overlay specific to
Flow Control because none is needed.

## Prerequisites

- Chapter 0 (Common Installation) complete.
- The `llm-d.ai` `InferenceObjective` CRD (see Step 0 below) — Flow Control's priority-tier
  objectives depend on it and it is not installed by Chapter 0's GAIE CRD step, which only covers
  the `InferencePool` CRD.

## Deployment Steps

```bash
export REPO_ROOT=$(realpath $(git rev-parse --show-toplevel))
source ${REPO_ROOT}/guides/env.sh
export GUIDE_NAME="flow-control"
export NAMESPACE="llm-d-flow-control"
export MODEL_NAME="Qwen/Qwen3-32B"   # swap for the CI-sized Qwen/Qwen3-0.6B on constrained Intel XPU test nodes

# 0. Install the llm-d.ai InferenceObjective CRD (ROUTER_RELEASE_URL is derived from
#    ROUTER_RELEASE_VERSION in guides/env.sh) — in addition to the GAIE InferencePool CRD
#    already installed in Chapter 0
kubectl apply -f https://github.com/llm-d/llm-d-router/${ROUTER_RELEASE_URL}/manifests.yaml

kubectl create namespace ${NAMESPACE} --dry-run=client -o yaml | kubectl apply -f -

# HF token secret (see Chapter 0.4)
kubectl create secret generic llm-d-hf-token \
  --from-literal="HF_TOKEN=${HF_TOKEN}" \
  --namespace "${NAMESPACE}" --dry-run=client -o yaml | kubectl apply -f -

# 1. Deploy the Router (Standalone Mode) — this guide was migrated to the guide.yaml-driven
#    "guide.py emit" method, so the README's own command now uses `helm upgrade --install`
#    (safe to re-run) instead of `helm install`
helm upgrade --install ${GUIDE_NAME} \
    ${ROUTER_STANDALONE_CHART} \
    -f ${REPO_ROOT}/guides/recipes/router/base.values.yaml \
    -f ${REPO_ROOT}/guides/${GUIDE_NAME}/router/${GUIDE_NAME}.values.yaml \
    -n ${NAMESPACE} --version ${ROUTER_CHART_VERSION}

# 2. Deploy the Model Server — reuse the Optimized Baseline Intel XPU overlay,
#    relabeled to this guide's name via `sed` (this is the pattern the guide itself
#    prescribes for every non-default accelerator, not an Intel-XPU-specific workaround)
kubectl kustomize ${REPO_ROOT}/guides/optimized-baseline/modelserver/xpu/vllm/ \
  | sed "s/optimized-baseline/${GUIDE_NAME}/g" \
  | kubectl apply -n ${NAMESPACE} -f -
```

For Gateway Mode (Kubernetes Gateway rather than standalone Envoy sidecar), see
`guides/flow-control/README.md` "Gateway Mode" — the pattern is identical to the one used in
[Chapter 1](01-optimized-baseline.md).

## Verification

```bash
export IP=$(kubectl get service ${GUIDE_NAME}-epp -n ${NAMESPACE} -o jsonpath='{.spec.clusterIP}')
kubectl logs deploy/${GUIDE_NAME}-epp -n ${NAMESPACE} | grep "Flow Control enabled"
```

## Inference Test

Apply the three priority-tier `InferenceObjective`s shipped with the guide, then send a request
tagged with a tenant/priority header:

```bash
kubectl apply -f ${REPO_ROOT}/guides/${GUIDE_NAME}/objectives.yaml -n ${NAMESPACE}

kubectl run curl-debug --rm -it \
    --image=cfmanteiga/alpine-bash-curl-jq \
    --namespace="$NAMESPACE" \
    --env="IP=$IP" --env="NAMESPACE=$NAMESPACE" --env="GUIDE_NAME=$GUIDE_NAME" \
    -- /bin/bash

# from inside the debug pod:
curl -X POST http://${IP}/v1/completions \
  -H 'Content-Type: application/json' \
  -H 'x-llm-d-inference-fairness-id: tenant-a' \
  -H 'x-llm-d-inference-objective: premium-traffic' \
  -d "{\"model\": \"${MODEL_NAME}\", \"prompt\": \"Say hello\"}"

# confirm queuing metrics are exposed
curl http://${GUIDE_NAME}-epp:9090/metrics | grep llm_d_epp_flow_control_queue_size
```

To actually observe backpressure (not just admission), drive concurrent load with `hey` per the
guide's "Use Case 2: Backpressure Management" section — a single request always dispatches
immediately because the system is work-conserving.

## Troubleshooting

- **Trust boundary**: never let end users self-assert `x-llm-d-inference-fairness-id` /
  `x-llm-d-inference-objective` directly — a production ingress Gateway must strip these headers
  from external traffic and re-inject them after authenticating the caller (see the EPP HTTP
  headers reference in `docs/api-reference/epp-http-headers.md`).
- If `"Flow Control enabled"` never appears in the EPP logs, confirm the
  `${GUIDE_NAME}.values.yaml` router overlay was actually applied (not just the base values file).
- `utilization-detector` (the default saturation detector) can lag under bursty Intel XPU
  telemetry collection intervals; switch to `concurrency-detector` per the Tuning Guide if you
  see saturation detected later than expected.

## Cleanup

```bash
helm uninstall ${GUIDE_NAME} -n ${NAMESPACE}
# Must reuse the same kustomize+sed rename pipeline as the deploy step above — the resources were
# created under the ${GUIDE_NAME}-prefixed names, not the original optimized-baseline names, so a
# plain `kubectl delete -k .../optimized-baseline/modelserver/xpu/vllm/` would not match them.
kubectl kustomize ${REPO_ROOT}/guides/optimized-baseline/modelserver/xpu/vllm/ \
  | sed "s/optimized-baseline/${GUIDE_NAME}/g" \
  | kubectl delete -n ${NAMESPACE} -f -
kubectl delete namespace ${NAMESPACE}
```

## Config Reference

| Field | Value | Notes |
|---|---|---|
| Default model (inherited) | `Qwen/Qwen3-32B` | 8 replicas × TP2 = 16 GPUs in the reference config; scale down for Intel XPU test clusters |
| Fairness policy | `global-strict-fairness-policy` | ignores flow isolation, single global FCFS order |
| Ordering policy | `fcfs-ordering-policy` | first-come-first-served |
| Saturation detector | `utilization-detector` (default) / `concurrency-detector` (recommended for production) | |
| Priority tiers (example) | Premium (100), Standard (0), Best-Effort (-10) | defined in `objectives.yaml` |
| Client headers | `x-llm-d-inference-fairness-id`, `x-llm-d-inference-objective` | must be stripped/re-injected by ingress Gateway in production |
