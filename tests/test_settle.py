import base64
from decimal import Decimal
import pytest
from app.workflow import load,run
from app.errors import DomainError
from app import store

ROSTER=[{'employee':'E201','shift_day':'2026-10-01','shift_start':'22:00','shift_end':'06:00'},
    {'employee':'E203','shift_day':'2026-10-01','shift_start':'22:00','shift_end':'06:00'}]
CUTOFF='2026-10-31T23:59:59+08:00'

def params(status='待批',approved_at='',settle='付薪',cutoff=CUTOFF,roster=ROSTER):
    return {'roster':roster,'cutoff':cutoff,
        'substitutions':[{'id':'SUB-1','shift_day':'2026-10-01','scheduled':'E201','actual':'E202',
            'status':status,'approved_at':approved_at,'settle':settle}]}

@pytest.fixture
def sub():return load('substitute.csv')

def row(state,actual):return next(r for r in state['settle']['payables'] if r['actual']==actual)

def test_no_roster_everything_payable():
    s=run(load('clean.csv'),{})
    settle=s['settle']
    assert settle['balanced'] and all(r['status']=='可付' for r in settle['payables'])
    assert all(r['payee']==r['actual']==r['scheduled'] and r['basis']=='排班' for r in settle['payables'])
    assert settle['totals']['payable']==s['business']['total'] and settle['totals']['held']=='0.00'

def test_unapproved_substitution_held_not_paid(sub):
    s=run(sub,params())
    held=row(s,'E202');normal=row(s,'E203')
    assert held['status']=='挂起' and held['basis']=='无有效审批' and held['payable']=='0.00' and held['payee']==''
    assert held['scheduled']=='E201' and held['amount']=='220.00'
    assert normal['status']=='可付' and normal['payable']=='220.00'
    settle=s['settle']
    assert settle['totals']['payable']=='220.00' and settle['totals']['held']=='220.00'
    assert 'E202' not in settle['by_employee'] and settle['by_employee']['E203']['minutes']==420

def test_approved_before_cutoff_pays_actual(sub):
    s=run(sub,params(status='已批准',approved_at='2026-10-30T09:00:00+08:00'))
    paid=row(s,'E202')
    assert paid['status']=='可付' and paid['payee']=='E202' and paid['payable']=='220.00'
    assert paid['basis']=='替班审批 SUB-1' and paid['approval']=='SUB-1'
    settle=s['settle']
    assert settle['totals']['payable']=='440.00' and settle['totals']['held']=='0.00'
    assert settle['by_employee']['E202']['minutes']==420 and 'E201' not in settle['by_employee']
    assert settle['approvals'][0]['applied'] is True

def test_approved_after_cutoff_still_held(sub):
    s=run(sub,params(status='已批准',approved_at='2026-11-02T09:00:00+08:00'))
    assert row(s,'E202')['status']=='挂起' and s['settle']['totals']['payable']=='220.00'

def test_comp_settlement_converts_to_leave(sub):
    s=run(sub,params(status='已批准',approved_at='2026-10-30T09:00:00+08:00',settle='调休'))
    comp=row(s,'E202')
    assert comp['status']=='调休' and comp['comp_employee']=='E202' and comp['comp_minutes']==420
    assert comp['payable']=='0.00' and comp['payee']==''
    settle=s['settle']
    assert settle['totals']['payable']=='220.00' and settle['totals']['comp_amount']=='220.00'
    assert settle['by_employee']['E202']['comp_minutes']==420

def test_minutes_and_money_have_exactly_one_destination(sub):
    for p in (params(),params(status='已批准',approved_at='2026-10-30T09:00:00+08:00'),
            params(status='已批准',approved_at='2026-10-30T09:00:00+08:00',settle='调休')):
        s=run(sub,p);settle=s['settle']
        assert settle['balanced'] is True
        total=Decimal(settle['totals']['payable'])+Decimal(settle['totals']['held'])+Decimal(settle['totals']['comp_amount'])
        assert total==Decimal(s['business']['total'])
        assert settle['totals']['minutes']==s['business']['minutes']
        attributed=sum(b['minutes'] for b in settle['by_employee'].values())
        held_minutes=sum(r['minutes'] for r in settle['payables'] if r['status']=='挂起')
        assert attributed+held_minutes+settle['totals']['comp_minutes']==settle['totals']['minutes']

