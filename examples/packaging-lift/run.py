"""Create or reopen the local reference project and run its declared environment matrix."""
import argparse
import json
import os
import time

from failureforge.project_ci import Api


PROJECT = {
    "name": "Packaging lift · tray mass and head force",
    "entry_stage": "simulation",
    "analysis_type": "robot_behavior",
    "robot_source": "supported",
    "robot_template": "packaging_lift_v1",
    "goal": "Raise a secured tray to the packing station and hold position while a head applies downward force.",
    "success_criteria": "Reach 150 mm within 10 mm at 1 s and stay within 10 mm for the full next second.",
    "notes": "A one-axis simulation of tray positioning. The controller compensates for the empty carriage. "
             "Payloads and head forces are illustrative operating conditions.",
    "test_plans": [{
        "name": "Tray positioning under load",
        "objective": "Compare the same lift and controller across nine combinations of payload and pressing force.",
        "variation": "Secure 0, 0.25 or 0.50 kg to the carriage. Apply 0, 1 or 2 N downward during the dwell.",
        "success_criteria": "Arrival error and maximum absolute error throughout the hold are each at most 10 mm.",
    }],
}

MATRIX = {
    "label": "Tray positioning under load",
    "adapter": "packaging_lift",
    "payload_kg": [0.0, 0.25, 0.5],
    "head_force_n": [0.0, 1.0, 2.0],
    "reference": {"payload_kg": 0.0, "head_force_n": 0.0},
}


def run(origin):
    api = Api(origin, os.environ.get("FAILUREFORGE_API_TOKEN"))
    created = api.request("POST", "/api/projects", data=PROJECT, key="packaging-lift-example-v1", timeout=15)
    path = "/api/projects/" + created["id"]
    project = api.request("GET", path, timeout=15)
    if project["robot_template"] != PROJECT["robot_template"] or project["analysis_type"] != "robot_behavior":
        raise ValueError("The example project has changed its model or analysis type. Choose the lift reference to run this matrix.")
    revision = project["revision"]
    matrix_path = path + "/environment-matrices"
    matrix = api.request("POST", matrix_path, data={**MATRIX, "expected_revision": revision},
                         key=f"packaging-lift-conditions-v1-rev-{revision}", timeout=30)
    deadline = time.monotonic() + 180
    while matrix["status"] == "running":
        if time.monotonic() >= deadline:
            raise TimeoutError(f"Matrix {matrix['suite_id']} is still running. Repeat the command to reconnect.")
        time.sleep(0.5)
        matrix = api.request("GET", matrix_path + "/" + matrix["suite_id"], timeout=15)
    if matrix["status"] != "completed" or len(matrix["cells"]) != 9 or any(c["passed"] is None for c in matrix["cells"]):
        raise RuntimeError(f"Matrix {matrix['suite_id']} has incomplete evidence: {matrix['counts']}")
    return {"project_id": project["id"], "project_url": f"{api.origin}/#/projects/{project['id']}/analysis", **matrix}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    print(json.dumps(run(args.api_url), indent=2, allow_nan=False))
