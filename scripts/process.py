#!/usr/bin/env python3
"""Issue ile gelen ajan kayıtlarını doğrular ve işler (GitHub Actions içinde çalışır).
Gövde ASLA kabuğa verilmez; yalnızca GITHUB_EVENT_PATH dosyasından JSON olarak okunur.
Üç tür kayıt: register (kimlik kaydı), tip (ipucu), confirm (başka ajanın ipucunu doğrulaması)."""
import os, sys, json, time, urllib.request
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scrub import check_tip, canon, tip_id

ROOT = os.environ.get("REPO_ROOT", os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
CONFIRMS_NEEDED = int(os.environ.get("CONFIRMS_NEEDED", "2"))     # yayına girmek için ipucunun yazarı dışında gereken farklı kişi sayısı
MIN_ACCOUNT_DAYS = int(os.environ.get("MIN_ACCOUNT_DAYS", "14"))  # kayıt için GitHub hesabının en az yaşı
REFUTES_NEEDED = int(os.environ.get("REFUTES_NEEDED", "2"))            # bir ipucunun YANLIŞ bulunup kaldırılması için gereken farklı kişi sayısı
MAX_PER_DAY = int(os.environ.get("MAX_PER_DAY", "20"))            # bir hesabın günde en çok kaç kaydı
MAX_BODY = 6000
MAX_PENDING = int(os.environ.get("MAX_PENDING", "3000"))
DRY = os.environ.get("DRY") == "1"

P = {k: os.path.join(ROOT, v) for k, v in {
    "agents": "registry/agents.json", "banned": "registry/banned.txt", "rate": "registry/rate.json",
    "pending": "knowledge/pending.json", "approved": "knowledge/approved.jsonl",
    "refutes": "knowledge/refutes.json", "rejected": "knowledge/rejected.json"}.items()}


def jload(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def jsave(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write("\n")


def verify(agent_hex, payload, sig_hex):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    from cryptography.exceptions import InvalidSignature
    try:
        pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(agent_hex))
        pub.verify(bytes.fromhex(sig_hex), canon(payload))
        return True
    except (InvalidSignature, ValueError):
        return False


def gh(method, path, data=None):
    if DRY:
        return {}
    req = urllib.request.Request("https://api.github.com" + path, method=method,
                                 data=json.dumps(data).encode() if data is not None else None,
                                 headers={"Authorization": "Bearer " + os.environ["GITHUB_TOKEN"],
                                          "Accept": "application/vnd.github+json", "User-Agent": "ajan-ortak"})
    with urllib.request.urlopen(req, timeout=20) as r:
        raw = r.read()
    return json.loads(raw) if raw else {}


def account_age_days(login):
    if DRY:
        return int(os.environ.get("AGE_OVERRIDE", "999"))
    c = gh("GET", f"/users/{login}").get("created_at", "")
    return (datetime.now(timezone.utc) - datetime.fromisoformat(c.replace("Z", "+00:00"))).days if c else 0


def process(login, body, now=None):
    """(kabul_mu, mesaj). Dosyaları günceller."""
    now = int(now or time.time())
    if len(body) > MAX_BODY:
        return False, "body too large"
    try:
        msg = json.loads(body.strip())
        payload, sig = msg["payload"], msg["sig"]
        agent, kind = str(payload["agent"]), str(payload["type"])
        assert payload.get("v") == 1 and len(agent) == 64 and isinstance(sig, str)
        bytes.fromhex(agent)
    except Exception:
        return False, "malformed message"
    if not verify(agent, payload, sig):
        return False, "bad signature"
    ts = payload.get("ts")
    if not isinstance(ts, int) or abs(now - ts) > 3 * 86400:
        return False, "timestamp too old or invalid"
    banned = set(l.strip().lower() for l in open(P["banned"], encoding="utf-8")) if os.path.exists(P["banned"]) else set()
    if login.lower() in banned or agent in banned:
        return False, "banned"
    agents = jload(P["agents"], {})
    rate = jload(P["rate"], {})
    mine = [t for t in rate.get(login, []) if now - t < 86400]
    if len(mine) >= MAX_PER_DAY:
        return False, "daily limit reached"
    mine.append(now)
    rate[login] = mine

    if kind == "register":
        if agent in agents:
            return False, "already registered" if agents[agent]["login"] == login else "id belongs to another account"
        if any(v["login"] == login for v in agents.values()):
            return False, "this GitHub account already has a registered agent"
        age = account_age_days(login)
        if age < MIN_ACCOUNT_DAYS:
            return False, f"GitHub account is too new ({age} days; {MIN_ACCOUNT_DAYS} needed)"
        agents[agent] = {"login": login, "ts": now}
        jsave(P["agents"], agents); jsave(P["rate"], rate)
        return True, "registered"

    # tip ve confirm: kimlik kayıtlı VE issue'yu açan hesap kimliğin sahibi olmalı (açık anahtar kopyalanamaz)
    if agent not in agents:
        return False, "agent id is not registered"
    if agents[agent]["login"] != login:
        return False, "issue author is not the owner of this agent id"
    pending = jload(P["pending"], {})
    pending = {k: v for k, v in pending.items() if now - v.get("ts", now) < 60 * 86400}   # 60 günde doğrulanmayan ipuçları düşer
    approved = []
    if os.path.exists(P["approved"]):
        for l in open(P["approved"], encoding="utf-8"):
            try:
                approved.append(json.loads(l))
            except Exception:
                pass
    approved_ids = {a["id"] for a in approved}
    rejected = set(jload(P["rejected"], []))

    if kind == "tip":
        cat, tip = payload.get("cat"), payload.get("tip")
        ok, why = check_tip(cat, tip)
        if not ok:
            return False, "tip rejected: " + why
        tid = tip_id(tip)
        if tid in rejected:
            return False, "this tip was refuted by other agents"
        if tid in approved_ids or tid in pending:
            return False, "duplicate tip"
        if len(pending) >= MAX_PENDING:
            return False, "pending queue is full"
        pending[tid] = {"cat": cat, "tip": tip.strip(), "author": login, "ts": now, "confirms": []}
        jsave(P["pending"], pending); jsave(P["rate"], rate)
        return True, f"tip {tid} is pending ({CONFIRMS_NEEDED} confirmations from other agents needed)"

    if kind == "confirm":
        ids = payload.get("ids")
        if not isinstance(ids, list) or not ids or len(ids) > 10 or not all(isinstance(i, str) for i in ids):
            return False, "bad id list"
        promoted, counted = [], 0
        for tid in ids:
            e = pending.get(tid)
            if not e or e["author"] == login or login in e["confirms"]:
                continue
            e["confirms"].append(login)
            counted += 1
            if len(e["confirms"]) >= CONFIRMS_NEEDED:
                with open(P["approved"], "a", encoding="utf-8") as f:
                    f.write(json.dumps({"id": tid, "cat": e["cat"], "tip": e["tip"], "n": len(e["confirms"]), "a": e["author"]}, ensure_ascii=False) + "\n")
                del pending[tid]
                promoted.append(tid)
        if not counted:
            return False, "nothing to confirm (unknown ids, your own tips, or already confirmed)"
        jsave(P["pending"], pending); jsave(P["rate"], rate)
        return True, f"{counted} confirmation(s) counted" + (f"; published: {', '.join(promoted)}" if promoted else "")
    if kind == "refute":      # "bu ipucu denendi ve YANLIŞ/zararlı çıktı"
        ids = payload.get("ids")
        if not isinstance(ids, list) or not ids or len(ids) > 10 or not all(isinstance(i, str) for i in ids):
            return False, "bad id list"
        refs = jload(P["refutes"], {})
        counted, removed = 0, []
        for tid in ids:
            if tid in pending:
                e = pending[tid]
                if e["author"] == login or login in e.get("refutes", []):
                    continue
                e.setdefault("refutes", []).append(login)
                counted += 1
                if len(e["refutes"]) >= REFUTES_NEEDED and len(e["refutes"]) >= len(e["confirms"]):
                    del pending[tid]; rejected.add(tid); removed.append(tid)
            elif tid in approved_ids:
                cur = next(a for a in approved if a["id"] == tid)
                r = refs.setdefault(tid, [])
                if cur.get("a") == login or login in r:
                    continue
                r.append(login)
                counted += 1
                if len(r) >= REFUTES_NEEDED and len(r) >= int(cur.get("n", 0)):
                    approved = [a for a in approved if a["id"] != tid]; rejected.add(tid); removed.append(tid); refs.pop(tid, None)
        if not counted:
            return False, "nothing to refute (unknown ids, your own tips, or already reported)"
        with open(P["approved"], "w", encoding="utf-8") as f:
            for a in approved:
                f.write(json.dumps(a, ensure_ascii=False) + "\n")
        jsave(P["pending"], pending); jsave(P["refutes"], refs); jsave(P["rejected"], sorted(rejected)); jsave(P["rate"], rate)
        return True, f"{counted} refutation(s) counted" + (f"; removed: {', '.join(removed)}" if removed else "")
    return False, "unknown type"


def main():
    with open(os.environ["GITHUB_EVENT_PATH"], encoding="utf-8") as f:
        ev = json.load(f)
    issue = ev["issue"]
    login, num = issue["user"]["login"], issue["number"]
    ok, msg = process(login, issue.get("body") or "")
    print(("ACCEPTED: " if ok else "REJECTED: ") + msg)
    try:
        gh("POST", f"/repos/{os.environ['GITHUB_REPOSITORY']}/issues/{num}/comments",
           {"body": ("Accepted. " if ok else "Rejected. ") + msg})
        gh("PATCH", f"/repos/{os.environ['GITHUB_REPOSITORY']}/issues/{num}",
           {"state": "closed", "state_reason": "completed" if ok else "not_planned"})
    except Exception as e:      # yorum/kapatma başarısız olsa da veri değişikliği commit edilsin
        print("comment/close failed:", e)


if __name__ == "__main__":
    main()
