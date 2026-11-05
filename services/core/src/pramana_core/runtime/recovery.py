"""Startup recovery (PLAN.md section 16): rebuild every open investigation from its event log.

The investigation state is the event log; the in-memory engine is only a cache (ADR 0003). On
boot the supervisor rebuilds the engine of every investigation that is not closed, checks that
the rebuilt belief equals the last recorded ``BeliefUpdated`` byte for byte, and warms the
cache. A mismatch means the replay is incomplete or the engine is not deterministic: it is
logged and appended to that investigation's log as ``EngineError`` so the console shows it.
Recovery never blocks startup on one bad investigation.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..investigations import InvestigationService
from ..observability import log


@dataclass
class RecoveryReport:
    checked: int = 0
    identical: int = 0
    mismatched: list[str] = field(default_factory=list)
    engine_changed: list[str] = field(default_factory=list)
    """Logs written by an older probability model: they replay differently by design."""
    failed: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "checked": self.checked,
            "identical": self.identical,
            "mismatched": self.mismatched,
            "engine_changed": self.engine_changed,
            "failed": self.failed,
        }


async def recover(svc: InvestigationService, limit: int = 1000) -> RecoveryReport:
    report = RecoveryReport()
    try:
        ids = await svc.open_investigations(limit)
    except Exception as exc:  # database down at boot: /ready reports it; do not crash
        log.warning("recovery_skipped", reason=type(exc).__name__)
        return report
    for inv_id in ids:
        report.checked += 1
        try:
            check = await svc.replay(inv_id, warm_cache=True)
        except Exception as exc:
            report.failed.append(inv_id)
            log.error("recovery_failed", investigation_id=inv_id, error=type(exc).__name__)
            continue
        if check.identical:
            report.identical += 1
            continue
        if check.engine_changed:
            # Not corruption: the engine was upgraded since this log was written. The
            # investigation continues under the current model (ADR 0008).
            report.engine_changed.append(inv_id)
            log.warning(
                "recovery_engine_changed",
                investigation_id=inv_id,
                recorded_model=check.recorded_model_version,
                current_model=check.current_model_version,
            )
            continue
        report.mismatched.append(inv_id)
        svc.evict(inv_id)
        log.error(
            "recovery_mismatch",
            investigation_id=inv_id,
            replayed_sha256=check.replayed_sha256,
            recorded_sha256=check.recorded_sha256,
        )
        try:
            await svc.record_engine_error(
                inv_id,
                {
                    "reason": "replay_mismatch",
                    "replayed_sha256": check.replayed_sha256,
                    "recorded_sha256": check.recorded_sha256,
                    "events_replayed": check.events_replayed,
                },
            )
        except Exception as exc:
            log.error("recovery_event_failed", investigation_id=inv_id, error=type(exc).__name__)
    log.info("recovery_done", **report.as_dict())
    return report
