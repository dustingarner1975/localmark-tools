"""Read-only access to LocalMark's public evidence."""

from .client import LocalMarkClient, LocalMarkError
from .policy import load_policy, validate_policy

__version__ = "0.4.0"
__all__ = ["LocalMarkClient", "LocalMarkError", "load_policy", "validate_policy"]
