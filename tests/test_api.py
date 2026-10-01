"""FastAPI 接口测试。"""

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_plan_ok():
    resp = client.post(
        "/api/plan",
        json={"ground": [100, 107, 114, 119, 124, 130], "width": 1.5},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["feasible"] is True
    assert data["plan"][0] == 100
    assert data["plan"][-1] == 130
    assert data["total_adjustment"] >= 0
    assert "segments" in data and len(data["segments"]) == 5
    ew = data["earthwork"]
    assert ew["width"] == 1.5
    assert len(ew["segments"]) == 5
    assert len(ew["flows"]) == 5
    assert ew["flows"][0]["from"] == "start"
    assert ew["flows"][0]["to"] == "midpoint:1"
    assert ew["flows"][0]["distance"] == 0.5
    assert all(f["distance"] == 1 for f in ew["flows"][1:])
    assert ew["transport_work"] >= 0


def test_invalid_count():
    resp = client.post("/api/plan", json={"ground": [1, 2], "width": 1.5})
    assert resp.status_code == 422
    data = resp.json()
    assert data["feasible"] is False
    assert "3" in data["reason"]


def test_invalid_range():
    resp = client.post("/api/plan", json={"ground": [0, 999, 0], "width": 1.5})
    assert resp.status_code == 422
    assert "超出范围" in resp.json()["reason"]


def test_reject_float_and_string():
    for bad in ([0, 1.5, 0], [0, "8", 0]):
        resp = client.post("/api/plan", json={"ground": bad, "width": 1.5})
        assert resp.status_code == 422
        assert "整数" in resp.json()["reason"]


def test_missing_ground():
    resp = client.post("/api/plan", json={"points": [1, 2, 3], "width": 1.5})
    assert resp.status_code == 400
    assert "ground" in resp.json()["reason"]


def test_missing_width():
    resp = client.post("/api/plan", json={"ground": [1, 2, 3]})
    assert resp.status_code == 400
    assert "width" in resp.json()["reason"]


def test_body_not_json():
    resp = client.post("/api/plan", content="not-json", headers={"Content-Type": "text/plain"})
    assert resp.status_code == 400


@pytest.mark.parametrize(
    "width",
    [0.4, 10.1, 0, -1, 1.555, "1.5", True, None],
)
def test_invalid_width(width):
    resp = client.post(
        "/api/plan", json={"ground": [100, 100, 100], "width": width}
    )
    assert resp.status_code == 422
    assert "净宽" in resp.json()["reason"]


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"])
def test_invalid_width_nonfinite(token):
    resp = client.post(
        "/api/plan",
        content='{"ground":[100,100,100],"width":' + token + "}",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 422
    assert "净宽" in resp.json()["reason"]


def test_width_boundary_values():
    for width in (0.5, 10, 1.25, 2):
        resp = client.post(
            "/api/plan",
            json={"ground": [100, 107, 114, 119, 124, 130], "width": width},
        )
        assert resp.status_code == 200
        assert resp.json()["feasible"] is True
        assert resp.json()["width"] == float(width)


def test_infeasible_is_200():
    # 合法输入但无解：200 + feasible=false，且不附土方核算
    resp = client.post(
        "/api/plan", json={"ground": [0, 8, 16, 24, 32, 40], "width": 1.5}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["feasible"] is False
    assert "无解" in data["reason"]
    assert "earthwork" not in data


def test_index_page():
    resp = client.get("/")
    assert resp.status_code == 200
    assert "步道坡线规划台".encode() in resp.content
    assert "步道净宽".encode() in resp.content


# ---------- /api/lockable：测点可锁定标高分析 ----------

def test_lockable_ok():
    resp = client.post(
        "/api/lockable", json={"ground": [100, 107, 114, 119, 124, 130]}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["feasible"] is True
    assert data["ground"] == [100, 107, 114, 119, 124, 130]
    points = data["points"]
    assert len(points) == 6
    assert [p["index"] for p in points] == [1, 2, 3, 4, 5, 6]
    # 首尾固定，只能锁定为地面标高
    assert points[0]["intervals"] == [[100, 100]]
    assert points[-1]["intervals"] == [[130, 130]]
    # 第 2 点精确集合 {100, 106, 107, 108}：两个区间，空档不填平
    assert points[1]["intervals"] == [[100, 100], [106, 108]]
    for p in points:
        iv = p["intervals"]
        assert all(lo <= hi for lo, hi in iv)
        for k in range(1, len(iv)):
            assert iv[k][0] >= iv[k - 1][1] + 2   # 升序且互不相邻


def test_lockable_only_needs_ground():
    # 只接收地面标高：不需要 width 等其它字段
    resp = client.post("/api/lockable", json={"ground": [0, 8, 0]})
    assert resp.status_code == 200
    data = resp.json()
    assert data["feasible"] is True
    assert [p["intervals"] for p in data["points"]] == [
        [[0, 0]], [[0, 8]], [[0, 0]],
    ]


def test_lockable_infeasible_is_200():
    resp = client.post("/api/lockable", json={"ground": [0, 8, 16, 24, 32, 40]})
    assert resp.status_code == 200
    data = resp.json()
    assert data["feasible"] is False
    assert "无解" in data["reason"]
    assert "points" not in data


@pytest.mark.parametrize(
    "ground",
    [[1, 2], [1] * 17, [0, -1, 0], [0, 201, 0], [0, 1.5, 0], [0, "8", 0]],
)
def test_lockable_invalid_ground(ground):
    resp = client.post("/api/lockable", json={"ground": ground})
    assert resp.status_code == 422
    assert resp.json()["feasible"] is False
    assert resp.json()["reason"]


def test_lockable_missing_ground():
    resp = client.post("/api/lockable", json={"points": [1, 2, 3]})
    assert resp.status_code == 400
    assert "ground" in resp.json()["reason"]


def test_lockable_body_not_json():
    resp = client.post(
        "/api/lockable", content="not-json",
        headers={"Content-Type": "text/plain"},
    )
    assert resp.status_code == 400


# ---------- /api/acceptance：施工验收复核 ----------

def test_acceptance_pass():
    resp = client.post(
        "/api/acceptance",
        json={
            "ground": [100, 100, 108, 108, 116, 116],
            "plan": [100, 100, 108, 108, 116, 116],
            "measured": [100, 102, 108, 109, 116, 116],
            "tolerance": 5,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["passed"] is True
    assert [d["deviation"] for d in data["deviations"]] == [0, 2, 0, 1, 0, 0]
    assert data["tolerance_violations"] == []
    assert data["steep_segments"] == []
    assert data["no_horizontal_windows"] == []
    assert data["endpoint_mismatches"] == []
    assert data["tolerance"] == 5


def test_acceptance_failure_is_200_not_422():
    # 实测违规是复核结论（200 + passed=false），不是请求错误
    resp = client.post(
        "/api/acceptance",
        json={
            "ground": [100, 100, 100],
            "plan": [100, 100, 100],
            "measured": [100, 130, 100],
            "tolerance": 5,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["passed"] is False
    assert data["tolerance_violations"] == [
        {"index": 2, "deviation": 30, "limit": 5}
    ]
    assert [(s["index"], s["delta"]) for s in data["steep_segments"]] == [
        (1, 30), (2, -30)
    ]


def test_acceptance_endpoint_mismatch():
    resp = client.post(
        "/api/acceptance",
        json={
            "ground": [100, 100, 100],
            "plan": [100, 100, 100],
            "measured": [101, 100, 100],
            "tolerance": 20,
        },
    )
    data = resp.json()
    assert resp.status_code == 200
    assert data["passed"] is False
    assert [e["index"] for e in data["endpoint_mismatches"]] == [1]


def test_acceptance_no_horizontal_window():
    resp = client.post(
        "/api/acceptance",
        json={
            "ground": [0, 0, 0, 0, 0, 0, 0],
            "plan": [0, 0, 0, 0, 0, 0, 0],
            "measured": [0, 1, 2, 3, 4, 5, 6],
            "tolerance": 20,
        },
    )
    data = resp.json()
    assert data["passed"] is False
    assert [w["segment_indices"] for w in data["no_horizontal_windows"]] == [
        [1, 2, 3, 4, 5], [2, 3, 4, 5, 6]
    ]


def test_acceptance_invalid_frozen_plan_is_422():
    # 冻结方案本身不合法（相邻高差 9 cm）→ 422，且不产生复核报告
    resp = client.post(
        "/api/acceptance",
        json={
            "ground": [100, 100, 109],
            "plan": [100, 100, 109],
            "measured": [100, 100, 109],
            "tolerance": 5,
        },
    )
    assert resp.status_code == 422
    assert resp.json()["feasible"] is False
    assert "高差" in resp.json()["reason"]


def test_acceptance_plan_length_mismatch_is_422():
    resp = client.post(
        "/api/acceptance",
        json={
            "ground": [100, 100, 100],
            "plan": [100, 100],
            "measured": [100, 100],
            "tolerance": 5,
        },
    )
    assert resp.status_code == 422


@pytest.mark.parametrize(
    "payload",
    [
        {"plan": [100, 100, 100], "measured": [100, 100, 100], "tolerance": 5},
        {"ground": [100, 100, 100], "measured": [100, 100, 100], "tolerance": 5},
        {"ground": [100, 100, 100], "plan": [100, 100, 100], "tolerance": 5},
        {"ground": [100, 100, 100], "plan": [100, 100, 100],
         "measured": [100, 100, 100]},
    ],
)
def test_acceptance_missing_fields_400(payload):
    resp = client.post("/api/acceptance", json=payload)
    assert resp.status_code == 400


def test_acceptance_body_not_json():
    resp = client.post(
        "/api/acceptance", content="not-json",
        headers={"Content-Type": "text/plain"},
    )
    assert resp.status_code == 400


@pytest.mark.parametrize("tol", [-1, 21, 1.5, "5", None, True])
def test_acceptance_invalid_tolerance_422(tol):
    resp = client.post(
        "/api/acceptance",
        json={
            "ground": [100, 100, 100],
            "plan": [100, 100, 100],
            "measured": [100, 100, 100],
            "tolerance": tol,
        },
    )
    assert resp.status_code == 422
    assert "容差" in resp.json()["reason"]


def test_acceptance_measured_invalid_422():
    resp = client.post(
        "/api/acceptance",
        json={
            "ground": [100, 100, 100],
            "plan": [100, 100, 100],
            "measured": [100, 201, 100],
            "tolerance": 5,
        },
    )
    assert resp.status_code == 422


def test_acceptance_against_live_plan():
    # 端到端：/api/plan 的输出可直接作为冻结方案送入复核
    ground = [100, 107, 114, 119, 124, 130]
    plan_resp = client.post("/api/plan", json={"ground": ground, "width": 1.5})
    plan = plan_resp.json()["plan"]
    resp = client.post(
        "/api/acceptance",
        json={"ground": ground, "plan": plan, "measured": plan, "tolerance": 0},
    )
    assert resp.status_code == 200
    assert resp.json()["passed"] is True
