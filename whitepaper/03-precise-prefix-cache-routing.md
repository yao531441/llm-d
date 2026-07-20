# 1.3 Precise Prefix Cache Routing (In Progress)

## Overview

Routes on precise, per-pod KV-cache state instead of traffic heuristics. Each vLLM pod publishes
KV-cache events over ZMQ; the router indexes them by block hash and scores candidates by resident
prefix fraction, combined with load-aware scoring. Intel XPU overlay uses the CI-sized
`Qwen/Qwen3-0.6B` model; update the router's `token-producer` `modelName` in
`router/precise-prefix-cache-routing.values.yaml` to match whatever model you deploy — precise
scoring only works if the two match.

## Prerequisites

Chapter 0 only. Note `--block-size` in the vLLM args must match the scorer's
`tokenProcessorConfig.blockSize` (default `64`).

## Deployment Steps

**Step 1 — Deploy the llm-d Router**

```bash
export GUIDE_NAME="precise-prefix-cache-routing"
export NAMESPACE="llm-d-precise-prefix-cache-routing"

helm install ${GUIDE_NAME} \
    ${ROUTER_STANDALONE_CHART} \
    -f ${REPO_ROOT}/guides/recipes/router/base.values.yaml \
    -f ${REPO_ROOT}/guides/${GUIDE_NAME}/router/${GUIDE_NAME}.values.yaml \
    -n ${NAMESPACE} --version ${ROUTER_CHART_VERSION}
```

> [!NOTE]
> The router defaults to **active-active HA** (2 EPP replicas), each subscribing to every vLLM pod
> so both indexes converge independently. Set `--set router.epp.replicas=1` for small fleets or
> smoke tests.

**Step 2 — Deploy the Model Server (Intel XPU overlay)**

```bash
kubectl apply -n ${NAMESPACE} -k ${REPO_ROOT}/guides/precise-prefix-cache-routing/modelserver/xpu/vllm
```

Key args baked into the overlay's `patch-vllm.yaml`:

```yaml
args:
  - "Qwen/Qwen3-0.6B"
  - "--dtype=float16"
  - "--disable-sliding-window"
  - "--block-size=64"
  - "--kv-events-config"
  - '{"enable_kv_cache_events":true,"publisher":"zmq","endpoint":"$(KV_EVENTS_ENDPOINT)","topic":"kv@$(POD_IP):$(POD_PORT)@Qwen/Qwen3-0.6B"}'
env:
  - name: KV_EVENTS_ENDPOINT
    value: "tcp://*:5556"        # pod-discovery mode: every router replica dials each pod directly
  - name: DO_NOT_TRACK
    value: "1"                   # disables vLLM telemetry writes to /.config, which fail under
                                  # restricted SecurityContexts (e.g. OpenShift)
```

Port `5556` (`kv-events`) is exposed on the pod so every router replica can reach the per-pod ZMQ
socket.

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
    -d '{"model": "Qwen/Qwen3-0.6B", "prompt": "How are you today?"}' | jq
```

## Troubleshooting

- **Scores look wrong / no cache hits registered**: confirm `router/precise-prefix-cache-
  routing.values.yaml`'s `modelName` matches the model actually deployed by the overlay.
- **vLLM telemetry write errors under OpenShift-style restricted `SecurityContext`**: confirm
  `DO_NOT_TRACK=1` is set.
- **Router not receiving KV events**: verify port `5556` is reachable from the router pod to each
  vLLM pod (`kubectl exec` into the router pod and test connectivity).

## Cleanup

```bash
helm uninstall ${GUIDE_NAME} -n ${NAMESPACE}
kubectl delete -n ${NAMESPACE} -k ${REPO_ROOT}/guides/${GUIDE_NAME}/modelserver/xpu/vllm
```

## Configuration Reference

| Parameter | Value | Purpose |
|---|---|---|
| `--block-size` | `64` | Must match scorer `tokenProcessorConfig.blockSize` |
| `enable_kv_cache_events` | `true` | Turns on KV-cache event publishing |
| `publisher` | `zmq` | Event transport |
| `KV_EVENTS_ENDPOINT` | `tcp://*:5556` | Pod-discovery mode ZMQ bind address |
| `DO_NOT_TRACK` | `1` | Disables vLLM telemetry (avoids write failures under restricted SCCs) |

---
