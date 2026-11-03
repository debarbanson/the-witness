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
    assert client.max_retries == 0
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


def test_open_model_output_bound_covers_reasoning_plus_answer():
    assert models.VERIFY_OPEN.max_output_tokens >= 16384


def test_chat_answer_reports_a_reasoning_cutoff():
    cut = chat_answer(None, reasoning="thinking" * 1000)
    cut["choices"][0]["finish_reason"] = "length"
    with pytest.raises(models.ModelError, match="cut off"):
        models.chat_answer(cut)


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


def test_failed_call_keeps_its_reservation(tmp_path):
    class FakeResponses:
        def create(self, **kwargs):
            raise TimeoutError("synthetic transport failure")

    class FakeClient:
        responses = FakeResponses()

    models.configure_spending(str(tmp_path), daily_cap_usd=10.0)
    try:
        with pytest.raises(TimeoutError):
            models.respond(FakeClient(), models.VERIFY, input="hi")
        assert models._DAILY.total_usd() == pytest.approx(
            models.VERIFY.ceiling_usd)
        assert models._DAILY.reserved_usd() == pytest.approx(0.0)
    finally:
        models.configure_spending(None)


def test_configure_spending_accepts_an_authority_object():
    class Custom:
        pass

    custom = Custom()
    models.configure_spending(authority=custom)
    assert models._DAILY is custom
    models.configure_spending(None)
    assert models._DAILY is None


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


def test_fake_provider_needs_no_keys(monkeypatch):
    monkeypatch.setenv("WITNESS_FAKE_PROVIDER", "1")
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    client = models.client_for(models.VERIFY)
    resp = client.responses.create(model=models.VERIFY.model,
                                   input="Write one sentence.")
    assert "years" in resp.model_dump_json()


def test_fake_provider_answers_pick_and_second_look(monkeypatch):
    import json

    monkeypatch.setenv("WITNESS_FAKE_PROVIDER", "1")
    client = models.client_for(models.VISION)
    prompt = ("Nearby known objects:\n1. Fake Mill (windmill)\n"
              "Which one does the photo show?")
    data = json.loads(client.responses.create(
        model=models.VISION.model, input=prompt).model_dump_json())
    assert data["output"][0]["content"][0]["text"].startswith("1 Fake Mill")
    data = json.loads(client.responses.create(
        model=models.VISION.model,
        input="Second look at the same photo. Does it show X?").model_dump_json())
    assert data["output"][0]["content"][0]["text"].startswith("YES")


def test_fake_provider_research_returns_lifespan(monkeypatch):
    import json

    monkeypatch.setenv("WITNESS_FAKE_PROVIDER", "1")
    client = models.client_for(models.RESEARCH)
    data = json.loads(client.responses.create(
        model=models.RESEARCH.model, tools=[{"type": "web_search"}],
        input="What happened to the mill itself over its lifetime?").model_dump_json())
    message = [o for o in data["output"] if o["type"] == "message"][-1]
    parsed = json.loads(message["content"][0]["text"])
    assert {e["year"] for e in parsed["events"]} == {1850, 1900, 1925}
    assert parsed["sources"]


def test_fake_provider_votes_supported(monkeypatch):
    import json

    monkeypatch.setenv("WITNESS_FAKE_PROVIDER", "1")
    client = models.client_for(models.VERIFY)
    data = json.loads(client.responses.create(
        model=models.VERIFY.model,
        input="Claim to check:\nBuilt in 1850.").model_dump_json())
    parsed = json.loads(data["output"][0]["content"][0]["text"])
    assert parsed["verdict"] == "supported"
    assert parsed["quote"] and parsed["url"]


def test_fake_provider_paints_a_png(monkeypatch):
    import base64
    import json

    monkeypatch.setenv("WITNESS_FAKE_PROVIDER", "1")
    client = models.client_for(models.PAINT)
    data = json.loads(client.responses.create(
        model=models.PAINT.model, input="paint it").model_dump_json())
    assert data["id"].startswith("fake-")
    assert base64.b64decode(
        data["output"][0]["result"])[:8] == b"\x89PNG\r\n\x1a\n"


def test_fake_second_look_is_priced_not_ceiling(tmp_path, monkeypatch):
    monkeypatch.setenv("WITNESS_FAKE_PROVIDER", "1")
    monkeypatch.setenv("WITNESS_FAKE_DELAY_S", "0")
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    models.configure_spending(str(tmp_path), daily_cap_usd=10.0)
    try:
        client = models.client_for(models.VISION)
        with models.job_ledger() as ledger:
            models.respond(client, models.VISION,
                           input="Second look at the same photo.")
            assert 0 < ledger.cost_usd < models.VISION.ceiling_usd
    finally:
        models.configure_spending(None)


