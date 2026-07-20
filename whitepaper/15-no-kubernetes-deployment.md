# 5.1 No-Kubernetes Deployment (In Progress)

**Status**: documented from official repo sources, not yet run hands-on. **This guide targets
NVIDIA GPUs + vLLM specifically** — the model-server image, CLI flags, and `--gpus` container
invocation shown upstream are NVIDIA-specific. It is **not** a maintained, first-class Intel XPU
path today; Intel XPU is explicitly left to the reader as a manual substitution. This chapter
documents the guide as-is and explains exactly what to substitute for Intel XPU, rather than
presenting an untested Intel XPU procedure as if it were upstream-supported.

## Overview

Deploys the llm-d routing stack (EPP + Envoy + one or more vLLM workers) **without a Kubernetes
cluster** — the EPP gets its endpoint inventory from a plain YAML file on disk via the
file-discovery plugin instead of watching a Kubernetes `InferencePool`. Configs are plain YAML —
no Helm chart, no Kustomize overlay; drop them on a host and run. Source:
`guides/no-kubernetes-deployment/README.md`.

The EPP and Envoy configs are themselves **accelerator-agnostic** — only the model-server
container invocation (image, `--gpus` flag) is NVIDIA-specific.

## What Needs to Change for Intel XPU

| Component | Upstream (NVIDIA) | Intel XPU substitution |
|---|---|---|
| Model server image | `vllm/vllm-openai:v0.19.1` | An Intel XPU-built vLLM image (`VLLM_TARGET_DEVICE=xpu`) — see the image-build notes referenced from [Optimized Baseline](01-optimized-baseline.md) / the equivalent Intel XPU vLLM container build process used for the Kustomize overlays in Chapter 1 |
| GPU allocation flag | `docker run --gpus '"device=0,1"'` | Intel XPU has no direct Docker `--gpus` equivalent; instead expose the render/video device nodes: `docker run --device=/dev/dri:/dev/dri` and add the container user to the host's `render`/`video` groups (same GIDs used in the Kustomize overlays' commented-out `securityContext.supplementalGroups`, typically 44/991 — verify on your actual host with `getent group render video`) |
| Tensor-parallel comms backend | NCCL (`--shm-size=20g` for `/dev/shm`) | XCCL for Intel XPU multi-device collectives (see the [Wide-EP guide](05-wide-ep.md) for the XCCL note) — keep `--shm-size` sized similarly since vLLM's shared-memory IPC mechanism is backend-agnostic |
| EPP / Envoy config | unchanged | fully accelerator-agnostic, no changes needed |

## Prerequisites

- A host with Intel XPU device(s) exposed via `/dev/dri`, Docker (or Podman), and an Intel XPU
  vLLM image already built (see substitution table above).
- A HuggingFace token in `HUGGING_FACE_HUB_TOKEN`.
- Same environment setup as upstream:

  ```bash
  export REPO_ROOT=$(realpath $(git rev-parse --show-toplevel))
  source ${REPO_ROOT}/guides/env.sh
  export ENVOY_IMAGE=docker.io/envoyproxy/envoy:distroless-v1.33.2
  export VLLM_IMAGE=<your-intel-xpu-vllm-image>   # substitution — not the upstream default
  export MODEL=Qwen/Qwen3-32B
  ```

## Deployment Steps

