# Experimental Router and Prefix-Cache Study on Intel B60

> **Status: Experimental / agent-planned**
>
> GitHub Copilot CLI, powered by GPT-5.6 Sol, independently planned this test
> matrix. The report author did not preregister or review the experiments
> item-by-item before execution. The measurements below are reported as
> observed evidence; their interpretation is exploratory and is not a
> production recommendation. The evidence and arithmetic were independently
> re-audited with GPT-5.6 Luna before publication.

## 1. Scope

This report separates six Router and cache questions that were tested during
the Qwen3-32B Intel B60 campaign:

| ID | Isolated question | Evidence status |
| --- | --- | --- |
| R0 | Does the Envoy/EPP path add overhead with one backend? | accepted performance |
| R1 | How does token-load routing differ from active-request routing? | accepted performance |
| K0 | What is the engine-level value of prefix caching? | accepted performance |
| R2 | Does approximate prefix affinity preserve reuse across replicas? | accepted performance |
| R3 | Can precise KV events recover actual cache ownership? | accepted performance |
| M4A | Does precise ownership help with four Aggregate replicas? | accepted performance |

These are not one cumulative A/B experiment. K0 changes the vLLM engine
cache, R1 changes load scoring, R2 adds approximate affinity, and R3/M4A
change the source of cache-ownership state. Their ratios must not be
multiplied or treated as additive feature gains.

## 2. Repository context and effective configuration

The relevant llm-d repository surfaces are:

- [optimized baseline](../../guides/optimized-baseline/README.md);
- [standalone Router base values](../../guides/recipes/router/base.values.yaml);
- [precise prefix-cache routing guide](../../guides/precise-prefix-cache-routing/README.md);
- [precise Router values](../../guides/precise-prefix-cache-routing/router/precise-prefix-cache-routing.values.yaml).

Those files describe the architecture and current examples. They are not
literal frozen manifests for this historical matrix. In particular, current
example models and calibration values differ from the values below.

### 2.1 Common model-server configuration

| Parameter | Effective value |
| --- | --- |
| Model | `Qwen/Qwen3-32B` |
| Snapshot | `9216db5781bf21249d130ec9da846c4624c16137` |
| Image | `ghcr.io/llm-d/llm-d-xpu:v0.9.0` |
| Image ID | `sha256:15156bdeea9d868f5bbbf3a9a1c4d874de32bf85008a79349e6b90bc8ef35443` |
| vLLM | 0.26.0 |
| Precision | BF16 |
| Tensor parallelism | TP4 per Aggregate replica |
| XPU allocation | 4 Intel B60 per replica |
| Block size | 64 |
| Maximum model length | 32,768 |
| XPU memory utilization | 0.89 |
| Maximum batched tokens | 2,048 |
| Maximum sequences | 128 |
| Chunked prefill | enabled |
| CPU / memory | 32 CPU / 128 GiB per replica |

R0 through R3 and M4A used Aggregate model servers. They did not use P/D KV
transfer or NIXL between Prefill and Decode roles.

### 2.2 Common validity rules

An arm was accepted only when:

1. measured request, input-token, and output-token counts were exact;
2. measured requests had no failures;
3. model Pods met the frozen resource contract and did not restart during
   measurement;
4. the feature-specific Router or cache gate passed;
5. frozen inputs and collected results passed checksum validation; and
6. the namespace and XPU claims were released after the run.

Ratios in this report use `treatment / control`. For throughput, values above
one favor treatment. For latency, values below one favor treatment.

## 3. R0: Direct Service versus EPP

### 3.1 Design

R0 used one Qwen3-32B TP4 Aggregate backend on one node. Both arms addressed
the same model configuration:

- **control:** direct Kubernetes Service;
- **treatment:** Envoy and EPP with in-flight load production,
  active-request scoring, and max-score picking.

The backend was recreated between arms to avoid carrying engine state across
the path comparison.

| ISL | OSL | Concurrency | Measured requests | Warm-up requests | Arrival |
| ---: | ---: | ---: | ---: | ---: | --- |
| 1,024 | 128 | 1 | 16 | 2 | closed loop |
| 1,024 | 128 | 32 | 64 | 4 | closed loop |
| 1,024 | 128 | 64 | 128 | 4 | closed loop |

### 3.2 Results

