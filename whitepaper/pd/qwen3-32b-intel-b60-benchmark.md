# Qwen3-32B P/D Disaggregation and Topology Benchmark on Intel B60

This report evaluates llm-d Prefill/Decode (P/D) disaggregation with
`Qwen/Qwen3-32B` on Intel B60 accelerators. It combines the deployment and
methodology summary with per-case results, grouped comparisons, ABBA arm
values, calculation rules, and failure evidence.

An editable [Excel chart workbook](./qwen3-32b-intel-b60-benchmark-charts.xlsx)
visualizes the principal throughput, TTFT, TPOT, topology, and failure
comparisons. It is generated directly from this report by
[`generate_benchmark_charts.py`](./generate_benchmark_charts.py).

## 1. Scope

The report covers eight related entries:

1. preliminary Raw vLLM P/D deployment validation;
2. canonical Raw versus llm-d 1P1D;
3. two-replica Aggregate 24-case baseline;
4. same-node Aggregate versus llm-d 1P1D;
5. equal-resource 2P2D versus 1P3D;
6. 3P1D capacity/liveness failure;
7. equal-resource Aggregate versus 2P2D ABBA;
8. a third independent-workload confirmation pair.

These entries do not all have the same statistical meaning:

| Entry | Type | Included in numerical comparison |
| --- | --- | --- |
| Preliminary Raw | deployment/harness validation | no |
| Raw versus llm-d | paired 24-case run | yes |
| Aggregate matrix | 24-case baseline dataset | absolute results |
| Aggregate versus 1P1D | cross-run post-processing | yes, 10 cases |
| 2P2D versus 1P3D | two topology runs | yes, 24 pairs |
| 3P1D | repeated failed operating point | no performance ratio |
| M1 | equal-resource ABBA | yes |
| Confirmation | one additional A/B pair | confirmation only |

## 2. llm-d repository baseline

The deployment is derived from:

- [P/D Disaggregation guide](../../guides/pd-disaggregation/README.md)
- [P/D architecture](../../docs/architecture/advanced/disaggregation/README.md)
- [vLLM P/D operations](../../docs/architecture/advanced/disaggregation/operations-vllm.md)
- [Intel XPU vLLM overlay](../../guides/pd-disaggregation/modelserver/xpu/vllm)
- [Intel XPU RDMA overlay](../../guides/pd-disaggregation/modelserver/xpu/vllm-rdma)
- [Standalone Router base values](../../guides/recipes/router/base.values.yaml)
- [P/D Router values](../../guides/pd-disaggregation/router/pd-disaggregation.values.yaml)
- [Aggregate baseline](../../guides/pd-disaggregation/baseline)

The repository provides the P/D object model, role labels, routing sidecar,
NIXL connector, XPU DRA claims, and RDMA overlay. The benchmark changes the
small XPU compatibility model into a fixed Qwen3-32B TP4 deployment.

### 2.1 Effective model-server configuration

| Parameter | Effective value |
| --- | --- |
| Model | `Qwen/Qwen3-32B` |
| Snapshot | `9216db5781bf21249d130ec9da846c4624c16137` |
| Served name | `Qwen/Qwen3-32B` |
| Image | `ghcr.io/llm-d/llm-d-xpu:v0.9.0` |
| Image ID | `sha256:15156bdeea9d868f5bbbf3a9a1c4d874de32bf85008a79349e6b90bc8ef35443` |
| vLLM | 0.26.0 |
| Precision | BF16 |
| Tensor parallelism | TP4 per model-server Pod |
| Block size | 64 |
| Maximum model length | 32,768 |
| XPU memory utilization | 0.89 |
| Maximum batched tokens | 2,048 |
| Maximum sequences | 128 |
| Prefix cache | enabled |
| Chunked prefill | enabled |
| CPU / memory | 32 CPU / 128 GiB per Pod |

### 2.2 Effective KV-transfer configuration

| Parameter | Effective value |
| --- | --- |
| Connector / role | `NixlConnector` / `kv_both` |
| KV buffer | XPU |
| KV lease | 300 seconds |
| UCX | `ib,rc,ze_copy` |
| UCX memtype cache | disabled |
| Per P/D Pod | 4 XPU + 2 RDMA NIC |
| Grouping | two groups of 2 XPU + 1 NIC |
| Alignment | same `resource.kubernetes.io/pcieRoot` per group |
| Prefill HTTP / NIXL | 8000 / 5600 |
| Decode HTTP / NIXL | 8200 / 5601 |

