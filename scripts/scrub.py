# Ortak (ajan + repo) kurallar: BU DOSYA ajan.py içindeki bölümle birebir aynıdır (testle doğrulanır).
import re, json, hashlib

MAX_TIP = 280
CATS = ("chromium", "browser", "xdotool", "raspberry-pi", "systemd", "python", "flask", "network", "apt", "gui",
        "shell", "git", "files", "forms", "general")
_INVISIBLE = re.compile("[​-‏‪-‮⁠-⁩﻿\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_BAD = [
    (r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "ip address"),
    (r"\b(?:[0-9a-f]{1,4}:){2,7}[0-9a-f]{1,4}\b", "ipv6 address"),
    (r"\b(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}\b", "mac address"),
    (r"[\w.+-]+@[\w-]+\.[\w.-]+", "email"),
    (r"(?i)https?://|ftp://|www\.|\b[a-z0-9-]+\.(?:com|net|org|io|dev|app|me|tr|ru|cn|xyz|sh|ly|co|info|local|lan)\b", "url or domain"),
    (r"/home/[^\s/]+|/Users/[^\s/]+|[A-Za-z]:\\+Users|~[a-z][\w-]*/", "path with a user name"),
    (r"\b[0-9a-fA-F]{24,}\b", "token-like string"),
    (r"\b[A-Za-z0-9_\-]{32,}\b", "token-like string"),
    (r"(?i)\b(?:ghp|gho|ghs|ghu|github_pat|sk|AIza|xox[abp])[-_A-Za-z0-9]{8,}", "token"),
    (r"(?i)\b(?:password|passwd|sifre|şifre|parola|secret|token|api[_ -]?key|ssid)\b\s*[:=]", "secret assignment"),
    # tehlikeli / komut enjeksiyonu kalıpları
    (r"(?i)\b(?:curl|wget|fetch)\b[^\n]*\|\s*(?:sudo\s+)?(?:ba|z|da)?sh\b", "pipe to shell"),
    (r"(?i)\|\s*(?:sudo\s+)?(?:ba|z|da)?sh\b|\|\s*(?:sudo\s+)?python3?\b", "pipe to interpreter"),
    (r"(?i)\brm\s+-[a-z]*[rf][a-z]*\b|\bmkfs\b|\bdd\s+if=|>\s*/dev/(?:sd|mmc|nvme)|\bchmod\s+-R\s+7|\bchown\s+-R\b|:\(\)\s*\{", "destructive command"),
    (r"(?i)\bbase64\b|\beval\b|\bexec\b\s*\(|\bos\.system\b|\bsubprocess\b", "obfuscated or code execution"),
    (r"(?i)authorized_keys|/etc/(?:passwd|shadow|sudoers)|\bcrontab\b|\.ssh/|\bnc\s+-[a-z]*e\b|reverse shell", "sensitive system target"),
    (r"(?i)ignore (?:all |any |the |your )?(?:previous|prior|above)|disregard|system prompt|override (?:the )?(?:rules|safety|guard)|"
     r"you (?:must|should) (?:now )?(?:run|execute|download|install|send|upload)|(?:run|execute) (?:this|the following)|download and (?:run|execute)|"
     r"\bjailbreak\b|new instructions", "instruction-like text"),
    (r"```|</?[a-zA-Z][^>]*>|\[/?INST\]|<\|", "markup or prompt delimiters"),
]
_BAD = [(re.compile(p), why) for p, why in _BAD]


def canon(obj):
    """İmzalanan kanonik bayt dizisi."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def tip_norm(text):
    return re.sub(r"[^a-z0-9]+", " ", str(text).lower()).strip()


def tip_id(text):
    return hashlib.sha256(tip_norm(text).encode("utf-8")).hexdigest()[:12]


def check_tip(cat, tip, extra=()):
    """(ok, neden). Kişisel veri, sır, komut enjeksiyonu ve yönerge benzeri metni REDDEDER (silmez)."""
    if cat not in CATS:
        return False, "unknown category"
    if not isinstance(tip, str):
        return False, "tip is not text"
    t = tip.strip()
    if len(t) < 15:
        return False, "too short"
    if len(t) > MAX_TIP:
        return False, "too long"
    if _INVISIBLE.search(t) or "\n" in t or "\r" in t:
        return False, "control or invisible characters"
    for rx, why in _BAD:
        if rx.search(t):
            return False, why
    low = t.lower()
    for x in extra:
        x = str(x or "").strip().lower()
        if len(x) >= 3 and x in low:
            return False, "contains a local identifier"
    return True, ""
