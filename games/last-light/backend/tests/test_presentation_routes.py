"""Presentation routes are real neighboring exits, not global reachability shortcuts."""
from test_engine_routes import ready, act, control


def test_expanded_litter_keeps_shape_after_snapshot_without_inventing_inventory_state():
    w=ready();act(w,'collect_stretcher');act(w,'prepare_stretcher')
    item=next(i for i in w.view()['inventory'] if i['id']=='stretcher')
    assert item['state']=='held' and item['visual_state']=='unfolded'
    assert w.state['items']['stretcher']['state']=='held'


def test_external_access_does_not_open_the_internal_passage_or_choose_it_as_exit():
    w=ready();control(w);act(w,'collect_lamp','lin');act(w,'scout_walkway','lin');act(w,'open_outer_door','lin');act(w,'light_walkway','lin');act(w,'open_external05','lin')
    w.move('cabin05')
    rooms={r['id']:r for r in w.view()['rooms']}
    assert rooms['cabin06']['accessible']
    assert not rooms['cabin06']['direct_accessible']
    assert rooms['cabin06']['exit_via']=='tunnel'
    assert rooms['cabin07']['exit_via']=='tunnel'
    assert 'inner_door_open' not in w.state['flags']
