"""Warm-JVM rendering session via plantuml's ``-pipe`` protocol.

A :class:`Session` keeps one JVM process alive and streams puml
diagrams through its stdin, reading rendered images from stdout.  The
first render still pays the JVM cold-start cost (~1s); subsequent
renders against the same session reuse the warm JVM and finish in
milliseconds.

Each session is bound to one output format chosen at construction time
because plantuml's ``-pipe`` protocol takes the format flag at startup,
not per-render.  Open multiple sessions for multiple formats.

Sessions are **not thread-safe**: one session = one stdin/stdout frame
channel.  To render concurrently from multiple threads, build a small
pool with one session per worker thread.
"""
import os
import subprocess
import threading

from . import (
    JAR_PATH,
    PlantUmlError,
    _build_env_and_java_args,
    _java_bin,
)

# A delimiter unique enough not to collide with rendered image bytes,
# yet plain ASCII so plantuml can echo it on stdout verbatim between
# renders.  Used with ``-pipedelimitor``.
_PIPE_DELIM = "__PYPLANTUML_PIPE_DELIM_b1f3a2c7__"
_PIPE_DELIM_BYTES = _PIPE_DELIM.encode("ascii")


def _read_until_delim_terminated(read_fn, delim_bytes, get_stderr_text):
    """Drive ``read_fn`` until ``delim_bytes`` followed by a line terminator
    is seen on stream; return everything before the delimiter.

    Earlier versions of this loop returned as soon as the delimiter byte
    sequence appeared on stdout — but on JDK 11 the underlying
    ``PrintStream`` sometimes flushes ``DELIM`` and the trailing ``\\n``
    in separate writes.  The lingering ``\\n`` then ended up at the head
    of the next render's read, breaking the PNG signature check.
    Waiting for ``DELIM`` + line terminator guarantees the OS pipe is
    drained back to the post-frame state plantuml expects.  Both LF
    and CRLF terminators are accepted (CRLF can appear when the pipe
    runs through a Windows shim).

    Extracted as a free function so the framing branches can be
    exhaustively unit-tested by passing synthetic ``read_fn`` callables
    without spawning a real JVM.

    Raises :class:`PlantUmlError` if ``read_fn`` returns a falsy chunk
    (EOF) before a complete frame has arrived.
    """
    out = bytearray()
    while True:
        chunk = read_fn(65536)
        if not chunk:
            raise PlantUmlError(
                "JVM closed stdout mid-render; stderr: {}".format(
                    get_stderr_text()[:500] or "(empty)"
                )
            )
        out.extend(chunk)
        idx = out.find(delim_bytes)
        if idx < 0:
            continue
        after_delim = idx + len(delim_bytes)
        # Need at least one more byte (the LF, optionally preceded by CR).
        if after_delim >= len(out):
            continue
        cursor = after_delim
        if out[cursor] == 0x0d:  # CR (Windows)
            cursor += 1
            if cursor >= len(out):
                continue  # CR present but LF not yet — keep reading
        if cursor < len(out) and out[cursor] == 0x0a:  # LF
            # Full DELIM + line terminator drained.
            return bytes(out[:idx])
        # Defensive: DELIM followed by neither CR nor LF.  Should not
        # happen with plantuml's -pipedelimitor implementation, but if
        # it does, return what we have rather than hanging.
        return bytes(out[:idx])


