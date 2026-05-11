"""Connector-layer exceptions."""


class ConnectorError(Exception):
    """Base class for connector failures."""

    pass


class AuthExpired(ConnectorError):
    """OAuth or bot token no longer valid; user must reconnect."""

    pass


class RateLimited(ConnectorError):
    """Upstream rate limit; retry after ``retry_after`` seconds."""

    def __init__(self, message: str = 'Rate limited', *, retry_after: int = 60):
        self.retry_after = retry_after
        super().__init__(message)


class InvalidPayload(ConnectorError):
    """Webhook or API body could not be parsed."""

    pass


class QuotaExceeded(ConnectorError):
    """Owner has no remaining verification quota (bits)."""

    pass


class CommandHandled(ConnectorError):
    """Webhook produced a synchronous reply (e.g. Telegram /start); no connector event to queue."""

    pass

