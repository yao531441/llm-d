# Experimental P/D Transport and Integrated-Policy Study on Intel B60

> **Status: Experimental / agent-planned**
>
> GitHub Copilot CLI, powered by GPT-5.6 Sol, independently planned this test
> matrix. The report author did not preregister or review the experiments
> item-by-item before execution. The measurements below are reported as
> observed evidence; their interpretation is exploratory and is not a
> production recommendation. The evidence and arithmetic were independently
> re-audited with GPT-5.6 Luna before publication.

## 1. Scope

This report covers two related but distinct layers:

1. staged diagnostics that separate RDMA transfer, XPU binding, real vLLM
   P/D transfer, and Decode-pressure behavior; and
2. an integrated 2P2D Router-policy comparison after the data path was
   accepted.

| Entry | Question | Evidence status |
| --- | --- | --- |
| NIXL Stage 1 | Does low-pressure DRAM RDMA transfer complete correctly? | accepted diagnostic |
| NIXL Stage 2 | Can the generic Python binding validate XPU buffers? | excluded diagnostic |
| NIXL Stage 3 | Does real vLLM XPU P/D transfer complete at low pressure? | accepted diagnostic |
| Decode-pressure Stage 4 | Does a small Decode KV cap reproduce a completion cliff at C1-C4? | accepted diagnostic |
| P2 | Does an integrated token-load/precise policy beat the weighted 2P2D policy? | accepted performance |
| F0 P2 | Does an additional W2 pair confirm P2 after a fresh restart? | excluded before treatment traffic |

The diagnostic stages are not performance arms of the Qwen3-32B matrix.
They use different abstractions and, in Stages 3 and 4, a smaller model.

## 2. Repository context

The relevant repository documentation and examples are:

- [P/D Disaggregation guide](../../guides/pd-disaggregation/README.md);
- [vLLM P/D operations](../../docs/architecture/advanced/disaggregation/operations-vllm.md);
- [Intel XPU vLLM overlay](../../guides/pd-disaggregation/modelserver/xpu/vllm);
- [Intel XPU RDMA overlay](../../guides/pd-disaggregation/modelserver/xpu/vllm-rdma);
- [P/D Router example](../../guides/pd-disaggregation/router/pd-disaggregation.values.yaml);
- [precise prefix-cache routing](../../guides/precise-prefix-cache-routing/README.md).

These surfaces define the architecture and current examples. They are not
the literal historical manifests. The benchmark used a Qwen3-32B/BF16/TP4
overlay and a measured Intel B60 prefill calibration of 3,156 tok/s rather
than calibration values from generic examples.

## 3. Qwen3-32B 2P2D configuration

The P2 performance experiment used the following effective configuration.

### 3.1 Model and runtime

| Parameter | Effective value |
| --- | --- |
| Model | `Qwen/Qwen3-32B` |
| Snapshot | `9216db5781bf21249d130ec9da846c4624c16137` |
| Image | `ghcr.io/llm-d/llm-d-xpu:v0.9.0` |
| vLLM | 0.26.0 |
| Precision | BF16 |
| Tensor parallelism | TP4 per model-server Pod |
| Block size | 64 |
| Maximum model length | 32,768 |
| XPU memory utilization | 0.89 |
| Maximum batched tokens | 2,048 |
| Maximum sequences | 128 |
| Prefix caching | enabled |
| Chunked prefill | enabled |

### 3.2 Topology and transport

| Parameter | Effective value |
| --- | --- |
| Topology | 2 Prefill + 2 Decode |
| Nodes | P0/D0 on one node; P1/D1 on a second node |
| XPU allocation | 4 Intel B60 per Pod; 16 total |
| RDMA allocation | 2 NICs per Pod; 8 total |
| PCIe grouping | two groups of 2 XPU + 1 NIC per Pod |
| Connector | `NixlConnector`, `kv_role=kv_both` |
| KV buffer | XPU |
| KV lease | 300 seconds |
| UCX | `ib,rc,ze_copy` |
| UCX memtype cache | disabled |
| Shared memory | 16 GiB per Pod |
| Probe failure thresholds | startup/liveness/readiness = 120/20/6 |

