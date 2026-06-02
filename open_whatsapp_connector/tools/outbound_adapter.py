"""Phase 25H: outbound-adapter registry. Maps a media type to a callable
that, given (account, message), dispatches the actual sidecar API call.

Default adapters live in models/owa_message.py — this registry exists
so third parties can add new types (e.g. WhatsApp Pay invoice messages)
without forking the model."""
_adapters = {}


def register(media_type):
    def deco(fn):
        _adapters[media_type] = fn
        return fn
    return deco


def get(media_type):
    return _adapters.get(media_type)


def all_types():
    return list(_adapters.keys())
