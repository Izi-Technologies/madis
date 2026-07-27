# Madis documentation

Madis is a SIP proxy/registrar with a separate WebUI and language-neutral carrier integration contracts. These guides describe what is implemented in this repository and identify the systems that remain external.

| Question | Guide |
| --- | --- |
| How are the worker, WebUI, database, and integrations arranged? | [`architecture.md`](architecture.md) |
| Which environment variables control listeners and integrations? | [`configuration.md`](configuration.md) |
| How do I install, operate, upgrade, and troubleshoot it? | [`operations.md`](operations.md) |
| How do application teams consume events or change SIP policy? | [`integrations.md`](integrations.md), [`../api/README.md`](../api/README.md) |
| How do signed SIP applications and external modules work? | [`modules.md`](modules.md) |
| What do tests and benchmarks prove? | [`testing.md`](testing.md), [`../bench/README.md`](../bench/README.md) |
| How do I build the browser WebUI? | [`../admin/README.md`](../admin/README.md) |
| What Diameter and IMS contracts are present? | [`../api/diameter.md`](../api/diameter.md), [`../api/ims-diameter.md`](../api/ims-diameter.md) |
| What is the plan to build IMS capabilities? | [`ims-roadmap.md`](ims-roadmap.md) |
| What schemas and client examples are available? | [`../api/`](../api/), [`../sdk/README.md`](../sdk/README.md) |
| What are the production and RFC boundaries? | [`../PRODUCTION.md`](../PRODUCTION.md), [`../RFC_COMPLIANCE.md`](../RFC_COMPLIANCE.md) |

The HTTP/JSON machine API is under `/admin/api/v1/`. It has separate carrier and control bearer scopes, a durable billing event outbox, bounded CDR reads, routing/dialplan validation, and an allowlisted control-resource API. It is not a generic application database API.

The supported deployment entry point is [`../main.mko`](../main.mko). The WebUI source is under [`../admin/`](../admin/). [`../sipproxy_full.mko`](../sipproxy_full.mko) is a legacy monolithic reference and is not the deployment target.
