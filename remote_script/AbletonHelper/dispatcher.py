"""Command registry, parameter validation helpers and error mapping.

Pure Python: handlers receive a Context (song / application) and a params dict.
"""

import math
import traceback

BAD_REQUEST = "bad_request"
UNKNOWN_COMMAND = "unknown_command"
NOT_FOUND = "not_found"
UNSUPPORTED = "unsupported"
CONFLICT = "conflict"
TIMEOUT = "timeout"
INTERNAL = "internal"

ERROR_CODES = (BAD_REQUEST, UNKNOWN_COMMAND, NOT_FOUND, UNSUPPORTED, CONFLICT, TIMEOUT, INTERNAL)

_MISSING = object()


class CommandError(Exception):
    """Raised by handlers; mapped 1:1 to the protocol error object."""

    def __init__(self, code, message):
        Exception.__init__(self, message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------- validation helpers

def _missing(key):
    return CommandError(BAD_REQUEST, "Missing required parameter '%s'" % key)


def _present(params, key):
    return key in params and params[key] is not None


def get_int(params, key, default=_MISSING, minimum=None, maximum=None):
    """Integer parameter. bool is rejected; floats with integral value are accepted."""
    if not _present(params, key):
        if default is _MISSING:
            raise _missing(key)
        return default
    value = params[key]
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, int):
        raise CommandError(BAD_REQUEST, "'%s' must be an integer" % key)
    if minimum is not None and value < minimum:
        raise CommandError(BAD_REQUEST, "'%s' must be >= %s" % (key, minimum))
    if maximum is not None and value > maximum:
        raise CommandError(BAD_REQUEST, "'%s' must be <= %s" % (key, maximum))
    return value


def get_number(params, key, default=_MISSING, minimum=None, maximum=None):
    if not _present(params, key):
        if default is _MISSING:
            raise _missing(key)
        return default
    value = params[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise CommandError(BAD_REQUEST, "'%s' must be a number" % key)
    value = float(value)
    if minimum is not None and value < minimum:
        raise CommandError(BAD_REQUEST, "'%s' must be >= %s" % (key, minimum))
    if maximum is not None and value > maximum:
        raise CommandError(BAD_REQUEST, "'%s' must be <= %s" % (key, maximum))
    return value


def get_str(params, key, default=_MISSING, allow_empty=False):
    if not _present(params, key):
        if default is _MISSING:
            raise _missing(key)
        return default
    value = params[key]
    if not isinstance(value, str):
        raise CommandError(BAD_REQUEST, "'%s' must be a string" % key)
    if not allow_empty and not value.strip():
        raise CommandError(BAD_REQUEST, "'%s' must not be empty" % key)
    return value


def get_bool(params, key, default=_MISSING):
    if not _present(params, key):
        if default is _MISSING:
            raise _missing(key)
        return default
    value = params[key]
    if not isinstance(value, bool):
        raise CommandError(BAD_REQUEST, "'%s' must be a boolean" % key)
    return value


def get_list(params, key, default=_MISSING):
    if not _present(params, key):
        if default is _MISSING:
            raise _missing(key)
        return default
    value = params[key]
    if not isinstance(value, list):
        raise CommandError(BAD_REQUEST, "'%s' must be an array" % key)
    return value


def get_dict(params, key, default=_MISSING):
    if not _present(params, key):
        if default is _MISSING:
            raise _missing(key)
        return default
    value = params[key]
    if not isinstance(value, dict):
        raise CommandError(BAD_REQUEST, "'%s' must be an object" % key)
    return value


# ---------------------------------------------------------------- envelopes

def ok_envelope(request_id, result):
    return {"id": request_id, "ok": True, "result": result}


def error_envelope(request_id, code, message):
    return {"id": request_id, "ok": False, "error": {"code": code, "message": message}}


class Dispatcher(object):
    """Maps command names to handlers `handler(ctx, params) -> result dict`."""

    def __init__(self, ctx, commands=None):
        self.ctx = ctx
        ctx.dispatcher = self
        if commands is None:
            from .handlers import all_commands
            commands = all_commands()
        self.commands = dict(commands)

    def execute(self, command, params=None):
        """Run one command; returns the result or raises CommandError."""
        handler = self.commands.get(command)
        if handler is None:
            raise CommandError(UNKNOWN_COMMAND, "Unknown command: %s" % (command,))
        if params is None:
            params = {}
        if not isinstance(params, dict):
            raise CommandError(BAD_REQUEST, "'params' must be an object")
        try:
            return handler(self.ctx, params)
        except CommandError:
            raise
        except Exception as exc:
            self.ctx.log("Command %s failed: %s" % (command, traceback.format_exc()))
            raise CommandError(INTERNAL, str(exc) or exc.__class__.__name__)

    def execute_envelope(self, command, params=None):
        """Like execute() but returns an id-less envelope (used by batch)."""
        try:
            return {"ok": True, "result": self.execute(command, params)}
        except CommandError as err:
            return {"ok": False, "error": {"code": err.code, "message": err.message}}

    def handle(self, request):
        """Full request dict -> response envelope. Never raises."""
        request_id = None
        try:
            if not isinstance(request, dict):
                return error_envelope(None, BAD_REQUEST, "Request must be a JSON object")
            request_id = request.get("id")
            command = request.get("command")
            if not isinstance(command, str) or not command:
                return error_envelope(request_id, BAD_REQUEST, "Missing 'command'")
            result = self.execute(command, request.get("params"))
            return ok_envelope(request_id, result)
        except CommandError as err:
            return error_envelope(request_id, err.code, err.message)
        except Exception as exc:  # pragma: no cover - defensive
            self.ctx.log("Unhandled dispatcher error: %s" % traceback.format_exc())
            return error_envelope(request_id, INTERNAL, str(exc) or exc.__class__.__name__)
