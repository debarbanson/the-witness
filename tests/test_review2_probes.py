"""Offline review probes. Each passing test demonstrates an existing gap."""
import io
import json
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from PIL import Image
from witness import captions, cli, identify, models, paint, photo, verify, web, webapp, webfilm, spot, children
from witness.render import builder


def answer(quote, url="https://example.org/history", verdict="supported"):
    return verify.text_answer(json.dumps({"verdict": verdict, "quote": quote,
        "url": url, "support": [{"url": url, "supports": True, "quote": quote}]}))


def job(**extras):
    return {"claim": "The tower opened in 1900.", "year": 1900,
        "event": "stood", "detail": "The tower stood.", "votes": 1,
        "keywords": ["tower"], "urls": ["https://example.org/history"],
        "passages": ["https://example.org/history\nThe tower opened in 1800 and was repaired much later."],
        **extras}


def test_four_calls_pass_without_reserving_budget(tmp_path):
    calls = []
    client = SimpleNamespace(responses=SimpleNamespace(create=lambda **kw: calls.append(1) or {"usage": {}}))
    models.configure_spending(tmp_path, daily_cap_usd=0.005)
    def attempt(_):
        try:
            return models.respond(client, models.PAINT)
        except models.SpendingCapExceeded:
            return None
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(attempt, range(4)))
    assert len(calls) == 4, "reservation now blocks the unsafe calls"


def test_unfetched_quote_is_accepted():
    forged = "The tower opened in 1900 with a spectacular golden roof."
    result = verify.judge_claim(lambda _: answer(forged), job(), completion=False)
    assert result["verdict"] == "supported"
    assert not verify.is_literal_quote(forged, job()["passages"], 1900, ["tower"])


def test_literal_quote_is_not_bound_to_its_claimed_url():
    quote = "The tower opened in 1900 with a spectacular golden roof."
    result = verify.judge_claim(lambda _: answer(quote, "https://unfetched.invalid/"),
        job(passages=["https://example.org/history\n" + quote]), completion=False)
    assert result["verdict"] == "supported"
    assert result["fast_path"] == "literal_quote"
    assert result["url"] == "https://unfetched.invalid/"


def test_anchor_accepts_negation_and_skips_dispute_check():
    checked=[]
    result=verify.judge_claim(lambda _: answer("", verdict="unsupported"),
        job(anchor="build", passages=["https://example.org/history\nThe tower was not built in 1900, despite popular claims."]),
        dispute_check=lambda *args: checked.append(True) or False)
    assert checked, "ported probe must reach the corrected dispute check"
    assert result["verdict"] == "supported", "negation should not confirm an inception"


def test_completion_failure_preserves_completed_true():
    def fail(_):
        raise TimeoutError("synthetic transport failure")
    quote = "In 1900 the town proposed that the tower should be rebuilt."
    result = verify.judge_claim(lambda _: answer(quote),
        job(event="rebuilt", detail="The tower was rebuilt.", passages=["https://example.org/history\n" + quote]),
        completion_respond=fail)
    assert result["verdict"] == "supported"
    assert result["completed"] is True
    assert "failed" in result["completion_note"]


def test_partly_supported_caption_keeps_unsupported_detail():
    result = captions.write_sentence(lambda *a: "I grew a golden roof and flew away.",
        lambda *a: "partly", {"claim": "The roof changed.", "quote": "The roof changed."}, 1900)
    assert result["verified"] is True
    assert result["sentence"].endswith("flew away.")


def test_jpeg_comment_survives_cleaning(tmp_path):
    src = tmp_path / "upload.jpg"
    marker = b"synthetic private metadata marker"
    Image.new("RGB", (8, 8)).save(src, comment=marker)
    dest = photo.prepare_photo(src, tmp_path / "job")
    assert Image.open(dest).info.get("comment") == marker
    assert Image.open(io.BytesIO(photo.photo_bytes_clean(src))).info.get("comment") == marker


def test_ingest_error_leaves_original_on_disk(tmp_path, monkeypatch):
    src = tmp_path / "upload.jpg"
    Image.new("RGB", (8, 8)).save(src)
    def fail(*args):
        raise OSError("synthetic encoder failure")
    monkeypatch.setattr(photo, "prepare_photo", fail)
    with pytest.raises(OSError):
        photo.ingest_upload(src, tmp_path / "job")
    assert src.exists()


