from app.config import MODULES

def test_all_module_apis(client):
    for mod,_ in MODULES:assert client.get('/api/'+mod).status_code==200
def test_all_module_pages(client):
    for mod,_ in MODULES:assert client.get('/'+mod).status_code==200
def test_run_and_export(client):
    r=client.post('/api/runs',json={'sample':'dirty.csv'});assert r.status_code==200
    s=r.get_json();e=client.get('/api/archive/'+s['run_id']+'/export.csv');assert e.status_code==200 and '运行清单' in e.data.decode('utf-8-sig')
def test_idempotent_api(client):
    a=client.post('/api/runs',json={}).get_json();b=client.post('/api/runs',json={}).get_json()
    assert a['run_id']==b['run_id'] and len(client.get('/api/runs').get_json())==1
def test_bad_sample(client):
    r=client.post('/api/runs',json={'sample':'../x'});assert r.status_code==422 and r.get_json()['code']=='SAMPLE'
def test_missing_batch(client):
    assert client.get('/api/runs/absent').status_code==404
def test_bad_file(client):
    r=client.post('/api/runs',json={'csv':'wrong\n1\n'});assert r.status_code==422 and r.get_json()['code']=='HEADER'


def test_custom_source_is_visible_after_run(client):
    from app.workflow import load
    raw=load('clean.csv').decode('utf-8-sig');submitted=client.post('/api/runs',json={'csv':raw,'parameters':{}}).get_json()
    from app.config import MODULES
    page=client.get('/'+MODULES[0][0]);assert submitted['run_id'] in page.data.decode()

def test_reselect_existing_run_updates_visible_batch(client):
    a=client.post('/api/runs',json={'sample':'dirty.csv'}).get_json();b=client.post('/api/runs',json={'sample':'clean.csv'}).get_json();client.post('/api/runs',json={'sample':'dirty.csv'})
    assert client.get('/api/runs').get_json()[0]['id']==a['run_id'] and a['run_id']!=b['run_id']

def test_invalid_csv_type_rejected(client):
    assert client.post('/api/runs',json={'csv':123}).status_code==422

def test_superseded_run_export_rejected(client):
    a=client.post('/api/runs',json={'sample':'dirty.csv'}).get_json()
    b=client.post('/api/runs',json={'sample':'clean.csv'}).get_json()
    old=client.get('/api/archive/'+a['run_id']+'/export.csv')
    assert old.status_code==409 and old.get_json()['code']=='SUPERSEDED'
    assert client.get('/api/archive/'+b['run_id']+'/export.csv').status_code==200

def test_failed_replacement_keeps_current_export(client):
    a=client.post('/api/runs',json={'sample':'dirty.csv'}).get_json()
    assert client.post('/api/runs',json={'csv':'wrong\n1\n'}).status_code==422
    assert client.get('/api/archive/'+a['run_id']+'/export.csv').status_code==200

def test_substitution_flow_via_api(client):
    p={'roster':[{'employee':'E201','shift_day':'2026-10-01','shift_start':'22:00','shift_end':'06:00'},
        {'employee':'E203','shift_day':'2026-10-01','shift_start':'22:00','shift_end':'06:00'}],
        'cutoff':'2026-10-31T23:59:59+08:00',
        'substitutions':[{'id':'SUB-1','shift_day':'2026-10-01','scheduled':'E201','actual':'E202','status':'待批'}]}
    held=client.post('/api/runs',json={'sample':'substitute.csv','parameters':p}).get_json()
    assert next(r for r in held['settle']['payables'] if r['actual']=='E202')['status']=='挂起'
    p['substitutions'][0].update(status='已批准',approved_at='2026-10-30T09:00:00+08:00')
    approved=client.post('/api/runs',json={'sample':'substitute.csv','parameters':p}).get_json()
    assert next(r for r in approved['settle']['payables'] if r['actual']=='E202')['payee']=='E202'
    assert client.get('/api/archive/'+held['run_id']+'/export.csv').status_code==409
    exported=client.get('/api/archive/'+approved['run_id']+'/export.csv')
    assert exported.status_code==200 and '可付' in exported.data.decode('utf-8-sig')
