"""Adapters retain existing workflow, evidence review and response contracts."""
from __future__ import annotations

import asyncio
import copy
import logging
from typing import Any

from app.services.chat.function_calling import (
    ResponsesModel, RunResult, TOOL_INTENTS, ToolArguments, ToolResult, run_tools,
)

logger = logging.getLogger(__name__)

def handler_executor(db):
    async def execute(name: str, args: ToolArguments, state: dict) -> ToolResult:
        from app.services.chat import chat_handlers as handlers
        from app.services.chat.handlers._quality_validator import validate_branch_result
        from app.services.chat.handlers._payload_builders import build_assistant_payload
        from app.ai.nodes.chat.profile_helpers import _missing_required
        from app.ai.nodes.chat import chat_nodes

        intent = TOOL_INTENTS[name]
        # Explicitly reset per-branch fields: previous eligibility/cards must not
        # authorize or contaminate the next branch's response.
        branch = {k: copy.deepcopy(state[k]) for k in (
            "user_id", "history", "slot", "recent_assistant_policy", "profile"
        ) if k in state}
        branch["user_content"] = state["user_content"] if intent == "recommend" else args.query
        branch.setdefault("profile", (branch.get("slot") or {}).get("profile") or {})
        branch["supervisor_decision"] = {
            "intent": intent, "raw": "responses_function_call",
            "resolved_policy_slug": args.policy_slugs[0] if len(args.policy_slugs) == 1 else None,
            "is_context_dependent": not bool(args.policy_slugs),
        }
        if len(args.policy_slugs) == 2:
            candidates = {p["slug"]: p for p in (branch.get("slot") or {}).get("recent_policies", [])}
            branch["user_content"] = "와 ".join(
                candidates[slug].get("policy_name") or slug for slug in args.policy_slugs
            ) + " 비교해줘. " + args.query
        if intent == "recommend":
            # Reuse existing server-side slot requirements, never infer a profile.
            missing = _missing_required("recommend", branch.get("profile"))
            if missing:
                branch["awaiting_slots"] = missing
                branch["pending_intent"] = "recommend"
                result = await handlers.handle_collect_slots(branch)
            else:
                result = await handlers.handle_recommend(branch, db)
        elif intent == "eligibility":
            result = await handlers.handle_eligibility(branch, db)
        elif intent == "compare":
            result = await handlers.handle_compare(branch)
        elif intent == "apply":
            result = await handlers.handle_apply(branch, db)
        else:
            # Information queries must retain the user's question rather than
            # always using a generic policy-summary graph.
            slug, policy_name, evidences, candidates = await handlers._resolve_single_policy_target(
                branch, intent="policy_summary"
            )
            if slug is None:
                if candidates:
                    result = handlers._build_policy_selection_response(
                        branch, candidates, "policy_summary", evidences
                    )
                else:
                    result = {**branch, "branch_content": "어떤 정책인지 정책명을 알려주세요.",
                              "pending": {"intent": "policy_summary", "kind": "clarification"}}
            else:
                from app.ai.tools.policy_chunk_search_tool import search_policy_chunks
                # Resolver already produced relevant evidence when available.
                chunks = await search_policy_chunks(
                    query=args.query, policy_ids=[slug],
                )
                evidences = [c.model_dump() if hasattr(c, "model_dump") else c for c in chunks]
                result = {**branch, "branch_content": await chat_nodes._generate_branch_answer(
                    "policy_summary", branch, evidences
                ), "branch_evidences": evidences,
                    "branch_policies": [{"policy_id": slug, "slug": slug,
                                         "policy_name": policy_name or slug}]}
        branch.update(result)
        correction = validate_branch_result(branch, intent)
        if correction:
            branch.update(correction)
        branch.update(await build_assistant_payload(branch))
        payload = branch["assistant_payload"]
        needs_input = bool(payload.get("slot_request") or payload.get("profile_confirm")
                           or payload.get("policy_selection") or branch.get("pending"))
        blocked = (payload.get("evidence_review") or {}).get("verdict") == "BLOCKED"
        failed = any(branch.get(key) in {"retryable_error", "fallback_needed"}
                     for key in ("recommend_flow_status", "apply_flow_status"))
        status = "needs_input" if needs_input else "blocked" if blocked else "temporary_error" if failed else "ok"
        return ToolResult(status, payload, branch, "workflow_unavailable" if failed else None)
    return execute

