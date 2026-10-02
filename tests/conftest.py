import pytest


@pytest.fixture(autouse=True)
def in_tmp(tmp_path, monkeypatch):
    """Run every test from an empty directory, as a user would run pavilion in a project."""
    monkeypatch.chdir(tmp_path)
