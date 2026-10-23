"""The ContextForge engine: deterministic context optimization, usable as a library.

    from contextforge import optimize, OptimizeRequest

    result = optimize(OptimizeRequest(model="gpt-4o", messages=[...],
                                      options={"max_input_tokens": 4000}))
    print(result.stats.reduction_percent, result.warnings)

No network, no database, no LLM: everything here runs in-process.
"""

from contextforge.engine.pipeline import BudgetUnsatisfiableError, optimize
from contextforge.engine.profiles import BUILTIN_PROFILES, Profile, detect_workload
from contextforge.engine.summarizer import ExtractiveSummarizer, Summarizer
from contextforge.engine.tokenizers import TokenizerRegistry, UnsupportedTokenizerError
from contextforge.engine.types import (
    Document,
    Message,
    OptimizeOptions,
    OptimizeRequest,
    OptimizeResult,
)

__all__ = [
    "BUILTIN_PROFILES",
    "BudgetUnsatisfiableError",
    "Document",
    "ExtractiveSummarizer",
    "Message",
    "OptimizeOptions",
    "OptimizeRequest",
    "OptimizeResult",
    "Profile",
    "Summarizer",
    "TokenizerRegistry",
    "UnsupportedTokenizerError",
    "detect_workload",
    "optimize",
]