### 2.3 Effective Router policy

The benchmark used the standalone Router chart and repository base values,
with one EPP replica and this test-specific policy:

```yaml
plugins:
- type: disagg-headers-handler
- type: disagg-profile-handler
  parameters:
    deciders:
      prefill: always-disagg-pd-decider
- type: always-disagg-pd-decider
- type: prefill-filter
- type: decode-filter
- type: prefix-cache-scorer
- type: queue-scorer
- type: kv-cache-utilization-scorer
- type: active-request-scorer
- type: max-score-picker
schedulingProfiles:
- name: prefill
  plugins:
  - pluginRef: prefill-filter
  - pluginRef: prefix-cache-scorer
    weight: 3
  - pluginRef: queue-scorer
    weight: 2
  - pluginRef: kv-cache-utilization-scorer
    weight: 2
  - pluginRef: max-score-picker
- name: decode
  plugins:
  - pluginRef: decode-filter
  - pluginRef: active-request-scorer
    weight: 2
  - pluginRef: prefix-cache-scorer
    weight: 3
  - pluginRef: max-score-picker
```

This graph is based on the repository P/D values, with the test configuration
freezing its EPP image and picker. In 1P1D there was only one endpoint per
role, so scoring could not influence endpoint selection.

### 2.4 Topology resource accounting

| Topology | Roles | TP4 Pods | XPU | RDMA NIC |
| --- | --- | ---: | ---: | ---: |
| 1P1D | 1P + 1D | 2 | 8 | 4 |
| Aggregate-2 | two full-model replicas | 2 | 8 | 0 |
| 2P2D | 2P + 2D | 4 | 16 | 8 |
| 1P3D | 1P + 3D | 4 | 16 | 8 |
| 3P1D | 3P + 1D | 4 | 16 | 8 |
| Aggregate-4 | four full-model replicas | 4 | 16 | 0 |

### 2.5 YAML generation and request paths

The llm-d P/D model-server YAML followed this Kustomize chain:

```text
guides/recipes/modelserver/base/single-host/pd/vllm
  -> guides/pd-disaggregation/modelserver/xpu/vllm
  -> guides/pd-disaggregation/modelserver/xpu/vllm-rdma
  -> Qwen3-32B TP4 and dual-rail resource patch
  -> per-run namespace, node, replica, probe, and KV-lease patch
```

The checked-in overlays are provenance, not a literal copy of the frozen
benchmark manifest. The current `vllm-rdma` overlay requests one NIC per Pod
and inherits side-channel port `5600` for both roles. The benchmark-specific
patch expanded each TP4 Pod to two PCIe-aligned RDMA rails and used ports
`5600` for Prefill and `5601` for Decode. The configuration tables in this
report describe that effective benchmark configuration.

The Router was rendered separately:

```text
guides/recipes/router/base.values.yaml
  + benchmark P/D Router values
```

The three request paths were:

```text
Raw P/D:
  Client -> vLLM disaggregation proxy -> Prefill -> Decode

llm-d P/D:
  Client -> Envoy/EPP -> Decode routing sidecar -> Prefill -> Decode

Aggregate:
  Client -> Kubernetes Service -> full-model replicas
```

Raw P/D held the Prefill/Decode model servers, NIXL configuration, resources,
placement, and workload constant while replacing the llm-d front door.
Aggregate used full-model TP4 replicas and did not use NIXL or RDMA NICs.

## 3. Execution protocol

Every formal topology followed the same lifecycle:

1. create a fresh namespace;
2. render and validate the Router and model-server objects;
3. create model Deployments at zero replicas;
4. scale model servers sequentially;
5. validate XPU/NIC allocation and placement;
6. run an exact-token canary;
7. restart model servers to remove canary cache state;
8. require new Pod UIDs and `restartCount=0`;
9. run warm-up requests with a seed not used for measurement;
10. run the frozen measured workload;
11. validate request counts, token lengths, Pod identity, logs, and NIXL
    counters;
12. accept the result or retain the attempt only as incident evidence.

The initial 24-case matrix used:

| Dimension | Values |
| --- | --- |
| ISL | 1,024; 8,192; 16,384 |
| OSL | 128; 1,024 |
| Concurrency | 1; 8; 32; 64 |
| Requests | 32 at C1/C8; 96 at C32; 192 at C64 |
| Warm-ups | 2 at C1; 8 otherwise |
| Temperature | 0 |
| EOS | ignored |
| Input generation | exact-length random synthetic |
| Rate | immediate, except long C64 at 0.04 requests/s |

