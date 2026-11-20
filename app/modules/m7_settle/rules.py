from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from app.errors import DomainError

CENT=Decimal('0.01')

def _hm(value):
    parts=str(value).strip().split(':')
    if len(parts)<2:raise ValueError('HM')
    return '%02d:%02d'%(int(parts[0]),int(parts[1]))

def _moment(value):
    point=datetime.fromisoformat(str(value).strip().replace('Z','+00:00'))
    if point.tzinfo is None:raise ValueError('TZ')
    return point

def _roster(entries,issues):
    slots=defaultdict(set);members=set()
    if entries in (None,''):return slots,members
    if not isinstance(entries,list):raise DomainError('ROSTER','排班参数必须是数组')
    for i,entry in enumerate(entries):
        try:
            employee=str(entry['employee']).strip();day=str(entry['shift_day']).strip()
            start=_hm(entry['shift_start']);end=_hm(entry['shift_end'])
            if not employee:raise ValueError('EMP')
        except (KeyError,TypeError,ValueError):
            issues.append({'kind':'排班','ref':i,'code':'ROSTER_INVALID','message':'排班条目无效，已忽略'});continue
        slots[(day,start,end)].add(employee);members.add((employee,day,start,end))
    return slots,members

def _approvals(entries,issues):
    ok=[]
    if entries in (None,''):return ok
    if not isinstance(entries,list):raise DomainError('SUBSTITUTION','替班审批参数必须是数组')
    for i,entry in enumerate(entries):
        try:
            item={'id':str(entry.get('id','')).strip() or 'SUB-%d'%(i+1),
                'shift_day':str(entry['shift_day']).strip(),
                'scheduled':str(entry['scheduled']).strip(),
                'actual':str(entry['actual']).strip(),
                'status':str(entry.get('status','待批')).strip(),
                'settle':str(entry.get('settle','付薪')).strip(),
                'approved_at':entry.get('approved_at') or None}
            if not item['scheduled'] or not item['actual']:raise ValueError('EMP')
            if item['status'] not in ('已批准','待批','驳回'):raise ValueError('STATUS')
            if item['settle'] not in ('付薪','调休'):raise ValueError('SETTLE')
            if item['status']=='已批准':
                if not item['approved_at']:raise ValueError('AT')
                item['moment']=_moment(item['approved_at'])
        except (KeyError,TypeError,ValueError,AttributeError):
            ref=entry.get('id',i) if isinstance(entry,dict) else i
            issues.append({'kind':'替班审批','ref':ref,'code':'APPROVAL_INVALID','message':'替班审批无效，不生效'});continue
        ok.append(item)
    return ok

def _money(value):
    return str(value.quantize(CENT))

