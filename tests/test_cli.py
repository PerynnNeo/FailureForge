import json

import pytest

from failureforge import cli
from failureforge.contracts import CampaignSpec


@pytest.fixture
def verified_source(monkeypatch):
    source = {"backend": "synthetic", "case_id": "case_source",
              "spec": CampaignSpec(backend="synthetic", candidate_count=8).model_dump(mode="json"),
              "case": {"scene_change": {"main_camera_dx_m": 0.04, "light_scale": 0.7}, "failure_state_ids": [0, 1]}}
    # Archive format/integrity is covered by artifact tests; exercise the real
    # import, queue, CLI and execution boundary with an already verified record.
    monkeypatch.setattr(cli, "inspect_bundle", lambda path: source)
    return source


def test_imported_bundle_executes_exactly_one_fresh_pair(tmp_path, verified_source, capsys):
    cli.main(["--data-dir", str(tmp_path), "rerun-bundle", "verified.zip", "--backend", "synthetic"])
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "succeeded"
    store, _ = cli.services(tmp_path)
    campaign = store.get_campaign(result["campaign_id"])
    assert campaign["budget"]["completed"] == 2
    assert campaign["budget"]["limits"]["max_attempts"] == 2
    assert {e["condition"] for e in campaign["episodes"]} == {"reference", "changed"}
    assert {e["phase"] for e in campaign["episodes"]} == {"rerun"}


def test_imported_bundle_does_not_claim_existing_work(tmp_path, verified_source):
    store, _ = cli.services(tmp_path)
    existing = store.create_campaign(verified_source["spec"], "existing-work")
    with pytest.raises(SystemExit) as error:
        cli.main(["--data-dir", str(tmp_path), "rerun-bundle", "verified.zip", "--backend", "synthetic"])
    assert error.value.code == 1
    assert store.get_job(existing["job_id"])["status"] == "queued"
    assert len(store.list_campaigns()) == 1


def test_unclaimed_import_is_not_reported_as_success(tmp_path, verified_source, monkeypatch, capsys):
    class WorkerAlreadyRunningElsewhere:
        runner = object()
        last_error = None

        def run_once(self, target_job_id=None):
            assert target_job_id is not None
            return False

    monkeypatch.setattr(cli, "make_worker", lambda *args: WorkerAlreadyRunningElsewhere())
    with pytest.raises(SystemExit) as error:
        cli.main(["--data-dir", str(tmp_path), "rerun-bundle", "verified.zip", "--backend", "synthetic"])
    assert error.value.code == 1
    output = capsys.readouterr()
    assert json.loads(output.out)["status"] == "queued"
    assert "is queued" in output.err
