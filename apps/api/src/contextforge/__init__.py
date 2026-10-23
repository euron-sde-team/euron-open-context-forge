"""Euron Open ContextForge: less context, fewer tokens, same intelligence.

The engine is importable on its own (``from contextforge import optimize``); the service,
proxy and dashboard API live in sibling packages and are only imported when used.
"""

from contextforge.engine import (
    BudgetUnsatisfiableError,
    Document,
    Message,
    OptimizeOptions,
    OptimizeRequest,
    OptimizeResult,
    TokenizerRegistry,
    UnsupportedTokenizerError,
    optimize,
)

__version__ = "0.1.0"

__all__ = [
    "BudgetUnsatisfiableError",
    "Document",
    "Message",
    "OptimizeOptions",
    "OptimizeRequest",
    "OptimizeResult",
    "TokenizerRegistry",
    "UnsupportedTokenizerError",
    "__version__",
    "optimize",
]
