import pytest
from odoo_migrator.core.planner import build_plan


def test_multi_hop_plan():
    plan = build_plan(15, 18)
    assert plan.path_label == "15 → 16 → 17 → 18"
    assert [s.key for s in plan.steps] == ["15_to_16", "16_to_17", "17_to_18"]


def test_target_must_be_higher():
    with pytest.raises(ValueError):
        build_plan(17, 17)
