"""The DSF connection to the Duet."""


import time


def real_link_factory(timeout):
    """A DSF command connection (the dsf-python library, installed on the Pi)."""
    from dsf.connections import CommandConnection
    return CommandConnection(timeout=timeout)


class DuetLink:
    """A lazily opened DSF connection that reconnects after a failure.

    timeout and connect_wait may be numbers or callables (so a settings change
    applies to the next connection). With connect_wait > 0 an order keeps
    retrying the connection for that many seconds before giving up; with 0 a
    query fails at once and the connection is retried after RETRY_AFTER_S."""

    RETRY_AFTER_S = 2.0

    def __init__(self, factory, timeout, clock, connect_wait=0, sleep=time.sleep, channel=None):
        self.factory = factory
        self.channel = channel          # name (or callable) of a DSF code channel; None = the default one
        self.timeout = timeout
        self.connect_wait = connect_wait
        self.clock = clock
        self.sleep = sleep
        self.conn = None
        self.failed_at = None

    @staticmethod
    def _val(v):
        return v() if callable(v) else v

    def _connect(self):
        wait = self._val(self.connect_wait)
        deadline = self.clock.mono() + wait
        while True:
            failed = self.failed_at
            if wait <= 0 and failed is not None and self.clock.mono() - failed < self.RETRY_AFTER_S:
                raise ConnectionError("machine connection is down (retrying shortly)")
            try:
                conn = self.factory(self._val(self.timeout))
                conn.connect()
                self.conn = conn
                self.failed_at = None
                return
            except Exception as e:
                self.failed_at = self.clock.mono()
                if self.clock.mono() >= deadline:
                    raise ConnectionError(f"cannot connect to DSF: {e}")
                self.sleep(min(1.0, max(0.0, deadline - self.clock.mono())))

    def _code_channel(self):
        """The CodeChannel of dsf-python for `channel`, or None (default channel) if it is unset, unknown or the
        library is not there (tests)."""
        name = self._val(self.channel) if self.channel is not None else None
        if not name:
            return None
        try:
            from dsf.commands.code_channel import CodeChannel
            return getattr(CodeChannel, name, None)
        except Exception:
            return None

    def execute(self, line):
        if self.conn is None:
            self._connect()
        try:
            ch = self._code_channel()
            if ch is not None:
                return self.conn.perform_simple_code(line, channel=ch)
            return self.conn.perform_simple_code(line)
        except Exception:
            self.close()
            raise

    def close(self):
        conn, self.conn = self.conn, None
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
