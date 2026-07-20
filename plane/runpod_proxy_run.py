"""Run the plane experiment on a RunPod COMMUNITY pod via proxy SSH.

Secure-cloud pods with a public TCP SSH port (needed for scp) are
supply-constrained; community pods are available and RunPod's basic
proxy SSH (ssh.runpod.io, keyed to the account) authenticates us. That
proxy is PTY-only — no scp, no exec-arg — so we drive it the one way it
supports: pipe a full bash script to `ssh -tt <podHostId>@ssh.runpod.io`
and read the result back as base64 between markers.

    python3 plane/runpod_proxy_run.py --dry-run
    python3 plane/runpod_proxy_run.py            # BILLABLE; auto-terminates
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
KEY_FILE = os.path.expanduser(
    "~/euearth/workspace/"
    "throne-room/council/skills/orchestration-engine/.runpod_api_key")
SSH_KEY = os.path.expanduser("~/.ssh/id_ed25519")
IMAGE = "runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04"
GPU_PREFS = ["RTX 3090", "RTX 4090", "A40", "RTX A5000", "RTX A6000", "L4"]
MAX_BOOT_WAIT_S = 420
MAX_RUN_S = 4200


def api(query: str) -> dict:
    key = open(KEY_FILE).read().strip()
    import urllib.request
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
    res = api('query { gpuTypes { id displayName memoryInGb secureCloud communityCloud '
              'lowestPrice(input:{gpuCount:1}){ uninterruptablePrice } } }')
    cands = []
    for g in res["data"]["gpuTypes"]:
        price = (g.get("lowestPrice") or {}).get("uninterruptablePrice")
        if not price or (g.get("memoryInGb") or 0) < 24:
            continue
        if not (g["secureCloud"] or g["communityCloud"]):
            continue
        for rank, pref in enumerate(GPU_PREFS):
            if pref in g["displayName"]:
                cands.append((price, rank, g["id"], g["displayName"]))
    cands.sort()
    return cands


def deploy(gpu_id: str):
    q = f'''mutation {{ podFindAndDeployOnDemand(input: {{
        name: "artisan-plane-proxy",
        imageName: "{IMAGE}",
        gpuTypeId: "{gpu_id}",
        gpuCount: 1,
        volumeInGb: 0,
        containerDiskInGb: 40,
        startSsh: true
    }}) {{ id costPerHr machine {{ gpuDisplayName podHostId }} }} }}'''
    r = api(q)["data"]["podFindAndDeployOnDemand"]
    if not r:
        return None
    return r


def wait_runtime(pod_id: str):
    start = time.time()
    while time.time() - start < MAX_BOOT_WAIT_S:
        r = api(f'query {{ pod(input: {{ podId: "{pod_id}" }}) {{ runtime {{ '
                f'uptimeInSeconds }} }} }}')
        rt = r["data"]["pod"].get("runtime")
        if rt and rt.get("uptimeInSeconds"):
            return True
        time.sleep(12)
        print(f"  booting... {int(time.time()-start)}s", flush=True)
    return False


def terminate(pod_id: str):
    # Tolerate POD_NOT_FOUND: a preempted/expired community pod is already
    # gone, and that must never turn into a nonzero wrapper exit that hides
    # a captured result. The account is what matters; verify it separately.
    try:
        api(f'mutation {{ podTerminate(input: {{ podId: "{pod_id}" }}) }}')
    except Exception as exc:
        print(f"terminate: pod {pod_id} already gone or unreachable ({exc})")


def proxy_run(host_id: str, script: str, timeout: int) -> str:
    """Pipe a bash script to the pod's interactive proxy shell; return the
    combined stdout (PTY-noisy)."""
    cmd = ["ssh", "-tt", "-o", "StrictHostKeyChecking=no",
           "-o", "UserKnownHostsFile=/dev/null", "-o", "ConnectTimeout=30",
           "-i", SSH_KEY, f"{host_id}@ssh.runpod.io"]
    p = subprocess.run(cmd, input=script + "\nexit\n",
                       capture_output=True, text=True, timeout=timeout)
    return p.stdout + "\n" + p.stderr


def extract(marker: str, blob: str) -> str | None:
    m = re.search(f"{marker}_START(.*?){marker}_END", blob, re.S)
    if not m:
        return None
    return re.sub(r"[^A-Za-z0-9+/=]", "", m.group(1))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    bal = balance()
    cands = pick_gpu()
    print(f"balance ${bal:.2f}; candidates:")
    for c in cands[:6]:
        print("   ", c)
    if not cands:
        print("no adequate GPU available — stop, no spend."); sys.exit(2)
    price, _, gpu_id, gpu_name = cands[0]
    print(f"chosen: {gpu_name} @ ${price}/hr")
    if args.dry_run:
        print("DRY RUN — no pod."); return

    # code payload
    tarball = "/tmp/artisan_plane.tar.gz"
    subprocess.run(["tar", "czf", tarball, "-C", str(REPO.parent),
                    "--exclude=artisan/.venv", "--exclude=artisan/.venv-plane",
                    "--exclude=artisan/var", "--exclude=artisan/.git",
                    "--exclude=artisan/__pycache__", "artisan"], check=True)
    b64 = base64.b64encode(Path(tarball).read_bytes()).decode()
    b64_wrapped = "\n".join(b64[i:i+76] for i in range(0, len(b64), 76))
    src_sha = subprocess.run(["shasum", "-a", "256", tarball],
                             capture_output=True, text=True).stdout.split()[0]

    pod = None
    t_pod0 = None
    try:
        pod = deploy(gpu_id)
        if not pod:
            print("deploy returned nothing (supply) — stop, no spend."); sys.exit(2)
        pod_id, cost_hr, host_id = pod["id"], pod["costPerHr"], pod["machine"]["podHostId"]
        t_pod0 = time.time()
        print(f"pod {pod_id} host {host_id} on {pod['machine']['gpuDisplayName']} "
              f"@ ${cost_hr}/hr — waiting for runtime...", flush=True)
        if not wait_runtime(pod_id):
            raise RuntimeError("pod never reached runtime")
        # proxy sshd inside the container may lag the runtime flag; settle.
        time.sleep(20)

        upload = f"""
