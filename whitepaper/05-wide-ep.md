# 1.5 Wide Expert Parallelism (In Progress)

## Overview

Deploys a wide expert-parallel MoE model with P/D disaggregation using LeaderWorkerSets and
DP-aware scheduling. The reference GPU configuration targets `DeepSeek-R1-0528` across 32 GPUs; the
**validated Intel XPU configuration** uses the smaller `DeepSeek-V2-Lite-Chat` shape:

| Parameter | Value |
|---|---|
| Model | `deepseek-ai/DeepSeek-V2-Lite-Chat` |
| Prefill Tensor Parallelism | 2 |
| Decode Tensor Parallelism | 2 |
| Total XPUs | 4 |
| Expert Parallelism | enabled |
| All2All backend | `allgather_reducescatter` |
| KV transfer | NIXL, `kv_buffer_device=xpu` |
| UCX transport | `tcp,ze_copy` (validated non-RDMA configuration) |

> [!NOTE]
> The Intel XPU backend uses **XCCL** for collective communication; NIC-ID-based rail-only
> connectivity configurations (used on some NVIDIA RoCE setups) are not compatible and will fail.

## Prerequisites

Chapter 0, plus:
- [Intel Resource Drivers for Kubernetes](https://github.com/intel/intel-resource-drivers-for-kubernetes)
  installed, with the `gpu.intel.com` DRA `DeviceClass` verified available

## Deployment Steps

**Step 1 — Deploy the llm-d Router (Standalone mode, with the XPU override)**

```bash
export GUIDE_NAME="wide-ep-lws"
export NAMESPACE="llm-d-wide-ep-lws"

helm install ${GUIDE_NAME} \
    ${ROUTER_STANDALONE_CHART} \
    -f ${REPO_ROOT}/guides/recipes/router/base.values.yaml \
    -f ${REPO_ROOT}/guides/${GUIDE_NAME}/router/${GUIDE_NAME}.values.yaml \
    -f ${REPO_ROOT}/guides/${GUIDE_NAME}/router/xpu.values.yaml \
    -n ${NAMESPACE} --version ${ROUTER_CHART_VERSION}
```

> [!IMPORTANT]
> The `xpu.values.yaml` override is required — without it, EPP does not target the single decode
> sidecar port exposed by the Intel XPU manifests.

**Step 2 — Deploy the Model Server**

```bash
export MODEL=deepseek-ai/DeepSeek-V2-Lite-Chat
kubectl apply -n ${NAMESPACE} -k ${REPO_ROOT}/guides/wide-ep-lws/modelserver/xpu/vllm
```

**Step 3 — (Optional) Enable Monitoring / Topology-Aware Scheduling**

Monitoring follows the same pattern as other guides
(`kubectl apply -k .../guides/recipes/modelserver/components/monitoring-pd`, if applicable). TAS
overlays in this guide are GKE H200/B200-specific and do not apply to the Intel XPU path.

## Verification

```bash
kubectl get pods -n ${NAMESPACE}
kubectl get pods -n ${NAMESPACE} -l llm-d.ai/role=decode -w
kubectl get pods -n ${NAMESPACE} -l llm-d.ai/role=prefill -w
```

## Inference Test

```bash
export IP=$(kubectl get service ${GUIDE_NAME}-epp -n ${NAMESPACE} -o jsonpath='{.spec.clusterIP}')

kubectl run curl-debug --rm -it \
    --image=cfmanteiga/alpine-bash-curl-jq \
    --namespace="${NAMESPACE}" \
    --env="IP=${IP}" \
    -- /bin/bash

curl -X POST http://${IP}/v1/completions \
    -H 'Content-Type: application/json' \
    -d '{"model": "deepseek-ai/DeepSeek-V2-Lite-Chat", "prompt": "Explain expert parallelism."}' | jq
```

## Troubleshooting

- **Collective communication failures / hangs**: confirm the cluster is using XCCL, not a
  NIC-ID/rail-only RoCE configuration — the latter is documented as incompatible with the Intel XPU
  backend.
- **EPP routing to the wrong port**: confirm `router/xpu.values.yaml` was included in the `helm
  install` — without it EPP targets the wrong (non-XPU) sidecar port.

## Cleanup

```bash
helm uninstall ${GUIDE_NAME} -n ${NAMESPACE}
kubectl delete -n ${NAMESPACE} -k ${REPO_ROOT}/guides/wide-ep-lws/modelserver/xpu/vllm
```

## Configuration Reference

| Parameter | Value | Purpose |
|---|---|---|
| `kv_buffer_device` | `xpu` | KV buffer resident on the accelerator (differs from the `cpu` default used by the PD-disaggregation guide) |
| All2All backend | `allgather_reducescatter` | MoE expert-parallel communication pattern |
| UCX transport | `tcp,ze_copy` | Validated non-RDMA transport for Intel XPU |
| Total XPUs | 4 | 2 (prefill TP) + 2 (decode TP), validated shape |

---
