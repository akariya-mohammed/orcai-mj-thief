"""Print the canonical SHA-256 of config/game.json (the constitution lock)."""
import hashlib
import json

raw = json.loads(open("config/game.json", encoding="utf-8").read())
canonical = json.dumps(raw, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False).encode("utf-8")
print(hashlib.sha256(canonical).hexdigest())
