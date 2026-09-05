"""The benchmark harness itself: fairness, honesty about failures, provenance."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.engines.base import OCREngine
from app.models import Block
from scripts import ocr_benchmark
from scripts.make_benchmark_dataset import PAGES, build


class PerfectEngine(OCREngine):
    """Reads the ground truth exactly. Its CER must be 0."""

    name = "perfect"

    def __init__(self, truths: dict[str, str], images: dict[str, str]) -> None:
        self.truths, self.images = truths, images

    def version(self):
        return "1.0"

    def process_image(self, image_path):
        page_id = Path(image_path).stem
        return [Block(type="text", bbox=[0, 0, 1, 1], reading_order=0,
                      text=self.truths[page_id])]


class BrokenEngine(OCREngine):
    name = "broken"

    def version(self):
        return "0"

    def process_image(self, image_path):
        raise RuntimeError("engine exploded")


def test_dataset_covers_every_requested_page_type(tmp_path):
    manifest = build(tmp_path / "ds", dpi=100)
    ids = {page["id"] for page in manifest["pages"]}
    assert ids == {p[0] for p in PAGES}
    assert len(ids) == 8
    for page in manifest["pages"]:
        truth = (tmp_path / "ds" / page["ground_truth"]).read_text(encoding="utf-8")
        assert truth.strip(), f"{page['id']} has no ground truth"


def test_dataset_is_reproducible(tmp_path):
    a = build(tmp_path / "a", dpi=100)
    b = build(tmp_path / "b", dpi=100)
    for pa, pb in zip(a["pages"], b["pages"]):
        assert (tmp_path / "a" / pa["ground_truth"]).read_bytes() == \
               (tmp_path / "b" / pb["ground_truth"]).read_bytes()


def _truths(dataset_dir: Path) -> dict[str, str]:
    manifest = json.loads((dataset_dir / "manifest.json").read_text(encoding="utf-8"))
    return {p["id"]: (dataset_dir / p["ground_truth"]).read_text(encoding="utf-8").strip()
            for p in manifest["pages"]}


def test_a_perfect_engine_scores_zero_error(tmp_path, monkeypatch):
    dataset = tmp_path / "ds"
    build(dataset, dpi=72)
    truths = _truths(dataset)

    monkeypatch.setattr(ocr_benchmark, "make_engine",
                        lambda name: (PerfectEngine(truths, {}), None))
    results = ocr_benchmark.run(engines=("perfect",), dpi=72,
                                out_dir=tmp_path / "out", dataset_dir=dataset)
    engine = results["engines"]["perfect"]
    assert engine["cer_strict"] == 0.0
    assert engine["wer_normalized"] == 0.0
    assert engine["successful_pages"] == 8


def test_a_broken_engine_is_recorded_not_hidden(tmp_path, monkeypatch):
    dataset = tmp_path / "ds"
    build(dataset, dpi=72)
    monkeypatch.setattr(ocr_benchmark, "make_engine",
                        lambda name: (BrokenEngine(), None))
    results = ocr_benchmark.run(engines=("broken",), dpi=72,
                                out_dir=tmp_path / "out", dataset_dir=dataset)
    engine = results["engines"]["broken"]
    assert engine["successful_pages"] == 0
    assert len(engine["failed_pages"]) == 8
    assert "engine exploded" in engine["pages"][0]["error"]
    assert engine["cer_normalized"] is None       # no fabricated score


def test_an_unavailable_engine_reports_its_reason(tmp_path, monkeypatch):
    dataset = tmp_path / "ds"
    build(dataset, dpi=72)
    monkeypatch.setattr(ocr_benchmark, "make_engine",
                        lambda name: (None, "models are unreachable"))
    results = ocr_benchmark.run(engines=("surya",), dpi=72,
                                out_dir=tmp_path / "out", dataset_dir=dataset)
    assert results["engines"]["surya"] == {
        "available": False, "reason": "models are unreachable"}
    report = (tmp_path / "out" / "report.md").read_text(encoding="utf-8")
    assert "models are unreachable" in report


def test_every_engine_reads_the_identical_image(tmp_path, monkeypatch):
    """Fairness rule §4: one render per page, shared by all engines."""
    dataset = tmp_path / "ds"
    build(dataset, dpi=72)
    truths = _truths(dataset)
    seen: list[str] = []

    class Watcher(PerfectEngine):
        def process_image(self, image_path):
            seen.append(str(image_path))
            return super().process_image(image_path)

    monkeypatch.setattr(ocr_benchmark, "make_engine",
                        lambda name: (Watcher(truths, {}), None))
    ocr_benchmark.run(engines=("a", "b"), dpi=72,
                      out_dir=tmp_path / "out", dataset_dir=dataset)
    assert len(seen) == 16
    assert seen[:8] == seen[8:]                   # byte-identical paths


def test_raw_and_markdown_are_scored_separately(tmp_path, monkeypatch):
    """§7: engine quality is measured before rendering, not after."""
    dataset = tmp_path / "ds"
    build(dataset, dpi=72)
    truths = _truths(dataset)
    monkeypatch.setattr(ocr_benchmark, "make_engine",
                        lambda name: (PerfectEngine(truths, {}), None))
    results = ocr_benchmark.run(engines=("perfect",), dpi=72,
                                out_dir=tmp_path / "out", dataset_dir=dataset)
    page = results["engines"]["perfect"]["pages"][0]
    assert page["raw"]["normalized"]["cer"] == 0.0
    # Markdown adds a heading line, so its CER is necessarily worse than raw.
    assert page["markdown"]["normalized"]["cer"] > page["raw"]["normalized"]["cer"]


def test_benchmark_writes_json_and_report(tmp_path, monkeypatch):
    dataset = tmp_path / "ds"
    build(dataset, dpi=72)
    truths = _truths(dataset)
    monkeypatch.setattr(ocr_benchmark, "make_engine",
                        lambda name: (PerfectEngine(truths, {}), None))
    out = tmp_path / "out"
    ocr_benchmark.run(engines=("perfect",), dpi=72, out_dir=out, dataset_dir=dataset)
    data = json.loads((out / "benchmark.json").read_text(encoding="utf-8"))
    assert data["environment"]["python"]
    assert data["dataset"]["page_count"] == 8
    assert (out / "report.md").read_text(encoding="utf-8").startswith("# مقارنة")


def test_surya_engine_reports_unavailability_without_crashing():
    """The adapter must never raise on import or on availability checks."""
    from app.engines.surya_engine import SuryaEngine, availability

    state = availability()
    assert set(state) == {"installed", "version", "usable", "reason"}
    assert SuryaEngine().name == "surya"          # constructing it loads nothing
