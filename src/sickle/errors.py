class SickleError(Exception):
    """Base exception for all Sickle business errors."""


class ConfigError(SickleError):
    """Raised when config loading or validation fails."""


class AgentBusyError(SickleError):
    """Raised when operator is busy and cannot accept new work."""


class UserCancelled(SickleError):
    """Raised when user requests cancellation."""


class SandboxRejected(SickleError):
    """Raised when sandbox policy rejects generated code."""


class LLMUnavailable(SickleError):
    """Raised when LLM is unavailable after retries."""
