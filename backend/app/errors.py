class StateError(ValueError):
    """The requested action isn't valid in the resource's current state (HTTP 409)."""


class NotFoundError(LookupError):
    """A referenced topic/resource/session doesn't exist (HTTP 404)."""
