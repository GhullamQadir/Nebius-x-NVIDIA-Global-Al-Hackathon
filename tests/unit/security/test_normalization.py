import os
import pathlib
from packages.policy_engine.normalization import normalize_path, is_within


def test_normalize_path_basic(tmp_path):
    sub = tmp_path / "foo" / ".." / "bar"
    norm = normalize_path(str(sub))
    assert norm == str((tmp_path / "bar").resolve())


def test_is_within_valid(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    file_inside = root / "src" / "main.py"
    file_inside.parent.mkdir()
    file_inside.touch()

    assert is_within(str(file_inside), str(root)) is True


def test_is_within_traversal_attack(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    outside_file = tmp_path / "etc" / "passwd"

    traversal_path = str(root) + "/../etc/passwd"
    assert is_within(traversal_path, str(root)) is False
