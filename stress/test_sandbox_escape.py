#!/usr/bin/env python3
"""SANDBOX ESCAPE battery — adversarial probes against harness.sandbox.

The `sandbox_exec` MCP tool runs untrusted agent-authored Python. This
battery fires the classic escape attempts and asserts each is CONTAINED
(blocked with a PermissionError, or killed by a resource/time limit):

  1. read a file OUTSIDE the workspace   (/etc/passwd, repo secrets)
  2. open a NETWORK socket               (socket.socket + ctypes libc bypass)
  3. FORK / process bomb                 (os.fork, subprocess, os.system)
  4. read os.environ SECRETS             (a planted secret in the parent env)
  5. WRITE outside the sandbox           (a file in the system temp dir)
  6. exceed the CPU / WALL-CLOCK limit   (busy loop, sleep past the deadline)

A legit in-workspace write is also checked to confirm the jail did not
break normal use.

KNOWN HOST LIMITATION: RLIMIT_AS is advisory on macOS, so a single large
allocation is NOT contained on a dev Mac (it IS on Linux / the Fly.io
deploy, where RLIMIT_AS is enforced). The memory probe therefore only
asserts containment on Linux and reports (does not fail) on macOS.

    .venv/bin/python stress/test_sandbox_escape.py    # exit 0 = all contained
"""
from __future__ import annotations

import os
import platform
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from harness.sandbox import run_sandboxed  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []


def _contained(r: dict) -> bool:
    """A result is 'contained' if the sandboxed code did NOT succeed: it was
    blocked (ok False) or killed (killed_by / negative exit)."""
    if r.get("ok") is True:
        return False
    return True


def check(name: str, contained: bool, detail: str) -> None:
    RESULTS.append((name, contained, detail))
    tag = "PASS" if contained else "FAIL — ESCAPE"
    print(f"  [{tag}] {name}\n           {detail[:110]}")


def main() -> int:
    # Plant a secret in the PARENT environment; the child must not see it.
    os.environ["SANDBOX_SECRET_TEST"] = "TOP_SECRET_XYZZY"

    # 1. read outside the workspace ------------------------------------- #
    r = run_sandboxed("result = open('/etc/passwd').read()[:32]")
    check("read /etc/passwd blocked", _contained(r), str(r.get("error")))

    secret_path = str(REPO / "harness" / "sandbox.py")  # a real repo file
    r = run_sandboxed(f"result = open({secret_path!r}).read()[:32]")
    check("read repo source outside jail blocked", _contained(r),
          str(r.get("error")))

    # 2. network -------------------------------------------------------- #
    r = run_sandboxed(
        "import socket\n"
        "s=socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
        "s.connect(('1.1.1.1',80)); result='connected'")
    check("socket.socket connect blocked", _contained(r), str(r.get("error")))

    r = run_sandboxed(
        "import ctypes, ctypes.util\n"
        "libc=ctypes.CDLL(ctypes.util.find_library('c'))\n"
        "result=libc.socket(2,1,0)")
    check("ctypes libc.socket bypass blocked", _contained(r),
          str(r.get("error")))

    # 3. fork / process bomb -------------------------------------------- #
    r = run_sandboxed("import os\nresult=os.fork()", cpu_seconds=2)
    check("os.fork blocked", _contained(r), str(r.get("error")))

    r = run_sandboxed(
        "import subprocess\nsubprocess.run(['echo','hi'])\nresult='ran'")
    check("subprocess spawn blocked", _contained(r), str(r.get("error")))

    r = run_sandboxed("import os\nresult=os.system('echo hi')")
    check("os.system spawn blocked", _contained(r), str(r.get("error")))

    # 4. env secrets ---------------------------------------------------- #
    r = run_sandboxed(
        "import os\nresult=os.environ.get('SANDBOX_SECRET_TEST','<absent>')")
    leaked = r.get("ok") is True and r.get("result") == "TOP_SECRET_XYZZY"
    check("os.environ secret not visible", not leaked,
          f"child saw: {r.get('result')!r}")

    # 5. write outside the sandbox -------------------------------------- #
    target = Path(tempfile.gettempdir()) / "euearth_escape_probe.txt"
    if target.exists():
        target.unlink()
    r = run_sandboxed(f"open({str(target)!r},'w').write('escaped')\n"
                      "result='wrote'")
    wrote = target.exists()
    check("write outside workspace blocked", _contained(r) and not wrote,
          f"{r.get('error')}  file_created={wrote}")
    if target.exists():
        target.unlink()

    # 6. CPU / wall-clock limits ---------------------------------------- #
    r = run_sandboxed("while True: pass", cpu_seconds=1, wall_seconds=10)
    check("CPU busy-loop killed", _contained(r),
          f"killed_by={r.get('killed_by')}")

    r = run_sandboxed("import time\ntime.sleep(30)\nresult='slept'",
                      cpu_seconds=30, wall_seconds=3)
    check("wall-clock overrun killed", _contained(r),
          f"killed_by={r.get('killed_by')}")

    # legit use still works --------------------------------------------- #
    r = run_sandboxed(
        "open('scratch.txt','w').write('ok')\nresult=open('scratch.txt').read()")
    check("legit in-workspace write still works", r.get("result") == "ok",
          f"ok={r.get('ok')} result={r.get('result')!r}")

    # memory bomb (platform-aware) -------------------------------------- #
    r = run_sandboxed("x=bytearray(2_000_000_000)\nresult=len(x)",
                      memory_mb=128, wall_seconds=10)
    mem_contained = _contained(r)
    if platform.system() == "Linux":
        check("memory bomb capped (RLIMIT_AS)", mem_contained,
              str(r.get("error")))
    else:
        note = "CONTAINED" if mem_contained else "NOT contained (macOS advisory)"
        print(f"  [KNOWN-LIMIT] memory bomb on {platform.system()}: {note} "
              "— RLIMIT_AS is enforced on Linux/Fly.io")

    passed = sum(1 for _, ok, _ in RESULTS if ok)
    total = len(RESULTS)
    print(f"\n=== {passed}/{total} escape attempts CONTAINED ===")
    if passed < total:
        print("  ⚠ A REAL SANDBOX ESCAPE IS OPEN — fix before exposure.")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
