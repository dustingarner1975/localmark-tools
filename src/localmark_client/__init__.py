"""Read-only access to LocalMark's public evidence."""

from .client import LocalMarkClient, LocalMarkError

__version__ = "0.3.0"
__all__ = ["LocalMarkClient", "LocalMarkError"]
