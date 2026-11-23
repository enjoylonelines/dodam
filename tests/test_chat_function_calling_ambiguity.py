import json
from unittest.mock import AsyncMock
import pytest
from app.services.chat.function_calling import ModelTurn, run_tools, tool_definitions
from app.services.chat.function_calling_adapter import render_run

@pytest.fixture
def anyio_backend():
    return "asyncio"

@pytest.mark.anyio
@pytest.mark.parametrize("slugs", [[], ["A"], ["A","B"]])
async def test_ambiguous_reference_cannot_become_model_selected_authority(slugs):
    class Model:
        async def turn(self,items):
            return ModelTurn([{"type":"function_call","name":"get_application_preparation",
                               "call_id":"c","arguments":json.dumps({"query":"신청 준비","policy_slugs":slugs})}])
    execute=AsyncMock()
    run=await run_tools(model=Model(),execute=execute,state={
        "user_content":"이거 신청 준비 알려줘","history":[],
        "slot":{"recent_policies":[{"slug":"A","policy_name":"가상 A"},{"slug":"B","policy_name":"가상 B"}]}})
    assert run.stop_reason=="needs_input"
    execute.assert_not_awaited()
    payload=render_run(run)["assistant_payload"]
    assert len(payload["policy_selection"]["candidates"])==2
    assert payload["apply_card"] is None

def test_native_tool_schema_expresses_policy_cardinality():
    tools={t["name"]:t for t in tool_definitions()}
    assert tools["get_policy_information"]["parameters"]["properties"]["policy_slugs"]["maxItems"]==1
    assert tools["compare_policies"]["parameters"]["properties"]["policy_slugs"]["maxItems"]==2