class Session(object):
    """A warm-JVM PlantUML rendering session.

    Use as a context manager to ensure the JVM is shut down even if a
    render raises::

        with Session(fmt="png") as s:
            png1 = s.render("@startuml\\nA -> B\\n@enduml")
            png2 = s.render("@startuml\\nC -> D\\n@enduml")

    Or manage lifecycle manually with :meth:`close`.
    """

    def __init__(self, fmt="png", jvm_args=()):
        """Spawn a warm JVM bound to ``fmt`` (one of ``png``, ``svg``, ...).

        ``jvm_args`` is an iterable of extra ``-D...`` style arguments
        inserted between the JVM defaults and ``-jar``.
        """
        env, java_extra = _build_env_and_java_args()
        cmd = [str(_java_bin())]
        cmd.extend(java_extra)
        cmd.extend(jvm_args)
        cmd.extend([
            "-jar", str(JAR_PATH),
            "-pipe",
            "-pipedelimitor", _PIPE_DELIM,
            "-t" + fmt,
        ])
        self._fmt = fmt
        self._closed = False
        self._proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            bufsize=0,
        )
        self._stderr_chunks = []
        self._stderr_lock = threading.Lock()
        # Drain stderr on a daemon thread to prevent pipe-full deadlock
        # when plantuml emits warnings during a long-lived session.
        self._stderr_thread = threading.Thread(
            target=self._drain_stderr,
            name="pyplantuml-session-stderr",
        )
        self._stderr_thread.daemon = True
        self._stderr_thread.start()

    @property
    def fmt(self):
        """The output format this session was constructed with."""
        return self._fmt

    @property
    def closed(self):
        """True once :meth:`close` (or ``__exit__``) has been called."""
        return self._closed

    def _drain_stderr(self):
        fd = self._proc.stderr.fileno()
        while True:
            try:
                chunk = os.read(fd, 4096)
            except (OSError, ValueError):  # pragma: no cover - rare race on close
                return
            if not chunk:
                return
            with self._stderr_lock:
                self._stderr_chunks.append(chunk)

    def _stderr_text(self):
        with self._stderr_lock:
            return b"".join(self._stderr_chunks).decode(
                "utf-8", errors="replace"
            )

    def render(self, source):
        """Render ``source`` and return the image bytes.

        Raises :class:`PlantUmlError` if the session is closed, the JVM
        has already exited, the JVM closes stdout mid-render, or
        ``source`` is not a string.

        A syntactically invalid ``source`` does **not** raise — plantuml
        renders an error image and the bytes are returned as-is.  Use
        :func:`pyplantuml.lint` if you need to reject invalid sources.
        """
        if self._closed:
            raise PlantUmlError("Session is closed")
        if not isinstance(source, str):
            raise PlantUmlError(
                "Session.render expects str, got {}".format(
                    type(source).__name__
                )
            )
        if self._proc.poll() is not None:
            raise PlantUmlError(
                "JVM exited unexpectedly (rc={}); stderr: {}".format(
                    self._proc.returncode,
                    self._stderr_text()[:500] or "(empty)",
                )
            )
        # Send the puml + a trailing newline so plantuml's parser sees
        # a clean line-terminated document.
        payload = source.encode("utf-8")
        if not payload.endswith(b"\n"):
            payload = payload + b"\n"
        try:
            self._proc.stdin.write(payload)
            self._proc.stdin.flush()
        except (OSError, ValueError) as exc:  # pragma: no cover - exercised via mock test
            raise PlantUmlError(
                "Session.render: write to JVM stdin failed: {}; stderr: {}".format(
                    exc, self._stderr_text()[:500] or "(empty)"
                )
            )
        out_fd = self._proc.stdout.fileno()

        def _read_chunk(size):
            try:
                return os.read(out_fd, size)
            except OSError as exc:  # pragma: no cover - rare race on close
                raise PlantUmlError(
                    "Session.render: stdout read error: {}; stderr: {}".format(
                        exc, self._stderr_text()[:500] or "(empty)"
                    )
                )

        return _read_until_delim_terminated(
            _read_chunk, _PIPE_DELIM_BYTES, self._stderr_text
        )

    def close(self):
        """Shut down the JVM.  Idempotent.

        Closes stdin so plantuml exits cleanly, then waits up to 5
        seconds before escalating to ``terminate()`` and finally
        ``kill()``.  Joins the stderr-drain thread before returning.
        """
        if self._closed:
            return
        self._closed = True
        try:
            if self._proc.stdin and not self._proc.stdin.closed:
                self._proc.stdin.close()
        except (OSError, ValueError):  # pragma: no cover
            pass
        try:
            self._proc.wait(timeout=5)
        except subprocess.TimeoutExpired:  # pragma: no cover - JVM should exit cleanly
            self._proc.terminate()
            try:
                self._proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait()
        if self._stderr_thread.is_alive():  # pragma: no cover - thread usually exits at proc.wait
            self._stderr_thread.join(timeout=2)
        for stream in (self._proc.stdout, self._proc.stderr):
            try:
                if stream and not stream.closed:
                    stream.close()
            except (OSError, ValueError):  # pragma: no cover
                pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def __del__(self):  # pragma: no cover - best-effort interpreter-shutdown cleanup
        try:
            self.close()
        except BaseException:
            pass
