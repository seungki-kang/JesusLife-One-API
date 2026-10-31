"""Synthetic, in-memory executable specification; no application integration."""
from dataclasses import dataclass, replace


LIVE_COPIES = ("rows_replicas_cache", "receipts", "tickets", "messages", "core_ledger", "log_sinks")
EVENTS = (
    "admit_old", "admit_new", "commit_old", "commit_new", "A", "F", "drain",
    "delete", *("clean_" + name for name in LIVE_COPIES), "D", "L",
    "aux_fail", "restart", "reconcile", "undo", "ack", "replay",
    "switch_other", "switch_owner", "consent_off", "consent_on",
    "upload_permission_off", "management_permission_off", "unverify", "status",
)


@dataclass(frozen=True)
class Durable:
    # One synthetic owner, generation, sync ID and two operation IDs.
    accepted: bool = False  # A: withdrawal acceptance, not a product fence
    fence: bool = False  # F
    drained: bool = False
    done: bool = False  # D: declared server live inventory only
    tickets: frozenset = frozenset()
    row: bool = False
    receipts: frozenset = frozenset()
    erased: frozenset = frozenset()
    barrier: bool = False
    cleanup: frozenset = frozenset()
    marker: bool = False  # L: authoritative original-store deletion evidence
    local_deleted: bool = False
    retired: bool = False
    journal: bool = False
    consent: bool = True
    epoch: int = 0  # bounded: only first L or A changes retirement epoch


@dataclass(frozen=True)
class Volatile:
    account: str = "synthetic-owner"
    verified: bool = True
    upload_permission: bool = True
    management_permission: bool = True
    aux_ok: bool = True
    startup_ready: bool = True
    client_active: bool = False


@dataclass(frozen=True)
class State:
    durable: Durable = Durable()
    volatile: Volatile = Volatile()


@dataclass(frozen=True)
class Effect:
    admitted: bool = False
    committed: bool = False
    management: bool = False
    metadata: bool = False


def owner(s):
    return s.volatile.verified and s.volatile.account == "synthetic-owner"


def management_allowed(s):
    return owner(s) and s.volatile.management_permission


def upload_allowed(s):
    d, v = s.durable, s.volatile
    return (owner(s) and v.upload_permission and d.consent and v.startup_ready
            and not d.accepted and not d.retired and not d.barrier)


def step(s, event, *, test_fault=None):
    """Atomic durable changes are assumptions. Fault switches are test-only mutants."""
    d, v, effect = s.durable, s.volatile, Effect()
    manage = management_allowed(s)
    if test_fault == "management_requires_consent":
        manage = manage and d.consent
    if event.startswith("admit_"):
        op = event.removeprefix("admit_")
        allowed = upload_allowed(s)
        if test_fault == "missing_barrier":
            allowed = (owner(s) and v.upload_permission and d.consent
                       and v.startup_ready and not d.accepted and not d.retired)
        if test_fault == "missing_startup_reconciliation":
            allowed = (owner(s) and v.upload_permission and d.consent
                       and not d.accepted and not d.retired and not d.barrier)
        if allowed and op not in d.tickets and op not in d.receipts and op not in d.erased:
            d = replace(d, tickets=d.tickets | {op})
            effect = Effect(admitted=True)
    elif event.startswith("commit_"):
        op = event.removeprefix("commit_")
        # Pre-A admission may finish before F even after consent withdrawal.
        if (op in d.tickets and (not d.fence or test_fault == "missing_fence")
                and (not d.barrier or test_fault == "missing_barrier")):
            d = replace(d, tickets=d.tickets - {op}, row=True,
                        receipts=d.receipts | {op})
            effect = Effect(committed=True)
    elif event in ("A", "delete", "status") and manage:
        effect = Effect(management=True)
        if event == "A":
            d = replace(d, accepted=True, consent=False, retired=True, epoch=1)
            v = replace(v, client_active=False)
        elif event == "delete":
            # Single-ID deletion is valid while generation is still active.
            d = replace(d, barrier=True, row=False, erased=d.erased | d.receipts,
                        receipts=frozenset())
    elif event == "F" and d.accepted:
        d = replace(d, fence=True)
    elif event == "drain" and d.fence:
        d = replace(d, drained=True, tickets=frozenset())
    elif event.startswith("clean_") and d.drained:
        copy = event.removeprefix("clean_")
        if copy in LIVE_COPIES:
            d = replace(d, cleanup=d.cleanup | {copy}, barrier=True, row=False,
                        erased=d.erased | d.receipts, receipts=frozenset())
    elif event == "D" and d.drained and d.cleanup == frozenset(LIVE_COPIES):
        d = replace(d, done=True)
    elif event == "L":
        d = replace(d, marker=True, local_deleted=True, retired=True, epoch=1)
        v = replace(v, client_active=False)
        if v.aux_ok:
            d = replace(d, journal=True)
    elif event == "aux_fail":
        v = replace(v, aux_ok=False)
    elif event == "restart":
        # All volatile state is lost; owner session must be verified again.
        v = Volatile(verified=False, startup_ready=False)
    elif event == "reconcile":
        d = replace(d, journal=d.journal or d.marker)
        v = replace(v, startup_ready=True)
    elif event == "undo":
        d = replace(d, local_deleted=False)
    elif event == "ack":
        # Delayed upload ACK is bound to owner, generation and captured epoch=0.
        if owner(s) and not d.retired and not d.barrier and (d.epoch == 0 or test_fault == "missing_ack_epoch") and d.receipts:
            v = replace(v, client_active=True)
    elif event == "replay":
        effect = Effect(metadata=bool(owner(s) and d.receipts and not d.accepted
                                      and not d.barrier and not d.erased))
    elif event == "switch_other":
        v = replace(v, account="synthetic-other", client_active=False)
    elif event == "switch_owner":
        v = replace(v, account="synthetic-owner", verified=True, client_active=False)
    elif event == "consent_off":
        d = replace(d, consent=False)
    elif event == "consent_on":
        # Permission stimulus only: cannot reopen retired generation or identity.
        d = replace(d, consent=True)
    elif event == "upload_permission_off":
        v = replace(v, upload_permission=False)
    elif event == "management_permission_off":
        v = replace(v, management_permission=False)
    elif event == "unverify":
        v = replace(v, verified=False, client_active=False)
    return State(d, v), effect


