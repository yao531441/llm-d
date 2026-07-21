# Chapter 0. Common Installation

> Applies to every case in this whitepaper. Later chapters link back here instead of repeating
> these steps.

## 0.1 Cluster and Hardware Requirements

- A Kubernetes cluster (1.29+ recommended) with nodes exposing Intel Data Center GPU Max series or
  Intel Arc Pro GPUs
- The **Intel GPU device plugin / DRA driver** installed, so that `kubectl get deviceclass`
  lists `gpu.intel.com`
- Local client tools: `kubectl`, `helm` (v3); see
  [`helpers/client-setup/README.md`](https://github.com/llm-d/llm-d/blob/main/helpers/client-setup/README.md)

## 0.2 Clone the Repository

```bash
export branch="main"
git clone https://github.com/llm-d/llm-d.git && cd llm-d && git checkout ${branch}
export REPO_ROOT=$(realpath $(git rev-parse --show-toplevel))
source ${REPO_ROOT}/guides/env.sh
```

`guides/env.sh` centralizes the chart versions and OCI addresses shared by every guide
(`GAIE_VERSION`, `ROUTER_CHART_VERSION`, `ROUTER_STANDALONE_CHART`, etc.), so commands never
hardcode a version.

## 0.3 Install the Gateway API Inference Extension CRDs

> [!IMPORTANT]
> CRD installation is a single command below. Gateway Provider installation (Istio / GKE /
> Agentgateway) lives under `docs/infrastructure/gateway/`.

```bash
kubectl apply -f https://github.com/kubernetes-sigs/gateway-api-inference-extension/releases/download/${GAIE_VERSION}/v1-manifests.yaml
```

If you plan to use a Kubernetes Gateway (instead of the Router's standalone mode), follow the
provider-specific guide under `${REPO_ROOT}/docs/infrastructure/gateway/` once. A single Gateway can
be shared across every case in this whitepaper via a dedicated HTTPRoute per case.

## 0.4 Namespace and HuggingFace Token

```bash
export NAMESPACE="llm-d-<case-name>"
kubectl create namespace ${NAMESPACE} --dry-run=client -o yaml | kubectl apply -f -

export HF_TOKEN=<your HuggingFace token>
kubectl create secret generic llm-d-hf-token \
    --from-literal="HF_TOKEN=${HF_TOKEN}" \
    --namespace "${NAMESPACE}" \
    --dry-run=client -o yaml | kubectl apply -f -
```

## 0.5 Proxy Configuration (if required)

If the cluster needs a corporate proxy to reach the HuggingFace Hub, add `HTTP_PROXY` /
`HTTPS_PROXY` / `NO_PROXY` (and lowercase equivalents) to the relevant container `env`. This is
applied via a Kustomize patch in the overlay-based cases in this whitepaper, or via `--set` / a
values file in Helm-based steps.

---