def test_typed_place_is_echoed_in_error():
    marker = "SYNTHETIC_PRIVATE_PLACE"
    identify.clear_cache()
    response = SimpleNamespace(raise_for_status=lambda: None, json=lambda: [])
    with pytest.raises(identify.NotIdentifiedError) as exc:
        identify.geocode(marker, get=lambda *a, **k: response, sleep=lambda _: None)
    assert marker in str(exc.value)


def test_redirect_is_checked_only_after_fetch(monkeypatch):
    seen=[]
    monkeypatch.setattr(web, "resolve_public_ips", lambda host: ["93.184.216.34"])
    def sender(url, **kwargs):
        seen.append(url)
        return SimpleNamespace(status_code=302, headers={"Location":"http://127.0.0.1/private"}, close=lambda:None)
    try:
        web.fetch_public("https://example.org/public", sender=sender)
    except web.WebError:
        pass
    assert len(seen)>1, "private redirect is now rejected before the second request"


def test_mixed_public_private_dns_is_allowed(monkeypatch):
    monkeypatch.setattr(web.socket, "getaddrinfo", lambda *a: [
        (2, 1, 6, "", ("93.184.216.34", 0)), (2, 1, 6, "", ("127.0.0.1", 0))])
    web.assert_public_url("https://example.org/")


def test_nat64_loopback_url_is_allowed():
    web.assert_public_url("http://[64:ff9b::7f00:1]/")


def test_capped_job_result_crashes_film_command(monkeypatch):
    monkeypatch.setattr(cli, "run_job", lambda *a, **k: {
        "identified": True, "confirmed": True, "cached": False, "capped": True})
    with pytest.raises(KeyError, match="chosen"):
        cli.cmd_film("unused", yes=True)


def test_reviewed_cache_skips_decline(tmp_path, monkeypatch):
    found = SimpleNamespace(name="Synthetic Tower", kind="tower", qid="Q1",
        articles={}, country_code="gb")
    monkeypatch.setattr(identify, "identify", lambda *a, **k: found)
    decisions = []
    cache = SimpleNamespace(get_reviewed=lambda *a: {"outcome": {"outcome": "short_film"}})
    result = cli.run_job("unused", cache=cache, quiet=True, out_dir=tmp_path,
        decide=lambda _: decisions.append(False) or False)
    assert result["confirmed"] is True
    assert decisions == []


def test_aftermath_retry_drops_photo_after_safety_error():
    seen = []
    def call(prompt, prev, image):
        seen.append(image is not None)
        if len(seen) == 1:
            raise paint.PaintSafetyError("synthetic refusal")
        return {"image": b"fake", "response_id": "synthetic"}
    result = paint.paint_aftermath(call, lambda *a: "MATCHES", {
        "from_year": 1900, "state": {"condition": "burnt"}}, "Tower", "Town",
        photo_bytes=b"synthetic image")
    assert result["verdict"] == "matches"
    assert seen == [True, False]


def test_rerender_leaves_previous_cutout_file(tmp_path):
    cutout = tmp_path / "synthetic.png"
    Image.new("RGBA", (8, 8)).save(cutout)
    research = {"object": {"name": "Tower"}, "scenes": []}
    builder.write_film(tmp_path / "job", research, {}, "today.jpg", "", {}, cutout_file=cutout)
    film = builder.write_film(tmp_path / "job", research, {}, "today.jpg", "", {}, cutout_file=None)
    assert json.loads((film / "film.json").read_text())["cutout"] is None
    assert (film / "cutout.png").exists()


def test_filmable_does_not_require_verified_claim_or_source():
    assert builder.filmable({"caption_sentence": {"text": "I flew away.", "claim_year": 1900}}, [])


def test_war_flag_is_not_removed_from_timeline():
    claim = {"year": 1900, "claim": "The tower was bombed in war.",
        "event": "destroyed", "verdict": "supported", "war_politics_only": True,
        "quote_span": "The tower was bombed in war.", "rewritten": None}
    verified, timeline, chosen = cli.refresh_film([claim])
    assert len(verified) == len(timeline) == 1
    assert chosen[0]["from_year"] == 1900


