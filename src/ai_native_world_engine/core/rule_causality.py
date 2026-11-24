"""Causal metadata helpers shared by authoritative rule feedback."""

from .feedback import ActionFeedback
from .rule_contracts import RuleCandidate


def attach_pressure_causality(
    feedback: ActionFeedback,
    decision: RuleCandidate,
) -> None:
    """Attach exact Provider-pressure provenance to authoritative feedback."""

    pressure = decision.metadata.get("pressure")
    if not isinstance(pressure, dict):
        return
    pressure_id = str(pressure.get("pressure_id", "")).strip()
    if not pressure_id:
        return
    existing_ids = feedback.metadata.get("caused_by_pressure_ids", [])
    caused_by = (
        [str(item) for item in existing_ids]
        if isinstance(existing_ids, list)
        else []
    )
    if pressure_id not in caused_by:
        caused_by.append(pressure_id)
    feedback.metadata["caused_by_pressure_ids"] = caused_by
    provider_job_id = str(pressure.get("provider_job_id", "")).strip()
    if provider_job_id:
        feedback.metadata["caused_by_provider_job_ids"] = [provider_job_id]
    option_id = str(pressure.get("option_id", "")).strip()
    if option_id:
        feedback.metadata["selected_action_option_id"] = option_id