def violations(before, event, after, effect):
    """Requirements checked independently of transition guard helper functions."""
    b, a, v = before.durable, after.durable, before.volatile
    errors = []
    # State deltas remain evidence even when a transition omits its effect flags.
    admitted = effect.admitted or bool(a.tickets - b.tickets)
    committed = (effect.committed or (not b.row and a.row)
                 or bool(a.receipts - b.receipts))
    management_change = (not b.accepted and a.accepted) or (
        event == "delete" and a != b)
    activated = not v.client_active and after.volatile.client_active
    if effect.admitted != bool(a.tickets - b.tickets):
        errors.append("admission effect must match ticket delta")
    if effect.committed != bool(a.receipts - b.receipts):
        errors.append("commit effect must match receipt delta")
    if admitted and not v.startup_ready:
        errors.append("startup reconciliation required before admission")
    if b.accepted and admitted:
        errors.append("A blocks new admission")
    if b.fence and committed:
        errors.append("F blocks retired-generation commit")
    if a.done and (not a.drained or set(a.cleanup) != set(LIVE_COPIES)):
        errors.append("D requires every live-copy acknowledgment")
    if b.barrier and (committed or admitted):
        errors.append("deleted sync ID cannot be recreated")
    if (b.erased or b.accepted or b.barrier) and effect.metadata:
        errors.append("retired receipt cannot return metadata")
    if b.marker and not a.marker or b.retired and not a.retired or b.barrier and not a.barrier:
        errors.append("retirement evidence must survive undo/restart")
    if b.marker and admitted:
        errors.append("undo cannot authorize upload")
    if (v.account != "synthetic-owner" or not v.verified) and (
            admitted or effect.management or management_change or effect.metadata or activated):
        errors.append("verified owner required to resume")
    if admitted and (not b.consent or not v.upload_permission):
        errors.append("upload requires current consent and permission")
    expected_management = (v.account == "synthetic-owner" and v.verified
                           and v.management_permission)
    if management_change and not expected_management:
        errors.append("management state change requires owner and permission")
    if event in ("A", "delete", "status") and effect.management != expected_management:
        errors.append("management is consent-independent and permission-restricted")
    if event == "ack" and activated:
        if (v.account != "synthetic-owner" or not v.verified or b.epoch != 0
                or b.retired or b.barrier or not b.receipts
                or a.retired or a.barrier):
            errors.append("stale ACK requires verified owner and captured epoch")
    return errors