| Case | Direct output tok/s | EPP output tok/s | EPP/direct | Direct p99 TTFT | EPP p99 TTFT | EPP/direct | Direct p99 E2E | EPP p99 E2E | EPP/direct |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| C1 | 19.423 | 19.301 | 0.9937 | 330.828 ms | 331.274 ms | 1.0013 | 6,647.288 ms | 7,090.495 ms | 1.0667 |
| C32 | 242.091 | 242.053 | 0.9998 | 10,399.594 ms | 10,385.679 ms | 0.9987 | 24,942.432 ms | 24,946.896 ms | 1.0002 |
| C64 | 258.689 | 260.568 | 1.0073 | 28,439.217 ms | 28,419.884 ms | 0.9993 | 52,814.606 ms | 52,805.707 ms | 0.9998 |

At C32 and C64, the observed throughput and p99 TTFT differences were within
0.8%. The C1 p99 E2E increase was 6.67%, but that case contained only 16
measured requests and one repetition.

All six arm-case results passed exact validation. One evidence caveat does
not change the numeric result: two files intended to capture EPP logs
captured the chart's default Envoy container because the collection command
did not select the EPP container explicitly.

### 3.3 Interpretation boundary

R0 supports only the statement that no measurable steady-state path penalty
appeared at C32/C64 in this single-backend test. It does not test
multi-replica selection or any cache-aware Router feature.

## 4. R1: Active-request versus token-load routing

### 4.1 Design

R1 used two fixed Qwen3-32B TP4 Aggregate replicas and two simultaneous
independent streams:

| Stream | ISL | OSL | Concurrency | Requests | Rate | Seed |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Short | 512 | 128 | 32 | 64 | 0.5 requests/s | 391510512 |
| Long | 8,192 | 128 | 32 | 32 | 0.1 requests/s | 391518192 |

Both policies used the same in-flight producer and max-score picker:

- **control:** active-request scorer;
- **treatment:** token-load scorer.

Three repetitions were completed; the second reversed policy order.

### 4.2 Results

The copied analysis snapshot preserves per-repetition ratios rather than
absolute arm values. Ratios below are token-load/active-request.

| Stream | Metric | Rep 1 | Rep 2, reversed | Rep 3 | Median |
| --- | --- | ---: | ---: | ---: | ---: |
| Short | output throughput | 0.9914 | 0.9850 | 1.0094 | 0.9914 |
| Short | p99 TTFT | 0.5915 | 0.1425 | 0.3179 | 0.3179 |
| Short | p99 E2E | 1.1271 | 0.8760 | 1.0600 | 1.0600 |
| Long | output throughput | 0.9996 | 1.0001 | 0.9983 | 0.9996 |
| Long | p99 TTFT | 1.0082 | 1.2828 | 1.1118 | 1.1118 |
| Long | p99 E2E | 1.1172 | 1.1160 | 0.9062 | 1.1160 |

Additional median ratios:

| Stream | Mean TTFT | Mean TPOT | p99 TPOT | Mean E2E |
| --- | ---: | ---: | ---: | ---: |
| Short | 0.7539 | 1.0503 | 1.0615 | 1.0276 |
| Long | 1.0020 | 1.0391 | 1.1570 | 1.0297 |

Token-load routing left throughput effectively unchanged. Its median short
p99 TTFT was 68.2% lower, while long p99 TTFT was 11.2% higher.

All 12 stream results passed exact validation. Each policy also emitted 15
error-level EPP records for non-inference readiness and metrics requests.
No measured inference request failed; therefore the records are retained as
observability noise, not described as an error-free EPP log.

### 4.3 Interpretation boundary

R1 shows latency allocation between mixed-length streams, not increased
model capacity. Equal endpoint request counts are not an objective because a
short request and a long request represent different amounts of work.

## 5. K0: Prefix cache off versus on

### 5.1 Design

K0 isolated vLLM prefix caching on one directly addressed Qwen3-32B TP4
Aggregate server:

- **control:** explicit prefix caching off;
- **treatment:** explicit prefix caching on.

The namespace and model Pod were recreated between arms.

| Parameter | Value |
| --- | --- |
| Shared-prefix groups | 1 |
| Shared prefix | 8,192 tokens |
| Unique suffix | 256 tokens |
| Input total | 8,448 tokens |
| Output | 128 tokens |
| Measured requests | 32 per arm |
| Concurrency | 8 |
| Warm-up | one directed request per arm |

Requests used deterministic token IDs.

### 5.2 Results

| Mode | Request throughput | Output throughput | Mean E2E | p99 E2E | Cache hits | Cache queries | Hit ratio |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Off | 0.2613 req/s | 33.441 tok/s | 29.649 s | 52.182 s | 0 | 0 | 0.0000 |
| On | 1.1181 req/s | 143.114 tok/s | 7.147 s | 7.187 s | 262,144 | 278,784 | 0.9403 |

Prefix-cache on/off ratios were:

- request and output throughput: `4.2796`;
- mean E2E: `0.2410`;
- p99 E2E: `0.1377`.