```bash
# 1. Stage the configs
sudo mkdir -p /etc/epp /etc/envoy
sudo cp guides/no-kubernetes-deployment/router/epp/config.yaml      /etc/epp/config.yaml
sudo cp guides/no-kubernetes-deployment/router/epp/endpoints.yaml   /etc/epp/endpoints.yaml
sudo cp guides/no-kubernetes-deployment/router/envoy/envoy.yaml     /etc/envoy/envoy.yaml

# 2. Start the model server — Intel XPU substitution of the upstream `docker run --gpus` example
docker run -d --name vllm-0 \
    --device=/dev/dri:/dev/dri \
    --group-add "$(getent group render | cut -d: -f3)" \
    --shm-size=20g \
    -p 8000:8000 \
    -e "HUGGING_FACE_HUB_TOKEN=${HUGGING_FACE_HUB_TOKEN}" \
    -e "VLLM_TARGET_DEVICE=xpu" \
    -v "${HOME}/.cache/huggingface:/root/.cache/huggingface" \
    --entrypoint vllm \
    "${VLLM_IMAGE}" \
    serve "${MODEL}" \
    --disable-access-log-for-endpoints=/health,/metrics,/v1/models \
    --tensor-parallel-size=2

until curl -sf http://127.0.0.1:8000/v1/models >/dev/null; do sleep 2; done

# 3. Edit /etc/epp/endpoints.yaml to list each worker (literal IPv4 addresses required —
#    the file-discovery plugin does not resolve hostnames)

# 4. Start the EPP (accelerator-agnostic — unchanged from upstream)
docker run -d --name epp --network host \
    -v /etc/epp:/etc/epp:ro \
    "${ROUTER_EPP_IMAGE}:${ROUTER_EPP_VERSION}" \
    --config-file=/etc/epp/config.yaml \
    --pool-name=file-discovery --pool-namespace=default \
    --grpc-port=9002 --grpc-health-port=9003 --metrics-port=9090 \
    --secure-serving=false --v=2

# 5. Start Envoy (accelerator-agnostic — unchanged from upstream)
docker run -d --name envoy --network host \
    -v /etc/envoy/envoy.yaml:/etc/envoy/envoy.yaml:ro \
    "${ENVOY_IMAGE}" \
    --service-node envoy-proxy --log-level warn --concurrency 8 \
    --drain-strategy immediate --drain-time-s 60 \
    -c /etc/envoy/envoy.yaml
```

## Verification

```bash
curl -s http://127.0.0.1:19000/ready
curl -s http://127.0.0.1:19000/clusters | grep -E '^(ext_proc|original_destination_cluster)'
curl -s http://127.0.0.1:9090/metrics | head
```

## Inference Test

```bash
curl -s http://127.0.0.1:8081/v1/completions \
    -H 'Content-Type: application/json' \
    -d '{"model": "Qwen/Qwen3-32B", "prompt": "How are you today?"}'
```

## Troubleshooting

- **EPP not detecting endpoint changes**: confirm `watchFile: true` in `router/epp/config.yaml`;
  update `endpoints.yaml` via atomic rename (`mv endpoints.yaml.tmp endpoints.yaml`), and check
  `docker logs epp` for `endpoints file changed, reloading`.
- **Envoy returns 503**: verify EPP health (`curl http://127.0.0.1:9090/metrics`), confirm
  `endpoints.yaml` lists literal IPv4 addresses (not hostnames), and check the Envoy→EPP cluster
  (`curl http://127.0.0.1:19000/clusters | grep ext_proc`).
- **vLLM worker unreachable**: confirm the worker is up (`curl http://<worker-ip>:8000/v1/models`)
  and that the `address` in `endpoints.yaml` matches the worker's actual IP.
- **Intel XPU device not visible inside the container**: confirm `/dev/dri` is actually passed
  through (`--device=/dev/dri:/dev/dri`) and the container user is in the host's `render` group —
  a mismatched GID here is the most common first-run failure for this substitution.

## Cleanup

```bash
docker rm -f envoy epp vllm-0
sudo rm -rf /etc/epp /etc/envoy
```

## Config Reference

| Field | Value | Notes |
|---|---|---|
| Default model (upstream) | `Qwen/Qwen3-32B`, TP=2 | same as Optimized Baseline |
| Discovery mechanism | file-discovery plugin, `endpoints.yaml` | literal IPv4 addresses only, no DNS |
| Live reload | `watchFile: true` | atomic-rename updates to `endpoints.yaml` apply without EPP restart |
| P/D disaggregation outside Kubernetes | combine with [P/D Disaggregation](02-pd-disaggregation.md)'s EPP plugin config, set `llm-d.ai/role: prefill`/`decode` labels per endpoint | not Intel-XPU-specific, but untested in combination here |
| Hardware support status | NVIDIA + vLLM only, upstream-maintained | Intel XPU is a manual reader substitution (this chapter), not a maintained path |
