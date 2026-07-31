"""Task 7.5: SVG artifact rendering — deterministic, dependency-free, README-embeddable."""
from police_thief.gui import docs_images
from police_thief.gui.render_svg import render_board_svg, render_progression, render_badge
from police_thief.gui.viewmodel import build_view
from tests.test_viewmodel import _rt  # reuse the runtime fixture


def _view():
    rt = _rt()
    rt.belief.update_from_smell({(5, 5): 0.9})
    return build_view(rt, step=4)


def test_board_svg_contains_grid_heat_and_status():
    svg = render_board_svg(_view(), title="POLICE — live view")
    assert svg.startswith("<svg") and svg.rstrip().endswith("</svg>")
    assert svg.count("<rect") >= 49 + 1                    # 7x7 cells + barrier overlay
    assert "#cc0000" in svg                                # argmax cell at full red
    assert "POLICE" in svg and "trust" in svg.lower()


def test_progression_composes_panels():
    svg = render_progression([_view(), _view(), _view()])
    assert svg.count("<g transform") == 3


def test_badge_renders_both_verdicts():
    ok = render_badge("Verified OK", {"steps_checked": 12})
    bad = render_badge("TAMPERED", {"step": 3, "layer": "record"})
    assert "Verified OK" in ok and "#1a7f37" in ok         # green
    assert "TAMPERED" in bad and "#cc0000" in bad          # red


def test_docs_images_end_to_end(tmp_path):
    written = docs_images.generate(out_dir=tmp_path, seed=1)
    names = {p.name for p in written}
    assert {"live_gui_frame.svg", "heatmap_progression.svg",
            "replay_verified.svg"} <= names
    for p in written:
        text = p.read_text(encoding="utf-8")
        assert text.startswith("<svg")
    # the replay badge must come from a REAL verification pass of a real log
    assert "Verified OK" in (tmp_path / "replay_verified.svg").read_text(encoding="utf-8")