mkdir -p /workspace && cd /workspace
base64 -d > artisan.tar.gz <<'B64EOF'
{b64_wrapped}
B64EOF
echo "GOT_SHA_START"; sha256sum artisan.tar.gz | cut -d' ' -f1; echo "GOT_SHA_END"
tar xzf artisan.tar.gz && echo UPLOAD_OK || echo UPLOAD_FAIL
"""
        out = proxy_run(host_id, upload, 180)
        got_sha = extract("GOT_SHA", out)
        try:
            got_sha = base64.b64decode(got_sha).decode() if got_sha and len(got_sha) > 44 else got_sha
        except Exception:
            pass
        print(f"upload: local_sha={src_sha[:16]} pod reported (raw block present={bool(got_sha)}); "
              f"UPLOAD_OK={'UPLOAD_OK' in out}")
        if "UPLOAD_OK" not in out:
            raise RuntimeError(f"upload failed; tail:\n{out[-800:]}")

        run = f"""
cd /workspace/artisan
pip install -q 'transformers>=4.44,<5' 'peft>=0.11' 'safetensors>=0.4' 'accelerate>=0.30' 'cryptography>=42' numpy 2>&1 | tail -2
export ARTISAN_GPU_USD_PER_HOUR={cost_hr}
python -u -m plane.run_experiment --router presence 2>&1 | tail -80
echo "RUN_EXIT=${{PIPESTATUS[0]}}"
echo "RESULTS_B64_START"; base64 var/plane_real/results.json 2>/dev/null; echo "RESULTS_B64_END"
echo "METER_B64_START"; base64 var/plane_real/meter.json 2>/dev/null; echo "METER_B64_END"
"""
        print("running experiment on pod (single proxy session)...", flush=True)
        out = proxy_run(host_id, run, MAX_RUN_S)
        out_dir = REPO / "var/plane_real_runpod"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "pod_stdout.log").write_text(out)
        for marker, fname in [("RESULTS_B64", "results.json"), ("METER_B64", "meter.json")]:
            b = extract(marker, out)
            if b:
                try:
                    (out_dir / fname).write_bytes(base64.b64decode(b))
                    print(f"retrieved {fname} ({len(base64.b64decode(b))} bytes)")
                except Exception as e:
                    print(f"could not decode {fname}: {e}")
            else:
                print(f"WARNING: {fname} not found in pod output")
        rexit = re.search(r"RUN_EXIT=(\d+)", out)
        print(f"remote RUN_EXIT={rexit.group(1) if rexit else '?'}")
    finally:
        if pod:
            terminate(pod["id"])
            life = time.time() - t_pod0 if t_pod0 else 0
            billing = {"pod_id": pod["id"], "gpu": pod["machine"]["gpuDisplayName"],
                       "usd_per_hour": pod["costPerHr"],
                       "pod_lifetime_seconds": round(life, 1),
                       "pod_lifetime_usd": round(life/3600*pod["costPerHr"], 4),
                       "balance_after": balance()}
            (REPO / "var").mkdir(exist_ok=True)
            (REPO / "var/runpod_billing.json").write_text(json.dumps(billing, indent=2))
            print(f"pod TERMINATED after {billing['pod_lifetime_seconds']}s = "
                  f"${billing['pod_lifetime_usd']} (balance ${billing['balance_after']:.2f})")


if __name__ == "__main__":
    main()