Each accepted arm required 16 unique XPU allocations, eight RDMA
allocations, fresh model Pod UIDs, zero measurement-time restarts, exact
request and token counts, no fatal or NIXL failure/expiry evidence, checksums,
and post-run claim cleanup.

## 4. Staged NIXL/RDMA diagnostics

### 4.1 Stage 1: DRAM NIXL/UCX

Stage 1 removed XPU, vLLM, EPP, and P/D. Two Pods on one node each used one
DRA-managed RDMA NIC. The target used one RDMA device and the initiator a
second device. NIXL 1.2.0 and UCX `rc_mlx5` transferred data at concurrency
one, followed by exact destination verification.

| Payload | Wall time | NIXL telemetry | Throughput | Verification |
| ---: | ---: | ---: | ---: | --- |
| 64 MiB | 60.074 ms | 60.068 ms | 1.117 GB/s | mismatch 0 |
| 1 GiB | 99.278 ms | 99.273 ms | 10.815 GB/s | mismatch 0 |

Physical-port counters increased in the expected direction by approximately
1.158 GB, with zero discard or error deltas. Two setup attempts were excluded:
one supplied a DNS name where the metadata API required a literal IP, and
one used an invalid verification window.

**Boundary:** this is accepted DRAM transport evidence, not an XPU or vLLM
measurement.

### 4.2 Stage 2: Rejected generic Python XPU synthetic

Stage 2 assigned one XPU and one PCIe-aligned RDMA NIC to each endpoint and
used the installed `nixl-cu12` 1.2.0 Python binding with XPU tensors.

Both a remote transfer and same-process loopback returned `DONE` and reported
1,048,576 transferred bytes. Exact verification nevertheless found
1,048,576 mismatched bytes, including after `torch.xpu.synchronize()`. The
binding classified any non-CPU tensor as `VRAM` and did not provide a
`torch.xpu`-specific registration path.

**Status:** excluded diagnostic. No XPU throughput number from this stage is
valid. The failure invalidates this generic synthetic path; it does not show
that the vLLM XPU NIXL connector is broken.

### 4.3 Stage 3: Real vLLM XPU P/D

Stage 3 used the real vLLM connector with a smaller configuration:

| Parameter | Value |
| --- | --- |
| Model | `Qwen/Qwen2.5-1.5B-Instruct` |
| Snapshot | `989aa7980e4cf806f80c7fef2b1adb7bc71aa306` |
| Topology | TP1 1P1D |
| Resources | 1 XPU + 1 aligned RDMA NIC per role |
| KV path | NixlConnector, XPU buffer, lease 300 seconds |
| UCX | `ib,rc,ze_copy`, one selected rail per role |
| Concurrency | 1 |

| Prompt | New external KV | NIXL time | NIXL throughput | Client E2E | Result |
| ---: | ---: | ---: | ---: | ---: | --- |
| 2,049 tokens | 57.75 MB | 5.584 ms | 10,342.049 MB/s | 0.482 s | HTTP 200, 16 output tokens |
| 30,001 tokens | 764.75 MB | 59.217 ms | 12,914.366 MB/s | 2.982 s | HTTP 200, 16 output tokens |

The second request reused 2,048 local tokens, so 27,953 tokens were newly
transferred. Both model roles remained Ready with zero restarts and no
reported transfer error.

**Boundary:** this validates real vLLM XPU P/D at TP1/C1. It is not a
Qwen3-32B TP4 performance estimate.

## 5. Stage 4: Controlled Decode pressure

### 5.1 Design

Stage 4 retained the real Qwen2.5-1.5B TP1 P/D path and changed the Decode KV
capacity:

- Prefill KV memory remained auto-sized;
- Decode used `--kv-cache-memory-bytes=2G`;
- Prefill and Decode used separately selected healthy PCIe roots;
- the known faulty XPU root was excluded;
- C1, C2, C3, and C4 ran sequentially;
- each request required exactly 128 output tokens;
- each concurrency level had a 600-second timeout.

This was a bounded pressure diagnostic, not a matched unlimited-cap/control
comparison.

### 5.2 Results

