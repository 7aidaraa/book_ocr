"""Job records must outlive the process that created them."""

from __future__ import annotations

import pytest

from app.jobs import (
    CANCELLED, COMPLETED, DOWNLOADING, FAILED, PROCESSING, QUEUED, JobStore,
)


def test_job_survives_a_restart(tmp_path):
    store = JobStore(tmp_path)
    job = store.create("acquire", title="كتاب")
    store.update(job["id"], state=PROCESSING)
    store.set_progress(job["id"], PROCESSING, 12, 424)

    reopened = JobStore(tmp_path)          # a fresh process
    recovered = reopened.get(job["id"])

    assert recovered is not None
    assert recovered["title"] == "كتاب"
    assert recovered["progress"] == {"stage": PROCESSING, "current": 12, "total": 424}


def test_interrupted_job_is_reopened_as_failed_not_lost(tmp_path):
    store = JobStore(tmp_path)
    job = store.create("acquire", title="كتاب")
    store.update(job["id"], state=DOWNLOADING)

    recovered = JobStore(tmp_path).get(job["id"])

    assert recovered["state"] == FAILED
    assert recovered["interrupted"] is True
    assert "restart" in recovered["error"]


def test_completed_job_is_untouched_by_a_restart(tmp_path):
    store = JobStore(tmp_path)
    job = store.create("acquire")
    store.update(job["id"], state=COMPLETED, output_dir="data/output/x")

    recovered = JobStore(tmp_path).get(job["id"])
    assert recovered["state"] == COMPLETED
    assert recovered["interrupted"] is False


def test_all_six_states_are_accepted_and_others_refused(tmp_path):
    store = JobStore(tmp_path)
    job = store.create("acquire")
    for state in (QUEUED, DOWNLOADING, PROCESSING, COMPLETED, FAILED, CANCELLED):
        assert store.update(job["id"], state=state)["state"] == state
    with pytest.raises(ValueError, match="unknown state"):
        store.update(job["id"], state="nonsense")


def test_cancellation_is_observable_by_the_worker(tmp_path):
    store = JobStore(tmp_path)
    job = store.create("acquire")
    assert store.cancel_requested(job["id"]) is False
    store.request_cancel(job["id"])
    assert store.cancel_requested(job["id"]) is True
    assert store.mark_cancelled(job["id"])["state"] == CANCELLED


def test_cancel_does_nothing_to_a_finished_job(tmp_path):
    store = JobStore(tmp_path)
    job = store.create("acquire")
    store.update(job["id"], state=COMPLETED)
    store.request_cancel(job["id"])
    assert store.cancel_requested(job["id"]) is False


def test_delete_removes_the_file(tmp_path):
    store = JobStore(tmp_path)
    job = store.create("acquire")
    assert (tmp_path / f"{job['id']}.json").exists()
    store.delete(job["id"])
    assert not (tmp_path / f"{job['id']}.json").exists()
    assert store.get(job["id"]) is None


def test_corrupt_job_file_is_skipped_not_fatal(tmp_path):
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    store = JobStore(tmp_path)
    assert store.list() == []