def test_double_coverage_same_shift_held():
    csv=('id,employee,shift_day,version,punch,at,shift_start,shift_end,break_start,break_end,hourly_rate,paid,note\n'
        '1,E202,2026-10-01,1,IN,2026-10-01T22:00:00+08:00,22:00,06:00,02:00,03:00,20,0,顶班一\n'
        '2,E202,2026-10-01,1,OUT,2026-10-02T06:00:00+08:00,22:00,06:00,02:00,03:00,20,0,顶班一\n'
        '3,E204,2026-10-01,1,IN,2026-10-01T22:00:00+08:00,22:00,06:00,02:00,03:00,20,0,顶班二\n'
        '4,E204,2026-10-01,1,OUT,2026-10-02T06:00:00+08:00,22:00,06:00,02:00,03:00,20,0,顶班二\n')
    p={'roster':[{'employee':'E201','shift_day':'2026-10-01','shift_start':'22:00','shift_end':'06:00'}]}
    s=run(csv.encode(),p)
    assert all(r['status']=='挂起' and r['basis']=='重复顶班' for r in s['settle']['payables'])
    assert s['settle']['totals']['payable']=='0.00' and s['settle']['balanced']

def test_roster_conflict_held(sub):
    p=params(roster=[{'employee':'E201','shift_day':'2026-10-01','shift_start':'22:00','shift_end':'06:00'},
        {'employee':'E205','shift_day':'2026-10-01','shift_start':'22:00','shift_end':'06:00'}])
    s=run(sub,p)
    assert row(s,'E202')['basis']=='排班冲突' and row(s,'E202')['status']=='挂起'

def test_unrostered_punch_held(sub):
    p=params(roster=[{'employee':'E203','shift_day':'2026-10-01','shift_start':'22:00','shift_end':'06:00'}])
    s=run(sub,p)
    assert row(s,'E202')['basis']=='未排班打卡' and row(s,'E202')['status']=='挂起'
    assert row(s,'E203')['status']=='可付'

def test_invalid_approval_ignored_and_listed(sub):
    p=params();p['substitutions']=[{'id':'BAD','shift_day':'2026-10-01','status':'已批准'}]
    s=run(sub,p)
    assert row(s,'E202')['status']=='挂起'
    assert any(i['code']=='APPROVAL_INVALID' for i in s['settle']['issues'])

def test_unmatched_approval_listed(sub):
    p=params();p['substitutions']=[{'id':'SUB-9','shift_day':'2026-10-05','scheduled':'E201','actual':'E202','status':'待批'}]
    s=run(sub,p)
    assert any(i['code']=='APPROVAL_UNMATCHED' for i in s['settle']['issues'])

def test_invalid_cutoff_fails_run(sub):
    p=params(cutoff='2026-10-31')
    with pytest.raises(DomainError) as e:run(sub,p)
    assert e.value.code=='CUTOFF'

def test_idempotent_rerun_never_double_pays(sub,tmp_path,monkeypatch):
    monkeypatch.setenv('DB_PATH',str(tmp_path/'r.db'))
    p=params(status='已批准',approved_at='2026-10-30T09:00:00+08:00')
    a=run(sub,p);b=run(sub,p)
    assert a['run_id']==b['run_id'] and a['settle']['payables']==b['settle']['payables']
    store.save(a['run_id'],a);store.save(b['run_id'],b)
    assert len(store.history())==1 and store.latest_id()==a['run_id']

def test_approval_change_supersedes_old_result(sub,tmp_path,monkeypatch):
    monkeypatch.setenv('DB_PATH',str(tmp_path/'r.db'))
    held=run(sub,params());store.save(held['run_id'],held)
    approved=run(sub,params(status='已批准',approved_at='2026-10-30T09:00:00+08:00'));store.save(approved['run_id'],approved)
    assert held['run_id']!=approved['run_id'] and store.latest_id()==approved['run_id']
    marks={h['id']:h['current'] for h in store.history()}
    assert marks[approved['run_id']] is True and marks[held['run_id']] is False
    old=store.get(held['run_id'])
    assert row(old,'E202')['status']=='挂起' and row(store.get(approved['run_id']),'E202')['status']=='可付'

def test_failed_replacement_keeps_old_run_and_records(sub,tmp_path,monkeypatch):
    monkeypatch.setenv('DB_PATH',str(tmp_path/'r.db'))
    good=run(sub,params());store.save(good['run_id'],good)
    with pytest.raises(DomainError):run(b'wrong\n1\n',{})
    assert store.latest_id()==good['run_id']
    kept=store.get(good['run_id'])
    assert base64.b64decode(kept['source_b64'])==sub
    assert kept['settle']['payables']==good['settle']['payables']
    assert kept['manifest']['parameters']['substitutions'][0]['id']=='SUB-1'

def test_quarantine_raw_survives_replacement(sub,tmp_path,monkeypatch):
    monkeypatch.setenv('DB_PATH',str(tmp_path/'r.db'))
    dirty=run(load('dirty.csv'),{});store.save(dirty['run_id'],dirty)
    newer=run(sub,params());store.save(newer['run_id'],newer)
    kept=store.get(dirty['run_id'])
    assert len(kept['quarantine'])==len(dirty['quarantine']) and all(q['raw'] for q in kept['quarantine'])
