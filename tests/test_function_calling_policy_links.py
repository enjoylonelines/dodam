from app.services.chat.function_calling import RunResult
from app.services.chat.function_calling_adapter import render_run
from app.services.chat.persistence._persistence import build_policy_link_rows

def test_information_sections_never_insert_null_action_type():
    sections = [
        {"result_ref":"r1","tool":"get_policy_information","intent":"policy_summary","status":"ok",
         "payload":{"content":"정보","policies":[{"policy_id":242,"slug":"WLF00006308","policy_name":"무료법률상담"}]}},
        {"result_ref":"r2","tool":"get_application_preparation","intent":"apply","status":"ok",
         "payload":{"content":"신청","policies":[{"policy_id":242,"slug":"WLF00006308","policy_name":"무료법률상담"}]}},
    ]
    run = RunResult(sections,[],{},"completed","",{},0,1)
    result = render_run(run)
    rows = build_policy_link_rows(1,result["policy_links_to_save"],{"WLF00006308":242})
    assert rows == [{"chat_message_id":1,"policy_id":242,"action_type":"APPLY_TARGET"}]
    assert len(result["assistant_payload"]["sections"]) == 2
