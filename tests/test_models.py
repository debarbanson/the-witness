"""One setting per model-using step, so switching provider is configuration."""

import pytest

from witness import models


def test_verify_defaults_to_meta_model_api():
    assert models.VERIFY.provider == "meta"
    assert models.VERIFY.base_url == "https://api.meta.ai/v1"
    assert models.VERIFY.model == "muse-spark-1.3"
    assert models.VERIFY.key_name == "MODEL_API_KEY"


def test_check_shares_the_verify_setting_until_it_needs_its_own():
    assert models.CHECK == models.VERIFY


def test_client_uses_base_url_and_key_from_environment():
    client = models.client_for(models.VERIFY, environ={"MODEL_API_KEY": "k-123"})
    assert str(client.base_url) == "https://api.meta.ai/v1/"
    assert client.api_key == "k-123"


def test_reset_usage_starts_a_fresh_job_tally():
    models.note_usage("meta", {"prompt_tokens": 5, "completion_tokens": 3,
                               "total_tokens": 8})
    assert models.usage_totals()["meta"]["total_tokens"] == 8
    models.reset_usage()
    assert models.usage_totals() == {}


def test_client_for_reuses_one_client_per_spec():
    first = models.client_for(models.VERIFY, environ={"MODEL_API_KEY": "k-123"})
    second = models.client_for(models.VERIFY, environ={"MODEL_API_KEY": "k-123"})
    assert first is second


def test_client_for_separates_specs_and_keys():
    meta = models.client_for(models.VERIFY, environ={"MODEL_API_KEY": "k-123"})
    baseten = models.client_for(
        models.VERIFY_OPEN, environ={"BASETEN_API_KEY": "b-456"})
    other_key = models.client_for(models.VERIFY, environ={"MODEL_API_KEY": "k-999"})
    assert baseten is not meta
    assert other_key is not meta


def test_client_for_separates_timeouts():
    quick = models.client_for(models.VERIFY, environ={"MODEL_API_KEY": "k-123"})
    slow = models.client_for(models.PAINT, environ={"MODEL_API_KEY": "k-123"})
    assert slow is not quick  # paint's 600 s must not inherit 120 s


def test_job_ledgers_isolate_visitors():
    models.reset_usage()
    with models.job_ledger() as first:
        models.note_usage("meta", {"prompt_tokens": 100, "completion_tokens": 0,
                                   "total_tokens": 100})
    with models.job_ledger() as second:
        models.note_usage("meta", {"prompt_tokens": 10, "completion_tokens": 0,
                                   "total_tokens": 10})
    assert first.totals["meta"]["total_tokens"] == 100
    assert second.totals["meta"]["total_tokens"] == 10
    assert models.usage_totals() == {}


def test_submit_context_carries_job_ledger():
    from concurrent.futures import ThreadPoolExecutor

    models.reset_usage()
    with models.job_ledger() as ledger:
        pool = ThreadPoolExecutor(max_workers=1)
        try:
            future = models.submit_context(
                pool, models.note_usage, "meta",
                {"prompt_tokens": 10, "completion_tokens": 5,
                 "total_tokens": 15})
            future.result()
        finally:
            pool.shutdown(wait=True)
        assert ledger.totals["meta"]["total_tokens"] == 15


def test_ledger_prices_tokens_and_calls():
    ledger = models.SpendingLedger()
    ledger.note("meta", "muse-spark-1.3",
                {"prompt_tokens": 1000, "completion_tokens": 500,
                 "total_tokens": 1500})
    ledger.note("meta", "muse-image-1.0", None)
    ledger.note("meta", "sam-3.1", None)
    ledger.note("meta", "muse-spark-1.3",
                {"prompt_tokens": 0, "completion_tokens": 0,
                 "total_tokens": 0}, searches=2)
    assert ledger.cost_usd == pytest.approx(
        1.25 / 1000 + 4.25 / 2000 + 0.01 + 0.0025 + 2 * 0.0025)
    assert ledger.totals["meta"]["total_tokens"] == 1500