All 64 requests returned exact 8,448-token prompts and 128 output tokens.
The cache-off hit ratio of zero is the analyzer's zero-query convention, not
a measured `0 / positive-query-count` fraction.

### 5.3 Interpretation boundary

K0 is an engine-cache upper-bound result for one highly reused prefix group.
It is not an llm-d Router benefit and cannot be generalized to traffic
without shared prefixes.

## 6. R2: Token-load versus approximate prefix affinity

### 6.1 Design

R2 used two cache-enabled Qwen3-32B TP4 Aggregate replicas. Both arms had the
approximate-prefix and in-flight producers, token-load scorer, and max-score
picker:

- **control:** token-load routing only;
- **treatment:** the same policy plus a prefix-cache-affinity filter.

The affinity filter used a live B60 calibration and the resolved 2,048-token
scheduler chunk.

| Parameter | Value |
| --- | --- |
| Prefix groups | 4 |
| Shared prefix | 8,192 tokens |
| Unique suffix | 256 tokens |
| Output | 128 tokens |
| Measured requests | 32 per arm |
| Concurrency | 8 |
| Repetition order | token-first, affinity-first, token-first |

Each group was warmed before measured traffic.

### 6.2 Results

Ratios are affinity/token-only. The retained analysis contains ratios and
cache counters, but not arm-level absolute throughput and latency values.

| Repetition | B60 calibration | Output throughput | Mean E2E | p99 E2E | Token-only hit ratio | Affinity hit ratio |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 3,159 tok/s | 1.1816 | 0.8871 | 0.8037 | 0.7811 | 0.8620 |
| 2, reversed | 3,156 tok/s | 1.2808 | 0.8412 | 0.5584 | 0.7542 | 0.8620 |
| 3 | 3,155 tok/s | 1.0909 | 0.8894 | 0.8074 | 0.7542 | 0.8620 |
| **Median** | **3,156 tok/s** | **1.1816** | **0.8871** | **0.8037** | **0.7542** | **0.8620** |

Median output throughput increased 18.2%, mean E2E decreased 11.3%, and p99
E2E decreased 19.6%. All three repetitions had the same direction.

The affinity arm's endpoint splits were 18/18, 27/9, and 27/9. That
imbalance is compatible with correct group ownership: this experiment
optimizes cache locality, not equal request counts.

All 192 measured requests were exact-valid; both arms explicitly enabled
prefix caching, no model Pod restarted, and checksum and cleanup gates
passed.

### 6.3 Interpretation boundary

The result applies to four repeatedly used prefix groups on two replicas. It
does not establish a generic load-balancing benefit or performance under
low prefix reuse.

## 7. R3: Approximate versus precise KV-event ownership

### 7.1 Functional gate

Before Qwen3-32B performance traffic, a two-replica Qwen3-8B TP1 smoke
validated:

- two active ZMQ publishers and subscribers;
- 98 admissions and 72 evictions;
- 8/8 index lookups;
- 64 matched blocks and 8 sticky decisions.

An earlier smoke was excluded because an XPU warning contaminated controller
stdout and broke the first parser revision.

### 7.2 Performance design

R3 used two cache-enabled and KV-event-enabled Qwen3-32B TP4 Aggregate
replicas. Both arms used token-load scoring, affinity filtering, and the same
B60 calibration:

- **control:** approximate prefix state built from Router observations;
- **treatment:** endpoint discovery and precise prefix state built from
  vLLM KV events.

Precise mode used 64-token blocks, speculative indexing, event discovery on
port 5556, tokenizer/render access, and a 3,156 tok/s prefill calibration.

| Parameter | Value |
| --- | --- |
| Prefix groups | 14 |
| Ownership warm-up | 7 groups per replica |
| Shared prefix | 8,192 tokens |
| Unique suffix | 256 tokens |
| Output | 128 tokens |
| Requests per group | 4 |
| Measured requests | 56 per arm |
| Concurrency | 8 |
| Repetition order | approximate-first, precise-first, approximate-first |

This deliberately created a warm-engine/cold-Router boundary.

### 7.3 Results

Ratios are precise/approximate.

| Rep | Approx output tok/s | Precise output tok/s | Output ratio | Approx mean E2E | Precise mean E2E | Mean ratio | Approx p99 E2E | Precise p99 E2E | p99 ratio |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 113.080 | 135.975 | 1.2025 | 9.006 s | 7.381 s | 0.8195 | 18.963 s | 7.936 s | 0.4185 |
| 2, reversed | 111.867 | 141.740 | 1.2670 | 8.970 s | 7.113 s | 0.7930 | 18.920 s | 7.718 s | 0.4079 |
| 3 | 113.502 | 141.715 | 1.2486 | 8.774 s | 7.125 s | 0.8121 | 19.864 s | 7.787 s | 0.3920 |
| **Median ratio** | — | — | **1.2486** | — | — | **0.8121** | — | — | **0.4079** |

