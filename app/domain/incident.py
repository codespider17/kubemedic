from enum import StrEnum


class IncidentStatus(StrEnum):
    RECEIVED = "RECEIVED"
    COLLECTING = "COLLECTING"
    ANALYZING = "ANALYZING"
    REPORTED = "REPORTED"
    RESOLVED = "RESOLVED"
    FAILED = "FAILED"


ALLOWED_TRANSITIONS: dict[IncidentStatus, set[IncidentStatus]] = {
    IncidentStatus.RECEIVED: {
        IncidentStatus.COLLECTING,
        IncidentStatus.FAILED,
        IncidentStatus.RESOLVED,
    },
    IncidentStatus.COLLECTING: {
        IncidentStatus.ANALYZING,
        IncidentStatus.FAILED,
        IncidentStatus.RESOLVED,
    },
    IncidentStatus.ANALYZING: {
        IncidentStatus.REPORTED,
        IncidentStatus.FAILED,
        IncidentStatus.RESOLVED,
    },
    IncidentStatus.REPORTED: {IncidentStatus.RESOLVED},
    IncidentStatus.FAILED: {
        IncidentStatus.COLLECTING,
        IncidentStatus.RESOLVED,
    },
    IncidentStatus.RESOLVED: {IncidentStatus.RECEIVED},
}


class InvalidIncidentTransition(ValueError):
    pass


def validate_transition(
    current: IncidentStatus,
    target: IncidentStatus,
) -> None:
    if current == target:
        return

    allowed = ALLOWED_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise InvalidIncidentTransition(
            f"invalid incident transition: {current} -> {target}"
        )
