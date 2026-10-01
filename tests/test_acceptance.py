"""施工验收复核（app.acceptance）单元测试。"""

import pytest

from app.acceptance import acceptance_review
from app.planner import PlanError, plan_trail


def test_exact_measurements_pass_with_zero_tolerance():
    ground = [100, 107, 114, 119, 124, 130]
    plan = plan_trail(ground)["plan"]
    r = acceptance_review(ground, plan, plan, 0)
    assert r["passed"] is True
    assert [d["deviation"] for d in r["deviations"]] == [0] * 6
    assert r["tolerance_violations"] == []
    assert r["steep_segments"] == []
    assert r["no_horizontal_windows"] == []
    assert r["endpoint_mismatches"] == []


def test_deviations_are_measured_minus_plan():
    ground = [100, 100, 100]
    plan = [100, 100, 100]
    measured = [100, 96, 100]
    r = acceptance_review(ground, plan, measured, 20)
    assert [d["deviation"] for d in r["deviations"]] == [0, -4, 0]
    assert r["passed"] is True   # 最大实测高差 4 cm，不超限；首尾与方案一致


def test_tolerance_violation_boundaries():
    ground = [100, 100, 100]
    plan = [100, 100, 100]
    assert acceptance_review(ground, plan, [100, 105, 100], 5)["passed"] is True
    r = acceptance_review(ground, plan, [100, 106, 100], 5)
    assert r["passed"] is False
    assert r["tolerance_violations"] == [
        {"index": 2, "deviation": 6, "limit": 5}
    ]
    r = acceptance_review(ground, plan, [100, 94, 100], 5)
    assert r["tolerance_violations"] == [
        {"index": 2, "deviation": -6, "limit": 5}
    ]


def test_steep_segment_in_measured():
    ground = [100, 100, 100]
    plan = [100, 100, 100]
    r = acceptance_review(ground, plan, [100, 109, 100], 20)
    assert r["passed"] is False
    assert [(s["index"], s["delta"]) for s in r["steep_segments"]] == [
        (1, 9), (2, -9)
    ]
    # 8 cm itself is allowed
    r = acceptance_review(ground, plan, [100, 108, 100], 20)
    assert r["steep_segments"] == []
    assert r["passed"] is True


def test_no_horizontal_window_only_triggers_with_five_segments():
    # 3 点 2 段：窗口约束不触发，即使两段都不水平（高差 1 cm，首尾回到方案）
    r = acceptance_review([0, 0, 0], [0, 0, 0], [0, 1, 0], 20)
    assert r["no_horizontal_windows"] == []
    assert r["passed"] is True

    # 7 点 6 段全部非水平：窗口 1..5 与 2..6 均无水平段
    r = acceptance_review(
        [0, 0, 0, 0, 0, 0, 0], [0, 0, 0, 0, 0, 0, 0],
        [0, 1, 2, 3, 4, 5, 6], 20,
    )
    windows = r["no_horizontal_windows"]
    assert [w["segment_indices"] for w in windows] == [
        [1, 2, 3, 4, 5], [2, 3, 4, 5, 6]
    ]


def test_no_horizontal_window_absent_when_each_window_has_flat():
    # 实测每 5 段至少一个水平（第 5 段水平）；6 段序列 1,1,1,1,0,-4，
    # 首尾均回到方案值 0。
    measured = [0, 1, 2, 3, 4, 4, 0]
    plan = [0] * 7
    r = acceptance_review(plan, plan, measured, 20)
    assert r["no_horizontal_windows"] == []
    assert r["steep_segments"] == []
    assert r["passed"] is True


def test_endpoint_mismatch():
    r = acceptance_review(
        [100, 100, 100], [100, 100, 100], [101, 100, 99], 20
    )
    assert r["endpoint_mismatches"] == [
        {"index": 1, "plan": 100, "measured": 101},
        {"index": 3, "plan": 100, "measured": 99},
    ]
    assert r["passed"] is False


def test_endpoint_equal_but_inner_different_passes_if_otherwise_clean():
    r = acceptance_review(
        [100, 100, 100], [100, 100, 100], [100, 103, 100], 5
    )
    assert r["endpoint_mismatches"] == []
    assert r["passed"] is True