def test_visible_change_bypasses_claim_verification():
    invented = "A golden roof and six purple spires."
    claim = {"year": 1900, "claim": "The tower was built in 1900.",
        "event": "built", "quote_span": "The tower was built.",
        "visible_change": invented, "sources": ["https://example.org/history"],
        "verdict": "supported", "war_politics_only": False, "rewritten": None}
    verification_job = cli.build_jobs([claim], {}, [], 1900)[0]
    assert invented not in verification_job["claim"]
    assert invented not in verification_job["detail"]
    _, timeline, chosen = cli.refresh_film([claim])
    assert timeline[0]["state"]["description"] == invented
    assert invented in paint.scene_prompt(chosen[0], "Tower", "Town")


def test_film_save_uses_restored_outer_ledger(monkeypatch):
    models.reset_usage()
    @models.with_job_ledger
    def fake_run(*args, **kwargs):
        models.current_ledger().note("meta", "muse-spark-1.3", {"input_tokens": 1000})
        return {"identified": True, "confirmed": True, "cached": False,
            "chosen": [], "order": [], "kept": [], "timeline": [], "result": {},
            "timings": {"total_s": 1}, "failures": [],
            "tokens": models.usage_totals(), "cost_usd": models.current_cost_usd()}
    saved = []
    def save(*args, **kwargs):
        saved.append(kwargs.get("cost_usd", models.current_cost_usd()))
    monkeypatch.setattr(cli, "run_job", fake_run)
    monkeypatch.setattr(cli, "report_and_save", save)
    assert cli.cmd_film("unused", yes=True) == 0
    assert saved == [0.0]


@pytest.fixture(autouse=True)
def isolate_accounting():
    models.configure_spending()
    models.reset_usage()
    verify.clear_cache()
    identify.clear_cache()
    yield
    models.configure_spending()
    models.reset_usage()
    verify.clear_cache()
    identify.clear_cache()

URL="https://example.org/history"
QUOTE="The tower was built in 1900 with a stone roof."
def evidence_claim(**changes):
    return {"year":1900,"claim":"The tower was built in 1900.","event":"built", "completed":True,
            "verdict":"supported","quote":QUOTE,"url":URL,"sources":[URL],"war_politics_only":False,
            **changes}
def evidence_scene(**changes):
    return {"from_year":1900,"date_label":"1900","state":{"condition":"standing","description":"stone roof"},
        "caption_lines":[],"caption_sentence":{"text":"I rose with a stone roof.","claim_year":1900,"claim_url":URL,
        "evidence":{"claim":"The tower was built in 1900.","quote":QUOTE,"url":URL}},**changes}

def make_client(tmp_path, runner=None, store=None, examples=None):
    from fastapi.testclient import TestClient
    store=store or webapp.MemoryStore()
    deps=webapp.WebDeps(store=store,authority=None,runner=runner or (lambda spec:None),
        jobs_root=tmp_path/"jobs",examples_root=tmp_path/"examples",examples=examples or [])
    return TestClient(webapp.create_app(deps),raise_server_exceptions=False),store

def new_record(directory, **extras):
    return {"vid":"synthetic-owner","token":"synthetic-capability","job_dir":str(directory),
        "status":"working","events":[],"started_at":0,"ended_at":None,"confirm":None,
        "decision":None,"cancel":False,"result":None,**extras}

def new_spec(tmp_path):
    return {"job_id":"synthetic-job","token":"synthetic-capability","vid":"synthetic-owner",
        "job_dir":str(tmp_path),"photo":"synthetic-photo", "place":"", "location":None,
        "lat":None,"lon":None}

def success_result(**extras):
    return {"identified":True,"confirmed":True,"cached":False,"slug":"synthetic-tower",
        "found":SimpleNamespace(name="Synthetic Tower",kind="tower",qid="Q1",articles={}),
        "order":[],"kept":[],"timeline":[],"chosen":[],"result":{"outcome":"full_film"},
        "timings":{},"failures":[],"comparison":None,"tokens":{},"cost_usd":0.0,**extras}

def test_n01_ambiguous_failure_releases_all_budget(tmp_path):
    models.configure_spending(tmp_path,daily_cap_usd=0.10)
    def create(**kwargs):
        raise TimeoutError("synthetic response lost after provider work")
    client=SimpleNamespace(responses=SimpleNamespace(create=create))
    with pytest.raises(TimeoutError): models.respond(client,models.VERIFY)
    assert models._DAILY.total_usd()==models._DAILY.reserved_usd()==0

