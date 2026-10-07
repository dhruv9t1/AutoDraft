from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AutoDraftError(Exception):
    """Base typed application error safe to expose through the API."""

    code: str
    message: str
    status_code: int = 500
    recoverable: bool = False

    def __str__(self) -> str:
        return self.message


class AIError(AutoDraftError):
    pass


class AIProviderUnavailable(AIError):
    def __init__(self, message: str = "The configured AI provider is unavailable."):
        super().__init__("AI_PROVIDER_UNAVAILABLE", message, 503, True)


class AIModelUnavailable(AIError):
    def __init__(self, message: str = "The configured AI model is unavailable."):
        super().__init__("AI_MODEL_UNAVAILABLE", message, 503, True)


class AIRequestTimeout(AIError):
    def __init__(self, message: str = "The AI request timed out."):
        super().__init__("AI_TIMEOUT", message, 503, True)


class AIOutputInvalid(AIError):
    def __init__(self, message: str = "The AI provider returned invalid structured output."):
        super().__init__("AI_OUTPUT_INVALID", message, 502, True)


class AIContextTooLarge(AIError):
    def __init__(self, message: str = "The document is too large for the configured AI context."):
        super().__init__("AI_CONTEXT_TOO_LARGE", message, 413, True)


class DatabaseUnavailable(AutoDraftError):
    def __init__(self, message: str = "The database is unavailable."):
        super().__init__("DATABASE_UNAVAILABLE", message, 503, True)
