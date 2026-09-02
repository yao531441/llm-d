# Experimental Feature and Reliability Study on Intel B60

> **Status: Experimental / agent-planned**
>
> GitHub Copilot CLI, powered by GPT-5.6 Sol, independently planned this test
> matrix. The report author did not preregister or review the experiments
> item-by-item before execution. The measurements below are reported as
> observed evidence; their interpretation is exploratory and is not a
> production recommendation. The evidence and arithmetic were independently
> re-audited with GPT-5.6 Luna before publication.

## 1. Scope

This report covers compatibility, overload control, and endpoint-loss
behavior:

| Entry | Question | Evidence status |
| --- | --- | --- |
| D0 | Do the flow-control, endpoint-removal, and offload paths boot on B60? | accepted diagnostic |
| M2A | Does native CPU KV offload work with Qwen3-32B TP4? | compatibility failure before traffic |
| M2B | How does flow control behave at a calibrated two-replica overload point? | accepted performance |
| M3 | How does four-replica Aggregate handle one hard endpoint loss? | accepted reliability |
| Closeout | Were results, checksums, and cluster cleanup revalidated? | accepted validation |

The D0 smokes are mechanism checks with a smaller model. They are not
performance controls for M2A, M2B, or M3.

## 2. Repository context

Relevant llm-d repository surfaces include:

- [flow-control guide](../../guides/flow-control/README.md);
- [flow-control tuning guidance](../../guides/flow-control/tuning.md);
- [flow-control Router values](../../guides/flow-control/router);
- [tiered prefix-cache guide](../../guides/tiered-prefix-cache/README.md);
- [precise prefix-cache routing](../../guides/precise-prefix-cache-routing/README.md);
- [optimized Aggregate baseline](../../guides/optimized-baseline/README.md).

The current examples describe feature use, not the literal frozen test
configuration. For example, the flow-control guide's example concurrency
limit was not copied into M2B; M2B calibrated its limit from a fresh
no-flow-control run. Likewise, results in the tiered-cache guide are separate
from M2A and cannot substitute for M2A's failed compatibility gate.

## 3. Common formal environment

| Parameter | Effective value |
| --- | --- |
| Formal nodes | two healthy worker nodes |
| Model | `Qwen/Qwen3-32B` |
| Snapshot | `9216db5781bf21249d130ec9da846c4624c16137` |
| Main image | `ghcr.io/llm-d/llm-d-xpu:v0.9.0` |
| vLLM | 0.26.0 |
| Precision | BF16 |
| Tensor parallelism | TP4 per Aggregate replica |
| XPU allocation | 4 Intel B60 per replica |
| Block size | 64 |
| Maximum model length | 32,768 |
| XPU memory utilization | 0.89 unless overridden by M2A |
| Maximum batched tokens | 2,048 |
| Maximum sequences | 128 |
| Prefix caching / chunked prefill | enabled |
| CPU / memory | 32 CPU / 128 GiB unless overridden by M2A |
| Shared memory | 16 GiB unless overridden by M2A |

Formal acceptance required fresh Pod UIDs, zero measurement-time restarts,
exact request and token counts, empty fatal scans, frozen and checksummed
inputs, feature-specific Router gates, and namespace/claim cleanup.

## 4. D0 compatibility lane

D0 used Qwen2.5-1.5B TP1 on one diagnostic worker and explicitly avoided a
known faulty XPU group. Each item was bounded and non-comparative.

### 4.1 Flow-control smoke

Twelve concurrent requests completed HTTP 200 with exact 16-token input and
128-token output:

- six `tenant-a` requests mapped to `premium-traffic`, priority 100;
- six `tenant-b` requests mapped to `standard-traffic`, priority 0;
- 17 flow-control metric families exposed queue, saturation, utilization,
  rejection, and fairness labels;
- model and Router Pods remained Ready with zero restarts.

**Status:** accepted mechanism diagnostic. It does not measure overload
performance.

### 4.2 Endpoint-removal smoke

