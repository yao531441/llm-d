# llm-d Whitepaper — Case Verification Status Tracker

Status legend: ✅ verified working / 🚧 documented from official sources, not yet run hands-on /
📝 outline only / ⛔ blocked / ➖ not applicable (no dedicated Intel XPU path exists)

## Chapter 1 — Guides with a real Intel XPU Kustomize overlay in-repo

| # | Case | Path | Status | Owner | Notes |
|---|---|---|---|---|---|
| 0 | Common installation (k8s + GAIE CRD + Router) | `guides/env.sh`, `docs/infrastructure/gateway/` | 🚧 | | Rewritten against current docs; pending hands-on validation on a real Intel XPU cluster |
| 1 | Optimized Baseline | `guides/optimized-baseline` (xpu: `modelserver/xpu/vllm`) | 🚧 | | Has a dedicated Intel XPU E2E CI workflow upstream — highest-confidence case to validate first |
| 2 | P/D Disaggregation | `guides/pd-disaggregation` (xpu: `modelserver/xpu/vllm`) | 🚧 | | First deep-dive case, rewritten from current repo, pending hands-on validation |
| 3 | Precise Prefix Cache Routing | `guides/precise-prefix-cache-routing` (xpu: `modelserver/xpu/vllm`) | 🚧 | | Rewritten from current repo |
| 4 | Tiered Prefix Cache | `guides/tiered-prefix-cache` (xpu: `modelserver/xpu/vllm/base`, `.../lmcache-connector/cpu/base`) | 🚧 | | Requires `privileged: true` — check cluster PSA policy before validating |
| 5 | Wide Expert Parallelism | `guides/wide-ep-lws` (xpu: `modelserver/xpu/vllm`) | 🚧 | | Validated Intel XPU shape documented upstream (DeepSeek-V2-Lite-Chat, 4 XPUs) |
| 6 | Multimodal Serving (Aggregated) | `guides/multimodal-serving/aggregation` (xpu: `modelserver/xpu/vllm`) | 🚧 | | Targets Intel Arc Pro B60 |

## Chapter 2-5 — Router-layer / composite features (accelerator-agnostic, no dedicated XPU overlay)

| # | Case | Path | Status | Owner | Notes |
|---|---|---|---|---|---|
| 7 | Flow Control | `guides/flow-control` | 🚧 | | Fully written; reuses Optimized Baseline Intel XPU overlay via `sed` relabeling |
| 8 | Predicted Latency-Based Routing | `guides/predicted-latency-routing` | 🚧 | | Fully written; reuses Optimized Baseline overlay directly, no relabeling needed |
| 9 | Workload Autoscaling (4 sub-modes) | `guides/workload-autoscaling` | 🚧 | | Fully written; `README.md` / `README.hpa-epp.md` KEDA+EPP path detailed with real commands, WVA path referenced |
| 10 | Rollouts | `docs/operations/rollouts` (moved from `guides/rollouts`) | 🚧 | | Fully written; includes Blue-Green Update example reframed as Intel XPU node/accelerator migration; the guide path itself moved in a repo reorg, noted in the chapter as a reminder to verify current paths |
| 11 | Agentic Serving | `guides/agentic-serving` | 🚧 | | Fully written; no ready-made upstream Intel XPU deployment (H200/TPU only) — chapter shows manual composition of Chapter 1 building blocks, explicitly caveated as not CI-validated as a combined stack |
| 12 | Multi-Model Routing | `guides/multi-model-routing` | 🚧 | | Fully written; IPP + HTTPRoute header-based routing, includes LoRA adapter routing |
| 13 | Asynchronous Processing | `guides/asynchronous-processing` | 🚧 | | Fully written; Async Processor via GCP Pub/Sub or Redis, dispatches to any Optimized Baseline endpoint |
| 14 | Batch Gateway | `guides/batch-gateway` | 🚧 | | Fully written; OpenAI-compatible Batch API, full JSONL upload/submit/monitor/download example |
| 15 | No-Kubernetes Deployment | `guides/no-kubernetes-deployment` | 🚧 | | Fully written; explicitly NVIDIA + vLLM specific upstream, chapter documents the exact Intel XPU substitution (image, `--device=/dev/dri`, XCCL) rather than presenting it as a maintained path |
| 16 | Encode Disaggregation (Multimodal) | `guides/multimodal-serving/e-disaggregation` | ➖ | | Newly discovered guide; "Supported Hardware Backends" table lists NVIDIA GPU (vLLM) only, no Intel XPU entry — documented as not applicable |
| 17 | RL (verl integration) | `guides/rl` | ⚠️ | | `verl-integration.md` has zero hardware-specific references (no CUDA/NVIDIA/XPU mentions); overrides verl's routing via the llm-d scheduler over "vLLM/SGLang actors on Ray" — same pattern as Flow Control / Multi-Model Routing, both confirmed hardware-agnostic. Investigated and found feasible-but-untemplated for Intel XPU; not yet written as a full chapter, and in/out-of-scope decision still pending stakeholder sign-off |

## Recommended next steps

1. Validate Chapter 1 cases on a real Intel XPU cluster, starting with **Optimized Baseline**
   (has upstream CI coverage) and **P/D Disaggregation** (already deep-dived).
2. Hands-on validate the now-fully-written Chapter 2–5 cases on a real Intel XPU cluster,
   confirming the "compose on top of Optimized Baseline" pattern actually works end-to-end for
   each (Flow Control, Predicted Latency Routing, Workload Autoscaling, Rollouts, Agentic Serving,
   Multi-Model Routing, Asynchronous Processing, Batch Gateway, No-Kubernetes Deployment).
3. Confirm scope for `guides/rl` with stakeholders before investing further writing time.
4. Re-check `guides/multimodal-serving/e-disaggregation/` periodically for an added Intel XPU
   `modelserver/xpu/` overlay; upgrade Case 16 from ➖ to 🚧/✅ if one appears.
