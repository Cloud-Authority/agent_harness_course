"""Shared fixtures for the offline tests of this track.

No test here needs a key, a network connection or a model. State is written to a
temporary folder, so a test run never touches ``data/`` or a home directory.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

TRACK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TRACK))

_SCRATCH = Path(tempfile.mkdtemp(prefix="ppa-tests-"))
os.environ["PPA_DATA_DIR"] = str(_SCRATCH / "data")
os.environ["PPA_WORKSPACE_DIR"] = str(_SCRATCH / "workspace")
os.environ["MEMORIZZ_HOME"] = str(_SCRATCH / "data" / "memorizz_home")
os.environ["MEMORIZZ_MEMORY_ROOT"] = str(_SCRATCH / "data" / "memory")

NOTEBOOKS = {
    "memagent": TRACK / "memorizz" / "assistant" / "notebook" / "ppa_memorizz_complete.ipynb",
    "metaharness": TRACK / "metaharness" / "notebook" / "ppa_metaharness_pi_deepseek_hermes.ipynb",
}


@pytest.fixture(scope="session")
def scratch() -> Path:
    return _SCRATCH


@pytest.fixture(scope="session")
def world():
    from ppa_dfy import world as world_module

    return world_module.load_world()


@pytest.fixture(scope="session")
def known(world):
    from ppa_dfy import world as world_module

    return world_module.known_answers(world)


@pytest.fixture(scope="session", params=sorted(NOTEBOOKS))
def notebook(request):
    """Each notebook as parsed JSON, with its short name."""
    path = NOTEBOOKS[request.param]
    if not path.is_file():
        pytest.skip(f"{path.name} has not been built")
    return {"name": request.param, "path": path,
            "cells": json.loads(path.read_text(encoding="utf-8"))["cells"],
            "metadata": json.loads(path.read_text(encoding="utf-8"))["metadata"]}
