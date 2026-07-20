<!--
Intel XPU Deployment Whitepaper — llm-d
This is the index/table-of-contents file. Each chapter/case is its own Markdown file in this
directory so no single document grows unmanageably long. Convert individual files or the whole
directory to PDF/Word with pandoc — see ../README.md.
Template reference: ../template.md
-->

# Intel XPU Deployment Whitepaper: llm-d

> Target hardware: Intel Data Center GPU (Max series, Arc Pro B60) exposed to Kubernetes via the
> `gpu.intel.com` Dynamic Resource Allocation (DRA) device class

## Why the old wiki BKM no longer applies

llm-d went through an architecture change that directly affects how this whitepaper is written.
The table below lists the key differences so readers understand why the old wiki content
(and the reference document this project started from) is out of date:

| Old approach (wiki BKM / earlier reference doc) | Current approach (main branch) |
|---|---|
| One-shot `helmfile apply -e xpu` deploying `infra-pd` / `gaie-pd` / `ms-pd` charts together | Separate `helm install` (Router) + `kubectl apply -k` (Kustomize model-server overlay) steps |
| Gateway/CRD prerequisites under `guides/prereq/gateway-provider` | Moved to `docs/infrastructure/gateway/` |
| GPU declared via `resources.limits."gpu.intel.com/xe"` | Declared via Kubernetes **DRA** `ResourceClaimTemplate` with `deviceClassName: gpu.intel.com` |
| A single, guide-specific `values_xpu.yaml` | A Kustomize overlay directory per guide (`modelserver/xpu/vllm/`) with `patch-vllm.yaml` / `patch-decode.yaml` / `patch-prefill.yaml` + a `resource-claim-template(s).yaml` |

**Bottom line:** any old BKM referencing `helmfile`, `values_xpu.yaml`, or
`gpu.intel.com/i915` / `gpu.intel.com/xe` resource `limits` is obsolete. This whitepaper is
written entirely from the current state of the repository.

---

## Table of Contents

> Status icons: ✅ verified working / 🚧 documented from official sources but not yet run hands-on /
> 📝 outline only, full deployment steps not yet written / ➖ not applicable (no Intel XPU backend exists upstream)

- [00-common-installation.md](00-common-installation.md) — Chapter 0. Common Installation (applies to every case below)
- **Chapter 1. Intel XPU Well-Lit Paths** (real Intel XPU overlay confirmed in-repo; deployment steps documented but not yet hands-on validated on a live cluster)
  - [01-optimized-baseline.md](01-optimized-baseline.md) — 1.1 Optimized Baseline 🚧
  - [02-pd-disaggregation.md](02-pd-disaggregation.md) — 1.2 P/D Disaggregation 🚧
  - [03-precise-prefix-cache-routing.md](03-precise-prefix-cache-routing.md) — 1.3 Precise Prefix Cache Routing 🚧
  - [04-tiered-prefix-cache.md](04-tiered-prefix-cache.md) — 1.4 Tiered Prefix Cache 🚧
  - [05-wide-ep.md](05-wide-ep.md) — 1.5 Wide Expert Parallelism 🚧
  - [06-multimodal-serving.md](06-multimodal-serving.md) — 1.6 Multimodal Serving (Aggregated) 🚧
- **Chapter 2. Router-Layer Features** (hardware-agnostic, compose on top of Chapter 1) — 🚧 fully written
  - [07-flow-control.md](07-flow-control.md) — 2.1 Flow Control
  - [08-predicted-latency-routing.md](08-predicted-latency-routing.md) — 2.2 Predicted Latency-Based Routing
  - [09-workload-autoscaling.md](09-workload-autoscaling.md) — 2.3 Workload Autoscaling
  - [10-rollouts.md](10-rollouts.md) — 2.4 Rollouts (note: repo path moved from `guides/rollouts/` to `docs/operations/rollouts/`)
- **Chapter 3. Composite Workloads** — 🚧 fully written
  - [11-agentic-serving.md](11-agentic-serving.md) — 3.1 Agentic Serving (Intel XPU: manual composition of Chapter 1 guides, no ready-made upstream deployment)
  - [12-multi-model-routing.md](12-multi-model-routing.md) — 3.2 Multi-Model Routing
- **Chapter 4. Experimental Guides** — 🚧 fully written
  - [13-asynchronous-processing.md](13-asynchronous-processing.md) — 4.1 Asynchronous Processing
  - [14-batch-gateway.md](14-batch-gateway.md) — 4.2 Batch Gateway
- **Chapter 5. Other Deployment Forms**
  - [15-no-kubernetes-deployment.md](15-no-kubernetes-deployment.md) — 5.1 No-Kubernetes Deployment 🚧 (NVIDIA-only upstream; this chapter documents the exact Intel XPU substitution)
  - [16-encode-disaggregation.md](16-encode-disaggregation.md) — 5.2 Encode Disaggregation (Multimodal) ➖ (confirmed no Intel XPU backend exists)
- [appendix-a-env-vars.md](appendix-a-env-vars.md) — Appendix A. Environment Variable Reference
- [appendix-b-known-issues.md](appendix-b-known-issues.md) — Appendix B. Known Issues
- [tracking.md](tracking.md) — Appendix C. Case Verification Status (live tracker)

### Scope note: which guides actually ship an Intel XPU configuration

A repo-wide search of `guides/**/*.md` and `guides/**/*.yaml` for `xpu`/`intel` found **dedicated
Kustomize overlays** (`modelserver/xpu/...`) in exactly six guides: `optimized-baseline`,
`pd-disaggregation`, `precise-prefix-cache-routing`, `tiered-prefix-cache`, `wide-ep-lws`, and
`multimodal-serving/aggregation`. These are Chapter 1, and are the only cases with complete,
fully-written deployment chapters today.

The remaining guides (`flow-control`, `predicted-latency-routing`, `workload-autoscaling`,
`rollouts`, `agentic-serving`, `multi-model-routing`, `asynchronous-processing`, `batch-gateway`,
`no-kubernetes-deployment`) are **router-layer or composite features that are accelerator-agnostic
by design** — they sit on top of whatever model-server overlay you deploy (including the Intel XPU
overlay from `optimized-baseline`), and reference it rather than shipping a separate XPU overlay of
their own. All nine now have fully-written deployment chapters (Chapters 2–5, 🚧).
`no-kubernetes-deployment` is explicitly documented as NVIDIA + vLLM specific, with the Intel XPU
substitution spelled out in full in its chapter — it is not a maintained, first-class Intel XPU
path upstream, but the chapter is complete. `encode-disaggregation` (also discovered via this
search, under `multimodal-serving/e-disaggregation/`) has **no** Intel XPU backend at all — its
"Supported Hardware Backends" table lists NVIDIA GPU only — so it is documented as ➖ not applicable
rather than given deployment steps. All case-by-case detail is tracked in `tracking.md`.
