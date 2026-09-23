"""MOCK: candidate files isolate worker selection before any expensive refit."""

import hashlib
import json

import numpy as np
import pandas as pd
import pytest

from scripts import train_gfs


@pytest.fixture
def search(tmp_path, monkeypatch):
    monkeypatch.setattr(train_gfs, "SEARCH", tmp_path)
    monkeypatch.setattr(train_gfs, "configurations", lambda worker: [{"family": "tree"}])
    valid = tmp_path / "validation.parquet"
    pd.DataFrame({"power": [0.1, 0.7]}).to_parquet(valid)
    protocol = {
        "train_sha256": "unused",
        "selection_months": ["2025-11", "2025-12"],
        "validation_sha256": hashlib.sha256(valid.read_bytes()).hexdigest(),
    }
    (tmp_path / "protocol.json").write_text(json.dumps(protocol))
    directory = tmp_path / "cpu"
    directory.mkdir()
    (directory / "cpu_000.json").write_text(
        json.dumps(
            {
                "name": "cpu_000",
                "config": {"family": "tree"},
                "metrics": {"mae": 0},
                **protocol,
            }
        )
    )
    (directory / "cpu_000.joblib").write_bytes(b"MOCK: existence check only")
    np.save(directory / "cpu_000.predictions.npy", np.array([0.1, 0.7]))
    return tmp_path


def test_one_worker_can_finalize(search, monkeypatch):
    def stop_before_refit():
        raise RuntimeError("selection completed")

    monkeypatch.setattr(train_gfs, "packed_data", stop_before_refit)
    with pytest.raises(RuntimeError, match="selection completed"):
        train_gfs.finalize(["cpu"])
    selection = json.loads((search / "selection.json").read_text())
    assert selection["workers"] == ["cpu"]
    assert selection["candidate_count"] == 1


def test_original_default_still_requires_all_workers(search):
    with pytest.raises(ValueError, match="local-gpu 0/1"):
        train_gfs.finalize()


def test_missing_prediction_is_incomplete(search):
    (search / "cpu/cpu_000.predictions.npy").unlink()
    with pytest.raises(ValueError, match="cpu 0/1"):
        train_gfs.finalize(["cpu"])


def test_changed_validation_is_rejected(search):
    (search / "validation.parquet").write_bytes(b"changed")
    with pytest.raises(ValueError, match="Validation pack changed"):
        train_gfs.finalize(["cpu"])
