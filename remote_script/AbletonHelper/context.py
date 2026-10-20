"""Context object handed to every command handler (no Live imports at module level)."""


class Context(object):
    """Bundles the Live objects a handler may touch. Only the main thread uses it."""

    def __init__(self, song, application, browser_index=None, log=None, live_module=None):
        self.song = song
        self.application = application
        self.browser_index = browser_index
        self.live_module = live_module   # tests inject a fake `Live` module here
        self.dispatcher = None           # set by Dispatcher
        self._log = log

    def log(self, message):
        if self._log is not None:
            try:
                self._log(message)
            except Exception:
                pass

    def get_live(self):
        """Return the `Live` module (lazy import) or None when unavailable."""
        if self.live_module is not None:
            return self.live_module
        try:
            import Live  # noqa  (only importable inside Ableton Live)
            return Live
        except Exception:
            return None
