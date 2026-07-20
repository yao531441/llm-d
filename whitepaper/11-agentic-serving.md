# 3.1 Agentic Serving 🚧

**Status**: 🚧 documented from official repo sources, not yet run hands-on. This is a **workload
composition guide**, not a standalone deployable overlay — its two ready-made hardware-specific
deployments (NVIDIA H200, Google TPU v7) do not include an Intel XPU variant; Intel XPU users
compose the same building blocks manually as described below.

## Overview

Agentic Serving is a horizontal, workload-centric umbrella guide for serving agentic *programs*
(e.g. coding agents) on llm-d — it composes several capability guides into one recommended,
cohesive deployment rather than being a single new feature. Source: `guides/agentic-serving/README.md`.

The reference workload is **long-horizon loops** (agentic code generation): deep multi-turn
sessions over large, repository-scale contexts with tool-call pauses between turns. Three
behaviors drive the design: prefill-heavy/decode-light (large context dominates TTFT), high
reusable locality (cache hit rate — not FLOPs — sets throughput), and bursty/stateful arrivals
(tool pauses leave sessions idle, then resume in bursts).

**The optimization stack** (each layer already covered elsewhere in this whitepaper):

| Layer | Chapter | What it does for the workload |
|---|---|---|
| [Optimized Baseline](01-optimized-baseline.md) | 1.1 | Prefix-cache scorer routes a turn to the replica already holding its prefix |
| [Tiered Prefix Cache](04-tiered-prefix-cache.md) | 1.4 | Offloads KV cache beyond accelerator memory so idle sessions restore on resume instead of recomputing prefill |
| [Precise Prefix Cache Routing](03-precise-prefix-cache-routing.md) | 1.3 | Exact, global cache-state view enabling session-centric orchestration |
| [P/D Disaggregation](02-pd-disaggregation.md) | 1.2 | Separates prefill/decode pools so heavy prefill never stalls token generation |

Upstream ships two **ready-made** deployments composing this stack, neither of which targets
Intel XPU:

- `nemotron-3-ultra-550b-h200.md` — P/D-disaggregated serving on 8× NVIDIA H200 with CPU
  KV-offloading and ready-to-use coding-agent client configs.
- `qwen3-coder-480b-tpu.md` — routing + CPU KV-offloading on 8× Google TPU v7x (2x2x1).

## Prerequisites

- Chapter 0 (Common Installation) complete.
- Each of the four composed guides' own prerequisites (Chapters 1.1–1.4 of this whitepaper),
  since Agentic Serving is additive on top of them rather than a replacement.

## Deployment Steps (Intel XPU — compose the building blocks manually)

Since no ready-made Intel XPU deployment ships upstream, assemble the stack yourself from the
already-validated Chapter 1 building blocks, following the same pattern as the two upstream
examples (routing + KV-offloading, optionally + P/D disaggregation for larger models):

```bash
# 1. Deploy P/D Disaggregation on Intel XPU as the serving foundation for a large model
#    (see Chapter 1.2 for full steps) — this gives you separate prefill/decode pools.

# 2. Layer Tiered Prefix Cache's KV-offloading connector on top of the same model server
#    (see Chapter 1.4) so idle agentic sessions can resume from offloaded KV state instead of
#    recomputing the full prompt prefix.

# 3. Deploy the router with BOTH the P/D and tiered-prefix-cache values files layered together
#    (adjust chart/values paths to match your actual guide combination):
helm install agentic-xpu \
    ${ROUTER_STANDALONE_CHART} \
    -f ${REPO_ROOT}/guides/recipes/router/base.values.yaml \
    -f ${REPO_ROOT}/guides/pd-disaggregation/router/pd-disaggregation.values.yaml \
    -f ${REPO_ROOT}/guides/tiered-prefix-cache/router/tiered-prefix-cache.values.yaml \
    -n ${NAMESPACE} --version ${ROUTER_CHART_VERSION}
```

> **Caveat**: this composition has not been validated by upstream CI for Intel XPU (unlike the
> individual Chapter 1 guides, which do have Intel XPU CI or documented validated configs). Treat
> this as a starting point requiring your own end-to-end validation, not a tested recipe.

## Verification

Reuse each composed guide's own verification steps (P/D disaggregation pod health, tiered
prefix-cache offload connector health) — see Chapters 1.2 and 1.4.

## Inference Test

Use a realistic agentic-style prompt sequence (large repository-scale context, multiple turns
reusing the same prefix) rather than a single short completion, since the whole point of this
composition is prefix-cache reuse across turns:

```bash
curl -X POST http://${IP}/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model": "'${MODEL_NAME}'", "messages": [
        {"role": "system", "content": "<large repository context>"},
        {"role": "user", "content": "Refactor this function to be async"}
      ], "max_tokens": 500}'
```

## Troubleshooting

- If cache-reuse benefits don't materialize, confirm Precise Prefix Cache Routing's
  `--block-size` matches the router's `tokenProcessorConfig.blockSize` exactly (both default 64
  — see [Chapter 1.3](03-precise-prefix-cache-routing.md)) — a mismatch silently degrades
  cache-aware scoring rather than erroring out.
- If offloaded sessions don't resume correctly, check that Tiered Prefix Cache's
  `securityContext.privileged: true` requirement (Chapter 1.4) is actually satisfied under your
  cluster's Pod Security Admission policy.

## Cleanup

```bash
helm uninstall agentic-xpu -n ${NAMESPACE}
# then clean up each composed guide's model-server overlay per its own Chapter 1 cleanup steps
```

## Config Reference

| Field | Value | Notes |
|---|---|---|
| Composed layers | Optimized Baseline + Tiered Prefix Cache + Precise Prefix Cache Routing + P/D Disaggregation | |
| Ready-made deployments (upstream) | NVIDIA H200 (Nemotron-3-Ultra-550B), Google TPU v7 (Qwen3-Coder-480B) | neither targets Intel XPU |
| Intel XPU status | Manual composition of Chapter 1 building blocks | not upstream-CI-validated as a combined stack |
| Benchmark harness | `inference-perf` via `llm-d-benchmark`, replaying agentic-style traces | see guide for exact preset |