| Phase | Result |
| --- | --- |
| Healthy baseline | 2/2 HTTP 200 |
| Sole Decode endpoint absent for 40 seconds | 8/8 explicit HTTP 429 |
| Replacement Ready | 2/2 HTTP 200 |

**Status:** accepted harness diagnostic. This single-Decode P/D behavior is
not the four-replica Aggregate result measured later by M3.

### 4.3 Native offload smoke

One Qwen2.5-1.5B TP1 Decode-style Pod used
`OffloadingConnector`, `kv_role=kv_both`, and a 20 GiB CPU tier. A direct
request completed HTTP 200 with exactly 16 output tokens and no connector,
NIXL, OOM, or fatal error.

**Status:** accepted compatibility diagnostic. It does not establish
Qwen3-32B TP4 support or a performance benefit.

## 5. M2A: Native CPU KV offload

### 5.1 Planned comparison

M2A planned an ABBA comparison on one Qwen3-32B TP4 Aggregate server:

- **control:** HBM-only;
- **treatment:** HBM plus a 100 GiB CPU KV tier.

Both arms were required to use
`ghcr.io/llm-d/llm-d-xpu-dev:pr-1230`. The intended order was control,
treatment, treatment, control with fresh namespaces and Pods.

| Parameter | Control | Treatment |
| --- | --- | --- |
| Connector | none | `OffloadingConnector` |
| Connector block size | — | 64 |
| CPU bytes | — | 107,374,182,400 |
| Pod memory | 128 GiB | 140 GiB |
| `/dev/shm` | 16 GiB | 110 GiB |
| XPU memory utilization | 0.85 | 0.85 |

The planned cache-churn workload was:

| Parameter | Value |
| --- | --- |
| Prefix groups | 60 |
| Prompts per group | 5 |
| Shared prefix | 3,000 tokens |
| Unique suffix | 256 tokens |
| Output | 256 tokens |
| QPS ladder | 1, 2, 3, 4 |
| Duration | 60 seconds per QPS |
| Total planned requests | 600 |

### 5.2 Actual result

**Status: compatibility failure; no performance comparison was reached.**

The initial Qwen3-32B TP4 control Pod failed before readiness while
initializing oneCCL ATL. The one permitted clean replacement had a different
Pod UID and reproduced the failure on all four workers:

```text
RuntimeError: oneCCL ... atl_ofi_comm.cpp:232 init_transport:
EXCEPTION: failed to initialize ATL
```

The run therefore produced:

- zero benchmark requests;
- no treatment startup;
- no CPU restore metrics;
- no throughput, TTFT, E2E, or treatment/control ratio.

The controller refused an additional replacement and cleaned up the
namespace. The smaller D0 TP1 smoke cannot be used to infer that the failed
Qwen3-32B TP4 comparison would have worked.

### 5.3 Interpretation boundary

M2A shows only that this exact PR image and TP4 configuration failed its
startup gate. It does not establish that native CPU KV offload is generally
incompatible with Intel B60.

## 6. M2B: Flow control and fairness

### 6.1 Design

M2B used two Qwen3-32B Aggregate TP4 replicas on one node, eight B60 devices
total. Both arms used the same precise cache/load-aware Router and identical
priority objectives:

- `tenant-a` / `premium-traffic`: priority 100;
- `tenant-b` / `standard-traffic`: priority 0.

**Control:** flow control disabled.

**Treatment:** the same Router plus:

- flow-control feature gate;
- request-mode concurrency detector with zero headroom;
- round-robin fairness;
- FCFS ordering;
- priority bands 100 and 0.

### 6.2 Calibration

A fresh no-flow-control namespace first ran:

| Parameter | Value |
| --- | ---: |
| Requests | 256 |
| Concurrency | 128 |
| Per-tenant requests | 128 |
| ISL pattern | alternating 512 / 8,192 |
| OSL | 128 |
| Request throughput | 1.712434 requests/s |
| Mean E2E | 51.080601 s |

The frozen per-replica limit was:

```text
ceil(request throughput * mean E2E seconds / 2 replicas)
= ceil(1.712434 * 51.080601 / 2)
= 44
```

