# 3.2 Multi-Model Routing (In Progress)

**Status**: documented from official repo sources, not yet run hands-on. Hardware-agnostic —
the Inference Payload Processor (IPP) and HTTPRoute-based routing operate purely at the Gateway
layer; each backing `InferencePool` can independently be an Intel XPU deployment.

## Overview

Deploys the **Inference Payload Processor (IPP)** to serve multiple LLMs behind a single Gateway
endpoint. IPP extracts the model name from the request body and sets routing headers; HTTPRoutes
then match those headers to direct traffic to the correct `InferencePool`. Source:
`guides/multi-model-routing/README.md`.

Use this guide when you need to serve multiple base models (e.g. Qwen for chat, DeepSeek for
reasoning) behind one OpenAI-compatible endpoint. For a single model, use
[Optimized Baseline](01-optimized-baseline.md) instead.

## Prerequisites

- Chapter 0 (Common Installation) complete.
- **Multiple `InferencePool`s already deployed**, each serving a different base model — follow
  [Optimized Baseline](01-optimized-baseline.md) independently for each pool you want to add
  (e.g. once on Intel XPU for Qwen, once for a second model). When deploying each pool for this
  guide, do **not** pass `--set httpRoute.create=true` — this guide's own HTTPRoutes (deployment
  step 3) handle model-name-header-based routing, and a pool-level catch-all route would conflict.
- A Kubernetes Gateway (Istio, GKE, AgentGateway, etc.) — see `docs/infrastructure/gateway/README.md`.

## Deployment Steps

```bash
export REPO_ROOT=$(realpath $(git rev-parse --show-toplevel))
source ${REPO_ROOT}/guides/env.sh
export GUIDE_NAME="multi-model-routing"
export NAMESPACE="llm-d-multi-model"

kubectl create namespace ${NAMESPACE} --dry-run=client -o yaml | kubectl apply -f -

# 1. Deploy IPP (clone its own repo; it is not part of the llm-d repo)
git clone https://github.com/llm-d/llm-d-inference-payload-processor.git /tmp/ipp
helm install ipp /tmp/ipp/config/charts/payload-processor \
    --set provider.name=istio \
    --set inferenceGateway.name=llm-d-inference-gateway \
    --set payloadProcessor.image.tag=v0.1.0-rc.4 \
    -n ${NAMESPACE}
# use --set provider.name=gke on GKE, or omit provider.name for standalone (no Gateway)

kubectl get pods -n ${NAMESPACE} -l app=payload-processor

# 2. Register each base model with IPP via ConfigMap (edit manifests/configmaps.yaml to match
#    your actual Intel XPU model names/pools first)
kubectl apply -n ${NAMESPACE} -f ${REPO_ROOT}/guides/multi-model-routing/manifests/configmaps.yaml
# each ConfigMap needs label inference.llm-d.ai/ipp-managed: "true" and a baseModel matching
# your Intel XPU pool's actual served model name

# 3. Configure HTTPRoutes matching IPP's injected X-Gateway-Base-Model-Name header
#    (edit manifests/httproutes.yaml: parentRefs -> your Gateway, backendRefs -> your pool names)
kubectl apply -n ${NAMESPACE} -f ${REPO_ROOT}/guides/multi-model-routing/manifests/httproutes.yaml
```

## Verification

```bash
kubectl logs -n ${NAMESPACE} -l app=payload-processor --tail=100
kubectl get configmap -l inference.llm-d.ai/ipp-managed=true -n ${NAMESPACE}
# confirm requests reach the correct pool (replace <pool-name> with your InferencePool name)
kubectl logs -n ${NAMESPACE} -l llm-d-router-gateway=<pool-name>-epp --tail=20
```

## Inference Test

```bash
export GATEWAY_IP=$(kubectl get gateway llm-d-inference-gateway -n ${NAMESPACE} -o jsonpath='{.status.addresses[0].value}')

# Request routed to your first (e.g. Intel XPU Qwen) pool
curl -X POST "http://${GATEWAY_IP}/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{"model": "Qwen/Qwen3-32B", "messages": [{"role": "user", "content": "Hello"}]}'

# Request routed to a second pool
curl -X POST "http://${GATEWAY_IP}/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{"model": "deepseek/DeepSeek-r1", "messages": [{"role": "user", "content": "Solve this problem"}]}'
```

### Advanced: LoRA Adapter Routing

Once base model routing works, extend a ConfigMap with an `adapters` field to route LoRA adapter
names to their base model's pool:

```bash
kubectl apply -n ${NAMESPACE} -f - <<EOF
apiVersion: v1
kind: ConfigMap
metadata:
  name: qwen-model-mapping
  labels:
    inference.llm-d.ai/ipp-managed: "true"
data:
  baseModel: "Qwen/Qwen3-32B"
  adapters: |
    - food-review-1
    - travel-assistant
EOF

curl -X POST "http://${GATEWAY_IP}/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{"model": "food-review-1", "messages": [{"role": "user", "content": "Review this restaurant"}]}'
```

All model and adapter names must be globally unique across all `InferencePool`s/ConfigMaps.

## Troubleshooting

- Requests routed to the wrong pool (or 404): confirm the ConfigMap's `baseModel` value matches
  the model name clients send exactly, and that the `inference.llm-d.ai/ipp-managed: "true"`
  label is present — IPP logs discovered model mappings at startup, check them first.
- If a pool's traffic bypasses IPP header-based routing entirely, verify that pool's Helm install
  did **not** include `--set httpRoute.create=true` (see Prerequisites) — its own catch-all route
  would out-compete this guide's header-matched HTTPRoutes.

## Cleanup

```bash
kubectl delete -n ${NAMESPACE} -f ${REPO_ROOT}/guides/multi-model-routing/manifests/httproutes.yaml
kubectl delete -n ${NAMESPACE} -f ${REPO_ROOT}/guides/multi-model-routing/manifests/configmaps.yaml
helm uninstall ipp -n ${NAMESPACE}
rm -rf /tmp/ipp
kubectl delete namespace ${NAMESPACE}
```

## Config Reference

| Field | Value | Notes |
|---|---|---|
| Routing header | `X-Gateway-Base-Model-Name` | injected by IPP, matched by HTTPRoute |
| ConfigMap label | `inference.llm-d.ai/ipp-managed: "true"` | required for IPP discovery |
| Per-pool Helm flag | must NOT set `httpRoute.create=true` | avoids catch-all route conflicts |
| LoRA routing | `adapters` field in ConfigMap | maps adapter name -> base model's pool |
| IPP repo | `github.com/llm-d/llm-d-inference-payload-processor` | separate repo, not part of `llmd` |