def test_fake_answers_are_priced_and_a_full_set_costs_under_five_cents(
        tmp_path, monkeypatch):
    monkeypatch.setenv("WITNESS_FAKE_PROVIDER", "1")
    monkeypatch.setenv("WITNESS_FAKE_DELAY_S", "0")
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("BASETEN_API_KEY", raising=False)
    models.configure_spending(str(tmp_path), daily_cap_usd=10.0)
    try:
        with models.job_ledger() as ledger:
            def cost_of(call):
                before = ledger.cost_usd
                call()
                return ledger.cost_usd - before

            vision = models.client_for(models.VISION)
            delta = cost_of(lambda: models.respond(
                vision, models.VISION,
                input="1. Old Mill (windmill)\nWhich one does the photo show"))
            assert 0 < delta < models.VISION.ceiling_usd
            delta = cost_of(lambda: models.respond(
                vision, models.VISION,
                input="Second look at the same photo."))
            assert 0 < delta < models.VISION.ceiling_usd
            research = models.client_for(models.RESEARCH)
            delta = cost_of(lambda: models.respond(
                research, models.RESEARCH,
                input="What happened to the mill itself over its lifetime?",
                tools=[{"type": "web_search"}]))
            assert 0 < delta < models.RESEARCH.ceiling_usd
            verify = models.client_for(models.VERIFY)
            delta = cost_of(lambda: models.respond(
                verify, models.VERIFY,
                input="Claim to check:\nBuilt in 1850."))
            assert 0 < delta < models.VERIFY.ceiling_usd
            opened = models.client_for(models.VERIFY_OPEN)
            delta = cost_of(lambda: models.chat(
                opened, models.VERIFY_OPEN,
                messages=[{"role": "user", "content": "vote"}]))
            assert 0 < delta < models.VERIFY_OPEN.ceiling_usd
            delta = cost_of(lambda: models.respond(
                verify, models.VERIFY,
                input="Did this change actually happen?"))
            assert 0 < delta < models.VERIFY.ceiling_usd
            delta = cost_of(lambda: models.respond(
                verify, models.CHECK,
                input="Answer MATCHES only if the photo shows it."))
            assert 0 < delta < models.CHECK.ceiling_usd
            delta = cost_of(lambda: models.respond(
                verify, models.VERIFY, input="Write one caption sentence."))
            assert 0 < delta < models.VERIFY.ceiling_usd
            paint = models.client_for(models.PAINT)
            delta = cost_of(lambda: models.respond(
                paint, models.PAINT, input="paint the era"))
            assert 0 < delta < models.PAINT.ceiling_usd
            sam = models.client_for(models.SAM)
            delta = cost_of(lambda: models.respond(
                sam, models.SAM, input="segment the mill"))
            assert 0 < delta < models.SAM.ceiling_usd
            assert ledger.cost_usd < 0.05
    finally:
        models.configure_spending(None)


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


def test_cancel_stops_paid_calls_before_they_run():
    calls = []

    class FakeResponses:
        def create(self, **kwargs):
            calls.append(1)
            return {"usage": {}}

    class FakeClient:
        responses = FakeResponses()

    control = models.JobControl()
    control.cancel()
    with models.job_control(control=control):
        with pytest.raises(models.JobCancelled):
            models.respond(FakeClient(), models.VERIFY, input="hi")
    assert calls == []


def test_deadline_stops_paid_calls():
    class FakeResponses:
        def create(self, **kwargs):  # pragma: no cover - must never run
            raise AssertionError("past-deadline call ran")

    class FakeClient:
        responses = FakeResponses()

    with models.job_control(deadline_s=-1):
        with pytest.raises(models.JobDeadlineExceeded):
            models.respond(FakeClient(), models.VERIFY, input="hi")


def test_control_reaches_worker_threads():
    from concurrent.futures import ThreadPoolExecutor

    control = models.JobControl()
    control.cancel()
    seen = []
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        with models.job_control(control=control):
            future = models.submit_context(pool, models._check_control)
            try:
                future.result()
            except models.JobCancelled:
                seen.append(1)
    finally:
        pool.shutdown(wait=True)
    assert seen == [1]


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


def test_failed_paid_call_keeps_its_reservation(tmp_path):
    import pytest

    auth = models.BudgetAuthority(tmp_path, daily_cap_usd=5.0)
    models.configure_spending(authority=auth)

    class Timeout(Exception):
        pass

    class Client:
        class responses:
            @staticmethod
            def create(**kw):
                raise Timeout("read timed out after the server billed")

    try:
        with pytest.raises(Timeout):
            models.respond(Client, models.RESEARCH, input="q")
    finally:
        models.configure_spending(None)
    assert auth.total_usd() == models.RESEARCH.ceiling_usd
    assert auth.reserved_usd() == 0.0


