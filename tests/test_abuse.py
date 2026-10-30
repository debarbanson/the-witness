"""The staging abuse script: every check declares its path."""

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "abuse_staging.py"


def _load():
    spec = importlib.util.spec_from_file_location("abuse_staging", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_check_declares_real_or_fake_provider():
    module = _load()
    assert module.CHECKS
    for entry in module.CHECKS:
        name, _, fake_provider = entry
        assert isinstance(fake_provider, bool), name


def test_new_abuse_cases_exist():
    module = _load()
    names = [entry[0] for entry in module.CHECKS]
    for wanted in ("cancel after research ends it",
                   "closed tab cancels through the beacon endpoint",
                   "oversize body refused before reading",
                   "foreign and missing origins refused",
                   "cookieless quota refuses the third film",
                   "cancel racing progress writes ends cancelled",
                   "cancelled job carries its retention end"):
        assert wanted in names, wanted


def test_staging_uploads_send_an_origin():
    import inspect

    module = _load()
    homologous = inspect.getsource(module._start)
    assert "Origin" in homologous