def test_n02_actual_cost_exceeds_reserved_ceiling(tmp_path):
    models.configure_spending(tmp_path,daily_cap_usd=0.10)
    client=SimpleNamespace(responses=SimpleNamespace(create=lambda **kw:{"usage":{"input_tokens":100000,"output_tokens":2048}}))
    models.respond(client,models.VERIFY,input="A "*100000)
    assert models._DAILY.total_usd()>0.10

def test_n03_budget_ticket_can_reconcile_twice(tmp_path):
    authority=models.BudgetAuthority(tmp_path,daily_cap_usd=0.20)
    first=authority.reserve(0.10); authority.reserve(0.10)
    authority.reconcile(first,0.01); authority.reconcile(first,0.01)
    assert authority.reserved_usd()==0

def test_n04_empty_account_resets_to_zero(tmp_path):
    authority=models.BudgetAuthority(tmp_path,daily_cap_usd=0.10)
    authority._file().write_text("")
    assert authority.reserve(0.10).ceiling_usd==0.10

def test_n05_nonwiki_tuple_timeout_breaks_pinned_socket(monkeypatch):
    monkeypatch.setattr(web,"resolve_public_ips",lambda host:["93.184.216.34"])
    def connect(address,timeout):
        import socket
        with socket.socket() as s: s.settimeout(timeout)
        raise AssertionError("scalar timeout unexpectedly accepted")
    monkeypatch.setattr(web.socket,"create_connection",connect)
    with pytest.raises(TypeError): verify.fetch_source_text(URL)

def test_n06_total_deadline_not_checked_while_reading(monkeypatch):
    clock=[0.0]
    monkeypatch.setattr(web.time,"monotonic",lambda:clock[0])
    monkeypatch.setattr(web,"assert_public_url",lambda _:None)
    class Resp:
        status_code=200; headers={}
        def iter_content(self,n):
            clock[0]=999.0; yield b"late body"
        def close(self): pass
    assert web.fetch_public(URL,sender=lambda *a,**k:Resp(),total_timeout=1).body==b"late body"

def test_n07_anchor_wrong_object_is_supported():
    quote="The nearby warehouse was built in 1900 beside the old tower."
    result=verify.judge_claim(lambda _:pytest.fail("anchor never asks model"),
        job(anchor="build",passages=[URL+"\n"+quote]))
    assert result["verdict"]=="supported"

def test_n08_generic_completion_quote_is_accepted():
    quote="In 1900 the tower was proposed for reconstruction but never built."
    result=verify.judge_claim(lambda _:answer(quote),job(event="rebuilt",detail="rebuilt",passages=[URL+"\n"+quote]),
        completion_respond=lambda _:verify.text_answer(json.dumps({"completed":True,"quote":"the"})))
    assert result["completed"] is True

def test_n09_evidence_attaches_to_wrong_scene_year():
    scene=evidence_scene(from_year=2000,date_label="2000")
    assert builder.filmable(scene,[evidence_claim()])

def test_n10_changed_claim_with_same_quote_keeps_caption():
    assert builder.filmable(evidence_scene(),[evidence_claim(claim="A different event from the same paragraph.")])

def test_n11_empty_eras_still_successful_film_plan():
    plan=builder.build_timeline([evidence_scene()],{},[evidence_claim()])
    assert plan[-1]["end"]>0 and not any(s["kind"]=="era" for s in plan)

def test_n12_reloaded_unverified_visuals_reach_both_painters(tmp_path,monkeypatch):
    scene=evidence_scene(state={"condition":"standing","description":"UNVERIFIED purple spires"})
    scene["caption_sentence"]["child"]={"text":"I rose with a stone roof."}
    root=tmp_path/"synthetic";root.mkdir()
    (root/"research.json").write_text(json.dumps({"object":{"name":"Tower","country_code":"gb"},"claims":[evidence_claim()],"scenes":[scene]}))
    monkeypatch.setattr(cli,"photo_bytes_clean",lambda _:b"synthetic")
    monkeypatch.setattr(identify,"capture_month",lambda _:None)
    monkeypatch.setattr(paint,"paint_directives",lambda *a:{"season":"summer","excluded":{}})
    seen=[]
    def parallel(*args,**kwargs):
        seen.append((args[2][0]["state"]["description"],kwargs["audience"]))
        return [{"image":None,"verdict":"dropped","attempts":1,"note":"synthetic"}]
    monkeypatch.setattr(paint,"paint_parallel",parallel)
    monkeypatch.setattr(cli,"recover_or_retry",lambda *a,**k:a[8])
    for audience in ("adult","child"):
        assert cli.cmd_paint("synthetic","unused",out_dir=tmp_path,audience=audience,photo_month=1)==0
    assert seen==[("UNVERIFIED purple spires","adult"),("UNVERIFIED purple spires","child")]

