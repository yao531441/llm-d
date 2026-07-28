# 2.3 Workload Autoscaling

## Overview

Hardware-agnostic — scales whatever model-server Deployment you already run (including the Intel
XPU Optimized Baseline overlay); no accelerator-specific autoscaling logic exists.

CPU/GPU utilization metrics are poor autoscaling signals for LLM inference — accelerators often
sit near 100% "utilized" during active batching regardless of actual load. This guide covers two
proactive, SLO-aware autoscaling paths built on real inference-demand signals (queue depth,
in-flight requests, KV-cache pressure). Source: `guides/workload-autoscaling/README.md`.

| Path | Signal source | Best for |
|---|---|---|
| **KEDA + EPP Metrics** (`README.hpa-epp.md`) | EPP-emitted queue depth / running-request-count metrics | Homogeneous hardware, each model-server pool scaled independently |
| **HPA + WVA Metrics** (`README.wva.md`) | Workload Variant Autoscaler's `wva_desired_replicas` (KV utilization, queue depth, perf budgets) | Multi-variant deployments across heterogeneous hardware, cost-aware scaling |

An experimental **Replica Rebalancing** feature (`README.replica-rebalancing.md`) adjusts max
replica counts across annotated HPAs sharing a GPU budget — explicitly flagged upstream as a
proof-of-concept, not production-ready.

KEDA (or the OpenShift Custom Metrics Autoscaler Operator) is the recommended metrics adapter for
both paths — Prometheus Adapter is deprecated. The **KEDA + EPP Metrics** path documents KEDA as
the primary supported route. The **HPA + WVA Metrics** path can use KEDA-managed HPA (recommended)
or a plain HPA reading the `wva_desired_replicas` external metric directly, without KEDA.

## Prerequisites

- Chapter 0 (Common Installation) complete, plus a running **Prometheus** instance (see
  `docs/operations/observability/setup.md`) — WVA requires TLS enabled on Prometheus.
- **KEDA** installed (recommended path) — see the [KEDA install guide](https://keda.sh/docs/2.20/deploy/).
  On OpenShift, use the Custom Metrics Autoscaler Operator instead.
- Complete [Optimized Baseline](01-optimized-baseline.md) on Intel XPU first, **including its
  optional monitoring step** — this guide layers on top of it and needs the EPP metrics endpoint
  already being scraped.

## Deployment Steps (KEDA + EPP Metrics path)

```bash
export REPO_ROOT=$(realpath $(git rev-parse --show-toplevel))
source ${REPO_ROOT}/guides/env.sh
export NAMESPACE=llm-d-optimized-baseline
export MONITORING_NAMESPACE=llm-d-monitoring
export KEDA_NAMESPACE=keda

# Upgrade the Optimized Baseline router with the KEDA+EPP overlay (enables EPP Flow Control)
# — reapply the monitoring feature values so the EPP metrics port/ServiceMonitor stay enabled
helm upgrade optimized-baseline \
  ${ROUTER_STANDALONE_CHART} \
  -f ${REPO_ROOT}/guides/recipes/router/base.values.yaml \
  -f ${REPO_ROOT}/guides/optimized-baseline/router/optimized-baseline.values.yaml \
  -f ${REPO_ROOT}/guides/recipes/router/features/monitoring.values.yaml \
  -f ${REPO_ROOT}/guides/workload-autoscaling/keda-epp/router.values.yaml \
  -n ${NAMESPACE} --version ${ROUTER_CHART_VERSION}
```

The rest of the KEDA `ScaledObject` setup (targeting `llm_d_epp_flow_control_queue_size` and
`llm_d_epp_request_running` via PromQL) is identical regardless of the accelerator backing the
model-server Deployment — see `guides/workload-autoscaling/README.hpa-epp.md` for the full
`ScaledObject` manifest and PromQL queries.

For the WVA path (multi-variant, cost-aware scaling across heterogeneous hardware), see
`guides/workload-autoscaling/README.wva.md` — most relevant if you run Intel XPU alongside other
accelerator types and want WVA to prefer the cheaper variant automatically.

## Verification

```bash
kubectl logs deployment/optimized-baseline-epp -n ${NAMESPACE} | grep "Flow Control enabled"
kubectl get servicemonitor -n ${NAMESPACE}

# confirm EPP exposes the metrics directly
kubectl port-forward -n ${NAMESPACE} service/optimized-baseline-epp 9091:9090 &
curl -s http://localhost:9091/metrics | grep -E 'llm_d_epp_flow_control_queue_size|llm_d_epp_request_running'
```

Then, in your Prometheus query UI, confirm the metric is actually being scraped:

```promql
sum(llm_d_epp_flow_control_queue_size{namespace="llm-d-optimized-baseline",service="optimized-baseline-epp",model_name="Qwen/Qwen3-32B"})
```

## Inference Test

Drive sustained concurrent load against the Optimized Baseline endpoint (see
[Optimized Baseline's Inference Test](01-optimized-baseline.md)) and watch the `ScaledObject`'s
managed HPA add replicas as queue depth/running-request-count rise, then scale back down as load
subsides.

## Troubleshooting

- **Do not create a separate HPA** for a Deployment already managed by a KEDA `ScaledObject` —
  two HPAs targeting the same Deployment produce conflicting scaling decisions. KEDA's generated
  HPA remains visible for inspection only.
- If metrics never populate in Prometheus, confirm the `ServiceMonitor` survived the router
  `helm upgrade` in the deployment step — reapplying the KEDA+EPP overlay without also
  re-including the monitoring values file will silently disable metric scraping.
- WVA requires TLS on the Prometheus endpoint; if the WVA controller can't reach Prometheus,
  check certificate/auth configuration first.

## Cleanup

```bash
# Remove the KEDA ScaledObject (see README.hpa-epp.md for its exact name)
kubectl delete scaledobject <scaledobject-name> -n ${NAMESPACE}

# Revert the router to the plain Optimized Baseline values (drop the keda-epp overlay)
helm upgrade optimized-baseline \
  ${ROUTER_STANDALONE_CHART} \
  -f ${REPO_ROOT}/guides/recipes/router/base.values.yaml \
  -f ${REPO_ROOT}/guides/optimized-baseline/router/optimized-baseline.values.yaml \
  -n ${NAMESPACE} --version ${ROUTER_CHART_VERSION}
```

## Config Reference

| Field | Value | Notes |
|---|---|---|
| Scaling signal (KEDA+EPP) | `llm_d_epp_flow_control_queue_size`, `llm_d_epp_request_running` | EPP-native metrics |
| Scaling signal (WVA) | `wva_desired_replicas` | aggregates KV utilization + queue depth + perf budget |
| Scale-to-zero | Supported on both paths | |
| Additional components (KEDA path) | KEDA, Prometheus | no Prometheus Adapter needed |
| Additional components (WVA path) | WVA controller, Prometheus (TLS required) | |
| Replica Rebalancing | experimental, proof-of-concept only | not production-ready per upstream |
