"""复核已请求的文档抽取，不重复调用模型；补齐最终来源/待审证据。"""

import json
import time
from pathlib import Path

import httpx


def main():
    path = Path("artifacts/alpha_handoff/live_workflow.json")
    report = json.loads(path.read_text(encoding="utf-8"))
    credentials = json.loads(
        Path("data/alpha-demo/local-credentials.json").read_text(encoding="utf-8")
    )
    entry = next(s for s in report["steps"] if s["kind"] == "document_extract_requested")
    run_id = entry["result"]["workflow_run_id"]
    with httpx.Client(base_url="http://127.0.0.1:18765", timeout=20, trust_env=False) as client:
        response = client.post(
            "/api/v1/auth/login", json={"login_name": "demo1", "password": credentials["password"]}
        )
        response.raise_for_status()
        client.headers["Authorization"] = "Bearer " + response.json()["access_token"]
        prefix = "/api/v1/projects/1"
        for _ in range(90):
            response = client.get(prefix + f"/workflow-runs/{run_id}")
            response.raise_for_status()
            run = response.json()
            if run["status"] in {"succeeded", "failed"}:
                break
            time.sleep(1)
        suggestions = client.get(prefix + "/suggestions", params={"status": "pending"}).json()[
            "items"
        ]
        linked = [s for s in suggestions if s["run_id"] == run_id]
        report["steps"].append(
            {"kind": "document_extract_verified", "run": run, "pending_suggestions": linked}
        )
        report["status"] = "succeeded" if run["status"] == "succeeded" and linked else "failed"
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        assert report["status"] == "succeeded", "文档抽取未成功或没有待审建议"
        assert any(ref["block_ids"] for s in linked for ref in s["source_refs"])
        print("document extraction verified: pending suggestions with source anchors", len(linked))


if __name__ == "__main__":
    main()
