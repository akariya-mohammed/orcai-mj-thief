"""Project exceptions."""


class PoliceThiefError(Exception):
    """Base for all project-specific errors."""


class HandshakeRejected(PoliceThiefError):
    """The opponent (or we) refused the pre-game handshake — do not play."""


class GatekeeperLocked(PoliceThiefError):
    """DOS detector tripped: outbound API pipe locked to protect the account (Rule 29)."""


class ProtocolViolation(PoliceThiefError):
    """An inbound message broke the wire contract — reject it, never crash on it."""
