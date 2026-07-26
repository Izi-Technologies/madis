# Madis documentation

Madis is a SIP edge proxy and registrar with a separate WebUI and a set of
language-neutral carrier integration contracts. These guides describe what is
implemented in this repository and what still belongs in an external carrier
system.

| Question | Guide |
| --- | --- |
| How is the system put together? | [`architecture.md`](architecture.md) |
| Which environment variables matter? | [`configuration.md`](configuration.md) |
| How do I install, operate, upgrade, or troubleshoot it? | [`operations.md`](operations.md) |
| What do the test and benchmark commands prove? | [`testing.md`](testing.md) |
| How do application teams integrate from Python, Go, or JavaScript? | [`integrations.md`](integrations.md) |
| How do external SIP applications and TTS/STT/LLM modules participate? | [`modules.md`](modules.md) |
| What is the carrier API and how is billing acknowledged? | [`../api/README.md`](../api/README.md) |
| What Diameter/IMS interfaces are present? | [`../api/diameter.md`](../api/diameter.md), [`../api/ims-diameter.md`](../api/ims-diameter.md) |
| What does the WebUI expose? | [`../admin/README.md`](../admin/README.md) |
| What are the production and protocol status summaries? | [`../PRODUCTION.md`](../PRODUCTION.md), [`../RFC_COMPLIANCE.md`](../RFC_COMPLIANCE.md) |
| How are CPS and concurrency measured? | [`../bench/README.md`](../bench/README.md) |

## Version and scope

- Madis package version: see [`../VERSION`](../VERSION).
- Required compiler and runtime: Mako **0.4.16**.
- Supported build entry point: `main.mko` and the modular files it pulls in.
- `sipproxy_full.mko` is a legacy monolithic reference and is not the
  supported deployment target.

Madis is not a complete IMS core, SS7 stack, media server, or billing system.
It provides bounded SIP processing plus interfaces for those systems. A
production deployment still needs an independent review of topology, TLS,
DNS, media, Diameter peer policy, database recovery, and carrier-specific
interoperability requirements.
