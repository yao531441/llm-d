# 5.2 Encode Disaggregation (Multimodal) ➖

**Status**: ➖ not applicable — confirmed **no Intel XPU backend exists** for this guide.

## Overview

`guides/multimodal-serving/e-disaggregation/` is an experimental guide deploying
`Qwen/Qwen3-VL-32B-Instruct` with **encode disaggregation**: offloading the multimodal encoding
stage (converting raw images/video/audio into embeddings) to dedicated Encode workers, consumed by
prefill/decode workers alongside text tokens. Two topologies are supported: **E/PD** (Encode
separated from combined Prefill+Decode) and **E/P/D** (full three-stage pipeline). Source:
`guides/multimodal-serving/e-disaggregation/README.md`.

This is distinct from the **Multimodal Serving (Aggregated)** case already covered in
[Chapter 1.6](06-multimodal-serving.md), which *does* have a dedicated Intel XPU overlay. Encode
Disaggregation is the more advanced, encode-stage-separated sibling of that guide.

## Why this chapter is empty of deployment steps

The guide's own "Supported Hardware Backends" table lists exactly one backend:

| Backend | Directory | Notes |
|---|---|---|
| NVIDIA GPU (vLLM) | `modelserver/gpu/vllm/` | vLLM with encode disaggregation |

There is no `modelserver/xpu/` (or any other non-NVIDIA) entry. Unlike the router-layer/composite
guides in Chapters 2–3 (which are hardware-agnostic and simply reuse whichever model-server
overlay you deploy), Encode Disaggregation's model-server manifests themselves are NVIDIA-specific
and there is no accelerator-agnostic substitution path documented upstream, unlike
[No-Kubernetes Deployment](15-no-kubernetes-deployment.md) where the substitution is
straightforward. Writing speculative Intel XPU steps here would not be traceable to any real
repository content, so this chapter intentionally stops at the scope note.

## If Intel XPU support is added upstream

Follow the same chapter template as [Chapter 1.6](06-multimodal-serving.md) once a
`modelserver/xpu/` overlay appears for this guide — check `guides/multimodal-serving/e-disaggregation/`
for updates, and update this chapter's status from ➖ to 🚧/✅ accordingly.

## Config Reference

| Field | Value | Notes |
|---|---|---|
| Reference model | `Qwen/Qwen3-VL-32B-Instruct` | |
| Topologies | E/PD (2 encode + 8× TP2 combined prefill/decode), E/P/D (2 encode + 2× TP4 prefill + 2× TP4 decode) | |
| Intel XPU support | None upstream | ➖ not applicable today |
| Related, Intel-XPU-supported case | [Multimodal Serving (Aggregated)](06-multimodal-serving.md) | simpler topology, has a real `modelserver/xpu/vllm` overlay |
