from app.models import Variable
from app.verifier import verify_document
def v(name,old): return Variable(name=name,originalText=old,position=0,confidenceScore=1)
def test_empty_warns_not_blocks():
 r=verify_document('Client: Alice',[v('Client Name','OLD')],{'Client Name':''});assert r['status']=='review';assert r['blockers']==0
def test_year_can_remain(): assert verify_document('Year: 2026',[v('Year','2026')],{'Year':'2026'})['blockers']==0
def test_placeholder_warns_not_blocks():
 r=verify_document('Name: {Client Name}',[],{});assert r['status']=='review';assert r['blockers']==0
