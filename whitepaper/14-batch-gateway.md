# 4.2 Batch Gateway (In Progress)

**Status**: documented from official repo sources, not yet run hands-on. Hardware-agnostic —
Batch Gateway dispatches to an existing llm-d Router endpoint; the backing model server can be
any Optimized Baseline overlay, including Intel XPU.

## Overview

[Batch Gateway](https://github.com/llm-d/llm-d-batch-gateway) provides an OpenAI-compatible Batch
API (`/v1/batches`, `/v1/files`) for submitting, tracking, and managing large-scale batch
inference jobs (up to 50,000 requests per job, configurable), designed to coexist with
interactive workloads on shared infrastructure. Source: `guides/batch-gateway/README.md`.

Three components: an **API Server** (REST endpoints), a **Batch Processor** (pulls jobs from a
priority queue, builds per-model execution plans, dispatches to the llm-d Router, writes output
files), and a **Garbage Collector** (cleans up expired jobs/files).

## Prerequisites

- Kubernetes v1.25+, Helm 3.0+.
- An existing [Optimized Baseline](01-optimized-baseline.md) stack on Intel XPU to dispatch
  requests to.
- **PostgreSQL 12+** for jobs/files metadata (Redis/Valkey dev-only alternative).
- **Redis 6+ / Valkey 8+** for the priority queue, events, and status updates.
- **S3 or a Filesystem PVC** for batch input/output file storage.

## Deployment Steps

```bash
export NAMESPACE=batch-gateway
kubectl create namespace ${NAMESPACE}

# 1. Storage/queue credentials secret
kubectl create secret generic batch-gateway-secrets -n ${NAMESPACE} \
  --from-literal=redis-url="redis://redis-master.redis.svc.cluster.local:6379/0" \
  --from-literal=postgresql-url="postgresql://user:pass@postgresql.postgresql.svc.cluster.local:5432/batchgateway" \
  --from-literal=s3-secret-access-key="<your-s3-secret-key>"

# 2. Point the Batch Processor at your Intel XPU-backed llm-d Router
export INFERENCE_GW_URL="http://infra-inference-scheduling-inference-gateway-istio.llm-d-inference-scheduler.svc.cluster.local:80"

# 3. Deploy
helm install batch-gateway oci://ghcr.io/llm-d-incubation/charts/batch-gateway \
  -n ${NAMESPACE} \
  --set processor.config.globalInferenceGateway.url="${INFERENCE_GW_URL}" \
  --set "apiserver.config.batchAPI.passThroughHeaders={Authorization}" \
  --set global.fileClient.fs.pvcName="batch-gateway-pvc"
```

For per-model gateways (different Intel XPU pools per model) instead of one global gateway URL,
use `processor.config.modelGateways` — see the
[Helm chart README](https://github.com/llm-d/llm-d-batch-gateway/blob/main/charts/batch-gateway/README.md).

## Verification

```bash
kubectl get pods -n ${NAMESPACE}   # expect apiserver, processor, gc all Running
kubectl port-forward -n ${NAMESPACE} svc/batch-gateway-apiserver 8081:8081 &
curl http://localhost:8081/health
```

`batch-gateway-apiserver` exposes two separate ports on the same Service: `8081` for the
health/readiness endpoint above, and `8000` for the actual REST API (confirmed by the in-cluster
URL `http://batch-gateway-apiserver:8000` used in the project's own benchmark manifests). The
Inference Test below needs its own port-forward to `8000`.

## Inference Test

```bash
kubectl port-forward -n ${NAMESPACE} svc/batch-gateway-apiserver 8000:8000 &

# 1. Prepare a JSONL input file (OpenAI Batch API format)
cat > batch_input.jsonl <<'EOF'
{"custom_id": "req-001", "method": "POST", "url": "/v1/chat/completions", "body": {"model": "my-model", "messages": [{"role": "user", "content": "Hello"}], "max_tokens": 100}}
{"custom_id": "req-002", "method": "POST", "url": "/v1/chat/completions", "body": {"model": "my-model", "messages": [{"role": "user", "content": "What is llm-d?"}], "max_tokens": 200}}
EOF

# 2. Upload it
curl -X POST http://localhost:8000/v1/files -F "purpose=batch" -F "file=@batch_input.jsonl"

# 3. Create the batch job
curl -X POST http://localhost:8000/v1/batches \
  -H "Content-Type: application/json" \
  -d '{"input_file_id": "<file-id-from-upload>", "endpoint": "/v1/chat/completions", "completion_window": "24h"}'

# 4. Monitor
curl http://localhost:8000/v1/batches/<batch-id> | jq '{status, request_counts}'

# 5. Download results once status is "completed"
OUTPUT_FILE_ID=$(curl -s http://localhost:8000/v1/batches/<batch-id> | jq -r '.output_file_id')
curl http://localhost:8000/v1/files/${OUTPUT_FILE_ID}/content > results.jsonl
```

## Troubleshooting

- `passThroughHeaders` must include any auth header (e.g. `Authorization`) your llm-d Router
  expects — the Batch Processor forwards these when dispatching individual requests; omitting a
  required header causes silent per-request auth failures inside batch jobs.
- For a production deployment with authentication, authorization, and TLS, see the
  [Kubernetes deployment guide](https://github.com/llm-d/llm-d-batch-gateway/blob/main/docs/guides/deploy-k8s.md)
  (Istio + Kuadrant + cert-manager) rather than the quick-start Helm install above.

## Cleanup

```bash
helm uninstall batch-gateway -n ${NAMESPACE}
kubectl delete namespace ${NAMESPACE}
```

## Config Reference

| Field | Value | Notes |
|---|---|---|
| Max requests/job | 50,000 (configurable) | |
| Metadata storage | PostgreSQL (prod) / Redis-Valkey (dev/test only) | |
| Queue/events storage | Redis/Valkey | |
| File storage | S3 or Filesystem PVC | |
| Dispatch target | `processor.config.globalInferenceGateway.url` or per-model `modelGateways` | any accelerator, incl. Intel XPU |
| Related guide | [Asynchronous Processing](13-asynchronous-processing.md) | per-request async queue; complementary to Batch Gateway's job-oriented API |
