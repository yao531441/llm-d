# 1.4 Tiered Prefix Cache

## Overview

Offloads evicted KV-cache blocks from accelerator memory to larger, cheaper tiers (CPU RAM, and
optionally shared filesystem), increasing effective cache size for multi-turn/long-context
workloads. Multiple offloading implementations exist (vLLM native `OffloadingConnector`, LMCache,
MooncakeStore, SGLang HiCache); the Intel XPU overlay ships the **vLLM native** and
**LMCache connector** paths, each with a CPU-RAM-only variant and a CPU RAM + shared-filesystem
variant.

## Prerequisites

Chapter 0, plus the prefix-aware routing from Optimized Baseline (already the default scorer stack
used here).

## Deployment Steps

**Step 1 — Deploy the llm-d Router**

```bash
export GUIDE_NAME="tiered-prefix-cache"
export NAMESPACE="llm-d-tiered-prefix-cache"

helm install ${GUIDE_NAME} \
    ${ROUTER_STANDALONE_CHART} \
    -f ${REPO_ROOT}/guides/recipes/router/base.values.yaml \
    -f ${REPO_ROOT}/guides/${GUIDE_NAME}/router/${GUIDE_NAME}.values.yaml \
    -n ${NAMESPACE} --version ${ROUTER_CHART_VERSION}
```

**Step 2 — Deploy the Model Server (Intel XPU overlay, choose a path)**

VRAM-only baseline (no CPU offloading, for comparison):

```bash
kubectl apply -n ${NAMESPACE} -k ${REPO_ROOT}/guides/tiered-prefix-cache/modelserver/xpu/vllm/base
```

Native (vLLM `OffloadingConnector`), CPU RAM only:

```bash
kubectl apply -n ${NAMESPACE} -k ${REPO_ROOT}/guides/tiered-prefix-cache/modelserver/xpu/vllm/native/cpu/base/
```

Native, CPU RAM + shared filesystem (requires a ReadWriteMany PVC mounted at
`/mnt/files-storage` — see [Storage Backends](https://github.com/llm-d/llm-d/blob/main/guides/tiered-prefix-cache/README.md#storage-backends)
for GCP Lustre / AWS EFS setup guides):

```bash
export STORAGE_CLASS=""  # cluster default if empty; or e.g. "lustre" / "efs-sc"
envsubst < ${REPO_ROOT}/guides/tiered-prefix-cache/manifests/pvc.yaml | kubectl apply -n ${NAMESPACE} -f -
kubectl apply -n ${NAMESPACE} -k ${REPO_ROOT}/guides/tiered-prefix-cache/modelserver/xpu/vllm/native/fs/base/
```

LMCache connector (CPU RAM, or CPU RAM + filesystem if the PVC above was created):

```bash
export VARIANT=cpu  # cpu | fs
kubectl apply -n ${NAMESPACE} -k ${REPO_ROOT}/guides/tiered-prefix-cache/modelserver/xpu/vllm/lmcache-connector/${VARIANT}/base/
```

> [!IMPORTANT]
> The Intel XPU base overlay sets `securityContext.privileged: true` on the model-server container
> in addition to the DRA `ResourceClaimTemplate` (`xpu-vllm-gpu`) — this is required for the
> offloading connector to manage host-pinned memory. Review your cluster's Pod Security Admission
> policy before applying.

## Verification

```bash
kubectl get pods -n ${NAMESPACE}
export IP=$(kubectl get service ${GUIDE_NAME}-epp -n ${NAMESPACE} -o jsonpath='{.spec.clusterIP}')
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
    -d '{"model": "Qwen/Qwen3-0.6B", "prompt": "Summarize the benefits of KV-cache offloading."}' | jq
```

Send a long, repeated-prefix prompt twice to observe a cache hit on the second call (check router
logs / metrics for prefix-cache reuse).

## Troubleshooting

- **Pod fails to start under Pod Security Admission "restricted" policy**: the overlay requires
  `privileged: true`; either relax the namespace's PSA label or use a different offloading path
  that doesn't need privileged access (verify per-connector requirements before assuming).
- **No observable cache reuse**: confirm the CPU-tier offload size is large enough for your
  workload and that requests are actually re-sending the same prefix.

## Cleanup

```bash
helm uninstall ${GUIDE_NAME} -n ${NAMESPACE}
export CONNECTOR=native  # native | lmcache-connector
export VARIANT=cpu       # cpu | fs
kubectl delete -n ${NAMESPACE} -k ${REPO_ROOT}/guides/tiered-prefix-cache/modelserver/xpu/vllm/${CONNECTOR}/${VARIANT}/base --ignore-not-found
# VRAM-only baseline, if that's what you deployed:
kubectl delete -n ${NAMESPACE} -k ${REPO_ROOT}/guides/tiered-prefix-cache/modelserver/xpu/vllm/base --ignore-not-found
# if a filesystem-tier PVC was created:
kubectl delete -f ${REPO_ROOT}/guides/tiered-prefix-cache/manifests/pvc.yaml -n ${NAMESPACE} --ignore-not-found
```

## Configuration Reference

| Parameter | Value | Purpose |
|---|---|---|
| `deviceClassName` | `gpu.intel.com` | DRA device class (claim name `xpu-vllm-gpu`) |
| `securityContext.privileged` | `true` | Required for host-pinned memory management |
| CPU cache offload tier | CPU RAM (native or LMCache) | Effective KV-cache size beyond accelerator memory |
| Filesystem tier | CPU RAM + shared filesystem (native `fs` or LMCache `fs` variant) | Requires a ReadWriteMany PVC at `/mnt/files-storage` (e.g. GCP Lustre, AWS EFS) |

---
