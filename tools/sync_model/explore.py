"""Deterministic breadth-first bounded safety exploration, never a full proof."""
from collections import deque
from dataclasses import dataclass

from model import EVENTS, State, step, violations


@dataclass(frozen=True)
class Result:
    states: int
    transitions: int
    depth: int
    state_limit: int
    truncated: bool
    trace: tuple = ()
    errors: tuple = ()


def explore(depth=10, state_limit=60000, *, test_fault=None):
    if depth < 0 or state_limit < 1:
        raise ValueError("nonnegative depth and positive state limit required")
    queue = deque([(State(), ())])
    seen = {State()}
    transitions = 0
    truncated = False
    while queue:
        before, trace = queue.popleft()
        if len(trace) >= depth:
            continue
        for event in EVENTS:
            after, effect = step(before, event, test_fault=test_fault)
            transitions += 1
            errors = violations(before, event, after, effect)
            if errors:
                return Result(len(seen), transitions, depth, state_limit, truncated,
                              trace + (event,), tuple(errors))
            if after not in seen:
                if len(seen) >= state_limit:
                    truncated = True
                    continue
                seen.add(after)
                queue.append((after, trace + (event,)))
    return Result(len(seen), transitions, depth, state_limit, truncated)


if __name__ == "__main__":
    result = explore()
    print(result)
    raise SystemExit(bool(result.errors))
