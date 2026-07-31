"""Task 7.3: the headless view-model — local truth only, banner from the phase machine."""
from police_thief.domain.belief import BeliefGrid
from police_thief.domain.board import Board
from police_thief.domain.brains import Role
from police_thief.domain.own_state import OwnGameState
from police_thief.gui.viewmodel import build_view, color_for
from police_thief.peer.runtime import PeerRuntime


class _T:
    def send_turn(self, m):
        return {}


def _rt(role=Role.POLICE):
    board = Board(7, barriers={(2, 2)})
    return PeerRuntime(role, None, _T(), OwnGameState((0, 0), board),
                       BeliefGrid(7), config={})


def test_view_is_local_truth_only():
    view = build_view(_rt(), step=3)
    assert view["own_pos"] == (0, 0)
    assert (2, 2) in view["barriers"]
    # Rules 8-9, structurally: the view CANNOT carry the opponent's position.
    assert not any("opponent" in k and "pos" in k for k in view)
    assert "opponent_pos" not in view


def test_belief_heatmap_is_normalized():
    rt = _rt()
    rt.belief.update_from_smell({(5, 5): 0.9})
    view = build_view(rt, step=1)
    cells = view["heat"]
    assert max(max(row) for row in cells) == 1.0          # argmax cell at full intensity
    assert cells[5][5] == 1.0


def test_banner_follows_phase_machine():
    rt = _rt()
    assert build_view(rt, 1)["banner"] == ("LOCKED", "gray")          # opponent's turn
    rt.phases.transition("COMPUTING_MOVE")
    assert build_view(rt, 1)["banner"] == ("YOUR TURN", "green")
    rt.phases.transition("TECHNICAL_LOSS")
    assert build_view(rt, 1)["banner"] == ("TECHNICAL LOSS", "red")


def test_color_scale_is_monotonic_red():
    lo, mid, hi = color_for(0.0), color_for(0.5), color_for(1.0)
    assert lo == "#ffffff" and hi == "#cc0000"
    # green/blue channels fall monotonically as intensity rises (ff -> ~80 -> 00)
    assert int(lo[3:5], 16) > int(mid[3:5], 16) > int(hi[3:5], 16) == 0
