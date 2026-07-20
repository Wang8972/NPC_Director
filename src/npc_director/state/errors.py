class StateStoreError(RuntimeError):
    """Base error for durable state operations."""


class RecordNotFoundError(StateStoreError):
    """Requested durable record does not exist."""


class OptimisticLockError(StateStoreError):
    """Persisted version changed before the attempted update."""


class IdempotencyConflictError(StateStoreError):
    """An idempotency key was reused for a different operation."""


class StatePatchPermissionError(StateStoreError):
    """A proposed state path is outside the caller's allowlist."""


class ApprovalAlreadyResolvedError(StateStoreError):
    """An approval cannot transition away from its terminal decision."""
