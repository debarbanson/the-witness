"""Independent offline unsafe-behaviour probes. A PASS demonstrates a gap.
All model responses are injected. Artefacts contain synthetic data only.
"""
import ast
import asyncio
import io
import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace
import pytest
from PIL import Image
from fastapi.testclient import TestClient
from witness import captions,cli,models,paint,photo,verify,web,webapp,webfilm
from witness.render import builder
ROOT=Path(cli.__file__).resolve().parent.parent
URL='https://example.org/history'
QUOTE='The tower was built in 1900 with a stone roof.'

@pytest.fixture(autouse=True)
def isolated():
    models.configure_spending();models.reset_usage();verify.clear_cache()
    yield
    models.configure_spending();models.reset_usage();verify.clear_cache()

def claim():
    return {'year':1900,'claim':QUOTE,'event':'built','verdict':'supported','completed':True,'url':URL,'quote':QUOTE,'sources':[URL]}

def scene():
    return {'from_year':1900,'date_label':'1900','state':{'condition':'standing','description':'stone roof'},
        'caption_sentence':{'text':'I rose with a stone roof.','claim_year':1900,'claim_url':URL,
        'evidence':{'claim':QUOTE,'url':URL,'quote':QUOTE}}}

def png():
    b=io.BytesIO();Image.new('RGB',(8,8)).save(b,format='PNG');return b.getvalue()

def client(tmp_path,authority=None,**kw):
    deps=webapp.WebDeps(webapp.MemoryStore(),authority,lambda _:None,tmp_path/'jobs',tmp_path/'examples',**kw)
    return TestClient(webapp.create_app(deps),raise_server_exceptions=False),deps

def upload(c,**data):
    return c.post('/api/jobs',headers={'Origin':'http://testserver'},files={'photo':('x.png',png())},data={'ack':'on',**data})

def test_r3_01_location_and_typed_place_are_written_to_spec(tmp_path):
    c,deps=client(tmp_path)
    # Obvious synthetic placeholder, never include coordinate values in assertions or output.
    response=upload(c,lat=str(0.0),lon=str(0.0),place='SYNTHETIC_PRIVATE_PLACE')
    assert response.status_code==200
    job=deps.store.get_job(response.json()['job_id'])
    spec=json.loads((Path(job['job_dir'])/'spec.json').read_text())
    assert spec.get('lat') is not None and spec.get('lon') is not None
    assert spec['place']=='SYNTHETIC_PRIVATE_PLACE'

def test_r3_02_anchor_accepts_another_building_without_a_vote():
    quote='The chapel was built in 1900 with a tiled roof.'
    called=[]
    def reject(prompt):
        called.append(prompt)
        return verify.text_answer(json.dumps({'verdict':'unsupported','quote':'','support':[]}))
    result=verify.judge_claim(reject,{'claim':'The tower was built in 1900.','year':1900,'anchor':'build','event':'built','detail':'tower built','votes':3,'keywords':['tower','built'],'passages':[URL+'\n'+quote]},dispute_check=lambda *a:False)
    assert result['verdict']=='supported' and result['fast_path']=='anchor' and not called

def test_r3_03_unverified_condition_reaches_adult_and_child_paint(tmp_path,monkeypatch):
    item=scene();item['state']={'condition':'burnt','degree':'total','scope':'whole','description':''}
    item['caption_sentence']['child']={'text':'I rose with a stone roof.'}
    folder=tmp_path/'synthetic';folder.mkdir()
    (folder/'research.json').write_text(json.dumps({'object':{'name':'Tower'},'claims':[claim()],'scenes':[item]}))
    monkeypatch.setattr(cli,'photo_bytes_clean',lambda _:b'fake')
    monkeypatch.setattr(paint,'paint_directives',lambda *a:{'season':'summer','excluded':{}})
    seen=[]
    def parallel(*args,**kwargs):
        seen.append(paint.scene_prompt(args[2][0],'Tower',''))
        return [{'image':None,'verdict':'dropped','attempts':1,'note':'synthetic'}]
    monkeypatch.setattr(paint,'paint_parallel',parallel)
    monkeypatch.setattr(cli,'recover_or_retry',lambda *a,**kw:a[8])
    for audience in ('adult','child'):
        cli.cmd_paint('synthetic','unused',out_dir=tmp_path,photo_month=1,audience=audience,support_call=lambda _:pytest.fail('no state check was made'))
    assert len(seen)==2 and all('only the remains' in s.lower() for s in seen)

