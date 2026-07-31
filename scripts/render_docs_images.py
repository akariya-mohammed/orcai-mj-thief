"""Regenerate the README/submission SVGs from a real seeded match.

Run: uv run python scripts/render_docs_images.py
"""
from police_thief.gui.docs_images import generate

if __name__ == "__main__":
    for path in generate():
        print(f"wrote {path}")
