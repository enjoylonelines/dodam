import asyncio
import json
from types import SimpleNamespace

import pytest

@pytest.fixture
def anyio_backend():
    return "asyncio"

from app.services.chat.function_calling import (
    ExecutionStopped, ModelTurn, ResponsesModel, ToolResult, run_tools,
)
from app.services.chat.function_calling_adapter import render_run

def call(name="get_policy_information", query="정책 안내", slugs=None, call_id="c1"):
    return {"type": "function_call", "call_id": call_id, "name": name,
            "arguments": json.dumps({"query": query, "policy_slugs": slugs or []})}

class FakeModel:
    def __init__(self, *outputs):
        self.outputs = list(outputs)
        self.inputs = []
    async def turn(self, items):
        self.inputs.append(list(items))
        output = self.outputs.pop(0)
        return ModelTurn(output, text="모델이 창작한 정책 사실", usage={"total_tokens": 3})

def state():
    return {"user_id": 17, "user_content": "추천 후 첫 번째 신청 안내", "history": [], "slot": {}}

def payload(slug="A"):
    return {"content": "서버에서 검증한 안내", "policies": [
        {"policy_id": "1", "slug": slug, "policy_name": "가상정책"}],
        "evidences": [{"chunk_id": 1, "snippet": "원문"}], "actions": [],
        "apply_card": None}

@pytest.mark.anyio
async def test_dynamic_native_round_trip_and_server_content():
    reasoning = {"type": "reasoning", "id": "r1", "summary": []}
    model = FakeModel([reasoning, call("recommend_policies")],
                      [call("get_application_preparation", slugs=["A"], call_id="c2")], [])
    seen = []
    async def execute(name, args, ctx):
        seen.append((name, args.policy_slugs))
        return ToolResult("ok", payload())
    run = await run_tools(model=model, execute=execute, state=state())
    assert seen == [("recommend_policies", []), ("get_application_preparation", ["A"])]
    assert reasoning in model.inputs[1]
    assert any(x.get("type") == "function_call_output" and x["call_id"] == "c1"
               for x in model.inputs[1])
    result = render_run(run)
    assert len(result["assistant_payload"]["sections"]) == 2
    assert "창작" not in result["assistant_payload"]["content"]
    assert run.usage["total_tokens"] == 9

@pytest.mark.anyio
@pytest.mark.parametrize("bad", [
    call("delete_user"), call(slugs=["forged"]),
    {**call(), "arguments": '{"query":"q","policy_slugs":[],"user_id":999}'},
    {**call(), "arguments": "not json"},
    call("compare_policies", slugs=["A"]),
])
async def test_invalid_calls_never_execute(bad):
    called = []
    async def execute(*args):
        called.append(args)
    run = await run_tools(model=FakeModel([bad]), execute=execute, state=state())
    assert run.stop_reason == "blocked"
    assert not called

@pytest.mark.anyio
async def test_duplicate_does_not_repeat_business_request():
    count = 0
    async def execute(*args):
        nonlocal count
        count += 1
        return ToolResult("ok", payload())
    run = await run_tools(model=FakeModel([call()], [call(call_id="c2")]),
                          execute=execute, state=state())
    assert count == 1
    assert run.stop_reason == "duplicate_call"

@pytest.mark.anyio
async def test_follow_up_stops_and_preserves_pending():
    async def execute(*args):
        return ToolResult("needs_input", {"content": "지역을 알려주세요", "slot_request": {"current": "region"}},
                          {"pending": {"intent": "recommend", "kind": "slot"}})
    run = await run_tools(model=FakeModel([call("recommend_policies")]),
                          execute=execute, state=state())
    assert run.stop_reason == "needs_input"
    assert run.state["pending"]["kind"] == "slot"

@pytest.mark.anyio
async def test_guard_before_second_business_call():
    active = True
    calls = []
    async def guard():
        return active
    async def execute(*args):
        nonlocal active
        calls.append(args)
        active = False
        return ToolResult("ok", payload())
    with pytest.raises(ExecutionStopped):
        await run_tools(model=FakeModel([call()]), execute=execute, state=state(), guard=guard)
    assert len(calls) == 1