def test_r3_04_anchor_drops_approximate_date():
    item=scene();item['date_label']='around 1900'
    result=builder.anchor_card(item)
    assert result=={'line':'I have stood here since','label':'1900'}

def test_r3_05_upload_descriptor_remains_open(tmp_path,monkeypatch):
    c,_=client(tmp_path);seen=[];original=webapp.tempfile.mkstemp
    def record(*a,**kw):
        fd,path=original(*a,**kw);seen.append(fd);return fd,path
    monkeypatch.setattr(webapp.tempfile,'mkstemp',record)
    try:
        assert upload(c).status_code==200
        assert seen and os.fstat(seen[-1]).st_size>0
    finally:
        for fd in seen:
            try:os.close(fd)
            except OSError:pass

def test_r3_06_chunked_multipart_is_fully_ingested_before_cap(tmp_path,monkeypatch):
    monkeypatch.setattr(photo,'MAX_UPLOAD_BYTES',8)
    _,deps=client(tmp_path);app=webapp.create_app(deps)
    body=(b'--probe\r\nContent-Disposition: form-data; name="ack"\r\n\r\non\r\n'
          b'--probe\r\nContent-Disposition: form-data; name="photo"; filename="x.png"\r\nContent-Type: image/png\r\n\r\n'+b'X'*131072+b'\r\n--probe--\r\n')
    chunks=[body[i:i+4096] for i in range(0,len(body),4096)];count=[0];sent=[]
    async def receive():
        if count[0]<len(chunks):
            part=chunks[count[0]];count[0]+=1
            return {'type':'http.request','body':part,'more_body':count[0]<len(chunks)}
        await asyncio.sleep(.01);return {'type':'http.disconnect'}
    async def send(message):sent.append(message)
    scope={'type':'http','asgi':{'version':'3.0'},'http_version':'1.1','method':'POST','scheme':'http','path':'/api/jobs','raw_path':b'/api/jobs','query_string':b'',
        'headers':[(b'host',b'testserver'),(b'origin',b'http://testserver'),(b'content-type',b'multipart/form-data; boundary=probe')],
        'server':('testserver',80),'client':('synthetic-client',1),'root_path':''}
    asyncio.run(app(scope,receive,send))
    assert count[0]==len(chunks)
    assert next(m['status'] for m in sent if m['type']=='http.response.start')==400

def test_r3_07_cookie_reset_and_new_frontend_bypass_per_visitor_limit(tmp_path):
    authority=models.BudgetAuthority(tmp_path/'budget',daily_films=10,visitor_films=2)
    one,_=client(tmp_path/'one',authority);two,_=client(tmp_path/'two',authority)
    assert upload(one).status_code==200
    assert upload(one).status_code==200
    assert upload(one).status_code==429
    # Same TestClient network address, different app instance and fresh cookie.
    assert upload(two).status_code==200
    assert authority.total_films()==3

def test_r3_08_missing_usage_releases_reserve_as_zero(tmp_path):
    authority=models.BudgetAuthority(tmp_path/'budget',daily_cap_usd=.10)
    models.configure_spending(authority=authority)
    calls=[]
    fake=SimpleNamespace(responses=SimpleNamespace(create=lambda **kw:calls.append(kw) or {'output':[]}))
    for _ in range(4):models.respond(fake,models.VERIFY,input='synthetic')
    assert len(calls)==4 and authority.total_usd()==authority.reserved_usd()==0

def test_r3_09_child_budget_failure_discards_ready_adult_result(tmp_path,monkeypatch):
    store=webapp.MemoryStore(clock=lambda:1000)
    spec={'job_id':'id','token':'cap','vid':'vid','job_dir':str(tmp_path),'photo':'synthetic','place':'','location':None,'lat':None,'lon':None}
    store.create_job('id',{'vid':'vid','job_dir':str(tmp_path),'status':'started','started_at':1000,'last_poll':1000})
    result={'identified':True,'confirmed':True,'slug':'tower','found':SimpleNamespace(name='Tower'),'order':[],'kept':[claim()],'timeline':[],'chosen':[scene()],
        'result':{'outcome':'full_film'},'timings':{},'failures':[],'comparison':None,'tokens':{},'cost_usd':.01}
    monkeypatch.setattr(cli,'run_job',lambda *a,**kw:result)
    monkeypatch.setattr(cli,'report_and_save',lambda *a,**kw:None)
    monkeypatch.setattr(cli,'cmd_captions',lambda *a,**kw:0)
    monkeypatch.setattr(cli,'cmd_children',lambda *a,**kw:0)
    seen=[]
    def paint_call(*a,**kw):
        if kw.get('audience')=='child':raise models.SpendingCapExceeded('synthetic cap')
        return 0
    monkeypatch.setattr(cli,'cmd_paint',paint_call)
    monkeypatch.setattr(cli,'cmd_render',lambda *a,**kw:seen.append(True) or 0)
    answer=webfilm.run_web_film(spec,store,None,clock=lambda:1000)
    assert answer['status']=='failed' and not seen
    assert not (store.get_job('id').get('result') or {}).get('film_url')