Across one complete 24-case arm this equals:

- 2,112 completed requests;
- 18,022,400 input tokens;
- 1,216,512 output tokens.

## 4. Metrics and calculations

| Metric | Definition | Better direction |
| --- | --- | --- |
| Output throughput | completed output tokens / measured duration | higher |
| TTFT | request start to first output token | lower |
| TPOT | inter-token generation time after first token | lower |
| E2E | request start to completed response | lower |

Three aggregation methods appear in this report:

1. **Per-case ratio:** numerator topology divided by denominator topology for
   the same ISL/OSL/concurrency case.
2. **Geometric-mean ratio:** geometric mean of per-case ratios. Every case has
   equal weight.
3. **Suite-normalized throughput:** total output tokens divided by the sum of
   case durations. Long-running cases therefore have more influence.

The Raw/llm-d normalized throughput ratio (`0.99472`) is a suite-level ratio.
Its per-case geometric mean is `0.99587`; these values are close but are not
the same statistic.

## 5. Preliminary Raw P/D

The preliminary run produced four complete ISL1,024/OSL128 results and two
partial OSL1,024 attempts. Completed results passed request-count and
exact-length checks, but the run was excluded because:

- measured prompts/seeds had been reused;
- smoke and canary traffic affected cache state;
- partial attempts had no complete result object;
- no paired llm-d arm existed.

It establishes that the Raw P/D deployment and benchmark client worked. It
does not provide a performance baseline.

## 6. Canonical Raw versus llm-d 1P1D

### 6.1 Comparison design

Fixed between arms:

- model snapshot, image, TP4 and vLLM arguments;
- one Prefill and one Decode on the same serving node;
- four XPU and two NIC per role;
- NIXL, UCX, KV lease and device placement;
- workload, measured seed and case order.

Changed between arms:

```text
Raw:   Client -> vLLM disaggregation proxy -> P -> D
llm-d: Client -> Envoy/EPP -> Decode sidecar -> P -> D
```

Both arms completed 24/24 cases and 2,112/2,112 requests with zero failures.

### 6.2 Overall statistics

Ratios are llm-d divided by Raw:

| Metric | Suite/geo ratio | Median ratio | llm-d wins | Range |
| --- | ---: | ---: | ---: | ---: |
| Output throughput | 0.99472 suite; 0.99587 geo | 0.99966 | 10/24 | 0.9559-1.0469 |
| p99 TTFT | 1.01016 geo | 1.00206 | 9/24 | 0.9846-1.0841 |
| p99 TPOT | 1.00592 geo | 1.00636 | 10/24 | 0.9179-1.1397 |
| p99 E2E | 1.00770 geo | 1.00204 | 10/24 | 0.9407-1.0625 |

### 6.3 Grouped ratios

| Dimension | Group | Cases | Throughput | p99 TTFT | p99 TPOT | p99 E2E |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| ISL | 1,024 | 8 | 1.0045 | 1.0092 | 1.0199 | 0.9986 |
| ISL | 8,192 | 8 | 0.9972 | 1.0117 | 0.9895 | 1.0087 |
| ISL | 16,384 | 8 | 0.9860 | 1.0096 | 1.0086 | 1.0159 |
| OSL | 128 | 12 | 1.0054 | 1.0001 | 0.9891 | 0.9998 |
| OSL | 1,024 | 12 | 0.9864 | 1.0204 | 1.0230 | 1.0157 |
| C | 1 | 6 | 1.0037 | 1.0152 | 1.0119 | 1.0066 |
| C | 8 | 6 | 0.9904 | 1.0209 | 0.9930 | 1.0111 |
| C | 32 | 6 | 0.9921 | 1.0052 | 1.0237 | 1.0072 |
| C | 64 | 6 | 0.9973 | 0.9995 | 0.9954 | 1.0059 |

### 6.4 Per-case data

`Delta out` is `(llm-d / Raw - 1) * 100`.