def test_failed_chat_call_keeps_its_reservation(tmp_path):
    import pytest

    from witness.models import VERIFY_OPEN

    auth = models.BudgetAuthority(tmp_path, daily_cap_usd=5.0)
    models.configure_spending(authority=auth)

    class Client:
        class chat:
            class completions:
                @staticmethod
                def create(**kw):
                    raise ConnectionError("billed then dropped")

    try:
        with pytest.raises(ConnectionError):
            models.chat(Client, VERIFY_OPEN, [{"role": "user"}])
    finally:
        models.configure_spending(None)
    assert auth.total_usd() == VERIFY_OPEN.ceiling_usd


def test_sdk_never_retries_behind_one_reservation():
    client = models.client_for(models.VISION, environ={"MODEL_API_KEY": "k"})
    assert client.max_retries == 0


def test_admit_checks_both_visitor_keys_counts_once(tmp_path):
    auth = models.BudgetAuthority(tmp_path, daily_films=10, visitor_films=2)
    import pytest

    auth.admit("vid-a", extra="ip:hash-a")
    auth.admit("vid-b", extra="ip:hash-a")  # new cookie, same network
    with pytest.raises(models.SpendingCapExceeded):
        auth.admit("vid-c", extra="ip:hash-a")
    auth.admit("vid-a", extra="ip:hash-b")  # second film, new network
    with pytest.raises(models.SpendingCapExceeded):
        auth.admit("vid-a", extra="ip:hash-c")
    assert auth.total_films() == 3


def test_reset_quotas_clears_films_and_visitors_keeps_spend(tmp_path):
    auth = models.BudgetAuthority(tmp_path, daily_films=10, visitor_films=1)
    auth.admit("vid-a", extra="ip:hash-a")
    with pytest.raises(models.SpendingCapExceeded):
        auth.admit("vid-a", extra="ip:hash-a")
    before = auth.total_usd()
    auth.reset_quotas()
    auth.admit("vid-a", extra="ip:hash-a")
    assert auth.total_films() == 1
    assert auth.total_usd() == before


def test_snapshot_reports_films_visitors_calls_and_spend(tmp_path):
    auth = models.BudgetAuthority(tmp_path, daily_films=10, visitor_films=2)
    auth.admit("vid-a", extra="ip:hash-a")
    snap = auth.snapshot()
    assert snap["films"] == 1
    assert snap["visitors"] == 2
    assert snap["calls"] == 0
    assert "total_usd" in snap and "reserved_usd" in snap
    assert "vid-a" not in str(snap) and "hash-a" not in str(snap)


def test_research_ceiling_covers_worst_case_searches():
    worst = models.SEARCH_BUDGET_PER_JOB * models.WEB_SEARCH_USD
    assert models.RESEARCH.ceiling_usd >= worst


def test_ticket_reconciles_only_once(tmp_path):
    auth = models.BudgetAuthority(tmp_path, daily_cap_usd=0.20)
    first = auth.reserve(0.10)
    auth.reserve(0.10)
    auth.reconcile(first, 0.01)
    with pytest.raises(models.AccountingError):
        auth.reconcile(first, 0.01)
    assert auth.reserved_usd() == pytest.approx(0.10)


def test_ticket_reconciles_against_its_own_day(tmp_path, monkeypatch):
    auth = models.BudgetAuthority(tmp_path, daily_cap_usd=0.10)
    current = [tmp_path / "day-one.json"]
    monkeypatch.setattr(auth, "_file", lambda: current[0])
    old = auth.reserve(0.10)
    current[0] = tmp_path / "day-two.json"
    auth.reserve(0.10)
    auth.reconcile(old, 0.0)
    assert auth.reserved_usd() == pytest.approx(0.10)


def test_empty_account_file_fails_closed(tmp_path):
    auth = models.BudgetAuthority(tmp_path, daily_cap_usd=0.10)
    auth._file().write_text("")
    with pytest.raises(models.AccountingError):
        auth.reserve(0.10)
    with pytest.raises(models.AccountingError):
        auth.total_usd()


def test_refused_reserve_leaves_no_empty_account_file(tmp_path):
    auth = models.BudgetAuthority(tmp_path, daily_cap_usd=0.005)
    with pytest.raises(models.SpendingCapExceeded):
        auth.reserve(0.10)
    assert not auth._file().exists()
    with pytest.raises(models.SpendingCapExceeded):
        auth.reserve(0.10)


