"""Apify runs that survive the process that started them.

Why (2026-09-17): on 11 Sep `discover_brand_branches.py --brand KFC` started
4 of its 9 province runs, then the 5th start was refused and the script died.
The 4 runs finished on Apify ("Succeeded", 961 places) but their dataset IDs
lived only in that dead process — nothing was saved and nothing could resume.
The same risk applies to crawl_google_places.py: closing the terminal during
its ~6 min wait throws the results away.

This module records every run in core/apify_runs/<job>.json the moment Apify
accepts it, so re-running the *same command* picks up where it stopped:
finished runs are collected, running ones are waited on, and only missing work
is started. It also caps concurrency, and when Apify refuses a start
(402/403/429 — plan memory, concurrency or credit limits) it waits for a
running run to free capacity instead of crashing.

When the caller has saved the results it calls mark_done(job), which renames
the state file to <job>.<timestamp>.done.json so the next run starts fresh.
"""
import json
import os
import time
from datetime import datetime, timezone

import requests

STATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "apify_runs")
API = "https://api.apify.com/v2"
LIMIT_CODES = {402, 403, 429}
TERMINAL = {"SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"}
MAX_ATTEMPTS = 2


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def state_path(job: str) -> str:
    return os.path.join(STATE_DIR, f"{job}.json")


def load_state(job: str) -> dict:
    try:
        with open(state_path(job)) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def save_state(job: str, state: dict) -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    tmp = state_path(job) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, state_path(job))


def mark_done(job: str) -> None:
    p = state_path(job)
    if os.path.exists(p):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        os.replace(p, os.path.join(STATE_DIR, f"{job}.{stamp}.done.json"))


def discard(job: str) -> None:
    """--fresh: set an unfinished job aside (kept for reference, not resumed)."""
    p = state_path(job)
    if os.path.exists(p):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        os.replace(p, os.path.join(STATE_DIR, f"{job}.{stamp}.discarded.json"))


def run_jobs(token: str, actor_id: str, job: str, bodies: dict, *, max_concurrent: int = 2,
             poll_seconds: int = 15, timeout_minutes: int = 120, run_params: dict = None) -> dict:
    """Run one Apify actor run per key in `bodies`; return {key: dataset_id}.

    Keys whose runs failed twice map to None. Safe to interrupt at any point:
    run the same command again and it resumes from core/apify_runs/<job>.json.
    """
    state = load_state(job)
    if state:
        print(f"↩️  Resuming {job} from {os.path.relpath(state_path(job))} "
              f"({sum(1 for s in state.values() if s.get('dataset_id'))}/{len(bodies)} already finished)")
    for key in list(state):
        if key not in bodies:
            print(f"  ℹ️ state has '{key}', which this command didn't ask for — ignoring it")
    deadline = time.time() + timeout_minutes * 60
    last_limit_note = 0.0

    def entry(k):
        return state.setdefault(k, {"attempts": 0})

    while True:
        # 1. refresh runs that are still going
        for key in bodies:
            s = state.get(key) or {}
            if s.get("run_id") and s.get("status") not in TERMINAL:
                # A 5xx or dropped connection on a status poll is Apify hiccuping, not a
                # failed run: wait and poll again instead of crashing the whole script.
                r = None
                for attempt in range(5):
                    try:
                        r = requests.get(f"{API}/actor-runs/{s['run_id']}", params={"token": token}, timeout=30)
                        if r.status_code < 500:
                            break
                    except requests.exceptions.RequestException:
                        r = None
                    time.sleep(5 * (attempt + 1))
                if r is None or r.status_code >= 500:
                    continue  # still unwell: leave the run as it is and check next cycle
                r.raise_for_status()
                d = r.json()["data"]
                if d["status"] != s.get("status"):
                    s["status"] = d["status"]
                    if d["status"] == "SUCCEEDED":
                        s["dataset_id"] = d["defaultDatasetId"]
                        s["finished_at"] = _now()
                        print(f"  ✅ {key}: run {s['run_id']} succeeded (dataset {s['dataset_id']})")
                    elif d["status"] in TERMINAL:
                        print(f"  ⚠️ {key}: run {s['run_id']} {d['status']}")
                    save_state(job, state)

        done = {k for k in bodies if (state.get(k) or {}).get("dataset_id")}
        dead = {k for k in bodies if k not in done
                and (state.get(k) or {}).get("status") in TERMINAL
                and (state.get(k) or {}).get("attempts", 0) >= MAX_ATTEMPTS}
        active = [k for k in bodies if (state.get(k) or {}).get("run_id")
                  and (state.get(k) or {}).get("status") not in TERMINAL]
        pending = [k for k in bodies if k not in done and k not in dead and k not in active]

        if not active and not pending:
            break
        if time.time() > deadline:
            raise TimeoutError(f"{job}: not finished after {timeout_minutes} min — run the same command again to keep waiting")

        # 2. start more work while there's capacity
        for key in pending:
            if len(active) >= max_concurrent:
                break
            r = requests.post(f"{API}/acts/{actor_id}/runs", params={"token": token, **(run_params or {})}, json=bodies[key], timeout=30)
            if r.status_code in LIMIT_CODES:
                if not active:
                    raise SystemExit(
                        f"❌ Apify refused to start '{key}' ({r.status_code}) with nothing else running — "
                        f"likely out of credit or over the plan limit: {r.text[:300]}\n"
                        f"Progress is saved; run the same command again once that's resolved.")
                if time.time() - last_limit_note > 120:
                    print(f"  ⏸ Apify at capacity ({r.status_code}); waiting for a running run to finish")
                    last_limit_note = time.time()
                break
            r.raise_for_status()
            d = r.json()["data"]
            e = entry(key)
            e.update(run_id=d["id"], status=d["status"], started_at=_now(),
                     attempts=e.get("attempts", 0) + 1, dataset_id=None)
            save_state(job, state)  # saved BEFORE any waiting — the whole point
            active.append(key)
            print(f"  ▶️ {key}: run {d['id']} started")

        time.sleep(poll_seconds)

    out = {k: (state.get(k) or {}).get("dataset_id") for k in bodies}
    failed = [k for k, v in out.items() if not v]
    if failed:
        print(f"  ⚠️ gave up on {', '.join(failed)} after {MAX_ATTEMPTS} attempts")
    return out
