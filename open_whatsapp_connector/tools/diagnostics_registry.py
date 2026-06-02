"""Phase 25I: diagnostics check registry.

Each registered check returns ``(label, status, detail)`` where status
is one of: 'ok' / 'warn' / 'error'. The aggregator collects all checks
into the chatter report posted by ``action_run_diagnostics``."""
_checks = {}


def register_diagnostic(name):
    """Usage::

        @register_diagnostic("sidecar.process")
        def check_sidecar(account):
            return ("Sidecar process up", 'ok', '')
    """
    def deco(fn):
        _checks[name] = fn
        return fn
    return deco


def run_all(account):
    """Run every registered check against an account, returning a list
    of (name, label, status, detail) tuples sorted by name."""
    out = []
    for name in sorted(_checks):
        try:
            label, status, detail = _checks[name](account)
        except Exception as e:  # never break diagnostics — surface the error
            label, status, detail = (name, 'error', f"check raised: {e}")
        out.append((name, label, status, detail))
    return out


def list_checks():
    return sorted(_checks)
