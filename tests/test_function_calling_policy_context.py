from app.services.chat.persistence._persistence import build_context_policy_links, build_policy_link_rows
from app.services.chat.persistence._slot_builder import build_next_slot

def test_two_information_results_remain_selectable_next_turn_without_db_enum_write():
    policies=[{"policy_id":242,"slug":"WLF00006308","policy_name":"무료법률상담"},
              {"policy_id":289,"slug":"WLF00000072","policy_name":"에너지바우처"}]
    db_links=[]
    context_links=build_context_policy_links(db_links,{"policies":policies})
    ids={"WLF00006308":242,"WLF00000072":289}
    assert build_policy_link_rows(1,db_links,ids)==[]
    slot=build_next_slot(current_slot={},policy_links=context_links,
                         branch_policies=policies,slug_to_policy_id=ids)
    assert len(slot["recent_policies"])==2
    assert all(p["last_action"]=="VIEWED" for p in slot["recent_policies"])

def test_context_does_not_replace_real_business_action():
    links=[{"policy_slug":"A","action_type":"APPLY_TARGET"}]
    assert build_context_policy_links(links,{"policies":[{"slug":"A"}]})==links