| ISL | OSL | C | Node | Raw out tok/s | llm-d out tok/s | Delta out | Raw p99 TTFT s | llm-d p99 TTFT s | Raw p99 TPOT ms | llm-d p99 TPOT ms |
| ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1,024 | 128 | 1 | smc-19 | 18.28 | 19.14 | 4.69% | 0.42 | 0.42 | 53.83 | 50.45 |
| 1,024 | 128 | 8 | smc-19 | 132.75 | 134.44 | 1.27% | 2.78 | 2.77 | 50.59 | 50.04 |
| 1,024 | 128 | 32 | smc-22 | 317.77 | 324.90 | 2.24% | 10.36 | 10.40 | 57.82 | 65.90 |
| 1,024 | 128 | 64 | smc-22 | 355.15 | 356.27 | 0.32% | 20.56 | 20.64 | 56.35 | 61.58 |
| 1,024 | 1,024 | 1 | smc-22 | 19.64 | 19.63 | -0.06% | 0.49 | 0.52 | 51.84 | 51.99 |
| 1,024 | 1,024 | 8 | smc-22 | 151.64 | 153.11 | 0.97% | 2.87 | 2.89 | 52.27 | 51.37 |
| 1,024 | 1,024 | 32 | smc-22 | 522.46 | 502.72 | -3.78% | 10.40 | 10.41 | 57.99 | 60.51 |
| 1,024 | 1,024 | 64 | smc-22 | 511.21 | 501.69 | -1.86% | 86.46 | 87.27 | 147.38 | 145.28 |
| 8,192 | 128 | 1 | smc-19 | 13.51 | 13.65 | 1.09% | 3.01 | 3.02 | 54.07 | 55.86 |
| 8,192 | 128 | 8 | smc-19 | 41.67 | 41.74 | 0.17% | 22.44 | 22.34 | 54.85 | 51.00 |
| 8,192 | 128 | 32 | smc-22 | 44.58 | 44.51 | -0.14% | 87.55 | 87.42 | 60.45 | 55.49 |
| 8,192 | 128 | 64 | smc-19 | 44.16 | 44.16 | -0.01% | 178.18 | 178.10 | 54.96 | 51.51 |
| 8,192 | 1,024 | 1 | smc-22 | 18.09 | 18.28 | 1.06% | 3.14 | 3.19 | 54.81 | 55.25 |
| 8,192 | 1,024 | 8 | smc-22 | 113.23 | 109.02 | -3.72% | 53.32 | 57.81 | 55.56 | 59.32 |
| 8,192 | 1,024 | 32 | smc-22 | 123.88 | 123.23 | -0.53% | 232.63 | 232.22 | 55.39 | 56.97 |
| 8,192 | 1,024 | 64 | smc-19 | 127.28 | 127.19 | -0.06% | 477.44 | 477.61 | 53.68 | 53.92 |
| 16,384 | 128 | 1 | smc-22 | 9.57 | 9.29 | -2.98% | 6.59 | 6.64 | 61.91 | 65.51 |
| 16,384 | 128 | 8 | smc-19 | 19.66 | 19.68 | 0.09% | 49.14 | 49.06 | 54.83 | 50.67 |
| 16,384 | 128 | 32 | smc-19 | 20.10 | 20.08 | -0.07% | 196.07 | 196.13 | 51.32 | 51.28 |
| 16,384 | 128 | 64 | smc-19 | 20.31 | 20.31 | -0.00% | 395.03 | 394.88 | 54.64 | 51.39 |
| 16,384 | 1,024 | 1 | smc-22 | 17.35 | 17.11 | -1.41% | 6.61 | 6.66 | 54.03 | 56.00 |
| 16,384 | 1,024 | 8 | smc-22 | 52.83 | 50.50 | -4.41% | 121.58 | 127.66 | 55.06 | 59.19 |
| 16,384 | 1,024 | 32 | smc-22 | 55.65 | 54.36 | -2.33% | 553.19 | 569.86 | 55.89 | 57.35 |
| 16,384 | 1,024 | 64 | smc-19 | 40.46 | 40.47 | 0.02% | 72.90 | 71.77 | 53.62 | 54.66 |

### 6.5 Interpretation boundary

The ratios remain close to parity across all groupings. The largest
throughput loss is 4.41% and the largest gain is 4.69%, without a consistent
direction across ISL, OSL, or concurrency.

This result tests one-endpoint request-path overhead. It does not test whether
llm-d scheduling improves multi-replica placement.

## 7. Aggregate baseline and same-node 1P1D comparison

### 7.1 Baseline validity

Two independent full-model TP4 replicas completed 24/24 cases with unchanged
Pod UIDs, zero restarts, exact request lengths, and zero failed requests.

Only ten Aggregate cases had a same-node 1P1D reference. The other fourteen
remain valid Aggregate measurements but are excluded from comparative ratios.

### 7.2 Aggregate/1P1D summary

