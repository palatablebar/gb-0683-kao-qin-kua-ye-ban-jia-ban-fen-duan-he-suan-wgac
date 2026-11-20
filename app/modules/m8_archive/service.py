from app.modules.m8_archive.export_out import checksum

def execute(state):
    ready=state.get('reconcile',{}).get('balanced',False) and state.get('settle',{}).get('balanced',False)
    state['archive']={'sha256':checksum(state),'ready':ready,
        'evidence_count':len(state.get('calculations',[]))+len(state['quarantine'])+len(state.get('settle',{}).get('payables',[]))}
    return state
