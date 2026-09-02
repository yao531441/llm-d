# P/D Benchmark Reports

This directory collects detailed benchmark reports for llm-d Prefill/Decode disaggregation.

| Report | Scope |
| --- | --- |
| [Qwen3-32B on Intel B60](./qwen3-32b-intel-b60-benchmark.md) | Initial 1P1D validation, Aggregate/P-D comparisons, P:D topology ratios, 3P1D failure boundary, and equal-resource ABBA |
| [Experimental Router and prefix-cache study](./experimental-qwen3-32b-intel-b60-router-cache.md) | Agent-planned R0/R1/K0/R2/R3 and four-replica ownership experiments |
| [Experimental P/D transport and integrated-policy study](./experimental-qwen3-32b-intel-b60-transport-policy.md) | Agent-planned staged NIXL/RDMA diagnostics, Decode-pressure test, and P2 policy ABBA |
| [Experimental feature and reliability study](./experimental-qwen3-32b-intel-b60-reliability.md) | Agent-planned CPU KV offload compatibility, flow control, endpoint loss, and closeout |

Files with the `experimental-` prefix report matrices independently planned
by GitHub Copilot CLI, powered by GPT-5.6 Sol. They were not preregistered or
reviewed item-by-item by the report author before execution. Their
interpretations are exploratory pending human review and independent
repetition.