Pool dispatch capacity was therefore 88. The formal workload used 352
requests at concurrency 176, exactly twice that calibrated capacity.

This is one deliberately overloaded operating point, not a sweep that
establishes a universal saturation threshold.

### 6.3 Overall results

Ratios are treatment/control.

| Metric | Control | Treatment | Ratio |
| --- | ---: | ---: | ---: |
| Exact requests | 352/352 | 352/352 | — |
| Rejected / failed | 0 / 0 | 0 / 0 | — |
| Request throughput | 1.774 requests/s | 2.711 requests/s | 1.5279 |
| Output throughput | 227.093 tok/s | 346.983 tok/s | 1.5279 |
| Mean E2E | 66.273 s | 52.347 s | 0.7899 |
| Jain completion-rate index | 1.0 | 1.0 | 1.0 |

### 6.4 Tenant and priority results

| Metric | Premium control | Premium treatment | Ratio | Standard control | Standard treatment | Ratio |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Exact requests | 176 | 176 | — | 176 | 176 | — |
| Request throughput | 0.887 req/s | 1.355 req/s | 1.528 | 0.887 req/s | 1.355 req/s | 1.528 |
| Output throughput | 113.547 tok/s | 173.492 tok/s | 1.528 | 113.547 tok/s | 173.492 tok/s | 1.528 |
| Mean TTFT | 52.266 s | 25.191 s | 0.482 | 53.052 s | 51.419 s | 0.969 |
| p99 TTFT | 108.910 s | 50.715 s | 0.466 | 108.268 s | 94.808 s | 0.876 |
| Mean TPOT | 105.082 ms | 111.270 ms | 1.059 | 109.313 ms | 109.865 ms | 1.005 |
| p99 TPOT | 192.581 ms | 198.975 ms | 1.033 | 180.342 ms | 199.149 ms | 1.104 |
| Mean E2E | 65.612 s | 39.323 s | 0.599 | 66.935 s | 65.372 s | 0.977 |
| p99 E2E | 120.147 s | 63.598 s | 0.529 | 119.111 s | 106.863 s | 0.897 |

Router evidence for treatment recorded:

| Signal | Value |
| --- | ---: |
| Queue-wait p99, premium | 30 s |
| Queue-wait p99, standard | 60 s |
| Peak pool saturation | 1.0341 |
| Peak total queue | 88 |
| Peak observed premium queue | 48 |
| Peak observed standard queue | 85 |
| Successful Router metric samples | 125/125 |

All 11 required flow-control metric families were present, with positive
queue-duration deltas for both tenant/priority combinations.

### 6.5 Interpretation boundary

At this calibrated overloaded point, flow control increased observed
throughput and reduced TTFT, particularly for premium traffic. TPOT worsened
modestly. The Jain value of 1.0 measures completion-rate fairness only; it
does not prove equal latency, equal queue wait, or long-run fairness.

The per-replica value 44 and all saturation and tenant results are specific
to two replicas on one node. They must not be copied to a four-replica fleet
without new calibration.

## 7. M3: Four-replica Aggregate hard endpoint loss

### 7.1 Protocol

M3 used four Aggregate TP4 replicas, two on each of two nodes, for 16 B60
devices total. Two fresh arms deleted one endpoint in reverse placement:

1. delete replica `a0` on the first node;
2. delete replica `a2` on the second node.

The request stream alternated ISL512 and ISL8192, used OSL128, temperature
zero, and ignored EOS. Offered load was one request/s, maximum client
concurrency 256, and request timeout 900 seconds.

Each arm ran:

1. a 300-second healthy baseline;
2. hard deletion with grace period zero;
3. continuous traffic while the replacement was absent;
4. replacement readiness observation; and
5. a 300-second recovery interval.

A successful stream required HTTP 200, exact usage, non-empty text, expected
text checksum, `finish_reason=length`, and the final stream marker.

### 7.2 Arm results

