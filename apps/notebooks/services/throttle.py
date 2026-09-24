"""Lightweight per-user cooldown for AI-backed endpoints.

This is not a hard rate limit (no daily/hourly quota) - just a minimum gap
between repeated calls to the same endpoint by the same user, so an
accidental double-click, a stuck retry loop, or two open tabs can't fire off
a burst of billed AI calls. Most of these endpoints already disable their
button client-side while a request is in flight; this is the server-side
backstop for the cases that don't go through that JS (a second tab, a direct
request, a client-side bug).

Uses Django's cache framework (LocMemCache by default here - fine for a
single-process dev/demo deployment; swap in Redis/memcached in CACHES for a
multi-process one, no code change needed).
"""
from django.core.cache import cache


def is_throttled(user, key, seconds=3):
    """Returns True (and does nothing else) if `user` called `key` within the
    last `seconds`. Otherwise marks this call and returns False. Anonymous
    users are never throttled here - callers should already require login."""
    if not getattr(user, 'is_authenticated', False):
        return False
    cache_key = f'ai_throttle:{key}:{user.pk}'
    if cache.get(cache_key):
        return True
    cache.set(cache_key, True, timeout=seconds)
    return False