def test_n13_caption_bundle_drops_actual_check_evidence(tmp_path,monkeypatch):
    root=tmp_path/"synthetic";root.mkdir()
    claim=evidence_claim()
    scene=evidence_scene();scene.pop("caption_sentence")
    (root/"research.json").write_text(json.dumps({"object":{"name":"Tower"},"claims":[claim],"scenes":[scene]}))
    extra="In 1900 the tower gained a blue roof after the stone roof collapsed."
    monkeypatch.setattr(cli,"caption_texts",lambda *a:{URL:extra})
    monkeypatch.setattr(cli,"recheck_paintings",lambda *a:[])
    seen=[]
    def support(sentence,passages):
        seen.extend(passages);return "supported" if any(extra in p for p in passages) else "unsupported"
    assert cli.cmd_captions("synthetic",out_dir=tmp_path,cache=object(),rewrite_call=lambda *a:"I gained a blue roof.",support_call=support)==0
    saved=json.loads((root/"research.json").read_text())["scenes"][0]["caption_sentence"]
    assert extra not in saved["evidence"]["quote"] and "blue roof" in saved["text"]

def test_n14_spot_accepts_arbitrary_text_with_reused_grounding():
    changes=["1900: roof lost","1950: rebuilt","2000: moved"]
    result=spot.choose(lambda *a:[{"text":f"Invented difference {i}","change":changes[0]} for i in range(3)],b"x",b"y",changes)
    assert result and len(result)==3 and len({d["change"] for d in result})==1

def test_n15_main_film_route_looks_in_wrong_directory(tmp_path):
    client,store=make_client(tmp_path)
    directory=tmp_path/"private-job";film=directory/"synthetic-tower"/"film";film.mkdir(parents=True)
    (film/"film.html").write_text("synthetic film")
    store.create_job("id",new_record(directory))
    assert client.get("/film/id/synthetic-capability/film.html").status_code==404

def test_n16_example_without_slash_breaks_relative_assets(tmp_path):
    from urllib.parse import urljoin
    client,store=make_client(tmp_path,examples=[{"slug":"demo","name":"Demo"}])
    directory=tmp_path/"examples"/"demo";directory.mkdir(parents=True)
    (directory/"film.html").write_text('<img src="today.jpg">')
    (directory/"today.jpg").write_bytes(b"synthetic fixture; not an image")
    page=client.get("/examples/demo")
    assert page.status_code==200
    assert client.get(urljoin(str(page.url),"today.jpg")).status_code==404

def test_n17_error_and_origin_rejection_miss_security_headers(tmp_path):
    def broken(spec): raise RuntimeError("synthetic")
    client,_=make_client(tmp_path,runner=broken)
    bad=client.post("/api/jobs",headers={"Origin":"https://foreign.invalid"})
    assert bad.status_code==403 and "content-security-policy" not in bad.headers
    buf=io.BytesIO();Image.new("RGB",(8,8)).save(buf,format="PNG")
    failed=client.post("/api/jobs",files={"photo":("x.png",buf.getvalue())},data={"ack":"on"})
    assert failed.status_code==500 and "content-security-policy" not in failed.headers

def test_n18_origin_substring_bypass(tmp_path):
    client,_=make_client(tmp_path)
    response=client.post("/api/jobs",headers={"Origin":"https://testserver.attacker.invalid"})
    assert response.status_code!=403

def test_n19_cancelled_and_crashed_jobs_never_expire(tmp_path):
    directory=tmp_path/"job";directory.mkdir();(directory/"derivative.txt").write_text("synthetic")
    store=webapp.MemoryStore();store.create_job("id",new_record(directory));store.set_cancel("id")
    assert webapp.prune_jobs(store,10*webapp.RETENTION_SECONDS)==0
    assert directory.exists()