def test_oversized_input_is_refused_before_any_reserve(tmp_path):
    class FakeClient:
        class responses:
            @staticmethod
            def create(**kw):
                raise AssertionError("refused calls never run")

    models.configure_spending(str(tmp_path), daily_cap_usd=10.0)
    try:
        with pytest.raises(models.SpendingCapExceeded):
            models.respond(FakeClient(), models.VERIFY, input="A " * 100000)
        assert models._DAILY.total_usd() == pytest.approx(0.0)
        assert models._DAILY.reserved_usd() == pytest.approx(0.0)
    finally:
        models.configure_spending(None)


def test_input_estimate_skips_data_uris_and_charges_images():
    assert models.estimate_input_tokens({"input": "abcd"}) == 1
    # the 100k data URI chars count for nothing; the tag text counts 3
    assert models.estimate_input_tokens(
        {"input": [{"type": "input_image",
                    "image_url": "data:image/png;base64," + "A" * 100000}]}
    ) == models.IMAGE_INPUT_TOKENS + 3


def test_spec_floors_cover_worst_case_inputs():
    for spec in (models.RESEARCH, models.VISION, models.VERIFY,
                 models.PAINT, models.SAM, models.VERIFY_OPEN):
        worst = models.call_ceiling(spec, spec.max_input_tokens or 0)
        assert worst <= spec.ceiling_usd, spec.model


def test_every_priced_spec_covers_a_real_call_shape(tmp_path):
    models.configure_spending(str(tmp_path), daily_cap_usd=10.0)
    try:
        assert models._DAILY.reserve(
            models.call_ceiling(models.VERIFY, 100)).ceiling_usd >= 0.0
    finally:
        models.configure_spending(None)


def test_timing_log_records_calls_and_authority_round_trips(
        tmp_path, monkeypatch):
    import json

    monkeypatch.setenv("WITNESS_FAKE_PROVIDER", "1")
    monkeypatch.setenv("WITNESS_FAKE_DELAY_S", "0")
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("BASETEN_API_KEY", raising=False)
    models.configure_spending(str(tmp_path), daily_cap_usd=10.0)
    try:
        models.reset_timing()
        with models.job_ledger():
            vision = models.client_for(models.VISION)
            models.respond(vision, models.VISION, phase="identify",
                           input="Which one does the photo show: secret-mill")
            opened = models.client_for(models.VERIFY_OPEN)
            models.chat(opened, models.VERIFY_OPEN, phase="verify",
                        messages=[{"role": "user", "content": "vote"}])
        rows = models.timing_rows()
        calls = [r for r in rows if r["op"] == "call"]
        authority = [r for r in rows if r["op"] in ("reserve", "reconcile")]
        assert len(calls) == 2
        assert len(authority) == 4
        assert [c["phase"] for c in calls] == ["identify", "verify"]
        for row in rows:
            assert row["duration_s"] >= 0
            assert row["t"] > 0
        assert calls[0]["model"] == models.VISION.model
        assert calls[1]["provider"] == "baseten"
        assert calls[0]["prompt_tokens"] > 0
        assert all(c["ok"] for c in calls)
        dumped = json.dumps(rows)
        assert "secret-mill" not in dumped
        assert "http" not in dumped
        assert "MODEL_API_KEY" not in dumped
        assert "data:image" not in dumped
    finally:
        models.configure_spending(None)


def test_timing_log_marks_failed_calls(tmp_path, monkeypatch):
    monkeypatch.setenv("WITNESS_FAKE_PROVIDER", "1")
    monkeypatch.setenv("WITNESS_FAKE_DELAY_S", "0")
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    models.configure_spending(str(tmp_path), daily_cap_usd=10.0)
    try:
        models.reset_timing()

        class FailingResponses:
            def create(self, **kwargs):
                raise TimeoutError("too slow")

        class FailingClient:
            responses = FailingResponses()

        with models.job_ledger():
            try:
                models.respond(FailingClient(), models.VERIFY,
                               phase="verify", input="hi")
            except TimeoutError:
                pass
        rows = models.timing_rows()
        calls = [r for r in rows if r["op"] == "call"]
        assert len(calls) == 1
        assert calls[0]["ok"] is False
        assert calls[0]["phase"] == "verify"
        assert "TimeoutError" in calls[0]["note"]
    finally:
        models.configure_spending(None)


def test_timing_log_survives_nested_job_ledgers(monkeypatch):
    monkeypatch.setenv("WITNESS_FAKE_PROVIDER", "1")
    monkeypatch.setenv("WITNESS_FAKE_DELAY_S", "0")
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    models.reset_timing()
    client = models.client_for(models.VERIFY)
    with models.job_ledger():
        models.respond(client, models.VERIFY, phase="verify", input="one")
    with models.job_ledger():
        models.respond(client, models.VERIFY, phase="verify", input="two")
    calls = [r for r in models.timing_rows() if r["op"] == "call"]
    assert len(calls) == 2
