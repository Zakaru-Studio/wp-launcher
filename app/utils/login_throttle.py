"""Brute-force throttling for the login form.

Deliberately dependency-free and in-process: WP Launcher runs a single
eventlet worker (Socket.IO needs sticky state anyway), so a module-level
dict is shared by every request and survives as long as the process does.
Adding Flask-Limiter would buy a distributed backend the deployment model
cannot use.

Two counters run side by side:

* ``(client ip, username)`` — tight budget, catches someone hammering one
  account. Keyed on the pair so an attacker cannot lock a legitimate user
  out from a different address.
* ``client ip`` alone — looser budget, catches password spraying, where a
  single source tries a handful of passwords against many usernames and
  would otherwise never trip the per-pair counter.
"""
import threading
import time

# Failed attempts tolerated before the (ip, username) pair is locked out.
MAX_ATTEMPTS = 5

# Failed attempts tolerated from one IP across *all* usernames, before that
# address is locked out wholesale. Loose enough that a shared NAT egress with
# several forgetful users won't trip it.
MAX_ATTEMPTS_PER_IP = 20

# Usernames are attacker-controlled and land in a dict key. MAX_CONTENT_LENGTH
# is 5 GB, so an unbounded key is a memory-exhaustion lever against the single
# worker process.
MAX_USERNAME_KEY_LEN = 64

# Lockout duration per additional failure past the threshold, in seconds.
# Roughly: 1 min, 5 min, 15 min, then an hour for anything beyond.
_BACKOFF_LADDER = (60, 300, 900, 3600)

# Failures older than this are forgotten, so a typo last week costs nothing.
ATTEMPT_TTL = 3600

# Safety valve: stop an attacker from growing the dict without bound by
# spraying random usernames. Well past any legitimate working set.
_MAX_TRACKED_KEYS = 10_000

_lock = threading.Lock()
# key -> {'failures': int, 'locked_until': float, 'last_seen': float}
_attempts: dict[tuple[str, str], dict] = {}


def _now() -> float:
    return time.monotonic()


def _prune(now: float) -> None:
    """Drop stale entries. Caller must hold the lock."""
    expired = [
        key for key, state in _attempts.items()
        if now - state['last_seen'] > ATTEMPT_TTL and now >= state['locked_until']
    ]
    for key in expired:
        del _attempts[key]

    if len(_attempts) > _MAX_TRACKED_KEYS:
        # Evict least-recently-seen first, but NEVER a currently locked entry:
        # otherwise an attacker floods the table with junk usernames to push
        # their own lockout out of it and walks straight back in.
        evictable = sorted(
            (kv for kv in _attempts.items() if kv[1]['locked_until'] <= now),
            key=lambda kv: kv[1]['last_seen'],
        )
        for key, _ in evictable[: len(_attempts) - _MAX_TRACKED_KEYS]:
            del _attempts[key]


def _key(ip: str, username: str) -> tuple[str, str]:
    """Bucket key. The username is truncated: it is attacker-controlled and
    would otherwise pin an arbitrarily long string in memory."""
    name = (username or '').strip().lower()[:MAX_USERNAME_KEY_LEN]
    return (ip or 'unknown', name)


def _ip_key(ip: str) -> tuple[str, str]:
    """Per-IP bucket. The empty username can't collide with a real one:
    ``_key`` is only reached from a login form that rejects blank usernames."""
    return (ip or 'unknown', '')


def _wait_for(state: dict, now: float) -> int:
    remaining = state['locked_until'] - now
    return int(remaining) + 1 if remaining > 0 else 0


def check(ip: str, username: str) -> int:
    """Seconds the caller must wait, or 0 when the attempt may proceed."""
    now = _now()
    with _lock:
        _prune(now)
        waits = [
            _wait_for(state, now)
            for state in (_attempts.get(_key(ip, username)), _attempts.get(_ip_key(ip)))
            if state
        ]
        return max(waits) if waits else 0


def _bump(key: tuple[str, str], threshold: int, now: float) -> int:
    """Increment one bucket and return its lockout in seconds (0 if none)."""
    state = _attempts.setdefault(
        key, {'failures': 0, 'locked_until': 0.0, 'last_seen': now}
    )
    state['failures'] += 1
    state['last_seen'] = now

    overshoot = state['failures'] - threshold
    if overshoot < 0:
        return 0

    penalty = _BACKOFF_LADDER[min(overshoot, len(_BACKOFF_LADDER) - 1)]
    state['locked_until'] = now + penalty
    return penalty


def record_failure(ip: str, username: str) -> int:
    """Count a failed login. Returns the lockout in seconds (0 if none yet).

    Bumps both buckets: the targeted one and the per-IP one. The longer of
    the two lockouts is what the caller reports.
    """
    now = _now()
    with _lock:
        _prune(now)
        return max(
            _bump(_key(ip, username), MAX_ATTEMPTS, now),
            _bump(_ip_key(ip), MAX_ATTEMPTS_PER_IP, now),
        )


def record_success(ip: str, username: str) -> None:
    """Clear the counters after a successful authentication.

    Clears the per-IP bucket too: a legitimate user who mistyped a few times
    across accounts shouldn't stay half-throttled once they get in.
    """
    with _lock:
        _attempts.pop(_key(ip, username), None)
        _attempts.pop(_ip_key(ip), None)


def reset() -> None:
    """Wipe all state — for tests."""
    with _lock:
        _attempts.clear()


def client_ip() -> str:
    """Best-effort client address.

    Relies on ``ProxyFix`` having already rewritten ``remote_addr`` from
    ``X-Forwarded-For`` when running behind a reverse proxy; without that
    every request would look like it came from the proxy itself.
    """
    from flask import request
    return request.remote_addr or 'unknown'
