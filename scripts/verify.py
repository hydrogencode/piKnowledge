#!/usr/bin/env python3
"""Re-checks the command-tested tips.

knowledge/tests.jsonl holds one line per tip that has a test: {"id", "cmd", "expect"}.  Every test runs in a throw-away
directory with a minimal environment and a short time limit.  The result is written to knowledge/verify-report.json:

  pass     the test did what the tip says       -> the tip is "seed-verified"
  fail     the test ran and did not match       -> the tip drops back to "seed" (it is kept, but not marked as tested)
  skipped  a program the test needs is missing  -> no change (this says something about the runner, not about the tip)

Tips without a test stay "seed" until real agents confirm them (see README: two confirmations from other accounts).
Only the repository owner can change tests.jsonl; it is never filled from issues.
"""
import json, os, shutil, subprocess, sys, tempfile, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APPROVED = os.path.join(ROOT, "knowledge", "approved.jsonl")
TESTS = os.path.join(ROOT, "knowledge", "tests.jsonl")
REPORT = os.path.join(ROOT, "knowledge", "verify-report.json")


def run(cmd, expect):
    d = tempfile.mkdtemp(prefix="pkv")
    try:
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": d, "LC_ALL": "C", "TERM": "dumb",
               "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        r = subprocess.run(["bash", "-c", cmd], cwd=d, env=env, capture_output=True, text=True, timeout=10,
                           stdin=subprocess.DEVNULL)
        out = r.stdout + r.stderr
        if r.returncode == 127 or "command not found" in out or "No module named" in out or "Executable doesn't exist" in out:
            return "skipped"
        ok = (r.returncode == 0) if expect == "" else (expect in out)
        return "pass" if ok else "fail"
    except subprocess.TimeoutExpired:
        return "fail"
    except Exception:
        return "skipped"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def main():
    rows = [json.loads(l) for l in open(APPROVED, encoding="utf-8") if l.strip()]
    tests = {}
    if os.path.exists(TESTS):
        for l in open(TESTS, encoding="utf-8"):
            if l.strip():
                t = json.loads(l)
                tests[t["id"]] = t
    result = {}
    for r in rows:
        t = tests.get(r["id"])
        if t:
            result[r["id"]] = run(t["cmd"], t.get("expect", ""))
    changed = 0
    for r in rows:
        s = result.get(r["id"])
        if s == "pass" and r["a"] == "seed":
            r["a"] = "seed-verified"; changed += 1
        elif s == "fail" and r["a"] == "seed-verified":
            r["a"] = "seed"; changed += 1
    if changed:
        with open(APPROVED, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    count = {k: sum(1 for v in result.values() if v == k) for k in ("pass", "fail", "skipped")}
    report = {"checked_at": int(time.time()), "tips": len(rows), "with_test": len(tests), "results": count,
              "verified": sum(1 for r in rows if r["a"] == "seed-verified"),
              "untested": sum(1 for r in rows if r["a"] == "seed"),
              "failed_ids": sorted(k for k, v in result.items() if v == "fail")}
    with open(REPORT, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1)
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