| Metric | Aggregate wins | P/D wins | Geomean Aggregate/P-D |
| --- | ---: | ---: | ---: |
| Output throughput | 9 | 1 | 1.2592 |
| Mean TTFT | 10 | 0 | 0.5989 |
| Mean TPOT | 2 | 8 | 1.7366 |
| Mean E2E | 9 | 1 | 0.8154 |
| p99 TTFT | 10 | 0 | 0.6770 |
| p99 TPOT | 1 | 9 | 1.9335 |
| p99 E2E | 7 | 3 | 0.8577 |

### 7.3 Per-case Aggregate/1P1D data

All ratios are Aggregate divided by llm-d P/D.

| ISL | OSL | C | Aggregate out | llm-d P/D out | Out ratio | p99 TTFT ratio | p99 TPOT ratio | p99 E2E ratio |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1,024 | 128 | 1 | 19.40 | 19.14 | 1.014 | 0.797 | 1.032 | 1.018 |
| 1,024 | 128 | 8 | 123.40 | 134.44 | 0.918 | 0.523 | 1.228 | 0.948 |
| 8,192 | 128 | 1 | 14.02 | 13.65 | 1.027 | 0.932 | 0.896 | 0.908 |
| 8,192 | 128 | 8 | 56.31 | 41.74 | 1.349 | 0.532 | 2.306 | 0.878 |
| 8,192 | 128 | 64 | 68.02 | 44.16 | 1.540 | 0.643 | 3.562 | 0.739 |
| 8,192 | 1,024 | 64 | 191.38 | 127.19 | 1.505 | 0.640 | 1.286 | 0.705 |
| 16,384 | 128 | 8 | 29.63 | 19.68 | 1.505 | 0.641 | 3.728 | 1.000 |
| 16,384 | 128 | 32 | 30.12 | 20.08 | 1.500 | 0.673 | 3.732 | 0.770 |
| 16,384 | 128 | 64 | 30.16 | 20.31 | 1.485 | 0.658 | 3.689 | 0.694 |
| 16,384 | 1,024 | 64 | 40.48 | 40.47 | 1.000 | 0.836 | 1.185 | 1.007 |

### 7.4 Interpretation boundary

Aggregate improves throughput most for long-input, short-output cases and
reduces p99 TTFT in all ten cases. P/D usually preserves a much lower
per-output-token cadence once generation starts.

This is a comparison between complete serving systems. It simultaneously
changes full-model versus role-separated engines, Service versus EPP request
path, and local execution versus NIXL transfer. It cannot attribute the ratio
to one component.

## 8. Equal-resource 2P2D versus 1P3D

### 8.1 Design and totals

Both topologies used four TP4 model servers, 16 XPU, 8 NICs, and the same
Router and workload.

| Topology | Cases | Requests | Failed | Input tokens | Output tokens | Suite-normalized out tok/s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 2P2D | 24 | 2,112 | 0 | 18,022,400 | 1,216,512 | 76.338 |
| 1P3D | 24 | 2,112 | 0 | 18,022,400 | 1,216,512 | 71.631 |

The suite-normalized 1P3D/2P2D ratio is 0.9383.

### 8.2 Overall and grouped ratios

All ratios are 1P3D divided by 2P2D.

| Metric | 1P3D wins | 2P2D wins | Geomean | Median |
| --- | ---: | ---: | ---: | ---: |
| Output throughput | 6 | 18 | 0.8374 | 0.9728 |
| Mean TTFT | 9 | 15 | 1.3135 | 1.1925 |
| Mean TPOT | 4 | 20 | 1.0184 | 1.0140 |
| Mean E2E | 5 | 19 | 1.1864 | 1.0209 |
| p99 TTFT | 11 | 13 | 1.2482 | 1.3471 |
| p99 TPOT | 5 | 19 | 1.0515 | 1.0311 |
| p99 E2E | 7 | 17 | 1.1505 | 1.0697 |

| Dimension | Group | Throughput | p99 TTFT | p99 TPOT | p99 E2E |
| --- | ---: | ---: | ---: | ---: | ---: |
| ISL | 1,024 | 0.8643 | 1.5172 | 1.0565 | 1.1680 |
| ISL | 8,192 | 0.8278 | 1.1839 | 1.0634 | 1.1540 |
| ISL | 16,384 | 0.8207 | 1.0828 | 1.0349 | 1.1299 |
| OSL | 128 | 0.6600 | 1.4888 | 1.0704 | 1.3727 |
| OSL | 1,024 | 1.0624 | 1.0465 | 1.0330 | 0.9643 |
| C | 1 | 0.9883 | 0.9685 | 1.0182 | 1.0143 |
| C | 8 | 0.8089 | 1.3099 | 1.0401 | 1.1250 |
| C | 32 | 0.8145 | 1.3333 | 1.0808 | 1.1985 |
| C | 64 | 0.7552 | 1.4353 | 1.0681 | 1.2813 |

