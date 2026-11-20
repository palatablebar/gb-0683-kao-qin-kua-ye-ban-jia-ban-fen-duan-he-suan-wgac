from app.modules.m7_settle.rules import adjudicate

def execute(state):
    state['settle']=adjudicate(state);return state