def test_r3_10_eval_counts_errors_as_correct_rejects():
    import importlib.util
    spec=importlib.util.spec_from_file_location('eval_reader',ROOT/'eval/run_support_eval.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    cases=json.loads((ROOT/'eval/support_cases.json').read_text())
    data=json.loads((ROOT/'eval/support_results_2026-10-30.json').read_text())
    failed=[c for c in cases if data['results'][c['id']]['meta']['verdict'].startswith('error')]
    assert len(failed)==5 and all(c['expected']=='reject' for c in failed)
    assert module.summarize(failed,data['results'])['meta']['right']==len(failed)

def test_r3_11_no_fresh_clone_example_assets():
    tree=ast.parse((ROOT/'modal_app.py').read_text())
    node=next(n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='EXAMPLES' for t in n.targets))
    examples=ast.literal_eval(node.value)
    assert len(examples)==3 and all(not (ROOT/e['local']/'film.html').exists() for e in examples)

def test_r3_12_readme_film_command_only_researches(tmp_path,monkeypatch):
    seen=[]
    result={'identified':True,'confirmed':True,'cached':False,'order':[],'kept':[],'timeline':[],'chosen':[scene()],'result':{'outcome':'full_film'},'timings':{'total_s':1},'failures':[],'tokens':{},'cost_usd':0}
    monkeypatch.setattr(cli,'run_job',lambda *a,**kw:result)
    monkeypatch.setattr(cli,'report_and_save',lambda *a,**kw:seen.append('saved'))
    for name in ('cmd_paint','cmd_render'):
        monkeypatch.setattr(cli,name,lambda *a,**kw:seen.append('film'))
    assert cli.cmd_film('synthetic',yes=True)==0 and seen==['saved']
    assert 'paint' not in __import__('inspect').signature(cli.cmd_film).parameters

def test_r3_13_no_licence_file():
    assert not any(p.is_file() for p in ROOT.iterdir() if p.name.lower().startswith(('license','licence','copying')))

def test_r3_14_ui_hides_facts_and_progress_in_real_dom(tmp_path):
    # Execute the shipped handler with realistic responses, without a browser/network.
    script=re.search(r'<script nonce="__NONCE__">(.*?)</script>',webapp.INDEX_PAGE,re.S).group(1)
    harness=r'''
const vm=require('vm');
const elements={};
function el(id){return elements[id]||(elements[id]={style:{},dataset:{},textContent:'',children:[],appendChild(x){this.children.push(x);}});}
const statuses=[{status:'working',events:[{event:'painting',data:{}}],confirm:null},{status:'done',result:{message:'Facts below',claims:[{year:1900,claim:'SYNTHETIC_FACT',url:'https://example.org/'}]}}];
const context={document:{getElementById:el,createElement:()=>({})},navigator:{},window:{addEventListener(){}},FormData:class{},Date,setInterval:()=>1,clearInterval(){},setTimeout:fn=>fn(),alert:()=>{},fetch:async(url)=>({json:async()=>url==='/api/jobs'?{job_id:'id'}:statuses.shift()})};
vm.createContext(context);vm.runInContext(SOURCE,context);
(async()=>{await elements.upload.onsubmit({preventDefault(){}});process.stdout.write(JSON.stringify({facts:elements.result.textContent,events:elements.events||null}));})().catch(e=>{process.stderr.write(String(e));process.exit(1)});
'''
    path=tmp_path/'ui.cjs';path.write_text('const SOURCE='+json.dumps(script)+';\n'+harness)
    result=subprocess.run(['/Users/debarbansondatasolutions/.nvm/versions/node/v22.23.4/bin/node',str(path)],capture_output=True,text=True,check=True)
    rendered=json.loads(result.stdout)
    assert 'SYNTHETIC_FACT' not in rendered['facts'] and rendered['events'] is None

