"""Run the plane experiment on a real RunPod GPU — provision, run,
fetch results, TERMINATE. Bills by the minute; never leaves a pod up.

    python3 plane/runpod_run.py --dry-run     # plan + prices, no spend
    python3 plane/runpod_run.py               # BILLABLE

The pod's ACTUAL $/hr is passed into the experiment as
ARTISAN_GPU_USD_PER_HOUR, so every metered phase reports real dollars.
Wall-clock pod lifetime x price is also recorded independently in
var/runpod_billing.json (the number that hits the account is the
lifetime one; the phase meter attributes it)."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
KEY_FILE = os.path.expanduser(
    "~/euearth/workspace/"
    "throne-room/council/skills/orchestration-engine/.runpod_api_key")
IMAGE = "runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04"
# 0.5B fp32 needs ~6GB peak; anything >=24GB is adequate. Cheapest first.
GPU_PREFS = ["RTX 3090", "RTX 4090", "A40", "RTX A5000", "RTX A6000", "L4", "A100"]
MAX_BOOT_WAIT_S = 450
MAX_RUN_S = 5400            # hard kill: never pay for more than 90 min
REMOTE_DIR = "/workspace/artisan"


def api(query: str) -> dict:
    key = open(KEY_FILE).read().strip()
    req = urllib.request.Request(
        "https://api.runpod.io/graphql",
        data=json.dumps({"query": query}).encode(),
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json", "User-Agent": "curl/8.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        out = json.loads(r.read())
    if out.get("errors"):
        raise RuntimeError(f"runpod api error: {out['errors']}")
    return out


def balance() -> float:
    return api("query { myself { clientBalance } }")["data"]["myself"]["clientBalance"]


def pick_gpu():
    # SECURE cloud only: it exposes a public TCP SSH port (privatePort 22),
    # which is what makes scp work. Community pods only give a proxy SSH
    # that needs a PTY and blocks scp — useless for shipping code/results.
    res = api('query { gpuTypes { id displayName memoryInGb secureCloud '
              'lowestPrice(input:{gpuCount:1}){ uninterruptablePrice } } }')
    rows = res["data"]["gpuTypes"]
    candidates = []
    for g in rows:
        price = (g.get("lowestPrice") or {}).get("uninterruptablePrice")
        if not price or (g.get("memoryInGb") or 0) < 24 or not g["secureCloud"]:
            continue
        for rank, pref in enumerate(GPU_PREFS):
            if pref in g["displayName"]:
                candidates.append((price, rank, g["id"], g["displayName"]))
    candidates.sort()
    return candidates


def deploy(gpu_id: str) -> tuple:
    # ports "22/tcp" forces a PUBLIC TCP SSH port (needed for scp).
    q = f'''mutation {{ podFindAndDeployOnDemand(input: {{
        name: "artisan-plane-experiment",
        imageName: "{IMAGE}",
        gpuTypeId: "{gpu_id}",
        cloudType: SECURE,
        gpuCount: 1,
        volumeInGb: 0,
        containerDiskInGb: 40,
        ports: "22/tcp",
        startSsh: true
    }}) {{ id costPerHr machine {{ gpuDisplayName }} }} }}'''
    r = api(q)["data"]["podFindAndDeployOnDemand"]
    if not r:
        return None, None, None
    return r["id"], r["costPerHr"], r["machine"]["gpuDisplayName"]


def wait_ssh(pod_id: str):
    start = time.time()
    while time.time() - start < MAX_BOOT_WAIT_S:
        r = api(f'query {{ pod(input: {{ podId: "{pod_id}" }}) {{ runtime {{ '
                f'uptimeInSeconds ports {{ ip isIpPublic privatePort publicPort }} }} }} }}')
        rt = r["data"]["pod"].get("runtime")
        if rt and rt.get("uptimeInSeconds"):
            for p in rt.get("ports") or []:
                if p["privatePort"] == 22 and p["isIpPublic"]:
                    return p["ip"], p["publicPort"]
        time.sleep(15)
        print(f"  booting... {int(time.time() - start)}s")
    return None, None


def terminate(pod_id: str):
    try:
        api(f'mutation {{ podTerminate(input: {{ podId: "{pod_id}" }}) }}')
    except Exception as exc:
        print(f"terminate: pod {pod_id} already gone or unreachable ({exc})")


def sh(cmd: list, timeout: int, check: bool = True) -> subprocess.CompletedProcess:
    print("  $", " ".join(cmd[:8]), "..." if len(cmd) > 8 else "")
    p = subprocess.run(cmd, timeout=timeout, capture_output=True, text=True)
    if check and p.returncode != 0:
        raise RuntimeError(f"command failed ({p.returncode}): "
                           f"{p.stderr[-800:] or p.stdout[-800:]}")
    return p


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--keep-pod", action="store_true", help="debug only")
    args = ap.parse_args()

    bal = balance()
    cands = pick_gpu()
    print(f"balance ${bal:.2f}; GPU candidates (price, pref, id, name):")
    for c in cands[:6]:
        print("   ", c)
    if not cands:
        print("NO adequate GPU available — stopping before any spend.")
        sys.exit(2)
    price, _, gpu_id, gpu_name = cands[0]
    est = price * 0.75
    print(f"chosen: {gpu_name} @ ${price}/hr (est. run ~45min => ~${est:.2f})")
    if args.dry_run:
        print("DRY RUN — no pod deployed.")
        return
    if bal < max(2.0, est * 2):
        print("balance too low for a safe run — stopping before any spend.")
        sys.exit(2)

    pod_id = None
    t_pod0 = None
    billing = {}
    try:
        pod_id, cost_hr, disp = deploy(gpu_id)
        if not pod_id:
            print("deploy returned nothing (supply). Stopping.")
            sys.exit(2)
        t_pod0 = time.time()
        print(f"pod {pod_id} on {disp} @ ${cost_hr}/hr — waiting for SSH...")
        ip, port = wait_ssh(pod_id)
        if not ip:
            raise RuntimeError("pod never reached SSH runtime")
        print(f"SSH up: {ip}:{port}")
        keyopt = ["-i", os.path.expanduser("~/.ssh/id_ed25519")]
        ssh = ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
               *keyopt, "-p", str(port), f"root@{ip}"]
        scp = ["scp", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
               *keyopt, "-P", str(port)]

        # ship the repo (code only)
        tarball = "/tmp/artisan_plane.tar.gz"
        sh(["tar", "czf", tarball, "-C", str(REPO.parent),
            "--exclude=artisan/.venv", "--exclude=artisan/.venv-plane",
            "--exclude=artisan/var", "--exclude=artisan/.git",
            "--exclude=artisan/__pycache__", "artisan"], 120)
        sh(ssh + ["mkdir -p /workspace"], 60)
        sh(scp + [tarball, f"root@{ip}:/workspace/artisan.tar.gz"], 300)
        sh(ssh + ["cd /workspace && tar xzf artisan.tar.gz"], 120)

        print("installing deps on pod (torch ships with the image)...")
        sh(ssh + ["cd /workspace/artisan && pip install -q "
                  "'transformers>=4.44,<5' 'peft>=0.11' 'safetensors>=0.4' "
                  "'accelerate>=0.30' 'cryptography>=42' 'numpy' 2>&1 | tail -2"], 900)

        print("running the experiment (streaming log)...")
        run_cmd = (f"cd {REMOTE_DIR} && ARTISAN_GPU_USD_PER_HOUR={cost_hr} "
                   f"python -u -m plane.run_experiment "
                   f"> /workspace/experiment.log 2>&1; echo EXIT=$?")
        t0 = time.time()
        proc = subprocess.Popen(ssh + [run_cmd], stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True)
        exit_line = ""
        while proc.poll() is None:
            if time.time() - t0 > MAX_RUN_S:
                proc.kill()
                raise RuntimeError(f"hard timeout after {MAX_RUN_S}s")
            time.sleep(10)
        exit_line = (proc.stdout.read() or "").strip()
        tail = sh(ssh + ["tail -40 /workspace/experiment.log"], 60, check=False)
        print(tail.stdout)
        print(f"remote said: {exit_line}")

        out_dir = REPO / "var/plane_real_runpod"
        out_dir.mkdir(parents=True, exist_ok=True)
        for f in ["var/plane_real/results.json", "var/plane_real/meter.json"]:
            sh(scp + [f"root@{ip}:{REMOTE_DIR}/{f}", str(out_dir)], 120, check=False)
        sh(scp + [f"root@{ip}:/workspace/experiment.log", str(out_dir)], 120, check=False)
        if "EXIT=0" not in exit_line:
            print("WARNING: remote experiment exited nonzero — see experiment.log")
    finally:
        if pod_id and not args.keep_pod:
            terminate(pod_id)
            lifetime = time.time() - t_pod0 if t_pod0 else 0
            billing = {
                "pod_id": pod_id, "gpu": gpu_name, "usd_per_hour": price,
                "pod_lifetime_seconds": round(lifetime, 1),
                "pod_lifetime_usd": round(lifetime / 3600 * price, 4),
                "balance_after": balance(),
            }
            (REPO / "var").mkdir(exist_ok=True)
            (REPO / "var/runpod_billing.json").write_text(json.dumps(billing, indent=2))
            print(f"pod TERMINATED after {billing['pod_lifetime_seconds']}s "
                  f"= ${billing['pod_lifetime_usd']} "
                  f"(balance now ${billing['balance_after']:.2f})")


if __name__ == "__main__":
    main()
