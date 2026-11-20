from flask import Blueprint
from app.web import api,page
bp=Blueprint('m8_archive',__name__)
@bp.get('/m8_archive')
def screen():return page(8,'m8_archive.html')
@bp.route('/api/m8_archive',methods=['GET','POST'])
def preview():return api(8)
