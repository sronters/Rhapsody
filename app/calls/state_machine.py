from __future__ import annotations

CALL_SESSION_STATUSES = {
    "REQUESTED",
    "WAITING_FOR_CALL",
    "CONNECTING",
    "JOINED",
    "RECORDING",
    "CONNECTED_NO_AUDIO",
    "RECONNECTING",
    "FINALIZING",
    "COMPLETED",
    "FAILED",
    "CANCELLED",
}

ACTIVE_CALL_SESSION_STATUSES = {
    "REQUESTED",
    "WAITING_FOR_CALL",
    "CONNECTING",
    "JOINED",
    "RECORDING",
    "CONNECTED_NO_AUDIO",
    "RECONNECTING",
    "FINALIZING",
}

TERMINAL_CALL_SESSION_STATUSES = {"COMPLETED", "FAILED", "CANCELLED"}

ALLOWED_CALL_SESSION_TRANSITIONS = {
    "REQUESTED": {"WAITING_FOR_CALL", "CONNECTING", "CANCELLED", "FAILED"},
    "WAITING_FOR_CALL": {"CONNECTING", "CANCELLED", "FAILED"},
    "CONNECTING": {"JOINED", "RECONNECTING", "CANCELLED", "FAILED"},
    "JOINED": {"RECORDING", "CONNECTED_NO_AUDIO", "FINALIZING", "CANCELLED", "FAILED"},
    "RECORDING": {"CONNECTED_NO_AUDIO", "RECONNECTING", "FINALIZING", "CANCELLED", "FAILED"},
    "CONNECTED_NO_AUDIO": {"RECONNECTING", "FAILED", "CANCELLED"},
    "RECONNECTING": {"RECORDING", "FAILED", "CANCELLED"},
    "FINALIZING": {"COMPLETED", "FAILED"},
    "COMPLETED": set(),
    "FAILED": set(),
    "CANCELLED": set(),
}


class CallSessionStateError(ValueError):
    pass


def assert_call_session_transition(current: str, target: str) -> None:
    if current not in CALL_SESSION_STATUSES:
        raise CallSessionStateError(f"Unknown call session status: {current}.")
    if target not in CALL_SESSION_STATUSES:
        raise CallSessionStateError(f"Unknown call session status: {target}.")
    if current == target:
        return
    if target not in ALLOWED_CALL_SESSION_TRANSITIONS[current]:
        raise CallSessionStateError(f"Cannot move call session from {current} to {target}.")
