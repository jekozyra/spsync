"""Tests for options that the spsync command line handles before any command runs."""

from importlib import metadata

import pytest

from spsync import main


def test_version_prints_the_package_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])
    assert exit_info.value.code == 0
    assert capsys.readouterr().out == f"spsync {metadata.version('spsync')}\n"
