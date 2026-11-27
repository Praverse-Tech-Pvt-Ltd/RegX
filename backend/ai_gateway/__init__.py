"""The REGX AI gateway: the one way REGX code asks a language model for text.

Thin slice only (docs/EXECUTION_PLAN_2026-11.md section C): provider interface,
off switch, prompt versioning, tenant check, safe logging, timeout / retry /
circuit breaker, basic metrics. No retrieval, no chat, no AI feature.

This app never opens a network connection itself. The HTTP adapter lives in
`external_integrations.ai_http` (the only outbound network edge) and registers
itself here at start-up, so the dependency runs edge -> domain, as the
import-linter contracts require.
"""