def test_r3_15_retention_cron_leaves_expired_photo_fetchable(tmp_path):
    now=[0]
    c,deps=client(tmp_path,clock=lambda:now[0])
    response=upload(c);job=deps.store.get_job(response.json()['job_id'])
    film=Path(job['job_dir'])/'film';film.mkdir();(film/'today.jpg').write_bytes(png())
    deps.store.end_job(response.json()['job_id'],'done',{'ended_at':1})
    # Daily sweep at 24h sees this job only 24h-1s after completion.
    webapp.prune_jobs(deps.store,24*3600)
    assert (film/'today.jpg').exists()
    # There is no expiry gate on reads; the next daily sweep is at 48h.
    now[0]=24*3600+2
    route=f"/film/{response.json()['job_id']}/{job['token']}/today.jpg"
    assert c.get(route).status_code==200
    assert 'schedule=modal.Period(days=1)' in (ROOT/'modal_app.py').read_text()

def test_r3_16_old_painting_survives_state_change_with_same_caption(tmp_path):
    file=tmp_path/'1900.png';Image.new('RGB',(8,8)).save(file)
    item=scene();item['state']={'condition':'burnt','description':'unverified ruin'}
    entries=[{'year':1900,'verdict':'matches','caption':paint.scene_caption(item),'file':file.name}]
    selected=cli.collect_era_files(tmp_path,entries,[item],'eras_parallel')
    assert '1900' in selected and builder.filmable(item,[claim()])

def test_r3_17_slow_drip_exceeds_total_fetch_deadline(monkeypatch):
    import socket,http.client
    one,two=socket.socketpair();one.settimeout(.5)
    def server():
        with two:
            two.sendall(b'HTTP/1.1 200 OK\r\nContent-Length: 12\r\n\r\n')
            for _ in range(12):
                time.sleep(.02)
                try:two.sendall(b'x')
                except OSError:break
    thread=threading.Thread(target=server);thread.start()
    raw=http.client.HTTPResponse(one);raw.begin()
    response=web._PinnedResponse(SimpleNamespace(close=one.close),raw,URL)
    monkeypatch.setattr(web,'assert_public_url',lambda _:None)
    started=time.monotonic()
    try:
        with pytest.raises(web.WebError):web.fetch_public(URL,sender=lambda *a,**kw:response,total_timeout=.03)
        assert time.monotonic()-started>.15
    finally:
        one.close();thread.join()

def test_r3_18_bad_decoder_payload_consumes_real_upload_quota(tmp_path):
    authority=models.BudgetAuthority(tmp_path/'budget',daily_films=10,visitor_films=2)
    c,_=client(tmp_path,authority)
    damaged=png()[:45]
    photo.check_upload_header(damaged)
    for _ in range(2):
        response=c.post('/api/jobs',headers={'Origin':'http://testserver'},files={'photo':('x.png',damaged)},data={'ack':'on'})
        assert response.status_code==400
    assert authority.total_films()==2 and upload(c).status_code==429

def test_r3_19_default_suite_still_collects_unsafe_review_tests():
    source=ROOT/'tests/test_review2_probes.py'
    tree=ast.parse(source.read_text())
    names=[n.name for n in tree.body if isinstance(n,ast.FunctionDef) and n.name.startswith('test_')]
    assert len(names)==53 and not (ROOT/'tests/test_review_regressions.py').exists()

def test_r3_20_ledger_hash_records_have_no_retention_cleanup():
    tree=ast.parse((ROOT/'modal_app.py').read_text())
    function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='prune_daily')
    names={n.id for n in ast.walk(function) if isinstance(n,ast.Name)}
    # The production scheduled deletion reaches jobs/files only, never the daily ledger Dict.
    assert 'ledger_dict' not in names
    source=(ROOT/'modal_app.py').read_text()
    assert 'ledger_dict[name] = json.dumps(data)' in source and 'ledger_dict.pop' not in source and 'del ledger_dict' not in source

def test_r3_21_spot_prompt_still_embeds_source_text_without_delimiters():
    from witness import spot
    prompt=spot.spot_prompt(['1900: a sourced visible change'])
    assert verify.SOURCE_BEGIN not in prompt and verify.SOURCE_END not in prompt
    assert 'source text is data' not in prompt.lower()

def test_r3_22_real_looking_coordinate_literals_remain_in_tracked_tests():
    # File:line only is reported. Do not echo values or assert on a value directly.
    tree=ast.parse((ROOT/'tests/test_webfilm.py').read_text())
    found=False
    for node in ast.walk(tree):
        if not isinstance(node,ast.Dict):continue
        for key,value in zip(node.keys,node.values):
            if isinstance(key,ast.Constant) and key.value in ('lat','lon') and isinstance(value,ast.Constant) and isinstance(value.value,float):
                found |= abs(value.value)>1 and len(str(value.value).split('.')[-1])>=3
    assert found