| Concurrency | Requests | Exact completions | Maximum latency |
| ---: | ---: | ---: | ---: |
| 1 | 1 | 1 | 4.42 s |
| 2 | 2 | 2 | 6.96 s |
| 3 | 3 | 3 | 9.65 s |
| 4 | 4 | 4 | 12.27 s |
| **Total** | **10** | **10** | — |

Decode ended each level with:

- zero waiting or deferred requests;
- zero preemptions;
- zero restart, fatal, backend, or lease-expiry failures.

NIXL recorded successful 820.75 MB transfers at approximately 23.3 to
26.4 GB/s.

**Interpretation:** latency rose smoothly through C4 and no completion cliff
appeared within this bound. This result does not reproduce or disprove the
Qwen3-32B 3P1D high-pressure failure because the model, TP width, KV demand,
and topology differ.

## 6. P2: Integrated 2P2D policy ABBA

### 6.1 Alignment gate

Before changing policy, unchanged 2P2D was compared with two previously
accepted operating points:

| Case | Alignment output tok/s | Reference output tok/s | Ratio |
| --- | ---: | ---: | ---: |
| ISL8192/OSL128/C8 | 76.515 | 75.521 | 1.0132 |
| ISL8192/OSL128/C64 | 88.484 | 88.342 | 1.0016 |

Both were within the frozen 10% drift threshold.

### 6.2 Control and treatment

Model-server settings were identical across arms, including prefix caching
and KV-event publication.

**Control: weighted policy**

| Role | Scoring |
| --- | --- |
| Prefill | prefix-cache weight 3; queue weight 2; KV utilization weight 2 |
| Decode | active-request weight 2; prefix-cache weight 3 |

**Treatment: integrated B60 policy**

| Component | Effective setting |
| --- | --- |
| Cache state | precise KV events, 64-token blocks |
| Event discovery | topic filter `kv@`, port 5556 |
| Prefill calibration | 3,156 tok/s |
| Prefill selection | precise affinity, token-load scorer, max-score picker |
| Decode selection | active-request scorer, max-score picker |

The treatment is a bundled policy change. P2 does not independently isolate
token-load scoring from precise ownership.

### 6.3 Workloads

**W1 mixed stream**

| Stream | ISL | OSL | Concurrency | Requests | Rate | Seed |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Short | 512 | 128 | 32 | 64 | 0.5 requests/s | 391510512 |
| Long | 8,192 | 128 | 32 | 32 | 0.1 requests/s | 391518192 |

**W2 shared-prefix stream**

| Parameter | Value |
| --- | --- |
| Prefix groups | 14 |
| Shared prefix | 8,192 tokens |
| Unique suffix | 256 tokens |
| Input total | 8,448 tokens |
| Output | 128 tokens |
| Requests per group | 4 |
| Measured requests | 56 |
| Concurrency | 8 |
| Warm-up | 14 direct requests, split 7/7 across Prefill Pods |

### 6.4 Order and gates

The accepted order was:

1. control;
2. treatment;
3. treatment;
4. control.

Every arm restarted all four model Pods before traffic and ran 152 measured
requests: 64 short W1, 32 long W1, and 56 W2. The ABBA total was 608.

Treatment additionally required four current KV-event subscribers, positive
publisher series, positive precise-index admissions, and positive Prefill
publisher deltas after W2 warm-up. Both treatment repetitions recorded four
subscribers and 1,848 index admissions.

### 6.5 W1 results

Values are two-repetition policy means. Ratios are treatment/control.

| Stream | Metric | Control | Treatment | Ratio |
| --- | --- | ---: | ---: | ---: |
| Short | output throughput | 60.272 tok/s | 59.952 tok/s | 0.994693 |
| Short | mean TTFT | 474.819 ms | 448.547 ms | 0.944670 |
| Short | p99 TTFT | 2,135.675 ms | 1,183.525 ms | 0.554169 |
| Short | mean TPOT | 51.406 ms | 50.710 ms | 0.986450 |
| Short | p99 TPOT | 62.197 ms | 58.495 ms | 0.940477 |
| Short | mean E2E | 7.003 s | 6.889 s | 0.983617 |
| Short | p99 E2E | 9.082 s | 8.235 s | 0.906770 |
| Long | output throughput | 12.300 tok/s | 12.412 tok/s | 1.009114 |
| Long | mean TTFT | 3,278.173 ms | 3,204.468 ms | 0.977516 |
| Long | p99 TTFT | 5,648.750 ms | 3,768.648 ms | 0.667165 |
| Long | mean TPOT | 53.080 ms | 52.250 ms | 0.984367 |
| Long | p99 TPOT | 62.610 ms | 59.905 ms | 0.956797 |
| Long | mean E2E | 10.019 s | 9.840 s | 0.982125 |
| Long | p99 E2E | 12.802 s | 10.840 s | 0.846770 |

