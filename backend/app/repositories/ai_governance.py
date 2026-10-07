from __future__ import annotations

import hashlib
import uuid
from typing import Any

from ..db import Database

RULES_VERSION = "candidate-rules-2026-10-06"
PROMPT_SCHEMA_VERSION = "field-candidate-schema-v2"


class AIGovernanceRepository:
    def __init__(self, db: Database):
        self.db = db

    async def policy(self) -> dict[str, Any]:
        row = await self.db.p().fetchrow(
            """SELECT organization_id,external_system1_enabled,provider,provider_model,
                      consent_note,consented_by_user_id,consented_at,metadata,updated_at
                 FROM organization_ai_policies
                WHERE organization_id=autodraft_current_organization_id()"""
        )
        if not row:
            return {
                "external_system1_enabled": False,
                "provider": "off",
                "provider_model": "",
                "consent_note": "",
                "consented_by_user_id": None,
                "consented_at": None,
                "metadata": {},
            }
        return dict(row)

    async def update_policy(
        self,
        *,
        enabled: bool,
        provider: str,
        provider_model: str,
        consent_note: str,
        user_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized = provider.strip().lower()
        if normalized not in {"off", "jev"}:
            raise ValueError("AI provider must be off or jev")
        if enabled and normalized == "off":
            raise ValueError("An external provider must be selected when external System-1 is enabled")
        return dict(await self.db.p().fetchrow(
            """INSERT INTO organization_ai_policies(
                   organization_id,external_system1_enabled,provider,provider_model,consent_note,
                   consented_by_user_id,consented_at,metadata
                 ) VALUES(
                   autodraft_current_organization_id(),$1,$2,$3,$4,$5::uuid,
                   CASE WHEN $1 THEN NOW() ELSE NULL END,$6::jsonb
                 )
                 ON CONFLICT(organization_id) DO UPDATE SET
                   external_system1_enabled=EXCLUDED.external_system1_enabled,
                   provider=EXCLUDED.provider,
                   provider_model=EXCLUDED.provider_model,
                   consent_note=EXCLUDED.consent_note,
                   consented_by_user_id=EXCLUDED.consented_by_user_id,
                   consented_at=EXCLUDED.consented_at,
                   metadata=EXCLUDED.metadata,
                   updated_at=NOW()
                 RETURNING *""",
            bool(enabled), normalized, provider_model.strip(), consent_note.strip(), user_id, metadata or {},
        ))

    @staticmethod
    def candidate_fingerprint(document: str, variable: Any) -> str:
        candidate_id = str(getattr(variable, "candidate_id", None) or getattr(variable, "candidateId", None) or "")
        text = str(getattr(variable, "original_text", None) or getattr(variable, "originalText", None) or "")
        position = int(getattr(variable, "position", 0) or 0)
        context_start = max(0, position - 80)
        context_end = min(len(document), position + len(text) + 80)
        material = f"{candidate_id}\n{position}\n{text}\n{document[context_start:context_end]}".encode("utf-8")
        return hashlib.sha256(material).hexdigest()

    async def persist_candidates(
        self,
        *,
        document: str,
        variables: list[Any],
        actor_user_id: str,
        request_id: uuid.UUID,
        provider: str,
        model_version: str,
        provider_chain: list[str],
        provider_versions: dict[str, str] | None = None,
    ) -> dict[str, str]:
        result: dict[str, str] = {}
        async with self.db.p().transaction() as conn:
            for variable in variables:
                candidate_id = str(getattr(variable, "candidate_id", None) or "")
                if not candidate_id:
                    continue
                text = str(getattr(variable, "original_text", None) or "")
                evidence = []
                for item in list(getattr(variable, "candidate_evidence", None) or []):
                    if hasattr(item, "model_dump"):
                        evidence.append(item.model_dump(by_alias=True))
                    elif isinstance(item, dict):
                        evidence.append(dict(item))
                decision_source=str(getattr(variable,"decision_source",None) or "")
                versions=dict(provider_versions or {})
                candidate_provider={"rule":"rules","system1":"jev","qwen":"ollama","lawyer":"lawyer"}.get(decision_source,provider)
                candidate_model=str(versions.get(candidate_provider) or (model_version if candidate_provider==provider else ""))
                decision_path=[]
                for ev in evidence:
                    decision_path.append({"stage":ev.get("source") or ev.get("decisionSource") or "evidence","classification":ev.get("classification"),"confidence":ev.get("confidence"),"reasonCodes":ev.get("reasonCodes") or ev.get("reason_codes") or []})
                decision_path.append({"stage":decision_source or candidate_provider,"classification":str(getattr(variable,"classification",None) or ""),"reasonCodes":list(getattr(variable,"reason_codes",None) or [])})
                row = await conn.fetchrow(
                    """INSERT INTO candidate_decision_audit(
                           organization_id,actor_user_id,request_id,candidate_id,candidate_fingerprint,
                           source_position,source_length,provider_chain,provider_versions,provider,model_version,
                           rules_version,prompt_schema_version,classification,decision_source,review_state,
                           reason_codes,evidence,decision_path
                         ) VALUES(
                           autodraft_current_organization_id(),$1::uuid,$2,$3,$4,$5,$6,$7::jsonb,$8::jsonb,$9,$10,
                           $11,$12,$13,$14,$15,$16::jsonb,$17::jsonb,$18::jsonb
                         )
                         ON CONFLICT(organization_id,request_id,candidate_id) DO UPDATE SET
                           provider_chain=EXCLUDED.provider_chain,provider_versions=EXCLUDED.provider_versions,provider=EXCLUDED.provider,
                           model_version=EXCLUDED.model_version,classification=EXCLUDED.classification,
                           decision_source=EXCLUDED.decision_source,review_state=EXCLUDED.review_state,
                           reason_codes=EXCLUDED.reason_codes,evidence=EXCLUDED.evidence,decision_path=EXCLUDED.decision_path
                         RETURNING id""",
                    actor_user_id, request_id, candidate_id, self.candidate_fingerprint(document, variable),
                    int(getattr(variable, "position", 0) or 0), len(text), provider_chain,versions,candidate_provider,candidate_model,
                    RULES_VERSION, PROMPT_SCHEMA_VERSION,
                    str(getattr(variable, "classification", None) or ""),decision_source,
                    str(getattr(variable, "review_state", None) or ""),
                    list(getattr(variable, "reason_codes", None) or []), evidence,decision_path,
                )
                result[candidate_id] = str(row["id"])
        return result

    async def lawyer_disposition(
        self,
        record_id: uuid.UUID,
        *,
        lawyer_user_id: str,
        disposition: str,
        reason: str,
    ) -> dict[str, Any] | None:
        normalized = disposition.strip().lower()
        if normalized not in {"accepted", "rejected"}:
            raise ValueError("Lawyer disposition must be accepted or rejected")
        row = await self.db.p().fetchrow(
            """UPDATE candidate_decision_audit
                  SET final_lawyer_disposition=$1,lawyer_user_id=$2::uuid,lawyer_reason=$3,
                      lawyer_reviewed_at=NOW()
                WHERE id=$4 RETURNING *""",
            normalized, lawyer_user_id, reason.strip(), record_id,
        )
        return dict(row) if row else None