def test_n20_browser_location_is_not_forwarded_to_identify(tmp_path,monkeypatch):
    spec=new_spec(tmp_path);spec.update(lat=1.25,lon=2.25)
    store=webapp.MemoryStore();store.create_job(spec["job_id"],new_record(tmp_path))
    seen=[]
    def run(*a,**kw):
        seen.append(kw["location"]);return {"identified":False}
    monkeypatch.setattr(cli,"run_job",run)
    webfilm.run_web_film(spec,store,SimpleNamespace())
    assert seen==[None]

def test_n21_render_phase_cancel_escapes_and_leaves_working_job(tmp_path,monkeypatch):
    spec=new_spec(tmp_path);store=webapp.MemoryStore();store.create_job(spec["job_id"],new_record(tmp_path))
    monkeypatch.setattr(cli,"run_job",lambda *a,**k:success_result())
    monkeypatch.setattr(cli,"report_and_save",lambda *a,**k:None)
    def stop(*a,**kw): raise models.JobCancelled("synthetic")
    monkeypatch.setattr(cli,"cmd_captions",stop)
    with pytest.raises(models.JobCancelled): webfilm.run_web_film(spec,store,SimpleNamespace())
    assert store.get_job(spec["job_id"])["status"]=="working"

def test_n22_headers_allow_inline_styles(tmp_path):
    client,_=make_client(tmp_path)
    assert "style-src 'unsafe-inline'" in client.get("/").headers["content-security-policy"]

def test_n23_original_upload_file_descriptor_is_not_closed(tmp_path,monkeypatch):
    import os
    client,_=make_client(tmp_path);seen=[]
    original=webapp.tempfile.mkstemp
    def mkstemp(*a,**k):
        fd,path=original(*a,**k);seen.append(fd);return fd,path
    monkeypatch.setattr(webapp.tempfile,"mkstemp",mkstemp)
    buf=io.BytesIO();Image.new("RGB",(8,8)).save(buf,format="PNG")
    client.post("/api/jobs",files={"photo":("x.png",buf.getvalue())},data={"ack":"on"})
    try:
        assert seen and os.fstat(seen[0]).st_size>0
    finally:
        for fd in seen: os.close(fd)

def test_n24_pixel_limit_checked_after_decode(tmp_path,monkeypatch):
    seen=[]
    class FakeImage:
        size=(100000,100000); format="PNG"
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def load(self):seen.append("decoded")
        def convert(self,*a):return self
    path=tmp_path/"synthetic.dat";path.write_bytes(b"fake")
    monkeypatch.setattr(photo.Image,"open",lambda *a:FakeImage())
    monkeypatch.setattr(photo.ImageOps,"exif_transpose",lambda x:x)
    with pytest.raises(photo.PhotoError):photo.load_clean(path)
    assert seen==["decoded"]

def test_n25_recorder_partial_extension_has_no_muxer(tmp_path):
    import subprocess,shutil
    binary=shutil.which("ffmpeg")
    if not binary:pytest.skip("ffmpeg unavailable")
    result=subprocess.run([binary,"-v","error","-f","lavfi","-i","color=c=black:s=16x16", "-frames:v","1","-c:v","libx264",str(tmp_path/"film.mp4.partial")],capture_output=True)
    assert result.returncode!=0 and b"output format" in result.stderr.lower()

def test_n26_canonical_country_and_municipality_are_saved(tmp_path):
    found=SimpleNamespace(name="Tower",kind="tower",qid="Q1",articles={},municipality="SYNTHETIC_TOWN",country_code="gb")
    slug=cli.report_and_save(found,"en",[],[],[],[],{}, {},"baseten",[],None,out_root=tmp_path,quiet=True)
    saved=json.loads((tmp_path/slug/"research.json").read_text())
    assert saved["object"]["municipality"]=="SYNTHETIC_TOWN" and saved["object"]["country_code"]=="gb"

def test_n27_raw_source_prompts_lack_delimiters():
    prompts=[captions.sentence_prompt("fact","untrusted source",1900),children.rewrite_prompt("adult","untrusted source"),spot.spot_prompt(["untrusted source"])]
    assert all(verify.SOURCE_DATA_NOTE not in p and verify.SOURCE_BEGIN not in p for p in prompts)