def test_daily_cap_blocks_before_call(tmp_path):
    calls = []

    class FakeResponses:
        def create(self, **kwargs):
            calls.append(kwargs)
            return {"usage": {"prompt_tokens": 10000, "completion_tokens": 0,
                             "total_tokens": 10000}}

    class FakeClient:
        responses = FakeResponses()

    models.configure_spending(str(tmp_path), daily_cap_usd=0.10)
    try:
        models.respond(FakeClient(), models.VERIFY, input="hi")
        with pytest.raises(models.SpendingCapExceeded):
            models.respond(FakeClient(), models.VERIFY, input="hi again")
        assert len(calls) == 1  # the second call never ran
    finally:
        models.configure_spending(None)


def test_daily_ledger_persists_per_day(tmp_path):
    first = models.BudgetAuthority(str(tmp_path), daily_cap_usd=10.0)
    ticket = first.reserve(0.25)
    first.reconcile(ticket, 0.25)
    second = models.BudgetAuthority(str(tmp_path), daily_cap_usd=10.0)
    assert second.total_usd() == pytest.approx(0.25)


def test_cap_error_is_a_model_error():
    assert issubclass(models.SpendingCapExceeded, models.ModelError)


def test_respond_counts_web_searches(tmp_path):
    from types import SimpleNamespace

    class FakeResponses:
        def create(self, **kwargs):
            return SimpleNamespace(
                usage={"prompt_tokens": 0, "completion_tokens": 0,
                       "total_tokens": 0},
                output=[SimpleNamespace(type="web_search_call"),
                        SimpleNamespace(type="web_search_call"),
                        SimpleNamespace(type="message")])

    class FakeClient:
        responses = FakeResponses()

    models.reset_usage()
    with models.job_ledger() as ledger:
        models.respond(FakeClient(), models.RESEARCH, input="hi")
    assert ledger.cost_usd == pytest.approx(2 * 0.0025)


def test_client_bounds_timeout_and_retries_per_spec():
    client = models.client_for(models.VERIFY, environ={"MODEL_API_KEY": "k-123"})
    assert client.timeout == models.VERIFY.timeout
    assert client.max_retries == 1
    assert models.PAINT.timeout > models.VERIFY.timeout


def test_missing_key_names_the_variable_not_a_value():
    with pytest.raises(models.ModelError) as exc_info:
        models.client_for(models.VERIFY, environ={})
    assert "MODEL_API_KEY" in str(exc_info.value)
    assert "k-123" not in str(exc_info.value)


def test_verify_and_vision_run_low_effort_research_default():
    assert models.VERIFY.effort == "low"
    assert models.VISION.effort == "low"
    assert models.RESEARCH.effort is None


def test_verify_runs_temperature_zero():
    assert models.VERIFY.temperature == 0
    assert models.RESEARCH.temperature is None


def test_respond_injects_model_and_effort():
    calls = []

    class FakeResponses:
        def create(self, **kwargs):
            calls.append(kwargs)
            return "ok"

    class FakeClient:
        responses = FakeResponses()

    assert models.respond(FakeClient(), models.VERIFY, input="hi") == "ok"
    assert calls[0]["model"] == "muse-spark-1.3"
    assert calls[0]["reasoning"] == {"effort": "low"}
    assert calls[0]["temperature"] == 0
    calls.clear()
    models.respond(FakeClient(), models.RESEARCH, input="hi")
    assert "reasoning" not in calls[0]
    assert "temperature" not in calls[0]


def test_switching_to_baseten_is_configuration():
    baseten = models.ModelSpec(
        provider="baseten",
        base_url="https://inference.baseten.co/v1",
        model="meta-models/muse-spark-open-1026",
        key_name="BASETEN_API_KEY",
    )
    client = models.client_for(baseten, environ={"BASETEN_API_KEY": "b-456"})
    assert str(client.base_url) == "https://inference.baseten.co/v1/"
    assert client.api_key == "b-456"
    assert baseten.model == "meta-models/muse-spark-open-1026"