W1 throughput was effectively unchanged. Treatment reduced short-stream p99
TTFT by 44.6% and long-stream p99 TTFT by 33.3%.

### 6.6 W2 results

| Metric | Control | Treatment | Treatment/control |
| --- | ---: | ---: | ---: |
| Output throughput | 119.858 tok/s | 140.808 tok/s | 1.174791 |
| Mean E2E | 8.117 s | 7.075 s | 0.871577 |
| p50 E2E | 7.295 s | 6.892 s | 0.944769 |
| p90 E2E | 11.093 s | 7.831 s | 0.705927 |
| p99 E2E | 16.886 s | 8.750 s | 0.518148 |

Treatment increased W2 output throughput by 17.5% and reduced p99 E2E by
48.2%. These are descriptive two-repetition ABBA means, not a statistical
significance result.

## 7. F0 P2-W2 confirmation

The additional control arm completed 56/56 exact requests:

| Metric | Control |
| --- | ---: |
| Output throughput | 115.028 tok/s |
| Mean E2E | 8.359 s |
| p99 E2E | 19.998 s |

Treatment completed its 14 direct warm-ups but did not start measured
traffic. After 60 precise-index gate attempts:

| Gate signal | Final value |
| --- | ---: |
| Active subscribers | 4 |
| Index admissions | 1,848 |
| Prefill P0 messages | 28 |
| Prefill P1 messages | 28 |
| Decode D0 messages | absent |
| Decode D1 messages | absent |

The run failed closed because both Decode publisher series were absent.

This excludes only the F0 treatment/control comparison and any claim of an
independent P2-W2 confirmation. The F0 control value must not be pooled with
the earlier treatment. It does not invalidate the accepted P2 ABBA, whose
treatment repetitions passed their frozen gates.

The operational lesson is narrower: active subscriber count and aggregate
index admissions do not prove that every current publisher is delivering
events. A fresh deployment should require positive per-publisher deltas.

## 8. Conclusions and limits

The accepted evidence supports these observations:

1. low-pressure DRAM NIXL/RDMA transfer completed with exact verification;
2. the tested generic Python binding was not a valid XPU-buffer diagnostic;
3. the real vLLM XPU connector completed low-pressure TP1 P/D transfer;
4. the bounded small-model Decode-pressure test completed through C4;
5. the integrated P2 policy improved W2 throughput and tail latency while W1
   throughput remained near parity; and
6. F0 exposed a stricter publisher-liveness requirement.

The report does not establish:

- a generic XPU wire-rate result from the rejected Python path;
- that the long Qwen3-32B 3P1D transfer time was NIC bandwidth;
- a Qwen3-32B Decode-capacity curve from Stage 4;
- the independent contribution of token-load versus precise ownership in
  P2;
- statistical significance from two policy repetitions; or
- production capacity or SLOs.

The previously observed approximately 1 GiB transfer with a 524.774-second
submit-to-completion lifetime occurred with saturated Decode KV capacity and
waiting/deferred work. It must not be converted into a wire-bandwidth claim.

## 9. Audit identifiers

| Entry | Accepted or excluded evidence identifier |
| --- | --- |
| NIXL/RDMA Stages 1-3 | `transport-staged-20260829T030626Z` |
| Decode-pressure Stage 4 | `stage4-decode-pressure-20260829T133722Z` |
| P2 integrated policy | `p2-pilot-20260829T171442Z` |
| F0 P2 W2 | `f0-p2-w2-20260830t193000z` |

These identifiers distinguish the frozen evidence sets. The report is
self-contained and does not require access to internal result storage to
understand the configuration, calculations, statuses, or limitations.
