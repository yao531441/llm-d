# 2.4 Rollouts

> **Repo location note**: the guides-index (`guides/README.md`) links to `./rollouts/README.md`,
> but that path has moved to `docs/operations/rollouts/` as part of a broader documentation
> reorganization ("Reorganize part 2: create two new pillars, operations and infrastructure").
> The commands below reference the current `docs/operations/rollouts/` path.

## Overview

Hardware-agnostic — directly useful for migrating an existing NVIDIA deployment to Intel XPU (or
vice versa) with minimal disruption, see "Node/Accelerator Update Roll Out" below.

Rollout guides cover three incremental deployment strategies for updating inference
infrastructure with minimal service disruption. Source: `docs/operations/rollouts/README.md`.

| Strategy | Mechanism | Deployment mode | Best for |
|---|---|---|---|
| **Rolling Update** | Standard Kubernetes Deployment rolling update (e.g. 25% at a time) | Standalone or Gateway | General, non-critical updates; conserves compute |
| **Blue-Green Update** | Second complete `InferencePool` + `HTTPRoute` traffic-weight splitting | Gateway only | Critical production rollouts, fast rollback, canary by header |
| **LoRA Adapter Rollout** | `InferenceModelRewrite` mapping model names to adapter versions | Standalone or Gateway | Updating LoRA adapters without touching base model/infra |

**Why this matters for Intel XPU specifically**: Blue-Green Update's documented use case #1 is
literally "**Node(compute, accelerator) update roll out**" — safely migrating inference workloads
to new node hardware or accelerator configurations without interrupting service. This is the
recommended mechanism for migrating an existing NVIDIA `InferencePool` to Intel XPU nodes
incrementally (e.g. 1% → 10% → 50% → 100% traffic shift) rather than a hard cutover.

## Prerequisites

- Chapter 0 (Common Installation) complete, with a working deployment already running (e.g.
  [Optimized Baseline](01-optimized-baseline.md) on Intel XPU) that you intend to update/migrate.
- For Blue-Green Update: llm-d Router in **Gateway mode** (a Kubernetes Gateway + HTTPRoute) — see
  `docs/infrastructure/gateway/`; Blue-Green does not work in standalone mode.

## Deployment Steps

### Rolling Update

Standard Kubernetes mechanics — update the vLLM image/tag or config in your existing Helm
values/Kustomize overlay and re-apply; Kubernetes replaces pods incrementally while old pods keep
serving traffic. No llm-d-specific steps beyond your normal `helm upgrade` / `kubectl apply -k`.

### Blue-Green Update — example: Intel XPU node/accelerator migration

Starting from an existing `InferencePool` (e.g. `vllm-qwen3-32b` on NVIDIA GPU nodes):

```bash
# 1. Deploy a second, complete InferencePool (the "green" pool) on Intel XPU nodes,
#    with a different Helm release name / selector — e.g. by applying the Optimized
#    Baseline Intel XPU overlay under a new name:
kubectl kustomize ${REPO_ROOT}/guides/optimized-baseline/modelserver/xpu/vllm/ \
  | sed "s/optimized-baseline/vllm-qwen3-32b-new/g" \
  | kubectl apply -n ${NAMESPACE} -f -

# 2. Edit the HTTPRoute to split traffic between old (blue, NVIDIA) and new (green, Intel XPU)
kubectl edit httproute llm-route
```

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: llm-route
spec:
  parentRefs:
    - group: gateway.networking.k8s.io
      kind: Gateway
      name: inference-gateway
  rules:
    - backendRefs:
        - group: inference.networking.k8s.io
          kind: InferencePool
          name: vllm-qwen3-32b       # old (blue)
          weight: 90
        - group: inference.networking.k8s.io
          kind: InferencePool
          name: vllm-qwen3-32b-new   # new (green, Intel XPU)
          weight: 10
      matches:
        - path:
            type: PathPrefix
            value: /
```

Gradually increase the green weight (10 → 50 → 100) as you validate correctness/performance on
Intel XPU, then finish the rollout by setting the green pool's weight to 100 and removing the
`backendRefs` entry for the old pool entirely. Roll back instantly at any point by flipping the
weights back.

### LoRA Adapter Rollout

See `docs/operations/rollouts/adapter-rollout.md` — uses `InferenceModelRewrite` to gradually
shift traffic between adapter versions without any infrastructure change. Fully accelerator
agnostic; identical on Intel XPU.

## Verification

```bash
IP=$(kubectl get gateway/inference-gateway -o jsonpath='{.status.addresses[0].value}'); PORT=80

# send a batch of requests and confirm the observed split roughly matches the configured weights
for i in $(seq 1 20); do
  curl -s -o /dev/null -w "%{http_code}\n" ${IP}:${PORT}/v1/completions \
    -H 'Content-Type: application/json' \
    -d '{"model":"vllm-qwen3-32b","prompt":"ping","max_tokens":1}'
done
```

Cross-check which pool actually served each request via response headers or per-pool EPP logs.

## Inference Test

```bash
curl -i ${IP}:${PORT}/v1/completions -H 'Content-Type: application/json' -d '{
  "model": "vllm-qwen3-32b",
  "prompt": "Write as if you were a critic: San Francisco",
  "max_tokens": 100,
  "temperature": 0
}'
```

## Troubleshooting

- Blue-Green **requires Gateway mode** — attempting this in standalone mode has no `HTTPRoute` to
  edit; use Rolling Update or LoRA Adapter Rollout instead if you're on standalone.
- Keep the old (blue) `InferencePool` and its nodes running until the new (green) pool is fully
  validated — this is your rollback path; deleting it early forfeits instant rollback.
- If traffic doesn't appear to split according to configured weights, confirm both
  `InferencePool`s are correctly referenced in `backendRefs` and that neither pool's own
  Helm chart was installed with `httpRoute.create=true` (a pool-level catch-all route will
  conflict with this guide's manually-edited `HTTPRoute`, the same conflict called out in
  [Multi-Model Routing](12-multi-model-routing.md)).

## Cleanup

```bash
# Once fully migrated to the new (green) pool, remove the old one:
helm uninstall vllm-qwen3-32b -n ${NAMESPACE}
```

## Config Reference

| Field | Value | Notes |
|---|---|---|
| Strategy | Blue-Green (`HTTPRoute` weight-based traffic split) | Gateway mode only |
| `backendRefs[].weight` | integer, relative | e.g. 90/10 → 50/50 → 0/100 |
| Rollback | flip weights back to 100/0 | instant, no pod recreation needed |
| Alternative strategy | Rolling Update | standalone + gateway, in-place pod replacement |
| Alternative strategy | LoRA Adapter Rollout | `InferenceModelRewrite`, no infra change |
