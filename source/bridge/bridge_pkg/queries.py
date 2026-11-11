"""Query service: coalescing, cache, stale answers."""


import queue
import threading

from bridge_pkg.duet import DuetLink
from bridge_pkg.log import LOG
from bridge_pkg.textutil import first_token, query_key


class _Waiter:
    __slots__ = ("callback", "t0", "client", "answered")

    def __init__(self, callback, t0, client):
        self.callback = callback
        self.t0 = t0
        self.client = client
        self.answered = False


class _Job:
    __slots__ = ("key", "line", "waiters")

    def __init__(self, key, line):
        self.key = key
        self.line = line
        self.waiters = []


class QueryService:
    """Answers queries for every client.

    request(line, callback) -> source, where source is "cache" (answered now
    from the cache), "coalesced" (joined a request already on its way) or
    "duet" (a new Duet request). callback(text, source) is called exactly once
    with source "cache", "duet", "stale" (a recent cached answer served because
    the Duet was slow or failed) or "error".
    """

    CACHE_MAX = 64

    def __init__(self, bridge):
        self.bridge = bridge
        self.lock = threading.Lock()
        self.cache = {}          # key -> (mono time, text)
        self.inflight = {}       # key -> _Job
        self.jobs = queue.Queue()
        self.threads = []
        self.stopping = False

    # -- client side --
    def request(self, line, callback, client=None):
        b = self.bridge
        key = query_key(line)
        now = b.clock.mono()
        if not b.settings.get("queries_in_job") and b.live_job.get("active"):
            # the user does not want the board asked while the job runs: the last known answer, or a plain ok
            with self.lock:
                entry = self.cache.get(key)
            b.dbg(getattr(client, "name", "-"), "cache", f"{key} answered without asking the board (live job, queries off)")
            self._call(callback, entry[1] if entry is not None else "ok", "cache")
            return "cache"
        ttl = (b.settings.get("query_cache_ms").get(first_token(line), 0)) / 1000.0
        hit = None
        source = "duet"
        with self.lock:
            entry = self.cache.get(key)
            if entry is not None and ttl > 0 and now - entry[0] <= ttl:
                hit = entry
                source = "cache"
            else:
                waiter = _Waiter(callback, now, client)
                job = self.inflight.get(key)
                if job is not None:
                    job.waiters.append(waiter)
                    source = "coalesced"
                else:
                    job = _Job(key, line)
                    job.waiters.append(waiter)
                    self.inflight[key] = job
                    self.jobs.put(job)
        if hit is not None:
            b.dbg(getattr(client, "name", "-"), "cache", f"{key} answered from cache ({int((now - hit[0]) * 1000)} ms old)")
            self._call(callback, hit[1], "cache")
        elif source == "coalesced":
            b.dbg(getattr(client, "name", "-"), "coalesce", f"{key} joined the request already on its way")
        return source

    @staticmethod
    def _call(callback, text, source):
        try:
            callback(text, source)
        except Exception as e:
            LOG.warning("query callback failed: %s", e)

    def _stale(self, key, now):
        """A cached answer young enough to be served when the Duet is slow."""
        limit = self.bridge.settings.get("query_stale_s")
        entry = self.cache.get(key)
        if entry is not None and now - entry[0] <= limit:
            return entry
        return None

    # -- worker side --
    def start(self):
        n = self.bridge.settings.get("query_workers")
        for i in range(n):
            t = threading.Thread(target=self._worker, name=f"query-{i}", daemon=True)
            t.start()
            self.threads.append(t)

    def stop(self):
        self.stopping = True
        for _ in self.threads:
            self.jobs.put(None)

    def _worker(self):
        b = self.bridge
        link = DuetLink(b.link_factory, lambda: b.settings.get("query_timeout_s"), b.clock,
                        channel=lambda: b.settings.get("query_channel"))
        while not self.stopping:
            job = self.jobs.get()
            if job is None:
                break
            self.run_job(job, link)
        link.close()

    def run_next(self, link, block=False):
        """Run one queued job synchronously (tests). Returns False if none."""
        try:
            job = self.jobs.get(block, 1.0 if block else None)
        except queue.Empty:
            return False
        if job is None:
            return False
        self.run_job(job, link)
        return True

    def run_job(self, job, link):
        b = self.bridge
        t0 = b.clock.mono()
        text, error = None, None
        try:
            text = (link.execute(job.line) or "").strip()
        except Exception as e:
            error = e
        ms = (b.clock.mono() - t0) * 1000
        now = b.clock.mono()
        with self.lock:
            self.inflight.pop(job.key, None)
            waiters = [w for w in job.waiters if not w.answered]
            for w in waiters:
                w.answered = True
            if error is None:
                self.cache[job.key] = (now, text)
                if len(self.cache) > self.CACHE_MAX:
                    oldest = min(self.cache, key=lambda k: self.cache[k][0])
                    self.cache.pop(oldest, None)
            stale = self._stale(job.key, now) if error is not None else None
        with b.lock:
            b.totals["duet_queries"] += 1
            if error is not None:
                b.totals["query_errors"] += 1
        if error is None:
            b.timing["query"].add(ms)
            b.timing["all"].add(ms)
            b.dbg("-", "duet", f"{job.key} answered by the Duet in {int(ms)} ms ({len(waiters)} waiting)")
            for w in waiters:
                self._call(w.callback, text, "duet")
        else:
            b.dbg("-", "error", f"{job.key} failed after {int(ms)} ms: {error}")
            b.event("error", "duet_error", f"Machine error on query '{job.line[:40]}': {error}", line=job.line[:40], error=str(error))
            for w in waiters:
                if stale is not None:
                    self._call(w.callback, stale[1], "stale")
                else:
                    self._call(w.callback, f"Error: {error}", "error")

    def expire(self):
        """Answer waiters that waited too long: a recent cached answer after
        `query_soft_ms`, an error (or the cached answer) after the query timeout."""
        b = self.bridge
        soft = b.settings.get("query_soft_ms") / 1000.0
        hard = b.settings.get("query_timeout_s") + 0.5
        now = b.clock.mono()
        due = []
        with self.lock:
            for key, job in self.inflight.items():
                stale = self._stale(key, now)
                for w in job.waiters:
                    if w.answered:
                        continue
                    waited = now - w.t0
                    if stale is not None and waited >= soft:
                        w.answered = True
                        due.append((w, stale[1], "stale"))
                    elif waited >= hard:
                        w.answered = True
                        due.append((w, "Error: the machine did not answer the query in time", "error"))
        for w, text, source in due:
            b.dbg(getattr(w.client, "name", "-"), "stale" if source == "stale" else "error",
                  f"query answered with {source} data after {int((now - w.t0) * 1000)} ms")
            self._call(w.callback, text, source)