def test_n28_computed_sort_year_becomes_anchor():
    scene=evidence_scene(from_year=1026,date_label="around a thousand years ago")
    assert builder.anchor_card(scene)["label"]=="1026"

def test_n29_child_switch_resolves_assets_against_adult_page():
    from urllib.parse import urljoin
    page="https://example.org/film/id/cap/film.html"
    sibling="child/film.json"
    child={"photo":"today.jpg","sibling":"../film.json","spot":"spot.html"}
    template=Path(builder.__file__).with_name("film.html").read_text()
    assert "start(next)" in template
    assert urljoin(page,child["photo"])!=urljoin(urljoin(page,sibling),child["photo"])
    assert urljoin(page,child["spot"]).endswith("/cap/spot.html")


def test_n30_modal_dict_update_loses_concurrent_cancel(monkeypatch,tmp_path):
    import ast, copy
    tree=ast.parse(Path('/tmp/witness-c3d7087/modal_app.py').read_text())
    node=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='DictStore')
    namespace={}
    exec(compile(ast.Module(body=[node],type_ignores=[]),'modal_dict_store','exec'),namespace)
    class RemoteDict(dict):
        def __getitem__(self,key):return copy.deepcopy(super().__getitem__(key))
        def __setitem__(self,key,value):super().__setitem__(key,copy.deepcopy(value))
    store=namespace['DictStore'](RemoteDict())
    store.create_job('id',new_record(tmp_path,status='started'))
    original=store._save
    raced=[False]
    def save(job_id,job):
        if not raced[0]:
            raced[0]=True;store.set_cancel(job_id)
        original(job_id,job)
    monkeypatch.setattr(store,'_save',save)
    store.set_status('id','working')
    assert store.is_cancelled('id') is False


def test_n31_previous_day_ticket_releases_new_day_reservation(tmp_path,monkeypatch):
    authority=models.BudgetAuthority(tmp_path,daily_cap_usd=0.10)
    current=[tmp_path/'day-one.json']
    monkeypatch.setattr(authority,'_file',lambda:current[0])
    old=authority.reserve(0.10)
    current[0]=tmp_path/'day-two.json'
    authority.reserve(0.10)
    authority.reconcile(old,0)
    assert authority.reserved_usd()==0


def test_n32_multipart_consumed_before_upload_size_gate(tmp_path,monkeypatch):
    import asyncio
    monkeypatch.setattr(photo,'MAX_UPLOAD_BYTES',8)
    store=webapp.MemoryStore()
    app=webapp.create_app(webapp.WebDeps(store,None,lambda _:None,tmp_path/'jobs',tmp_path/'examples'))
    body=(b'--synthetic\r\nContent-Disposition: form-data; name="ack"\r\n\r\non\r\n'
          b'--synthetic\r\nContent-Disposition: form-data; name="photo"; filename="x.png"\r\nContent-Type: image/png\r\n\r\n'+b'X'*65536+b'\r\n--synthetic--\r\n')
    chunks=[body[i:i+4096] for i in range(0,len(body),4096)]
    count=[0];sent=[]
    async def receive():
        if count[0]<len(chunks):
            chunk=chunks[count[0]];count[0]+=1
            return {'type':'http.request','body':chunk,'more_body':count[0]<len(chunks)}
        await asyncio.sleep(0.01)
        return {'type':'http.disconnect'}
    async def send(message):sent.append(message)
    scope={'type':'http','asgi':{'version':'3.0'},'http_version':'1.1','method':'POST','scheme':'http',
        'path':'/api/jobs','raw_path':b'/api/jobs','query_string':b'',
        'headers':[(b'host',b'testserver'),(b'content-type',b'multipart/form-data; boundary=synthetic')],
        'server':('testserver',80),'client':('synthetic-client',1),'root_path':''}
    asyncio.run(app(scope,receive,send))
    assert count[0]==len(chunks)
    assert next(m['status'] for m in sent if m['type']=='http.response.start')==400


def test_n33_search_snippets_crowd_out_real_fetched_evidence():
    claim=evidence_claim(sources=[URL],visible_change='stone roof')
    jobs=cli.build_jobs([claim],{URL:QUOTE},['https://example.org/: snippet']*13,1900)
    assert jobs and all(verify._fetched_para(p) is None for p in jobs[0]['passages'])
