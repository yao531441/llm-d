# 1.1 Optimized Baseline (In Progress)

## Overview

Deploys the recommended out-of-the-box routing configuration for vLLM/SGLang/TensorRT-LLM:
prefix-cache-aware scoring (via the `prefix-cache-scorer` and `no-hit-lru-scorer`) combined with
load-aware scoring (`kv-cache-utilization` and `queue-size` scorers). This is the baseline that
several other guides (Flow Control, Predicted Latency Routing, Agentic Serving) build on top of.
This guide has a dedicated **Intel XPU E2E CI workflow** (`consolidate-status-optimized-baseline-
intel-acc-xpu-vllm-x.yaml`), making it the most CI-validated Intel XPU path in the repo today.

Default model: `Qwen/Qwen3-32B` (GPU); the Intel XPU overlay uses a CI-sized `Qwen/Qwen3-0.6B` for
fast validation — swap in a production model before real deployment.

## Prerequisites

Chapter 0 only. No case-specific prerequisites.

## Deployment Steps

**Step 1 — Deploy the llm-d Router (Standalone mode)**

```bash
export GUIDE_NAME="optimized-baseline"
export NAMESPACE="llm-d-optimized-baseline"

helm install ${GUIDE_NAME} \
    ${ROUTER_STANDALONE_CHART} \
    -f ${REPO_ROOT}/guides/recipes/router/base.values.yaml \
    -f ${REPO_ROOT}/guides/${GUIDE_NAME}/router/${GUIDE_NAME}.values.yaml \
    -n ${NAMESPACE} --version ${ROUTER_CHART_VERSION}
```

**Step 2 — Deploy the Model Server (Intel XPU overlay)**

> [!IMPORTANT]
> The Intel XPU path uses Kubernetes **DRA**: GPUs are declared via a `ResourceClaimTemplate`
> (`deviceClassName: gpu.intel.com`), not `resources.limits`. Confirm the cluster has DRA enabled
> and the `gpu.intel.com` device class available before deploying.

```bash
export ACCELERATOR_TYPE=xpu
export MODEL_SERVER=vllm
kubectl apply -n ${NAMESPACE} -k ${REPO_ROOT}/guides/${GUIDE_NAME}/modelserver/${ACCELERATOR_TYPE}/${MODEL_SERVER}/
```

> [!NOTE]
> Unlike the NVIDIA GPU path, the Intel XPU overlay path has **no** `${INFRA_PROVIDER}` suffix —
> apply the directory directly.

This overlay (`modelserver/xpu/vllm/`):
- uses `recipes/modelserver/base/single-host/default` as its base and the
  `recipes/modelserver/components/images/xpu-vllm` image component
- patches the decode Deployment (`patch-vllm.yaml`) to run
  `vllm serve Qwen/Qwen3-0.6B --dtype=float16 --disable-sliding-window ...`
- adds a `ResourceClaimTemplate` (`resource-claim-template.yaml`) requesting 1 `gpu.intel.com`
  device per replica, with `fsGroup: 107` / `supplementalGroups: [107]` for Intel GPU device
  node access

**Step 3 — (Optional) Enable Monitoring**

```bash
kubectl apply -n ${NAMESPACE} -k ${REPO_ROOT}/guides/recipes/modelserver/components/monitoring
```

## Verification

```bash
export IP=$(kubectl get service ${GUIDE_NAME}-epp -n ${NAMESPACE} -o jsonpath='{.spec.clusterIP}')
kubectl get pods -n ${NAMESPACE}
```

## Inference Test

```bash
kubectl run curl-debug --rm -it \
    --image=cfmanteiga/alpine-bash-curl-jq \
    --namespace="${NAMESPACE}" \
    --env="IP=${IP}" \
    -- /bin/bash

curl -X POST http://${IP}/v1/completions \
    -H 'Content-Type: application/json' \
    -d '{"model": "Qwen/Qwen3-0.6B", "prompt": "How are you today?"}' | jq
```

## Troubleshooting

- **`ResourceClaim` stuck `Pending`**: confirm the node has registered the `gpu.intel.com` device
  class; `kubectl describe resourceclaim <name> -n ${NAMESPACE}`.
- **vLLM usage-telemetry write failures under restricted `SecurityContext`** (e.g. OpenShift): set
  `DO_NOT_TRACK=1` in the container env (already applied in the precise-prefix-cache-routing XPU
  overlay; port the same fix here if you hit it).

## Cleanup

```bash
helm uninstall ${GUIDE_NAME} -n ${NAMESPACE}
kubectl delete -n ${NAMESPACE} -k ${REPO_ROOT}/guides/${GUIDE_NAME}/modelserver/${ACCELERATOR_TYPE}/${MODEL_SERVER}/
kubectl delete namespace ${NAMESPACE}
```

## Configuration Reference

| Parameter | Value | Purpose |
|---|---|---|
| `--dtype` | `float16` | Intel XPU overlay dtype |
| `--disable-sliding-window` | set | Required by the CI-sized model |
| `deviceClassName` | `gpu.intel.com` | DRA device class |
| `fsGroup` / `supplementalGroups` | `107` | Intel GPU render-node group access |

Resource requirements (Intel XPU overlay, `Qwen/Qwen3-0.6B`, 2 replicas):

| Role | Replicas | CPU (req/limit) | Memory (req/limit) | GPU |
|---|---|---|---|---|
| Decode | 2 | 4 / 8 cores | 12Gi / 24Gi | 1× `gpu.intel.com` per replica (DRA claim) |

---
