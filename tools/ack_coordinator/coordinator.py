"""Synthetic, sequential, memory-only ACK experiment; no authentication."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Request:
    account: str
    epoch: int
    operation: int


@dataclass(frozen=True)
class Snapshot:
    account: str | None
    epoch: int
    next_operation: int
    pending: frozenset[Request]
    effects: tuple[Request, ...]


class AckCoordinator:
    def __init__(self) -> None:
        self._account: str | None = None
        self._epoch = 0
        self._next_operation = 1
        self._pending: set[Request] = set()
        self._effects: list[Request] = []

    def replace_session(self, account: str) -> None:
        """Also advances the epoch when replacing with the same account."""
        if not isinstance(account, str) or not account:
            raise ValueError("A nonempty synthetic account label is required")
        self._epoch += 1
        self._account = account

    def logout(self) -> None:
        self._epoch += 1
        self._account = None

    def start_request(self) -> Request:
        if self._account is None:
            raise ValueError("A synthetic session is required")
        request = Request(self._account, self._epoch, self._next_operation)
        self._next_operation += 1
        self._pending.add(request)
        return request

    def accept_ack(self, request: Request) -> bool:
        """Return False without mutation for stale, unknown or consumed ACKs."""
        if (
            self._account is None
            or request.account != self._account
            or request.epoch != self._epoch
            or request not in self._pending
        ):
            return False
        self._pending.remove(request)
        self._effects.append(request)
        return True

    def snapshot(self) -> Snapshot:
        return Snapshot(
            self._account,
            self._epoch,
            self._next_operation,
            frozenset(self._pending),
            tuple(self._effects),
        )
