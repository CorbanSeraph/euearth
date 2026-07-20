"""Subprocess sandbox for untrusted agent actions (MVP stand-in for WASM).

Any untrusted action the harness runs (challenger self-tests, downloaded
occupant probes, agent-authored snippets) executes in a SEPARATE python
process with:

  * rlimits — CPU seconds (SIGXCPU kill), address-space/data caps, a
    PROCESS cap (RLIMIT_NPROC — blocks fork bombs), file-descriptor cap,
    output-file-size cap;
  * a wall-clock timeout enforced by the parent (backstop);
  * networking disabled (socket constructors replaced before user code
    runs) and `-I` isolated mode (no site, no env injection);
  * a SCRUBBED environment — the child inherits NO parent env vars, so
    process secrets in os.environ are not readable;
  * a per-run WORKSPACE JAIL — the child runs in a throwaway temp dir and
    an audit hook (`sys.addaudithook`, fires at the C level so ctypes can't
    dodge it) blocks: file writes outside the workspace, file reads outside
    the workspace + the Python runtime, `ctypes` (the classic net/syscall
    bypass), and process spawning (subprocess/os.exec*/os.spawn*);
  * results returned only as JSON over stdout — no shared state.

HONEST LIMITS: RLIMIT_AS is ADVISORY on macOS (a memory bomb is contained
on Linux/Fly.io but not on a dev Mac), and an in-process audit hook is a
Python-level boundary — native code loaded some other way, or a CPython
zero-day, could still slip. This is containment for accidents and hostile
Python, not a hardened boundary. Production mapping (council, unanimous): a
WASM sandbox (Wasmtime/WASI) or microVM (gVisor/Firecracker) with all
FS/net/GPU calls mediated by the Rust daemon.
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

_RUNNER = r"""
import json, sys, os
sys.dont_write_bytecode = True
spec = json.load(sys.stdin)
import resource, socket
import os.path as _osp

WORKSPACE = _osp.realpath(spec["workspace"])
try:
    os.chdir(WORKSPACE)
except Exception:
    pass
# Scratchpad multi-file: companion modules live in the workspace. Make the
# jailed cwd importable (same privilege as reading workspace files).
if WORKSPACE not in sys.path:
    sys.path.insert(0, WORKSPACE)

# -- network off (defense in depth; the audit hook also blocks sockets) --
def _deny(*a, **k):
    raise PermissionError("harness sandbox: network disabled")
socket.socket = _deny
socket.create_connection = _deny
socket.socketpair = _deny
socket.getaddrinfo = _deny

# -- rlimits -------------------------------------------------------------
cpu = int(spec.get("cpu_seconds", 2))
try:
    resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
except Exception:
    pass
mem = int(spec.get("memory_mb", 256)) * 1024 * 1024
for name in ("RLIMIT_AS", "RLIMIT_DATA"):
    try:
        resource.setrlimit(getattr(resource, name), (mem, mem))
    except Exception:
        pass
# Block fork/memory bombs at the OS level: no new processes.
try:
    resource.setrlimit(resource.RLIMIT_NPROC, (0, 0))
except Exception:
    pass
for name, val in (("RLIMIT_NOFILE", 32), ("RLIMIT_FSIZE", 1_000_000)):
    try:
        resource.setrlimit(getattr(resource, name), (val, val))
    except Exception:
        pass

# -- workspace jail + no-ctypes + no-spawn via an audit hook -------------
_READ_OK = tuple(sorted({_osp.realpath(p) for p in (
    WORKSPACE, sys.base_prefix, sys.prefix, _osp.dirname(os.__file__)) if p}))

def _guard(event, args):
    if event == "socket.socket":
        raise PermissionError("harness sandbox: network disabled")
    if event.startswith("ctypes."):
        raise PermissionError("harness sandbox: ctypes disabled")
    if event in ("subprocess.Popen", "os.system", "os.exec", "os.spawn",
                 "os.posix_spawn", "os.startfile", "os.fork", "os.forkpty",
                 "pty.spawn"):
        raise PermissionError("harness sandbox: process spawn disabled")
    if event == "open":
        path, mode, flags = (list(args) + [None, None, None])[:3]
        if not path:
            return
        writing = False
        if isinstance(flags, int):
            writing = bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT
                                    | os.O_APPEND | os.O_TRUNC))
        if isinstance(mode, str) and any(c in mode for c in "wax+"):
            writing = True
        try:
            rp = _osp.realpath(os.fspath(path))
        except Exception:
            return
        if writing:
            if not (rp == WORKSPACE or rp.startswith(WORKSPACE + os.sep)):
                raise PermissionError(
                    "harness sandbox: write outside workspace denied")
        else:
            if not any(rp == p or rp.startswith(p + os.sep) for p in _READ_OK):
                raise PermissionError(
                    "harness sandbox: read outside workspace denied")

sys.addaudithook(_guard)

ns = {"payload": spec.get("payload")}
try:
    exec(spec["code"], ns)
    print(json.dumps({"ok": True, "result": ns.get("result")}))
except BaseException as exc:
    print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}))
"""


def run_sandboxed(code: str, payload: dict | None = None, *,
                  cpu_seconds: int = 2, memory_mb: int = 256,
                  wall_seconds: int = 8,
                  files: dict[str, str] | None = None) -> dict:
    """Run untrusted `code` (must set a variable `result`) against
    `payload` inside the sandbox. Never raises for sandboxed failures.

    Optional ``files`` maps relative paths -> text content materialized into
    the jailed workspace BEFORE exec (scratchpad multi-file support). Same
    jail, rlimits, scrubbed env, no network — no extra privileges."""
    workspace = tempfile.mkdtemp(prefix="euearth_sandbox_")
    # Materialize companion files into the jail (relative paths only).
    if files:
        ws = Path(workspace).resolve()
        for rel, content in files.items():
            if not rel or not isinstance(rel, str) or ".." in rel.split("/"):
                continue
            if rel.startswith("/") or "\x00" in rel:
                continue
            target = (ws / rel).resolve()
            try:
                target.relative_to(ws)
            except ValueError:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content if isinstance(content, str) else "",
                              encoding="utf-8")
    spec = json.dumps({
        "code": code, "payload": payload or {},
        "cpu_seconds": cpu_seconds, "memory_mb": memory_mb,
        "workspace": workspace,
    })
    # A scrubbed environment: the child sees NO parent secrets. Only the
    # minimum to start CPython, with tempdir + bytecode writes pinned into
    # the jailed workspace.
    child_env = {
        "PATH": "/usr/bin:/bin",
        "TMPDIR": workspace,
        "HOME": workspace,
        "LC_ALL": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    try:
        proc = subprocess.run(
            [sys.executable, "-I", "-c", _RUNNER],
            input=spec, capture_output=True, text=True, timeout=wall_seconds,
            cwd=workspace, env=child_env,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "killed_by": "wall_clock_timeout",
                "error": f"exceeded {wall_seconds}s wall clock"}
    finally:
        shutil.rmtree(workspace, ignore_errors=True)
    out = proc.stdout.strip().splitlines()
    if out:
        try:
            report = json.loads(out[-1])
            report["exit_code"] = proc.returncode
            return report
        except json.JSONDecodeError:
            pass
    killed_by = None
    if proc.returncode < 0:
        try:
            killed_by = signal.Signals(-proc.returncode).name
        except ValueError:
            killed_by = f"signal {-proc.returncode}"
    return {"ok": False, "exit_code": proc.returncode,
            "killed_by": killed_by or "no_output",
            "error": (proc.stderr.strip()[-300:] or
                      f"process ended ({killed_by or proc.returncode}) with no result")}