def test_verify_open_points_at_baseten_hackathon_model():
    assert models.VERIFY_OPEN.provider == "baseten"
    assert models.VERIFY_OPEN.base_url == "https://inference.baseten.co/v1"
    assert models.VERIFY_OPEN.model == "meta-models/muse-spark-open-1026"
    assert models.VERIFY_OPEN.key_name == "BASETEN_API_KEY"
    assert models.VERIFY_OPEN.temperature == 0


class FakeChatCompletions:
    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.answer


class FakeChatClient:
    def __init__(self, answer):
        self.chat = type("chat", (), {"completions": FakeChatCompletions(answer)})()


def chat_answer(content, reasoning="", prompt=10, completion=5):
    message = {"content": content}
    if reasoning:
        message["reasoning_content"] = reasoning
    return {
        "choices": [{"message": message}],
        "usage": {"prompt_tokens": prompt, "completion_tokens": completion,
                  "total_tokens": prompt + completion},
    }


def test_chat_injects_model_and_temperature():
    client = FakeChatClient(chat_answer("hi"))
    models.chat(client, models.VERIFY_OPEN, [{"role": "user", "content": "hi"}])
    call = client.chat.completions.calls[0]
    assert call["model"] == "meta-models/muse-spark-open-1026"
    assert call["temperature"] == 0
    assert call["messages"] == [{"role": "user", "content": "hi"}]


def test_chat_answer_separates_reasoning_and_counts_tokens():
    parsed = models.chat_answer(chat_answer("final", reasoning="thinking", prompt=10, completion=5))
    assert parsed["content"] == "final"
    assert parsed["reasoning"] == "thinking"
    assert parsed["usage"] == {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    bare = models.chat_answer({"choices": [{"message": {"content": "x"}}]})
    assert bare == {"content": "x", "reasoning": "", "usage": {}}


def test_usage_accumulates_per_provider():
    models.reset_usage()
    models.note_usage("meta", {"prompt_tokens": 10, "completion_tokens": 5})
    models.note_usage("baseten", {"prompt_tokens": 3, "completion_tokens": 1})
    models.note_usage("meta", {"prompt_tokens": 2, "completion_tokens": 1})
    assert models.usage_totals() == {
        "meta": {"prompt_tokens": 12, "completion_tokens": 6, "total_tokens": 18},
        "baseten": {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4},
    }
    models.reset_usage()
    assert models.usage_totals() == {}


def test_paint_uses_muse_image_on_meta():
    assert models.PAINT.provider == "meta"
    assert models.PAINT.model == "muse-image-1.0"
    assert models.PAINT.key_name == "MODEL_API_KEY"
    assert models.PAINT.effort is None
    assert models.PAINT.temperature is None


def test_sam_uses_segmentation_model_on_meta():
    assert models.SAM.provider == "meta"
    assert models.SAM.model == "sam-3.1"
    assert models.SAM.key_name == "MODEL_API_KEY"


def test_parallel_reserves_against_last_budget_unit(tmp_path):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    authority = models.BudgetAuthority(str(tmp_path), daily_cap_usd=0.15)
    barrier = threading.Barrier(4)
    won = []
    refused = []

    def attempt():
        barrier.wait(timeout=5)
        try:
            authority.reserve(0.10)
            won.append(1)
        except models.SpendingCapExceeded:
            refused.append(1)

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: attempt(), range(4)))
    assert len(won) == 1
    assert len(refused) == 3


def test_respond_reserves_ceiling_then_reconciles_actual(tmp_path):
    from types import SimpleNamespace

    class FakeResponses:
        def create(self, **kwargs):
            return {"usage": {"prompt_tokens": 1000, "completion_tokens": 0,
                             "total_tokens": 1000}}

    class FakeClient:
        responses = FakeResponses()

    models.configure_spending(str(tmp_path), daily_cap_usd=10.0)
    try:
        models.respond(FakeClient(), models.VERIFY, input="hi")
        assert models._DAILY.total_usd() == pytest.approx(1000 / 1e6 * 1.25)
        assert models._DAILY.reserved_usd() == pytest.approx(0.0)
    finally:
        models.configure_spending(None)


