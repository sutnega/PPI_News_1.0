class AdapterError(RuntimeError):
    """Base adapter error."""


class FetchError(AdapterError):
    """The endpoint could not be fetched safely."""


class ExtractionError(AdapterError):
    """The page was fetched but no valid records were extracted."""


class RobotsDenied(AdapterError):
    """robots.txt explicitly denies the configured endpoint."""