def render_run(run: RunResult, preseed=None) -> dict[str, Any]:
    """Render verified workflow outputs; ignore model-authored policy claims."""
    from app.services.chat.persistence._persistence import fallback_payload
    result = dict(preseed or {})
    result.update(run.state)
    payload = fallback_payload()
    if run.sections:
        for section in run.sections:
            part = section["payload"]
            payload["content"] += ("\n\n" if payload["content"] else "") + part.get("content", "")
        # fallback_payload's generic text is not part of a successful answer.
        payload["content"] = "\n\n".join(s["payload"].get("content", "") for s in run.sections)
        for key in ("policies", "evidences", "actions", "sources", "key_points",
                    "suggested_actions", "claim_evidence_links"):
            values = []
            for section in run.sections:
                for item in section["payload"].get(key, []):
                    if item not in values:
                        values.append(item)
            payload[key] = values
        # Singular legacy fields remain compatible; sections preserve all cards.
        for key in ("apply_card", "eligibility_result", "slot_request", "profile_confirm", "policy_selection"):
            payload[key] = next((s["payload"].get(key) for s in reversed(run.sections)
                                 if s["payload"].get(key)), None)
        payload["disclaimer"] = any(s["payload"].get("disclaimer") for s in run.sections)
    else:
        # Model text is not accepted as a factual answer without tool evidence.
        payload["content"] = "어떤 정책이나 상담 업무가 필요한지 구체적으로 알려주세요."
        payload["disclaimer"] = True
    if run.stop_reason not in {"completed", "needs_input"}:
        payload["content"] += "\n\n일부 요청은 완료하지 못했습니다. 위 내용은 확인된 결과만 표시합니다."
        payload["disclaimer"] = True
    payload["sections"] = run.sections
    payload["execution_status"] = run.stop_reason
    intents = [s["intent"] for s in run.sections]
    result["supervisor_decision"] = {
        "intent": intents[-1] if intents else "unclear", "raw": "responses_function_calling",
        "secondary_intents": list(dict.fromkeys(intents[:-1])),
    }
    result["assistant_payload"] = payload
    result["evidences_to_save"] = [
        {"chunk_id": e["chunk_id"], "snippet": e.get("snippet"), "evidence_role": e.get("evidence_role")}
        for e in payload.get("evidences", []) if e.get("chunk_id") is not None
    ]
    from app.ai.nodes.chat.constants import INTENT_TO_ACTION_TYPE
    result["policy_links_to_save"] = [
        {"policy_slug": p["slug"], "action_type": INTENT_TO_ACTION_TYPE[s["intent"]]}
        for s in run.sections for p in s["payload"].get("policies", [])
        if p.get("slug") and s["intent"] in INTENT_TO_ACTION_TYPE
    ]
    result["tool_execution"] = {
        "version": "responses-business-tools-v1", "stop_reason": run.stop_reason,
        "calls": run.records, "usage": run.usage, "model_calls": run.model_calls,
        "elapsed_ms": run.elapsed_ms,
    }
    return result

async def run_function_chat(*, db, user_id, user_content, history, slot=None,
                            recent_assistant_policy=None, on_progress=None,
                            on_token=None, on_intent=None, emit_intent=False,
                            preseed_result=None, execution_guard=None, model=None,
                            execute=None, max_calls=4, timeout_seconds=120):
    from app.core.config import settings
    from app.ai.nodes.chat.constants import LLM_MODEL
    from app.ai.utils.progress import set_progress_callback, reset_progress_callback
    if emit_intent and on_intent:
        await on_intent("general")
    state = {"user_id": user_id, "user_content": user_content, "history": history,
             "slot": slot or {}, "recent_assistant_policy": recent_assistant_policy,
             "profile": (slot or {}).get("profile") or {}}
    owned_model = model is None
    model = model or ResponsesModel(model=LLM_MODEL, api_key=settings.openai_api_key or "")
    progress_token = set_progress_callback(on_progress)
    try:
        kwargs = {"guard": execution_guard} if execution_guard else {}
        run = await run_tools(model=model, execute=execute or handler_executor(db), state=state,
                              max_calls=max_calls, timeout_seconds=timeout_seconds,
                              on_progress=on_progress, **kwargs)
        result = render_run(run, preseed_result)
        if on_token:
            await on_token(result["assistant_payload"]["content"])
        return result
    finally:
        reset_progress_callback(progress_token)
        if owned_model:
            await model.close()
