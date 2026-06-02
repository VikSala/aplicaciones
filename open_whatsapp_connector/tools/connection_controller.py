"""Phase 25F: pluggable connection state-machine for owa.account.

Third-party modules can register a transition handler for any
(from_state, to_state) pair. Default handlers cover today's behaviour
(connect/disconnect/qr_pending/etc.); registering a new handler with
the same key replaces the default, allowing extensions to interpose
custom logic without monkey-patching the model."""
from collections import defaultdict


_handlers = defaultdict(dict)


def register_transition(from_state, to_state):
    """Decorator. Usage::

        @register_transition('connecting', 'connected')
        def on_connected(account):
            ...
    """
    def deco(fn):
        _handlers[from_state][to_state] = fn
        return fn
    return deco


def fire_transition(account, from_state, to_state):
    """Look up the handler for (from_state, to_state); fall back to the
    wildcard `(*, to_state)` and finally `(*, *)` if registered."""
    fn = (_handlers.get(from_state, {}).get(to_state)
          or _handlers.get('*', {}).get(to_state)
          or _handlers.get('*', {}).get('*'))
    if fn:
        fn(account)


def list_transitions():
    """For diagnostics — returns a list of registered (from, to) pairs."""
    out = []
    for f, sub in _handlers.items():
        for t in sub:
            out.append((f, t))
    return out
