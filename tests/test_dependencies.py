from concurrent.futures import ThreadPoolExecutor

import pytest

from tests.conftest import new_task


def edge(a, b, **kwargs):
    return {
        "predecessor_task_id": a["id"],
        "successor_task_id": b["id"],
        "predecessor_required_progress": 100,
        "successor_gate": "start",
        **kwargs,
    }


def test_cycle_duplicate_and_start_gate(env):
    a, b, c = [new_task(env, title=name) for name in ("A", "B", "C")]
    url = env.prefix + "/dependencies"
    assert env.client.post(url, json=edge(a, b)).status_code == 201
    assert env.client.post(url, json=edge(b, c)).status_code == 201
    loop = env.client.post(url, json=edge(c, a))
    assert loop.status_code == 409 and loop.json()["error"]["code"] == "dependency_cycle"
    assert env.client.post(url, json=edge(a, b)).status_code == 409
    blocked = env.client.patch(
        env.prefix + f"/tasks/{b['id']}", json={"expected_version": 1, "status": "in_progress"}
    )
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "start_blocked"
    assert (
        env.client.patch(
            env.prefix + f"/tasks/{a['id']}",
            json={"expected_version": 1, "status": "done", "progress": 100},
        ).status_code
        == 200
    )
    assert (
        env.client.patch(
            env.prefix + f"/tasks/{b['id']}", json={"expected_version": 1, "status": "in_progress"}
        ).status_code
        == 200
    )
    assert env.client.delete(env.prefix + f"/tasks/{a['id']}?expected_version=2").status_code == 409


@pytest.mark.parametrize(
    "changes",
    [
        {"successor_gate": "progress"},
        {"successor_gate": "start", "successor_gate_progress": 20},
        {"successor_gate": "progress", "successor_gate_progress": 100},
        {"predecessor_required_progress": 0},
        {"predecessor_required_progress": 101},
    ],
)
def test_gate_validation(env, changes):
    a, b = new_task(env), new_task(env)
    assert (
        env.client.post(env.prefix + "/dependencies", json=edge(a, b, **changes)).status_code == 422
    )
    assert env.client.post(env.prefix + "/dependencies", json=edge(a, a)).status_code == 422


def test_concurrent_edges_cannot_form_cycle(env):
    a, b = new_task(env), new_task(env)

    def create(payload):
        return env.client.post(env.prefix + "/dependencies", json=payload).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(create, [edge(a, b), edge(b, a)]))
    assert sorted(statuses) == [201, 409]


def test_cancelled_predecessor_not_satisfied(env):
    a = new_task(env, status="cancelled", progress=100)
    b = new_task(env)
    assert env.client.post(env.prefix + "/dependencies", json=edge(a, b)).status_code == 201
    assert (
        env.client.patch(
            env.prefix + f"/tasks/{b['id']}",
            json={"expected_version": 1, "status": "done", "progress": 100},
        ).status_code
        == 409
    )
