# Appendix B. Known Issues

- Routing proxy init container hang: [llm-d/llm-d#241](https://github.com/llm-d/llm-d/issues/241) —
  workaround: `proxy.enabled: false`.
- vLLM usage-telemetry write failures under restricted `SecurityContext` (e.g. OpenShift): set
  `DO_NOT_TRACK=1`.
