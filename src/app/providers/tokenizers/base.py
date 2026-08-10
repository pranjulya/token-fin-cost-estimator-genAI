"""TokenCounter abstraction (PRD §13)."""

from __future__ import annotations

from typing import Protocol


class TokenCounter(Protocol):
    def count(self, model: str, text: str) -> int:
        """Estimate the number of tokens ``text`` maps to for ``model``."""
        ...
