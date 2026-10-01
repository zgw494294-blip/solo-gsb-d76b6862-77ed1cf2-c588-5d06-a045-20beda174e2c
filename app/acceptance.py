"""步道坡线规划台 —— 施工验收复核。

对一份已经计算完成、且与当前地面（及净宽）一致的**冻结方案**做施工
验收复核：录入与测点等数量的实测标高与 0～20 整数厘米容差，后端只
逐项核对实测与冻结方案的偏差，**不重新求优、不修改方案**。

校验分两层
----------
1. 冻结方案本身（随请求一并提交的 ``ground`` 与 ``plan``）：
   长度一致（3～16 点）、地面与方案标高均为 0～200 整数厘米、
   方案首尾分别等于地面首尾、相邻高差 ≤ 8、任意连续 5 段至少 1 段
   水平。规则全部复用 :mod:`app.planner` 的唯一份实现
   （:func:`step_rule` 等），与规划、可锁定分析同源。方案不合法属于
   请求本身非法（冻结数据与当前地面/方案不一致），抛
   :class:`~app.planner.PlanError`，由接口返回 ``422``。

2. 实测与容差：数量与方案一致、实测标高为 0～200 整数厘米、
   容差为 0～20 整数厘米。非法同样抛 :class:`~app.planner.PlanError`；
   合法时逐点核对，任何违规都以 ``200`` 且 ``passed=false`` 返回
   （这是复核结论，不是请求错误）。

复核结论
--------
- ``deviations``：逐点偏差（实测 − 方案）；
- ``tolerance_violations``：偏差绝对值超过该点容差的点；
- ``steep_segments``：实测相邻高差绝对值超过 8 厘米的段；
- ``no_horizontal_windows``：实测任意连续 5 段中无 1 段水平的窗口；
- ``endpoint_mismatches``：实测首/尾不等于方案首/尾的点。

以上四类违规均为空时 ``passed=true``，全部无违规才通过。
"""

from __future__ import annotations

from typing import Any, Dict, List

from .planner import (
    H_MAX,
    H_MIN,
    N_MAX,
    N_MIN,
    WINDOW,
    INITIAL_MASK,
    MAX_GRADE,
    PlanError,
    _validate,
    step_rule,
)

TOL_MIN = 0
TOL_MAX = 20          # 容差允许 0～20 整数厘米


def _validate_heights(values: Any, label: str) -> List[int]:
    """校验标高数组：必须为列表、长度 3～16、元素为 0～200 整数厘米。"""
    if not isinstance(values, list):
        raise PlanError(f"{label}必须是数组。")
    if not (N_MIN <= len(values) <= N_MAX):
        raise PlanError(
            f"{label}数量必须在 {N_MIN}～{N_MAX} 个之间（当前 {len(values)} 个）。"
        )
    heights: List[int] = []
    for i, v in enumerate(values):
        if isinstance(v, bool) or not isinstance(v, int):
            raise PlanError(f"{label}第 {i + 1} 个标高必须是整数厘米。")
        if not (H_MIN <= v <= H_MAX):
            raise PlanError(
                f"{label}第 {i + 1} 个标高 {v} 超出范围"
                f"（{H_MIN}～{H_MAX} 厘米）。"
            )
        heights.append(v)
    return heights


def _validate_frozen_plan(ground: List[int], plan: List[int]) -> None:
    """核对冻结方案与随请求提交的地面：长度、首尾、坡度与水平段约束。

    长度与值域先经 :func:`_validate_heights`；此处逐段走 planner 的
    :func:`step_rule`（唯一的合法转移判定），因此“方案是否可行”与
    ``/api/plan`` 用的是同一套语义，不会出现口径分歧。
    """
    _validate(ground)
    p = _validate_heights(plan, "冻结方案")
    if len(p) != len(ground):
        raise PlanError(
            f"冻结方案长度（{len(p)} 个）必须与地面标高数量"
            f"（{len(ground)} 个）一致。"
        )
    if p[0] != ground[0]:
        raise PlanError(
            f"冻结方案首点标高 {p[0]} 必须等于原地面首点标高 {ground[0]}。"
        )
    if p[-1] != ground[-1]:
        raise PlanError(
            f"冻结方案尾点标高 {p[-1]} 必须等于原地面尾点标高 {ground[-1]}。"
        )

    mask = INITIAL_MASK
    for seg in range(len(p) - 1):
        mask = step_rule(mask, p[seg], p[seg + 1], seg)
        if mask is None:
            if abs(p[seg + 1] - p[seg]) > MAX_GRADE:
                raise PlanError(
                    f"冻结方案第 {seg + 1} 段高差 {p[seg + 1] - p[seg]:+d} 厘米，"
                    f"相邻高差绝对值不得超过 {MAX_GRADE} 厘米。"
                )
            raise PlanError(
                f"冻结方案第 {seg - WINDOW + 2}～{seg + 1} 段连续 {WINDOW} 段"
                "均无水平段，不满足水平段约束。"
            )

