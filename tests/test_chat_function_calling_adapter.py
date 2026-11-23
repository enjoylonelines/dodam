import asyncio
from unittest.mock import AsyncMock

import pytest

from app.services.chat.function_calling import ToolArguments, ToolResult, ModelTurn, run_tools
from app.services.chat.function_calling_adapter import handler_executor, run_function_chat

@pytest.fixture
def anyio_backend():
    return "asyncio"

def state():
    return {"user_id":7,"user_content":"원래 사용자 요청","history":[],
            "slot":{"recent_policies":[{"slug":"A","policy_id":1,"policy_name":"가상 A"}]},
            "profile":{}}

@pytest.mark.anyio
async def test_information_adapter_uses_policy_scoped_search(monkeypatch):
    from app.services.chat import chat_handlers as h
    from app.ai.nodes.chat import chat_nodes
    from app.ai.tools import policy_chunk_search_tool as search
    from app.services.chat.handlers import _quality_validator as quality
    from app.services.chat.handlers import _payload_builders as builders
    monkeypatch.setattr(h,"_resolve_single_policy_target",AsyncMock(return_value=("A","가상 A",[],[])))
    lookup = AsyncMock(return_value=[{"chunk_id":1,"snippet":"근거","source_title":"가상 A",
                                     "source_url":"https://example.invalid"}])
    monkeypatch.setattr(search,"search_policy_chunks",lookup)
    monkeypatch.setattr(chat_nodes,"_generate_branch_answer",AsyncMock(return_value="근거 안내"))
    monkeypatch.setattr(chat_nodes,"_load_policy_detail",AsyncMock(return_value={"policy_id":1}))
    monkeypatch.setattr(quality,"validate_branch_result",lambda *a:None)
    async def build(s):
        return {"assistant_payload":{"content":s["branch_content"],
                                     "policies":s["branch_policies"],
                                     "evidences":s["branch_evidences"]}}
    monkeypatch.setattr(builders,"build_assistant_payload",build)
    result = await handler_executor(None)("get_policy_information",
        ToolArguments(query="가상 A 신청 기간",policy_slugs=["A"]),state())
    assert result.status == "ok"
    lookup.assert_awaited_once_with(query="가상 A 신청 기간",policy_ids=["A"])
    assert result.payload["policies"][0]["slug"] == "A"

@pytest.mark.anyio
async def test_adapter_resets_prior_card_and_injects_authenticated_user(monkeypatch):
    from app.services.chat import chat_handlers as h
    from app.services.chat.handlers import _quality_validator as quality
    from app.services.chat.handlers import _payload_builders as builders
    captured = {}
    async def apply(s,db):
        captured.update(s)
        return {**s,"branch_content":"신청 안내","branch_apply_card":{"policy_id":"1"}}
    monkeypatch.setattr(h,"handle_apply",apply)
    monkeypatch.setattr(quality,"validate_branch_result",lambda *a:None)
    async def build(s):
        return {"assistant_payload":{"content":s["branch_content"],"apply_card":s.get("branch_apply_card")}}
    monkeypatch.setattr(builders,"build_assistant_payload",build)
    ctx = {**state(),"branch_eligibility_result":{"status":"ELIGIBLE"},"branch_apply_card":{"policy_id":"999"}}
    result = await handler_executor(None)("get_application_preparation",
        ToolArguments(query="신청 안내",policy_slugs=["A"]),ctx)
    assert captured["user_id"] == 7
    assert "branch_eligibility_result" not in captured
    assert "branch_apply_card" not in captured
    assert result.payload["apply_card"]["policy_id"] == "1"

@pytest.mark.anyio
async def test_model_cannot_rewrite_recommendation_user_conditions(monkeypatch):
    from app.services.chat import chat_handlers as h
    from app.ai.nodes.chat import profile_helpers
    from app.services.chat.handlers import _quality_validator as quality
    from app.services.chat.handlers import _payload_builders as builders
    captured={}
    monkeypatch.setattr(profile_helpers,"_missing_required",lambda *a:[])
    async def recommend(s,db):
        captured.update(s)
        return {**s,"branch_content":"추천 결과"}
    monkeypatch.setattr(h,"handle_recommend",recommend)
    monkeypatch.setattr(quality,"validate_branch_result",lambda *a:None)
    async def build(s):
        return {"assistant_payload":{"content":s["branch_content"]}}
    monkeypatch.setattr(builders,"build_assistant_payload",build)
    await handler_executor(None)("recommend_policies",
        ToolArguments(query="모델이 임의로 바꾼 소득 조건",policy_slugs=[]),state())
    assert captured["user_content"] == "원래 사용자 요청"

@pytest.mark.anyio
async def test_business_failure_stops_without_retrying_other_tasks():
    class Model:
        async def turn(self,items):
            return ModelTurn([{"type":"function_call","name":"get_policy_information",
                               "call_id":"c1","arguments":'{"query":"q","policy_slugs":[]}'}])
    called=[]
    async def execute(*args):
        called.append(args)
        raise RuntimeError("internal database secret")
    run=await run_tools(model=Model(),execute=execute,state=state())
    assert len(called)==1
    assert run.stop_reason=="temporary_error"
    assert run.records[0]["error"]=="business_execution_failed"
    assert "secret" not in str(run.records)

@pytest.mark.anyio
async def test_guard_prevents_first_model_call():
    class Model:
        async def turn(self,items):
            pytest.fail("cancelled request must not invoke provider")
    async def guard():
        return False
    from app.services.chat.function_calling import ExecutionStopped
    with pytest.raises(ExecutionStopped):
        await run_tools(model=Model(),execute=AsyncMock(),state=state(),guard=guard)
