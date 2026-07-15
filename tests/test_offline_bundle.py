from pathlib import Path
from zipfile import ZipFile

import pytest

from scripts import build_offline_bundle


def test_safe_remove_rejects_parent_and_outside_paths(tmp_path: Path):
    with pytest.raises(ValueError):
        build_offline_bundle._safe_remove(tmp_path, tmp_path)
    with pytest.raises(ValueError):
        build_offline_bundle._safe_remove(tmp_path.parent, tmp_path)


def test_source_only_bundle_contains_launchers_application_and_manifest(tmp_path: Path):
    output = tmp_path / "ReqPilot-source-test.zip"
    built = build_offline_bundle.build(
        output, include_models=False, include_wheels=False
    )
    assert built == output.resolve()
    assert output.is_file()
    with ZipFile(output) as bundle:
        names = set(bundle.namelist())
    assert "ReqPilot/OFFLINE_BUNDLE.json" in names
    assert "ReqPilot/run_windows.bat" in names
    assert "ReqPilot/run_mac.sh" in names
    assert "ReqPilot/src/server.py" in names
    assert "ReqPilot/scripts/fetch_models.py" in names
