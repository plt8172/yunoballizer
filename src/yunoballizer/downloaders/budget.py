"""Cross-platform, cross-account total-download cap shared by one `download` run.

Mirrors how --limit already works (a requested cap per account, not a
guaranteed exact count -- dedup can still skip posts already on disk): each
account is granted up to its share of what's left, and that share is spent
immediately regardless of how many of those posts turn out to be new.
"""
from __future__ import annotations


class TotalBudget:
    def __init__(self, limit: int | None) -> None:
        self.remaining = limit

    @property
    def exhausted(self) -> bool:
        return self.remaining is not None and self.remaining <= 0

    def take(self, requested: int) -> int:
        """Cap `requested` to what's left, and reserve (spend) that amount."""
        if self.remaining is None:
            return requested
        granted = max(0, min(requested, self.remaining))
        self.remaining -= granted
        return granted