def _validate_measurements(
    plan: List[int], measured: Any, tolerance: Any
) -> tuple[List[int], int]:
    """校验实测标高数组与统一容差。"""
    m = _validate_heights(measured, "实测")
    if len(m) != len(plan):
        raise PlanError(
            f"实测标高数量（{len(m)} 个）必须与冻结方案数量"
            f"（{len(plan)} 个）一致。"
        )
    if isinstance(tolerance, bool) or not isinstance(tolerance, int):
        raise PlanError("容差必须是 0～20 的整数厘米。")
    if not (TOL_MIN <= tolerance <= TOL_MAX):
        raise PlanError(
            f"容差必须在 {TOL_MIN}～{TOL_MAX} 整数厘米之间"
            f"（当前 {tolerance} 厘米）。"
        )
    return m, tolerance


def acceptance_review(
    ground: Any, plan: Any, measured: Any, tolerance: Any
) -> Dict[str, Any]:
    """施工验收复核：只核对实测与冻结方案，不对实测重新求优。

    可行（通过或不通过）时返回::

        {
          "passed": bool,
          "ground": [...], "plan": [...], "measured": [...],
          "tolerance": int,
          "deviations": [{"index", "plan", "measured", "deviation"}],
          "tolerance_violations": [{"index", "deviation", "limit"}],
          "steep_segments": [{"index", "from", "to", "delta"}],
          "no_horizontal_windows": [{"start_segment", "end_segment",
                                     "segment_indices": [...]}],
          "endpoint_mismatches": [{"index", "plan", "measured"}],
        }

    非法输入（含冻结方案不合法）抛 :class:`~app.planner.PlanError`。
    """
    _validate_frozen_plan(ground, plan)
    m, tol = _validate_measurements(plan, measured, tolerance)
    n = len(plan)

    deviations = [
        {"index": i + 1, "plan": plan[i], "measured": m[i],
         "deviation": m[i] - plan[i]}
        for i in range(n)
    ]
    tolerance_violations = [
        {"index": d["index"], "deviation": d["deviation"], "limit": tol}
        for d in deviations
        if abs(d["deviation"]) > tol
    ]

    steep_segments = []
    horizontal: List[bool] = []
    for i in range(n - 1):
        delta = m[i + 1] - m[i]
        horizontal.append(delta == 0)
        if abs(delta) > MAX_GRADE:
            steep_segments.append(
                {"index": i + 1, "from": i + 1, "to": i + 2, "delta": delta}
            )

    # 起点之前的 WINDOW-1 个虚拟段视为水平，与 planner.INITIAL_MASK 同义，
    # 不足 5 段时窗口约束不触发。padded 下标 k >= WINDOW-1 对应第 k-3 段。
    padded = [True] * (WINDOW - 1) + horizontal
    no_horizontal_windows = []
    for start in range(WINDOW - 1, len(padded) - WINDOW + 1):
        window = padded[start:start + WINDOW]
        if not any(window):
            first_seg = start - WINDOW + 2
            seg_indices = list(range(first_seg, first_seg + WINDOW))
            no_horizontal_windows.append({
                "start_segment": seg_indices[0],
                "end_segment": seg_indices[-1],
                "segment_indices": seg_indices,
            })

    endpoint_mismatches = []
    for idx in (0, n - 1):
        if m[idx] != plan[idx]:
            endpoint_mismatches.append(
                {"index": idx + 1, "plan": plan[idx], "measured": m[idx]}
            )

    passed = not (
        tolerance_violations
        or steep_segments
        or no_horizontal_windows
        or endpoint_mismatches
    )

    return {
        "passed": passed,
        "ground": list(ground),
        "plan": list(plan),
        "measured": m,
        "tolerance": tol,
        "deviations": deviations,
        "tolerance_violations": tolerance_violations,
        "steep_segments": steep_segments,
        "no_horizontal_windows": no_horizontal_windows,
        "endpoint_mismatches": endpoint_mismatches,
    }
