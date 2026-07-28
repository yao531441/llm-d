# 1.2 P/D Disaggregation

## Overview

Splits inference into independently-scaled Prefill and Decode deployments, connected via NIXL KV
transfer. Native to the llm-d Router, so it composes with prefix-cache-aware and load-aware
routing from Optimized Baseline. Default GPU example uses `openai/gpt-oss-120b` (8× TP=1 Prefill +
2× TP=4 Decode); the Intel XPU overlay uses the smaller `Qwen/Qwen3-0.6B` for fast validation.

Best suited for: medium-large models, long input sequences (e.g. 10k ISL / 1k OSL), sparse MoE
architectures.

## Prerequisites

Chapter 0 only.

## Deployment Steps

**Step 1 — Deploy the llm-d Router (Standalone mode)**

```bash
export GUIDE_NAME="pd-disaggregation"
export NAMESPACE="llm-d-pd-disaggregation"
export MODEL_NAME="Qwen/Qwen3-0.6B"   # Intel XPU overlay default; swap for production models

helm install ${GUIDE_NAME} \
    ${ROUTER_STANDALONE_CHART} \
    -f ${REPO_ROOT}/guides/recipes/router/base.values.yaml \
    -f ${REPO_ROOT}/guides/${GUIDE_NAME}/router/${GUIDE_NAME}.values.yaml \
    -n ${NAMESPACE} --version ${ROUTER_CHART_VERSION}
```

**Step 2 — Deploy the Model Server (Intel XPU overlay)**

> [!IMPORTANT]
> GPUs are declared via DRA `ResourceClaimTemplate` (`deviceClassName: gpu.intel.com`), not
> `resources.limits."gpu.intel.com/xe"`.

```bash
kubectl apply -n ${NAMESPACE} -k ${REPO_ROOT}/guides/pd-disaggregation/modelserver/xpu/vllm
```

This overlay includes:
- `patch-prefill.yaml` / `patch-decode.yaml`: vLLM launch args, including `--kv-transfer-config`
  with `kv_connector: NixlConnector`, `kv_role: kv_both`, `kv_buffer_device: cpu`; and env vars
  `VLLM_USE_V1=1`, `VLLM_NIXL_SIDE_CHANNEL_HOST` (from `status.podIP`),
  `VLLM_NIXL_SIDE_CHANNEL_PORT=5600`, `UCX_TLS=tcp`, `VLLM_WORKER_MULTIPROC_METHOD=spawn`
- `resource-claim-templates.yaml`: two `ResourceClaimTemplate`s, `xpu-prefill-claim` and
  `xpu-decode-claim`, each requesting 1 `gpu.intel.com` device

For clusters with RDMA connectivity, use `modelserver/xpu/vllm-rdma` instead (UCX transport
`ib,rc,ze_copy`).

**Step 3 — (Optional) Enable Monitoring**

```bash
kubectl apply -n ${NAMESPACE} -k ${REPO_ROOT}/guides/recipes/modelserver/components/monitoring-pd
```

## Verification

```bash
kubectl get pods -n ${NAMESPACE}
kubectl get pods -n ${NAMESPACE} -l llm-d.ai/role=decode -w
kubectl get pods -n ${NAMESPACE} -l llm-d.ai/role=prefill -w

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
    -d '{"model": "Qwen/Qwen3-0.6B", "prompt": "How are you today?"}' | jq
```

## Troubleshooting

- **Pod stuck at `Init:0/1`**: known routing-proxy sidecar issue
  ([llm-d/llm-d#241](https://github.com/llm-d/llm-d/issues/241)); workaround: set
  `proxy.enabled: false` — the Gateway API + InferencePool routing already covers what the sidecar
  provided.
- **KV transfer failures**: check decode/prefill container logs for `nixl`:
  `kubectl logs -n ${NAMESPACE} <pod> -c modelserver | grep -i nixl`.
- **`ResourceClaim` stuck `Pending`**: confirm the `gpu.intel.com` device class is registered;
  `kubectl get resourceclaims -n ${NAMESPACE}` for details.
- **HuggingFace download failures**: check proxy env vars and DNS (`nslookup huggingface.co`).

## Cleanup

```bash
helm uninstall ${GUIDE_NAME} -n ${NAMESPACE}
kubectl delete -n ${NAMESPACE} -k ${REPO_ROOT}/guides/pd-disaggregation/modelserver/xpu/vllm
```

## Configuration Reference

| Parameter | Value | Purpose |
|---|---|---|
| `kv_connector` | `NixlConnector` | KV transfer connector |
| `kv_role` | `kv_both` | Both send and receive |
| `kv_buffer_device` | `cpu` | Reduces GPU memory pressure |
| `VLLM_USE_V1` | `1` | Required for P/D |
| `VLLM_WORKER_MULTIPROC_METHOD` | `spawn` | Multiprocess start method |
| `UCX_TLS` | `tcp` (or `ib,rc,ze_copy` for the RDMA overlay) | UCX transport |

Resource requirements (Intel XPU overlay, `Qwen/Qwen3-0.6B`):

| Role | Replicas | CPU | Memory | GPU |
|---|---|---|---|---|
| Decode | 1 | 16 cores | 64Gi | 1× `gpu.intel.com` (DRA claim) |
| Prefill | 3 | 16 cores/replica | 64Gi/replica | 1× `gpu.intel.com`/replica (DRA claim) |

> [!WARNING]
> Production models (e.g. `openai/gpt-oss-120b`) require substantially more CPU/memory/GPU than the
> table above — re-plan capacity for your target model.

---