### 8.3 Per-case 2P2D/1P3D data

| ISL | OSL | C | 2P2D out | 1P3D out | Out ratio | p99 TTFT ratio | p99 TPOT ratio | p99 E2E ratio |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1,024 | 128 | 1 | 18.56 | 18.17 | 0.979 | 0.941 | 1.053 | 1.044 |
| 1,024 | 128 | 8 | 134.47 | 128.80 | 0.958 | 1.786 | 1.005 | 1.140 |
| 1,024 | 128 | 32 | 451.76 | 324.70 | 0.719 | 1.805 | 1.034 | 1.393 |
| 1,024 | 128 | 64 | 644.71 | 352.27 | 0.546 | 1.884 | 1.260 | 1.560 |
| 1,024 | 1,024 | 1 | 19.77 | 19.47 | 0.985 | 0.948 | 1.029 | 1.029 |
| 1,024 | 1,024 | 8 | 152.47 | 135.13 | 0.886 | 1.557 | 1.140 | 1.137 |
| 1,024 | 1,024 | 32 | 603.32 | 575.82 | 0.954 | 1.776 | 1.015 | 1.096 |
| 1,024 | 1,024 | 64 | 1,048.82 | 1,064.67 | 1.015 | 1.876 | 0.946 | 1.046 |
| 8,192 | 128 | 1 | 13.20 | 13.09 | 0.992 | 0.975 | 0.967 | 0.976 |
| 8,192 | 128 | 8 | 75.52 | 41.77 | 0.553 | 1.349 | 1.033 | 1.253 |
| 8,192 | 128 | 32 | 85.56 | 43.75 | 0.511 | 1.839 | 1.359 | 1.755 |
| 8,192 | 128 | 64 | 88.34 | 44.70 | 0.506 | 1.893 | 1.039 | 1.837 |
| 8,192 | 1,024 | 1 | 18.57 | 18.52 | 0.998 | 0.985 | 1.000 | 0.999 |
| 8,192 | 1,024 | 8 | 139.19 | 134.51 | 0.966 | 1.346 | 1.024 | 1.094 |
| 8,192 | 1,024 | 32 | 242.45 | 296.60 | 1.223 | 0.766 | 1.107 | 0.843 |
| 8,192 | 1,024 | 64 | 246.94 | 325.18 | 1.317 | 0.830 | 1.022 | 0.864 |
| 16,384 | 128 | 1 | 9.68 | 9.57 | 0.989 | 0.990 | 1.028 | 1.009 |
| 16,384 | 128 | 8 | 37.89 | 19.76 | 0.522 | 1.355 | 1.059 | 1.326 |
| 16,384 | 128 | 32 | 40.03 | 20.23 | 0.505 | 1.917 | 1.021 | 1.876 |
| 16,384 | 128 | 64 | 40.71 | 20.41 | 0.501 | 1.764 | 1.046 | 1.748 |
| 16,384 | 1,024 | 1 | 17.63 | 17.41 | 0.987 | 0.973 | 1.034 | 1.029 |
| 16,384 | 1,024 | 8 | 96.85 | 114.59 | 1.183 | 0.739 | 0.986 | 0.860 |
| 16,384 | 1,024 | 32 | 108.20 | 145.77 | 1.347 | 0.648 | 0.989 | 0.699 |
| 16,384 | 1,024 | 64 | 40.44 | 40.47 | 1.001 | 0.893 | 1.121 | 0.978 |

### 8.4 Detailed interpretation

The ratio is strongly workload-dependent:

- OSL128 favors 2P2D because one Prefill must feed all three Decode replicas.
- The effect grows at C32/C64, where short-output throughput for 1P3D falls to
  roughly one half of 2P2D in several long-input cases.
- OSL1,024 shifts more work into Decode. In this group 1P3D throughput is
  6.24% higher overall.
- The strongest 1P3D wins occur at ISL8,192/OSL1,024/C32-C64 and
  ISL16,384/OSL1,024/C8-C32.
- The long C64 rate-limited point is at throughput parity; it should not be
  read as a saturation-capacity result.

