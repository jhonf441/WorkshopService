"""A handler that refuses says so with an exception, and the API answers an error instead of a sentence with ok true.

The modules of handlers/ are below the API layer and do not import workshop_api. A handler that cannot do what was asked raises its
own small exception carrying `api_error = (code, message, extra fields of the error)`; run() here, the one place api_ops calls a
handler through, turns it into the ApiError of the answer (HTTP status by code, the message in the language of the request).
Any other exception of a handler goes up unchanged. First users: password.set / password.clear and comms.set (a caller could not
tell a refusal from a success).
"""
from workshop_api import ApiError


def run(module, params, bridge, config):
    try:
        return module.run(params, bridge, config)
    except Exception as e:
        refusal = getattr(e, "api_error", None)
        if isinstance(refusal, tuple) and len(refusal) == 3:
            raise ApiError(refusal[0], refusal[1], **refusal[2]) from None
        raise
