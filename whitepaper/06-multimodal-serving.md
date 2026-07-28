# 1.6 Multimodal Serving (Aggregated)

## Overview

Deploys the recommended configuration for multimodal (image + text) vLLM serving with prefix-cache
aware routing that matches combined text + image hashes, plus load-aware scoring. Default GPU model
is `Qwen/Qwen3-VL-32B-Instruct`; the Intel XPU overlay targets **Intel Arc Pro B60**.

## Prerequisites

Chapter 0 only.

## Deployment Steps

**Step 1 — Deploy the llm-d Router**

```bash
export GUIDE_NAME="aggregation"
export NAMESPACE="llm-d-multimodal-aggregation"

helm install ${GUIDE_NAME} \
    ${ROUTER_STANDALONE_CHART} \
    -f ${REPO_ROOT}/guides/recipes/router/base.values.yaml \
    -f ${REPO_ROOT}/guides/multimodal-serving/${GUIDE_NAME}/router/${GUIDE_NAME}.values.yaml \
    -n ${NAMESPACE} --version ${ROUTER_CHART_VERSION}
```

**Step 2 — Deploy the Model Server (Intel XPU overlay)**

```bash
kubectl apply -n ${NAMESPACE} -k ${REPO_ROOT}/guides/multimodal-serving/${GUIDE_NAME}/modelserver/xpu/vllm/
```

The overlay patches the decode Deployment's resource requests/limits and DRA claim
(`intel-claim-template-decode`, requesting 1 `gpu.intel.com` device); the base image and multimodal
serving args come from the shared base manifest.

**Step 3 — (Optional) Enable Monitoring**

```bash
kubectl apply -n ${NAMESPACE} -k ${REPO_ROOT}/guides/recipes/modelserver/components/monitoring
```

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

curl -X POST http://${IP}/v1/chat/completions \
    -H 'Content-Type: application/json' \
    -d '{
      "model": "Qwen/Qwen3-VL-32B-Instruct",
      "messages": [{"role": "user", "content": [
        {"type": "text", "text": "What is in this image?"},
        {"type": "image_url", "image_url": {"url": "https://example.com/sample.jpg"}}
      ]}]
    }' | jq
```

## Troubleshooting

- **GPU allocation fails**: confirm the node advertises `gpu.intel.com` resources compatible with
  Intel Arc Pro B60 and that the DRA driver version supports it.
- **Image decoding errors**: check vLLM logs for multimodal preprocessing errors; verify the image
  URL is reachable from within the cluster.

## Cleanup

```bash
helm uninstall ${GUIDE_NAME} -n ${NAMESPACE}
kubectl delete -n ${NAMESPACE} -k ${REPO_ROOT}/guides/multimodal-serving/${GUIDE_NAME}/modelserver/xpu/vllm/
```

## Configuration Reference

| Parameter | Value | Purpose |
|---|---|---|
| `deviceClassName` | `gpu.intel.com` | DRA device class (claim `intel-claim-template-decode`) |
| Target hardware | Intel Arc Pro B60 | As documented in the guide's hardware table |

---