The P:D ratio and network-locality distribution change together, so the
experiment cannot assign all differences solely to replica count.

## 9. 3P1D capacity/liveness failure

The first formal case was ISL16,384/OSL128/C64 with 192 requests. It was run
twice against fresh model Pods.

| Evidence | First attempt | Second attempt |
| --- | ---: | ---: |
| No-token-progress interval | 916 s | 913 s |
| EPP received lifecycles | 210 | 210 |
| EPP completed response bodies | 199 | 201 |
| Missing completions | 11 | 9 |
| Longest nominal 1 GiB transfer | approximately 683 s | 524.774 s |
| Explicit NIXL expiry/failure | 0 | 0 |
| Pod restart/UID change during measurement | 0 | 0 |

In both attempts:

- the single Decode reached approximately 100% KV utilization;
- waiting and deferred requests accumulated;
- model queues eventually drained;
- some client-visible response lifecycles did not complete;
- the 15-minute no-progress gate terminated the case.

This is accepted as a reproducible operating-point failure, not as a
performance measurement. Starting at the highest-risk C64 case means it does
not establish the safe lower-load boundary for 3P1D.

## 10. Equal-resource Aggregate versus 2P2D ABBA

### 10.1 Design

Both topologies used 16 XPU:

```text
Aggregate: four full-model TP4 replicas
P/D:       two Prefill TP4 + two Decode TP4
Order:     Aggregate -> 2P2D -> 2P2D -> Aggregate
```

Each arm used a fresh namespace and model-server lifecycle.

### 10.2 Independent-workload arms

ISL8,192/OSL128/C64, 192 requests:

| Arm | Topology | Out tok/s | Mean TTFT s | p99 TTFT s | Mean TPOT ms | p99 TPOT ms | Mean E2E s | p99 E2E s |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| A1 | Aggregate | 133.966 | 35.096 | 60.095 | 166.007 | 184.001 | 56.179 | 82.753 |
| A2 | 2P2D | 87.584 | 71.798 | 89.430 | 51.182 | 59.407 | 78.298 | 95.909 |
| B1 | 2P2D | 87.559 | 71.757 | 89.489 | 50.936 | 59.316 | 78.225 | 96.243 |
| B2 | Aggregate | 133.384 | 35.024 | 59.852 | 165.522 | 184.532 | 56.045 | 82.255 |

Topology means and Aggregate/2P2D ratios:

| Metric | Aggregate mean | 2P2D mean | Ratio |
| --- | ---: | ---: | ---: |
| Output throughput | 133.675 tok/s | 87.571 tok/s | 1.5265 |
| Mean TTFT | 35.060 s | 71.777 s | 0.4885 |
| p99 TTFT | 59.973 s | 89.459 s | 0.6704 |
| Mean TPOT | 165.765 ms | 51.059 ms | 3.2465 |
| p99 TPOT | 184.267 ms | 59.361 ms | 3.1042 |
| Mean E2E | 56.112 s | 78.262 s | 0.7170 |
| p99 E2E | 82.504 s | 96.076 s | 0.8587 |

The two same-topology repetitions are tight: Aggregate throughput differs by
0.43%, while 2P2D differs by 0.03%.

### 10.3 Shared-prefix arms

Fourteen prefix groups, 8,192 shared + 256 unique input tokens, OSL128, C8:

| Arm | Topology | Out tok/s | Mean E2E s | p99 E2E s |
| --- | --- | ---: | ---: | ---: |
| A1 | Aggregate | 134.581 | 6.910 | 11.639 |
| A2 | 2P2D | 139.357 | 7.243 | 8.652 |
| B1 | 2P2D | 130.942 | 7.391 | 9.663 |
| B2 | Aggregate | 149.392 | 6.792 | 7.348 |

| Metric | Aggregate mean | 2P2D mean | Aggregate/2P2D |
| --- | ---: | ---: | ---: |
| Output throughput | 141.986 tok/s | 135.150 tok/s | 1.0506 |
| Mean E2E | 6.851 s | 7.317 s | 0.9363 |
| p99 E2E | 9.493 s | 9.157 s | 1.0367 |

This workload shows more between-arm variation than the independent workload;
the 5.06% mean throughput difference should be read together with that drift.

### 10.4 Long-output arms

ISL16,384/OSL1,024/C64, 192 requests, 0.04 requests/s:

