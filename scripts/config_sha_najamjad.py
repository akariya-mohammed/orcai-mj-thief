"""Print the canonical SHA-256 of config/game.najamjad.json AND the 14-key
signed-terms digest (NajAmjad §1) re-derived through our own loader."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from police_thief.interop import najamjad  # noqa: E402
from police_thief.interop.refcrypto import digest  # noqa: E402
from police_thief.interop.terms import build_terms  # noqa: E402
from police_thief.shared.config import Config  # noqa: E402

cfg = Config.load(shared_path="config/game.najamjad.json",
                  private_path="config/najamjad/police.toml")
print(digest(cfg.shared))
print(najamjad.terms_sha256(build_terms(cfg, 6)))