@pytest.mark.anyio
async def test_task_cancellation_propagates():
    async def execute(*args):
        raise asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await run_tools(model=FakeModel([call()]), execute=execute, state=state())

@pytest.mark.anyio
async def test_timeout_cancels_in_flight_execution():
    cancelled = asyncio.Event()
    async def execute(*args):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
    run = await run_tools(model=FakeModel([call()]), execute=execute, state=state(),
                          timeout_seconds=.01)
    assert run.stop_reason == "timeout"
    assert cancelled.is_set()

@pytest.mark.anyio
async def test_budget_limits_valid_distinct_calls():
    seen = []
    async def execute(name, args, ctx):
        seen.append(args.query)
        return ToolResult("ok", payload())
    run = await run_tools(
        model=FakeModel([call(query="one")], [call(query="two", call_id="c2")]),
        execute=execute, state=state(), max_calls=1,
    )
    assert seen == ["one"]
    assert run.stop_reason == "budget_exhausted"

@pytest.mark.anyio
async def test_multiple_calls_rejected_before_execution():
    async def execute(*args):
        pytest.fail("must not execute")
    run = await run_tools(model=FakeModel([call(), call(call_id="c2")]),
                          execute=execute, state=state())
    assert run.stop_reason == "parallel_calls_rejected"

@pytest.mark.anyio
async def test_partial_result_survives_provider_failure():
    class Model(FakeModel):
        async def turn(self, items):
            if self.inputs:
                raise RuntimeError("provider failed")
            return await super().turn(items)
    async def execute(*args):
        return ToolResult("ok", payload())
    run = await run_tools(model=Model([call()]), execute=execute, state=state())
    result = render_run(run)["assistant_payload"]
    assert run.stop_reason == "provider_error"
    assert len(result["sections"]) == 1
    assert "일부 요청" in result["content"]

@pytest.mark.anyio
async def test_responses_provider_disables_parallel_and_preserves_native_items():
    class Item:
        def model_dump(self, **kwargs):
            return call()
    sent = {}
    async def create(**kwargs):
        sent.update(kwargs)
        return SimpleNamespace(status="completed", output=[Item()], output_text="", usage=None)
    client = SimpleNamespace(responses=SimpleNamespace(create=create))
    model = ResponsesModel(model="test-model", api_key="test", client=client)
    turn = await model.turn([{"role": "user", "content": "질문"}])
    assert turn.output[0]["call_id"] == "c1"
    assert sent["store"] is False
    assert sent["parallel_tool_calls"] is False
    assert all(t["strict"] for t in sent["tools"])

def test_sections_survive_schema_and_persistence_round_trip():
    from app.services.chat.persistence._persistence import build_structured_json, build_assistant_response
    from app.services.chat.persistence._message_serializer import unwrap_message_meta
    from app.schemas.chat_schema import AssistantMessage
    sections = [{"result_ref": "r1", "tool": "get_policy_information", "intent": "policy_summary",
                 "status": "ok", "payload": payload()}]
    p = {"content": "완료", "sections": sections, "execution_status": "completed"}
    stored = build_structured_json({"intent": "policy_summary"}, p)
    assert unwrap_message_meta(stored)["sections"] == sections
    response = build_assistant_response(SimpleNamespace(chat_message_id=1), p, [], {})
    assert response.sections[0].result_ref == "r1"
    assert AssistantMessage.model_validate(response.model_dump()).sections

@pytest.mark.anyio
async def test_pending_keeps_legacy_resume(monkeypatch):
    from app.services.chat import _routing
    from app.services.chat.routing_dispatch import run_chat
    from app.core.config import settings
    async def legacy(**kwargs):
        return {"legacy": True}
    monkeypatch.setattr(settings, "chat_routing_mode", "function_calling")
    monkeypatch.setattr(_routing, "run_chat_legacy", legacy)
    result = await run_chat(slot={"pending": {"kind": "slot"}})
    assert result == {"legacy": True}
