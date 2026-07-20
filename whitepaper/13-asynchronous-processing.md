# 4.1 Asynchronous Processing 🚧

**Status**: 🚧 documented from official repo sources, not yet run hands-on. Hardware-agnostic —
the Async Processor dispatches to whatever llm-d Router endpoint you give it; the backing model
server can be any Optimized Baseline overlay, including Intel XPU.

## Overview

The [Async Processor](https://github.com/llm-d-incubation/llm-d-async) processes inference
requests asynchronously via a queue-based architecture — ideal for latency-insensitive workloads
or filling idle accelerator capacity. It decouples submission from execution (clients submit to a
queue, retrieve results later), optimizes resource utilization, and provides automatic retries
without impacting real-time traffic. Source: `guides/asynchronous-processing/README.md`.

Two supported queue implementations:

- **GCP Pub/Sub** (`gcp-pubsub/README.md`) — cloud-native, scalable messaging.
- **Redis Sorted Set** (`redis/README.md`) — high-performance, persisted, prioritized queue.

## Prerequisites

- Kubernetes v1.31+ (Kind/Minikube for local dev; GKE/AKS/OpenShift for production).
- A Gateway control plane deployed (`docs/infrastructure/gateway/README.md`).
- An existing [Optimized Baseline](01-optimized-baseline.md) stack on Intel XPU to dispatch
  requests to — Async Processor is additive, not a replacement for the model-serving stack.

## Deployment Steps

```bash
export REPO_ROOT=$(realpath $(git rev-parse --show-toplevel))

# 1. Get the IP of the llm-d Router deployed for Optimized Baseline (Chapter 1.1)
# Standalone Mode:
export IP=$(kubectl get service optimized-baseline-epp -n llm-d-optimized-baseline -o jsonpath='{.spec.clusterIP}')
# Gateway Mode:
export IP=$(kubectl get gateway llm-d-inference-gateway -n llm-d-optimized-baseline -o jsonpath='{.status.addresses[0].value}')

# 2. Choose a queue implementation and review/edit its values.yaml:
#    guides/asynchronous-processing/gcp-pubsub/values.yaml
#    guides/asynchronous-processing/redis/values.yaml

# 3. Deploy the Async Processor
export NAMESPACE=llm-d-async
export MQ_PROVIDER=redis   # or gcp-pubsub
export ASYNC_VERSION=0.6.1

helm install async-processor \
    oci://ghcr.io/llm-d-incubation/charts/async-processor \
    -f ${REPO_ROOT}/guides/asynchronous-processing/${MQ_PROVIDER}/values.yaml \
    --set ap.igwBaseURL=http://${IP}:80 \
    -n ${NAMESPACE} --create-namespace --version ${ASYNC_VERSION}
```

## Verification

```bash
kubectl get pods -n ${NAMESPACE}
kubectl logs -n ${NAMESPACE} -l app.kubernetes.io/name=async-processor --tail=50
```

## Inference Test

Testing steps are queue-implementation specific — follow the "Testing" section of whichever
sub-guide you chose:

- Redis: `guides/asynchronous-processing/redis/README.md#testing`
- GCP Pub/Sub: `guides/asynchronous-processing/gcp-pubsub/README.md#testing`

Both follow the same submit-then-poll pattern: publish a request payload to the configured queue,
then poll for the corresponding result once the Async Processor has dispatched it to the Intel
XPU-backed Optimized Baseline endpoint and received a response.

## Troubleshooting

- If the Async Processor never dispatches requests, confirm `ap.igwBaseURL` actually resolves to
  a live llm-d Router endpoint (`curl` it directly first) — a common mistake is pointing at the
  wrong namespace's Router IP.
- Redis is documented as sufficient for both development and production priority-queue needs;
  GCP Pub/Sub requires GCP-side IAM/topic setup not covered by the llm-d chart itself.

## Cleanup

```bash
helm uninstall async-processor -n ${NAMESPACE}
```

## Config Reference

| Field | Value | Notes |
|---|---|---|
| Queue implementations | GCP Pub/Sub, Redis Sorted Set | choose one via `MQ_PROVIDER` |
| Dispatch target | `ap.igwBaseURL` | must point at a live llm-d Router (any accelerator, incl. Intel XPU) |
| Chart | `oci://ghcr.io/llm-d-incubation/charts/async-processor` | separate incubation repo |
