"""6.2: the Step-0 declaration — hardware, model and code commit, sealed before turn 1."""
import pytest

from police_thief.domain.crypto import verify
from police_thief.peer.sealing import SEALING_SCHEME, step_zero_record
from police_thief.report.artifact_schemas import STEP0_PAYLOAD_FIELDS, STEP0_SPEC_FIELDS
from police_thief.shared import sysinfo


def _record():
    return step_zero_record(group_name="Orcai-MJ", model="template", sub_game_number=1)


def test_spec_probe_never_raises_and_fills_every_field():
    spec = sysinfo.hardware_spec()
    assert set(spec) == set(STEP0_SPEC_FIELDS)
    assert all(v not in ("", None) for v in spec.values())


def test_gpu_probe_degrades_instead_of_failing(monkeypatch):
    monkeypatch.setattr(sysinfo.shutil, "which", lambda _: None)
    assert sysinfo.gpu_info() == (sysinfo.UNKNOWN, sysinfo.UNKNOWN)


def test_step_zero_payload_matches_the_book_schema():
    payload = _record()["payload"]
    assert set(payload) == set(STEP0_PAYLOAD_FIELDS)
    assert payload["step"] == 0 and payload["type"] == "system_spec"
    assert set(payload["spec"]) == set(STEP0_SPEC_FIELDS)


def test_step_zero_declares_the_playing_commit():
    # Rule 53: the exact commit that played this game must be on the record.
    assert _record()["payload"]["code_version"]


def test_step_zero_is_sealed_and_verifiable():
    rec = _record()
    assert len(rec["commit"]) == 64 and rec["nonce"]
    assert verify(rec["state"], rec["move"], rec["intent"], rec["nonce"], rec["commit"])


def test_tampering_with_a_declared_spec_breaks_the_seal():
    rec = _record()
    rec["state"] = rec["state"].replace("template", "claude-opus-4-8")
    assert not verify(rec["state"], rec["move"], rec["intent"],
                      rec["nonce"], rec["commit"])


def test_scheme_is_declared_for_interop():
    assert SEALING_SCHEME == "canonical-json-v1"