Median output throughput increased 24.9%, mean E2E decreased 18.8%, and p99
E2E decreased 59.2%.

Precise hit ratio was 0.7758 in every repetition; approximate hit ratios
were 0.6372, 0.6511, and 0.6511. Precise routing sent 28 measured requests to
each replica and recorded:

- 56/56 lookup requests and hits;
- 7,168 matched blocks;
- 56 sticky decisions;
- 9,520 admissions and 7,481 evictions;
- 142 to 150 event messages per run.

All 336 measured requests were exact-valid, with zero restarts and passed
feature, checksum, and cleanup gates.

### 7.4 Interpretation boundary

R3 is not a cost-free one-line plugin substitution: precise mode also adds
publishers, endpoint discovery, tokenization/render access, and block-index
maintenance. The result applies to recovery of real ownership when engine
caches are already warm but Router history is absent. It does not establish
the same benefit for low-reuse traffic or an already trained approximate
Router.

## 8. M4A: Four-replica precise ownership ABBA

### 8.1 Design

M4A extended the shared-prefix ownership question to four Aggregate TP4
replicas distributed as two replicas on each of two nodes. Each arm used 16
fresh B60 allocations and KV-event-enabled, prefix-cache-enabled model
servers.

- **control:** approximate cache state with in-flight/token-load routing;
- **treatment:** precise KV-event prefix ownership;
- **workload:** the same 14-group, 8,192-prefix + 256-suffix, OSL128, C8 W2
  workload used by R3;
- **order:** control, ownership, ownership, control;
- **measured traffic:** 56 requests per arm, 224 total.

### 8.2 Slot and ABBA results

| Slot | Variant | Output tok/s | Mean E2E | p99 E2E |
| ---: | --- | ---: | ---: | ---: |
| 1 | Control | 127.678 | 7.674 s | 13.207 s |
| 2 | Ownership | 141.543 | 6.978 s | 8.220 s |
| 3 | Ownership | 143.288 | 7.013 s | 9.008 s |
| 4 | Control | 123.197 | 8.058 s | 14.224 s |

| Metric | Control mean | Ownership mean | Ownership/control |
| --- | ---: | ---: | ---: |
| Output throughput | 125.437 tok/s | 142.416 tok/s | 1.1354 |
| Mean E2E | 7.866 s | 6.995 s | 0.8893 |
| p99 E2E | 13.716 s | 8.614 s | 0.6280 |

The ABBA means correspond to 13.5% higher throughput, 11.1% lower mean E2E,
and 37.2% lower p99 E2E. All 224 measured requests were exact-valid; all
model Pod UIDs were fresh, no Pod restarted, and routing, stability,
checksum, and cleanup gates passed.

M4A did not publish a comparable cache-hit-ratio table. Its latency and
throughput result must not be described as a directly measured hit-ratio
increase.

## 9. Cross-experiment observations

The matrix supports these narrowly scoped observations:

1. the single-backend EPP path had no measurable steady-state penalty at C32
   or C64 in R0;
2. token-load scoring redistributed TTFT between short and long streams
   without increasing R1 throughput;
3. vLLM prefix caching was the dominant optimization in K0's one-prefix
   upper-bound workload;
4. approximate affinity reduced duplicate cache population in R2;
5. precise KV state recovered actual ownership at the deliberately cold
   Router boundary in R3;
6. the four-replica M4A result repeated the favorable direction for precise
   ownership on the same high-reuse workload.

The matrix does not establish:

- that all traffic has reusable prefixes;
- that precise ownership always outperforms approximate history;
- that Router feature gains add linearly;
- that M4A improved cache hit ratio, because that comparable metric was not
  published; or
- production capacity, SLOs, or cost effectiveness.

## 10. Audit identifiers

| Experiment | Accepted run or analysis identifier |
| --- | --- |
| R0 | `router-r0-20260829T044244Z` |
| R1 | `router-r1-three-rep-analysis` |
| K0 | `prefix-k0-20260829T062540Z` |
| R2 | `router-r2-three-rep-analysis` |
| R3 | `router-r3-three-rep-analysis` |
| M4A | `final-m4a-20260830t170000z` |

These identifiers distinguish the frozen evidence sets. The report is
self-contained and does not require access to internal result storage to
understand the configuration, calculations, status, or limitations.
