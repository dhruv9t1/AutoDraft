from __future__ import annotations

from typing import Any, AsyncIterator

from ..errors import AutoDraftError, AIModelUnavailable, AIProviderUnavailable
from ..models import Variable
from ..ollama_service import OllamaService
from ..db import Database
from ..repositories.ai_governance import AIGovernanceRepository


class AIGateway:
    """Single application-facing gateway for AI capabilities.

    The active provider is Ollama today. Keeping routes and business flows behind
    this facade means a future local/hosted/Jev provider does not leak provider
    details across the application.
    """

    provider_name = "ollama"

    def __init__(self, provider: OllamaService, db: Database | None = None):
        self.provider = provider
        self.governance = AIGovernanceRepository(db) if db is not None else None

    async def external_system1_policy(self) -> dict[str, Any]:
        if self.governance is None:
            return {"enabled": False, "provider": "off", "model": ""}
        policy = await self.governance.policy()
        enabled = bool(policy.get("external_system1_enabled")) and str(policy.get("provider") or "off").lower() == "jev"
        return {"enabled": enabled, "provider": str(policy.get("provider") or "off"), "model": str(policy.get("provider_model") or "")}

    def provenance_descriptor(self, *, external_system1_enabled: bool) -> dict[str, Any]:
        chain=["rules"]
        if external_system1_enabled and self.provider.jev.enabled:
            chain.append("jev")
        chain.append("ollama")
        versions={"rules":"candidate-rules-2026-10-06","ollama":self.provider.settings.field_model}
        if external_system1_enabled and self.provider.jev.enabled:
            versions["jev"]=self.provider.jev.model
        return {"provider":"ollama","model":self.provider.settings.field_model,"providerChain":chain,"providerVersions":versions}

    @property
    def readiness(self) -> dict[str, Any]:
        return self.provider.readiness

    async def close(self) -> None:
        await self.provider.close()

    async def check_readiness(self, *, probe: bool = True) -> dict[str, Any]:
        state = await self.provider.check_readiness(probe=probe)
        return {"provider": self.provider_name, **state}

    def require_ready(self) -> None:
        state = self.readiness
        if not state.get("reachable"):
            raise AIProviderUnavailable(state.get("error") or "Ollama is not reachable.")
        if not state.get("modelAvailable"):
            raise AIModelUnavailable(state.get("error") or "Configured Ollama model is not installed.")
        if state.get("structuredOutput") is False:
            raise AIProviderUnavailable(state.get("error") or "Structured AI output is not ready.")

    async def _ensure_ready(self) -> None:
        if not self.readiness.get("ready"):
            await self.check_readiness(probe=True)
        self.require_ready()

    async def identify_variables(
        self,
        document: str,
        known: list[Variable] | None = None,
        boilerplate_values: set[str] | None = None,
    ):
        policy = await self.external_system1_policy()
        try:
            await self._ensure_ready()
        except AutoDraftError as exc:
            preview, mode = await self.provider.preview_candidates(document, boilerplate_values, allow_external_system1=policy["enabled"])
            return preview, True, mode, [
                f"System-2 AI is unavailable ({exc.message}). Deterministic/System-1 candidates are shown for lawyer review only and were not auto-bound."
            ]
        return await self.provider.identify_variables(document, known, boilerplate_values, allow_external_system1=policy["enabled"])

    async def stream_variables(
        self,
        document: str,
        known: list[Variable] | None = None,
        boilerplate_values: set[str] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        policy = await self.external_system1_policy()
        try:
            await self._ensure_ready()
        except AutoDraftError as exc:
            preview, mode = await self.provider.preview_candidates(document, boilerplate_values, allow_external_system1=policy["enabled"])
            yield {
                "event": "start",
                "data": {"identificationMode": mode.value, "totalChunks": 0, "plan": 0, "blocks": 0},
            }
            yield {
                "event": "_final",
                "data": {
                    "variables": preview,
                    "ai_failed": True,
                    "identificationMode": mode.value,
                    "coverageWarnings": [
                        f"System-2 AI is unavailable ({exc.message}). Candidates are review-only and were not auto-bound."
                    ],
                    "plan": 0,
                    "blocks": 0,
                },
            }
            return
        async for item in self.provider.stream_variables(document, known, boilerplate_values, allow_external_system1=policy["enabled"]):
            yield item

    async def structured_analysis(
        self,
        system: str,
        user: str,
        *,
        schema: dict[str, Any] | str = "json",
        purpose: str = "general",
    ) -> dict[str, Any]:
        await self._ensure_ready()
        return await self.provider.structured_analysis(system, user, schema=schema, purpose=purpose)
