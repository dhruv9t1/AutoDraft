from app.models import Variable
from app.wrapping import build_wrapping_plan

def test_wrapping_plan_is_shortest_first_and_marks_parent():
    vars_=[Variable(name="Bank",originalText="UCO BANK",position=0,confidenceScore=.9),Variable(name="Address",originalText="UCO BANK; JODHPUR",position=0,confidenceScore=.9),Variable(name="City",originalText="JODHPUR",position=10,confidenceScore=.9)]
    plan=build_wrapping_plan(vars_)
    assert len(plan)==3
    address=next(x for x in plan if vars_[x.variable_index].name=="Address")
    assert address.use_wildcards