def test_failed_call_releases_its_reservation(tmp_path):
    class FakeResponses:
        def create(self, **kwargs):
            raise TimeoutError("synthetic transport failure")

    class FakeClient:
        responses = FakeResponses()

    models.configure_spending(str(tmp_path), daily_cap_usd=10.0)
    try:
        with pytest.raises(TimeoutError):
            models.respond(FakeClient(), models.VERIFY, input="hi")
        assert models._DAILY.total_usd() == pytest.approx(0.0)
        assert models._DAILY.reserved_usd() == pytest.approx(0.0)
    finally:
        models.configure_spending(None)


def test_corrupt_accounting_fails_closed(tmp_path):
    from types import SimpleNamespace

    class FakeResponses:
        def create(self, **kwargs):  # pragma: no cover - must never run
            raise AssertionError("unreserved call ran")

    class FakeClient:
        responses = FakeResponses()

    from datetime import date
    path = tmp_path / f"spending-{date.today().isoformat()}.json"
    path.write_text("{not json")
    models.configure_spending(str(tmp_path), daily_cap_usd=10.0)
    try:
        with pytest.raises(models.AccountingError):
            models.respond(FakeClient(), models.VERIFY, input="hi")
    finally:
        models.configure_spending(None)


def test_film_quota_admits_then_refuses(tmp_path):
    authority = models.BudgetAuthority(str(tmp_path), daily_cap_usd=10.0,
                                      daily_films=2, visitor_films=5)
    authority.admit("visitor-a")
    authority.admit("visitor-b")
    with pytest.raises(models.SpendingCapExceeded):
        authority.admit("visitor-c")


def test_per_visitor_limit(tmp_path):
    authority = models.BudgetAuthority(str(tmp_path), daily_cap_usd=10.0,
                                      daily_films=10, visitor_films=1)
    authority.admit("visitor-a")
    with pytest.raises(models.SpendingCapExceeded):
        authority.admit("visitor-a")
    authority.admit("visitor-b")  # another visitor is unaffected


def test_respond_bounds_max_output_tokens():
    seen = {}

    class FakeResponses:
        def create(self, **kwargs):
            seen.update(kwargs)
            return {"usage": {}}

    class FakeClient:
        responses = FakeResponses()

    models.respond(FakeClient(), models.VERIFY, input="hi")
    assert seen["max_output_tokens"] == models.VERIFY.max_output_tokens
    assert models.VERIFY.max_output_tokens > 0


def test_every_paid_spec_carries_a_ceiling():
    for spec in (models.RESEARCH, models.VISION, models.VERIFY, models.PAINT,
                 models.SAM, models.VERIFY_OPEN):
        assert spec.ceiling_usd > 0


def test_job_search_budget_blocks_further_calls():
    class FakeResponses:
        def create(self, **kwargs):  # pragma: no cover - must never run
            raise AssertionError("over-budget call ran")

    class FakeClient:
        responses = FakeResponses()

    models.reset_usage()
    with models.job_ledger() as ledger:
        ledger.searches = models.SEARCH_BUDGET_PER_JOB
        with pytest.raises(models.SpendingCapExceeded):
            models.respond(FakeClient(), models.RESEARCH, input="hi")


def test_nested_job_ledger_shares_one_ledger():
    models.reset_usage()
    with models.job_ledger() as outer:
        models.note_usage("meta", {"prompt_tokens": 100, "completion_tokens": 0,
                                   "total_tokens": 100})
        with models.job_ledger() as inner:
            assert inner is outer
            models.note_usage("meta", {"prompt_tokens": 10, "completion_tokens": 0,
                                       "total_tokens": 10})
        assert models.usage_totals()["meta"]["total_tokens"] == 110
    assert models.usage_totals() == {}
