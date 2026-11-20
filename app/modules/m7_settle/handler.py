from flask import Blueprint
from app.web import api,page
bp=Blueprint('m7_settle',__name__)
@bp.get('/m7_settle')
def screen():return page(7,'m7_settle.html')
@bp.route('/api/m7_settle',methods=['GET','POST'])
def preview():return api(7)
