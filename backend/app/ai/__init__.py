"""AI package.

Keep package import side effects minimal so provider-side modules can import the
candidate decision subpackage without recursively importing OllamaService.
"""

__all__ = ["AIGateway"]


def __getattr__(name: str):
    if name == "AIGateway":
        from .gateway import AIGateway
        return AIGateway
    raise AttributeError(name)
