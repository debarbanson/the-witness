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
    for wanted in ("cancel after research ends the spending",
                   "closed tab keeps the job; resume restores facts",
                   "concurrent uploads past the slots get busy 503s",
                   "committed film serves to concurrent readers",
                   "oversize body refused before reading",
                   "handler spool refuses before admission",
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


def test_client_sends_proxy_auth_from_the_environment():
    import os

    module = _load()
    old = {key: os.environ.get(key)
           for key in ("MODAL_PROXY_KEY", "MODAL_PROXY_SECRET")}
    try:
        os.environ.pop("MODAL_PROXY_KEY", None)
        os.environ.pop("MODAL_PROXY_SECRET", None)
        bare = module._client("https://staging.example.modal.run")
        assert "modal-key" not in bare.headers
        os.environ["MODAL_PROXY_KEY"] = "wk-test-id"
        os.environ["MODAL_PROXY_SECRET"] = "ws-test-secret"
        authed = module._client("https://staging.example.modal.run")
        assert authed.headers["modal-key"] == "wk-test-id"
        assert authed.headers["modal-secret"] == "ws-test-secret"
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
