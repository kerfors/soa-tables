"""tools/dryrun.py: a brand-new protocol gets its extracted/ folder (B6); only staged studies with a
protocol folder in the collection are rehearsed (B26)."""

import importlib
import sys

import pytest

from soa_tables import config

sys.path.insert(0, str(config.REPO_ROOT / "tools"))


@pytest.fixture
def dryrun(tmp_path, monkeypatch):
    (tmp_path / "real" / "c" / "protocols" / "NEW").mkdir(parents=True)
    (tmp_path / "staging" / "NEW").mkdir(parents=True)
    (tmp_path / "staging" / "OTHER").mkdir()
    monkeypatch.setenv("SOA_TABLES_COLLECTIONS", str(tmp_path / "real"))
    monkeypatch.setenv("SOA_TABLES_STAGING", str(tmp_path / "staging"))
    monkeypatch.setenv("SOA_TABLES_SCRATCH", str(tmp_path / "scratch"))
    monkeypatch.setenv("SOA_TABLES_COLLECTION", "c")
    sys.modules.pop("dryrun", None)
    module = importlib.import_module("dryrun")
    yield module
    sys.modules.pop("dryrun", None)


def test_staged_study_outside_collection_is_skipped(dryrun, capsys):
    assert dryrun.select_studies([]) == ["NEW"]
    assert "OTHER: not in collection c — skipped" in capsys.readouterr().out


def test_named_study_outside_collection_is_refused(dryrun):
    with pytest.raises(SystemExit, match="not in collection c: OTHER"):
        dryrun.select_studies(["NEW", "OTHER"])


def test_new_protocol_gets_extracted_folder(dryrun, tmp_path):
    (tmp_path / "staging" / "NEW" / "NEW_Table_01_extraction.json").write_text("{}\n")
    assert dryrun.build_scratch(["NEW"]) == ["NEW/NEW_Table_01_extraction.json"]
    ext = tmp_path / "scratch" / "collections" / "c" / "protocols" / "NEW" / "soa-tables" / "extracted"
    assert (ext / "NEW_Table_01_extraction.json").read_text() == "{}\n"