| Arm | Baseline | In-flight at deletion | New requests while absent | Replacement Ready | First new success | First post-Ready success | Five sustained successes |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: |
| `a0`, first node | 294/294 exact | 8 exact, 1 failed of 9 | 270/270 exact | 270 s | 3.665 s | 0.448 s | 12.623 s |
| `a2`, second node | 292/292 exact | 8 exact, 2 failed of 10 | 271/271 exact | 271 s | 0.084 s | 0.200 s | 12.249 s |

| Arm | Baseline p99 TTFT | Outage/baseline | Baseline p99 E2E | Outage/baseline | Recovery requests | Recovery p99 E2E | Recovery/baseline |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `a0` | 3.082 s | 1.0099 | 17.534 s | 1.1533 | 300/300 exact | 16.114 s | 0.9190 |
| `a2` | 3.080 s | 1.0048 | 17.551 s | 1.1499 | 300/300 exact | 17.460 s | 0.9949 |

Short-request p99 E2E increased by 1.3648 and 1.3564 during the two outage
arms. Long-request p99 E2E increased by 1.0699 and 1.1498.

### 7.3 New requests versus in-flight requests

All 541 requests started while one endpoint was absent completed exactly:

- no HTTP 429 or 503;
- no local client-capacity rejection;
- traffic continued through the remaining three endpoints.

Requests already owned by the deleted endpoint did not migrate:

- first arm: one short request timed out;
- second arm: one short and one long request timed out.

These three failures surfaced only at the frozen 900-second timeout rather
than as immediate Router rejections.

One aggregate recovery statistic can hide a class-specific tail. In the
second arm, short-request recovery p99 TTFT was 2.163 seconds versus a
0.366-second baseline, or 5.914 times higher, even though aggregate recovery
p99 E2E was near baseline.

### 7.4 Interpretation boundary

M3 supports new-request availability after one hard loss in this
four-replica Aggregate configuration. It does not test graceful drain,
multiple simultaneous failures, P/D endpoint loss, or client retry behavior.
Because in-flight ownership was not migrated, a client-facing deployment
still requires an explicit retry and idempotency design.

## 8. Final closeout

The final validation recorded:

1. every accepted result independently revalidated;
2. root checksum manifests generated and rechecked;
3. excluded failure chains retained with checksums;
4. accepted, diagnostic, compatibility-failure, and excluded states kept
   distinct;
5. every benchmark namespace deleted;
6. zero matching ResourceClaims and ResourceClaimTemplates;
7. no benchmark controller process remaining;
8. all three worker nodes Ready; and
9. cross-run and complete-closeout checksums generated and revalidated.

One live-panel checkbox remained stale even though the dedicated closeout
record declared completion. This is treated as a documentation inconsistency,
not evidence that cluster resources remained.

## 9. Conclusions and limits

The accepted evidence supports these observations:

- the selected feature paths could be exercised at TP1 in D0;
- the exact M2A PR image could not start the Qwen3-32B TP4 control, so no
  offload performance claim exists;
- flow control changed throughput and latency allocation at one calibrated
  two-replica overload point;
- one hard loss did not interrupt newly dispatched traffic in the tested
  four-replica Aggregate pool; and
- already-owned in-flight requests were not migrated.

The report does not establish:

- general Intel B60 incompatibility with CPU KV offload;
- that flow control increases raw model capacity;
- that the measured concurrency limit applies to other pool sizes or
  workloads;
- equal latency fairness;
- transparent endpoint deletion for in-flight clients; or
- behavior under multiple failures or graceful drain.

## 10. Audit identifiers

| Entry | Accepted or excluded evidence identifier |
| --- | --- |
| D0 flow control | `d0-flowcontrol-20260830t035000z` |
| D0 endpoint removal | `d0-endpoint-20260830t035900z` |
| D0 native offload | `d0-offload-20260830t041700z` |
| M2A CPU offload | `m2a-abba-20260830t145100z` |
| M2B flow control | `m2b-flow-20260830t145100z` |
| M3 hard endpoint loss | `m3-agg-20260830t155000z` |
| Final closeout | `final-closeout-20260830t213000z` |

These identifiers distinguish the frozen evidence sets. The report is
self-contained and does not require access to internal result storage to
understand the configuration, calculations, statuses, or limitations.