def adjudicate(state):
    params=state.get('parameters') or {}
    issues=[]
    slots,members=_roster(params.get('roster'),issues)
    approvals=_approvals(params.get('substitutions'),issues)
    cutoff=params.get('cutoff')
    if cutoff in (None,''):cutoff_at=None
    else:
        try:cutoff_at=_moment(cutoff)
        except (ValueError,AttributeError):raise DomainError('CUTOFF','截止时间必须带时区')
    shifts={s['id']:s for s in state.get('shifts',[])}
    grouped=defaultdict(list)
    for calc in state.get('calculations',[]):grouped[calc['id']].append(calc)
    rows=[]
    for sid in sorted(grouped):
        calcs=grouped[sid]
        shift=shifts.get(sid) or {}
        slot=None
        if shift.get('in'):
            try:slot=(calcs[0]['shift_day'],_hm(shift['in']['shift_start']),_hm(shift['in']['shift_end']))
            except (KeyError,ValueError):slot=None
        rows.append({'shift':sid,'shift_day':calcs[0]['shift_day'],'actual':str(calcs[0]['employee']),
            'minutes':sum(c['minutes'] for c in calcs),
            'amount':sum((Decimal(str(c['amount'])) for c in calcs),Decimal(0)),
            'slot':slot,'scheduled':'','basis':'','approval':'','status':'',
            'payee':'','payable':Decimal(0),'comp_employee':'','comp_minutes':0})
    # 排班人判定：本人排班 > 未被本人占用的同槽位排班 > 审批指名 > 无排班数据按本人
    fulfilled=set()
    for row in rows:
        if members and row['slot']:
            day,start,end=row['slot']
            if (row['actual'],day,start,end) in members:fulfilled.add((row['actual'],day,start,end))
    for row in rows:
        slot=row['slot']
        if members and slot:
            day,start,end=slot
            if (row['actual'],day,start,end) in members:
                row['scheduled']=row['actual'];row['basis']='排班'
            else:
                open_slots=slots[slot]-{e for e,d,s,t in fulfilled if (d,s,t)==slot}
                if len(open_slots)==1:row['scheduled']=sorted(open_slots)[0]
                elif len(open_slots)>1:row['basis']='排班冲突';row['status']='挂起'
                else:row['basis']='未排班打卡';row['status']='挂起'
        elif not members:
            named={a['scheduled'] for a in approvals if a['actual']==row['actual'] and a['shift_day']==row['shift_day']}
            if len(named)==1:row['scheduled']=sorted(named)[0]
            elif len(named)>1:row['basis']='审批冲突';row['status']='挂起'
            else:row['scheduled']=row['actual'];row['basis']='排班'
        else:
            row['scheduled']=row['actual'];row['basis']='排班'
    # 同一排班班次被两人打卡：全部挂起，同一分钟不得记给两个人
    coverage=defaultdict(set)
    for row in rows:
        if row['scheduled'] and row['slot']:coverage[(row['slot'],row['scheduled'])].add(row['actual'])
    clash={key for key,actuals in coverage.items() if len(actuals)>1}
    for row in rows:
        if row['scheduled'] and row['slot'] and (row['slot'],row['scheduled']) in clash:
            row['basis']='重复顶班';row['status']='挂起'
    # 替班审批有效性：已批准且在截止前，条款决定付薪或调休
    applied=set();matched=set()
    for row in rows:
        if row['status']=='挂起':continue
        if row['scheduled']==row['actual']:
            row['status']='可付';row['payee']=row['actual'];row['payable']=row['amount'];continue
        candidates=[a for a in approvals if a['shift_day']==row['shift_day'] and a['scheduled']==row['scheduled'] and a['actual']==row['actual']]
        matched.update(a['id'] for a in candidates)
        effective=[a for a in candidates if a['status']=='已批准' and (cutoff_at is None or a['moment']<=cutoff_at)]
        if len(effective)>1:
            row['basis']='审批冲突';row['status']='挂起'
        elif effective:
            approval=effective[0];applied.add(approval['id'])
            row['approval']=approval['id'];row['basis']='替班审批 '+approval['id']
            if approval['settle']=='调休':
                row['status']='调休';row['comp_employee']=row['actual'];row['comp_minutes']=row['minutes']
            else:
                row['status']='可付';row['payee']=row['actual'];row['payable']=row['amount']
        else:
            row['basis']='无有效审批';row['status']='挂起'
    for approval in approvals:
        if approval['id'] not in matched and approval['id'] not in applied:
            issues.append({'kind':'替班审批','ref':approval['id'],'code':'APPROVAL_UNMATCHED','message':'审批未匹配任何班次'})
    total_payable=sum((r['payable'] for r in rows),Decimal(0))
    total_held=sum((r['amount'] for r in rows if r['status']=='挂起'),Decimal(0))
    comp_amount=sum((r['amount'] for r in rows if r['status']=='调休'),Decimal(0))
    by_employee=defaultdict(lambda:{'payable':Decimal(0),'minutes':0,'comp_minutes':0})
    for row in rows:
        if row['payee']:
            bucket=by_employee[row['payee']];bucket['payable']+=row['payable'];bucket['minutes']+=row['minutes']
        if row['comp_employee']:by_employee[row['comp_employee']]['comp_minutes']+=row['comp_minutes']
    business=state.get('business') or {}
    balanced=(total_payable+total_held+comp_amount==Decimal(str(business.get('total','0')))
        and sum(r['minutes'] for r in rows)==int(business.get('minutes',0)))
    payables=[{k:v for k,v in row.items() if k!='slot'} for row in rows]
    for row in payables:
        row['amount']=_money(row['amount']);row['payable']=_money(row['payable'])
    return {'payables':payables,
        'totals':{'payable':_money(total_payable),'held':_money(total_held),'comp_amount':_money(comp_amount),
            'comp_minutes':sum(r['comp_minutes'] for r in rows),'minutes':sum(r['minutes'] for r in rows),'rows':len(rows)},
        'by_employee':{emp:{'payable':_money(b['payable']),'minutes':b['minutes'],'comp_minutes':b['comp_minutes']} for emp,b in sorted(by_employee.items())},
        'approvals':[{'id':a['id'],'shift_day':a['shift_day'],'scheduled':a['scheduled'],'actual':a['actual'],
            'status':a['status'],'settle':a['settle'],'approved_at':a['approved_at'] or '',
            'applied':a['id'] in applied} for a in approvals],
        'issues':issues,'cutoff':cutoff or None,'balanced':balanced}