def test_review_does_not_reoptimize():
    # 实测并非相对当前地面的最优解（把中间点抬高），复核只对照冻结方案，
    # 不会重新求优；首尾与方案一致、偏差在容差内、结构合规即通过。
    ground = [100, 100, 100, 100, 100, 100]
    plan = [100, 100, 100, 100, 100, 100]
    measured = [100, 102, 102, 100, 100, 100]
    r = acceptance_review(ground, plan, measured, 3)
    assert r["passed"] is True
    assert r["plan"] == plan
    assert [d["deviation"] for d in r["deviations"]] == [0, 2, 2, 0, 0, 0]


# ---------- 冻结方案本身的校验（422 语义） ----------

def test_frozen_plan_length_mismatch():
    with pytest.raises(PlanError, match="数量"):
        acceptance_review([100, 100, 100], [100, 100], [100, 100], 5)


def test_frozen_plan_endpoint_must_match_ground():
    with pytest.raises(PlanError, match="首点"):
        acceptance_review([100, 100, 100], [99, 100, 100], [100, 100, 100], 5)
    with pytest.raises(PlanError, match="尾点"):
        acceptance_review([100, 100, 100], [100, 100, 99], [100, 100, 100], 5)


def test_frozen_plan_steep_segment_rejected():
    with pytest.raises(PlanError, match="高差"):
        acceptance_review(
            [100, 100, 109], [100, 100, 109], [100, 100, 109], 5
        )


def test_frozen_plan_without_horizontal_window_rejected():
    # 7 点、6 段方案全为 +1：首尾可固定为地面，但无水平段窗口
    plan = [0, 1, 2, 3, 4, 5, 6]
    with pytest.raises(PlanError, match="水平段"):
        acceptance_review([0, 0, 0, 0, 0, 0, 6], plan, plan, 5)


def test_frozen_plan_values_out_of_range():
    with pytest.raises(PlanError):
        acceptance_review([100, 100, 100], [100, 201, 100], [100, 100, 100], 5)


# ---------- 实测与容差校验（422 语义） ----------

def test_measured_length_mismatch():
    with pytest.raises(PlanError, match="实测"):
        acceptance_review(
            [100, 100, 100], [100, 100, 100], [100, 100], 5
        )


@pytest.mark.parametrize("bad", [
    [100, 100.5, 100], [100, "100", 100], [100, True, 100],
    [100, -1, 100], [100, 201, 100],
])
def test_measured_invalid_values(bad):
    with pytest.raises(PlanError):
        acceptance_review([100, 100, 100], [100, 100, 100], bad, 5)


@pytest.mark.parametrize("tol", [-1, 21, 5.0, "5", True, None])
def test_tolerance_invalid(tol):
    with pytest.raises(PlanError):
        acceptance_review(
            [100, 100, 100], [100, 100, 100], [100, 100, 100], tol
        )


def test_tolerance_boundary_values():
    for tol in (0, 20):
        r = acceptance_review(
            [100, 100, 100], [100, 100, 100], [100, 100, 100], tol
        )
        assert r["tolerance"] == tol
        assert r["passed"] is True


def test_echoes_inputs():
    ground = [100, 100, 108]
    plan = [100, 100, 108]
    measured = [100, 101, 108]
    r = acceptance_review(ground, plan, measured, 7)
    assert r["ground"] == ground
    assert r["plan"] == plan
    assert r["measured"] == measured
    assert r["tolerance"] == 7


def test_planner_output_always_reviewable():
    # 对求解器给出的任意可行方案，用方案本身作为实测必然通过。
    import random
    random.seed(42)
    for _ in range(40):
        n = random.randint(3, 16)
        ground = [random.randint(0, 200) for _ in range(n)]
        t = plan_trail(ground)
        if not t["feasible"]:
            continue
        r = acceptance_review(ground, t["plan"], t["plan"], 0)
        assert r["passed"] is True
        assert r["steep_segments"] == []
        assert r["no_horizontal_windows"] == []
        assert r["endpoint_mismatches"] == []
