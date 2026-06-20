"""Consistent audit-log writing.

Every important action (proposal, vote, risk decision, order, reconciliation) should
go through :func:`log_event` so the audit trail is uniform and JSON-serialized.
"""

from __future__ import annotations

import json
from typing import Any

from sqlmodel import Session

from trading_council.models import AuditLog


def log_event(
    session: Session,
    *,
    actor: str,
    action: str,
    entity_type: str,
    entity_id: str,
    decision: str | None = None,
    details: dict[str, Any] | None = None,
) -> AuditLog:
    """Add an audit entry to the caller's transaction and flush it.

    Flushes so the row gets its id, but does not commit — the caller owns the
    transaction. Serialization errors propagate (not swallowed) so bad payloads
    surface loudly instead of being silently dropped from the audit trail.
    """
    entry = AuditLog(
        actor=actor,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        decision=decision,
        details_json=json.dumps(details or {}),
    )
    session.add(entry)
    session.flush()
    return entry