| Arm | Topology | Out tok/s | Mean TTFT s | p99 TTFT s | Mean TPOT ms | p99 TPOT ms | Mean E2E s | p99 E2E s |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| A1 | Aggregate | 40.485 | 7.042 | 28.194 | 53.159 | 63.931 | 61.423 | 79.555 |
| A2 | 2P2D | 40.468 | 6.973 | 15.600 | 50.977 | 53.951 | 59.122 | 67.566 |
| B1 | 2P2D | 40.478 | 6.906 | 12.689 | 51.173 | 54.346 | 59.256 | 66.455 |
| B2 | Aggregate | 40.474 | 6.813 | 25.013 | 53.067 | 63.153 | 61.100 | 75.699 |

| Metric | Aggregate mean | 2P2D mean | Aggregate/2P2D |
| --- | ---: | ---: | ---: |
| Output throughput | 40.479 tok/s | 40.473 tok/s | 1.0002 |
| Mean TTFT | 6.927 s | 6.939 s | 0.9982 |
| p99 TTFT | 26.604 s | 14.145 s | 1.8808 |
| Mean TPOT | 53.113 ms | 51.075 ms | 1.0399 |
| p99 TPOT | 63.542 ms | 54.148 ms | 1.1735 |
| Mean E2E | 61.262 s | 59.189 s | 1.0350 |
| p99 E2E | 77.627 s | 67.011 s | 1.1584 |

Throughput is equal at the rate-limited operating point. The difference is in
tail behavior: 2P2D has lower p99 TTFT, TPOT, and E2E.

## 11. Third independent-workload pair

The confirmation repeated Aggregate then 2P2D:

| Metric | Aggregate | 2P2D | Aggregate/2P2D |
| --- | ---: | ---: | ---: |
| Output throughput | 134.352 tok/s | 86.557 tok/s | 1.5522 |
| Mean TTFT | 35.060 s | 72.970 s | 0.4804 |
| p99 TTFT | 59.843 s | 93.293 s | 0.6415 |
| Mean TPOT | 166.00 ms | 51.10 ms | 3.2484 |
| p99 TPOT | 183.97 ms | 58.83 ms | 3.1272 |
| Mean E2E | 56.142 s | 79.460 s | 0.7066 |
| p99 E2E | 82.272 s | 99.709 s | 0.8251 |

This pair reproduces the M1 independent-workload direction and approximate
effect size. Because it is one fixed-order pair, it confirms M1 rather than
forming a second independent study.

## 12. Cross-experiment interpretation

### 12.1 What is directly supported

- The llm-d 1P1D front door remained within approximately 1% of Raw on the
  complete suite-level throughput measure.
- Under equal 8-XPU resource count, Aggregate improved throughput and TTFT in
  most of the ten same-node cases; P/D improved TPOT.
- Under equal 16-XPU P/D resources, 2P2D was stronger for short-output and
  high-concurrency traffic, while 1P3D gained throughput in the OSL1,024
  group.
- 3P1D with one Decode failed reproducibly at the tested long-input,
  short-output C64 operating point.
- In equal-resource ABBA, Aggregate improved independent-workload throughput
  and TTFT, while 2P2D substantially improved generation cadence.
- At the rate-limited long-output point, Aggregate and 2P2D throughput was at
  parity and 2P2D improved tail latency.

### 12.2 What is not isolated

- Aggregate versus P/D changes model roles, request path, and KV transfer
  together.
- 2P2D versus 1P3D changes P:D ratio and cross-node transfer distribution
  together.
- Synthetic exact-length prompts do not represent a production conversation
  distribution.
- Initial matrix cases have one repetition and fixed topology order.
- The 3P1D evidence does not identify whether Decode pressure alone explains
  the missing response completions.

## 13. Audit identifiers

| Scope | Run identifier | Status |
| --- | --- | --- |
| Preliminary Raw | `raw-full-20260826T103800Z` | excluded from performance |
| Canonical base | `canonical-staggered-20260827T090700Z` | accepted source |
| Canonical completion | `canonical-two-node-completion-rate004-20260827T161225Z` | accepted 24-pair composite |
| Aggregate matrix | `aggregate-matrix-smc19-20260828T054500Z` | accepted |
| Multi-P/D | `multi-pd-20260828T111754Z` | 2P2D/1P3D accepted; 3P1D failure |
| Equal-resource ABBA | `m1-equal-abba-20260830t065500z` | accepted |
| Confirmation | `f0-m1-pair-20260830t181500z` | accepted confirmation |

Run identifiers provide audit identity only. The configuration, workload,
comparison direction, detailed values, result status, and interpretation
needed to read this report are included above.
