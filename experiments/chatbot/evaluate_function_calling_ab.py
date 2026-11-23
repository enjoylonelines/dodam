"""Real model routing A/B with shared synthetic business fixtures, no database.

Run: .venv/bin/python -m experiments.chatbot.evaluate_function_calling_ab --repeats 2
The baseline is the existing legacy router/classifier; handlers only are replaced.
Both arms use the same fixed business results, so this isolates orchestration.
"""
from __future__ import annotations
import argparse
import asyncio
import hashlib
import json
import statistics
import subprocess
import time
from pathlib import Path
from unittest.mock import patch
from dataclasses import asdict

from experiments.chatbot.function_calling_cases import CASES, POLICIES
from app.services.chat.function_calling import ResponsesModel, ToolResult, TOOL_INTENTS
from app.services.chat.function_calling_adapter import run_function_chat
from app.ai.nodes.chat.constants import LLM_MODEL
from app.core.config import settings

INTENT_TOOL = {value: key for key, value in TOOL_INTENTS.items()}
PROFILE = {"stage":"임신","child_age":"0","income":"중위소득100이하","region":"경기",
           "special":[], "skipped":["special"], "db_profile_confirmed":True}

def initial(case):
    return {"user_id":1, "user_content":case["query"], "history":[],
            "slot":{"profile":PROFILE, "recent_policies":[] if case.get("empty_context") else POLICIES},
            "recent_assistant_policy":None}

def fixture_result(intent, query, slugs, known):
    """Same deterministic business behavior for both arms; never consumes labels."""
    if not slugs:
        slugs = [p["slug"] for p in POLICIES if p["policy_name"] in query]
    if intent == "recommend":
        chosen = POLICIES
    elif intent == "compare":
        if len(slugs) != 2:
            return ToolResult("needs_input", {"content":"비교할 두 정책을 선택해주세요.",
                                              "policy_selection":{"candidates":known}})
        chosen = [p for p in POLICIES if p["slug"] in slugs]
    elif len(slugs) == 1:
        chosen = [p for p in POLICIES if p["slug"] == slugs[0]]
    elif len(known) == 1:
        chosen = known
    else:
        return ToolResult("needs_input", {"content":"대상 정책을 선택해주세요.",
                                          "policy_selection":{"candidates":known}})
    if not chosen:
        return ToolResult("needs_input", {"content":"정책명을 알려주세요."})
    # The name/result is explicitly synthetic; no actual benefit/eligibility claim.
    p = {"content": f"[가상 업무 결과] {intent}: " + ", ".join(x["policy_name"] for x in chosen),
         "policies": chosen, "actions":[intent], "disclaimer":True,
         "evidences":[{"chunk_id":str(index+1), "snippet":"가상 평가용 근거",
                       "source_title":item["policy_name"],"source_url":"https://example.invalid/policy",
                       "evidence_role":"target"} for index,item in enumerate(chosen)]}
    if intent == "apply":
        p["apply_card"] = {"policy_id":chosen[0]["policy_id"],"policy_name":chosen[0]["policy_name"],
                           "how_to_apply":"가상 준비 안내","checklist":[]}
    if intent == "eligibility":
        p["eligibility_result"] = {"status":"UNKNOWN","summary":"가상 평가 결과; 실제 자격 판단 아님"}
    return ToolResult("ok", p)

def task_from_payload(intent, payload):
    return [intent, sorted(p["slug"] for p in payload.get("policies", [])) if intent != "recommend" else []]

def score(case, tasks, error, needs_input):
    encode = lambda t: json.dumps(t, sort_keys=True)
    expected, actual = {encode(t) for t in case["expected"]}, {encode(t) for t in tasks}
    hit = len(expected & actual)
    return {
        "exact_task_match": not error and expected == actual and
                            (not case.get("needs_input") or needs_input),
        "task_recall": hit/len(expected) if expected else None,
        "task_precision": hit/len(actual) if actual else (1.0 if not expected else 0.0),
        "policy_argument_match": not error and expected == actual,
        "clarification_correct": (not error and not actual and needs_input) if case.get("needs_input") else None,
    }

async def baseline(case):
    from app.services.chat import chat_handlers as h
    from app.services.chat._routing import run_chat_legacy
    tasks = []
    follow_up = False
    def handler(intent):
        async def run(state, *args):
            nonlocal follow_up
            decision = state.get("supervisor_decision") or {}
            slug = decision.get("resolved_policy_slug")
            result = fixture_result(intent, state["user_content"], [slug] if slug else [],
                                    (state.get("slot") or {}).get("recent_policies", []))
            if result.status == "ok":
                tasks.append(task_from_payload(intent, result.payload))
            else:
                follow_up = True
            return {**state, "branch_content":result.payload["content"],
                    "branch_policies":result.payload.get("policies",[]),
                    "branch_evidences":result.payload.get("evidences",[]),
                    "branch_apply_card":result.payload.get("apply_card"),
                    "branch_eligibility_result":result.payload.get("eligibility_result"),
                    "branch_policy_candidates":(result.payload.get("policy_selection") or {}).get("candidates", [])}
        return run
    async def unclear(state, *args):
        nonlocal follow_up
        follow_up = True
        return {**state,"branch_content":"정책과 필요한 업무를 알려주세요."}
    from contextlib import ExitStack
    with ExitStack() as stack:
        for intent, name in [("recommend","handle_recommend"),("eligibility","handle_eligibility"),
                             ("compare","handle_compare"),("apply","handle_apply"),
                             ("policy_summary","handle_policy_summary"),("policy_summary","handle_summary")]:
            stack.enter_context(patch.object(h, name, handler(intent)))
        stack.enter_context(patch.object(h,"handle_unclear",unclear))
        state = initial(case)
        result = await run_chat_legacy(db=None, **state)
    # A's actual live model usage is captured at the ChatOpenAI response hook below.
    return {"tasks":tasks,"needs_input":follow_up,
            "decision":result.get("supervisor_decision"),"content":result.get("assistant_payload",{}).get("content")}

async def candidate(case, model):
    async def execute(name, args, state):
        return fixture_result(TOOL_INTENTS[name], args.query, args.policy_slugs,
                              (state.get("slot") or {}).get("recent_policies",[]))
    result = await run_function_chat(db=None, **initial(case), model=model, execute=execute)
    tasks = [task_from_payload(s["intent"],s["payload"]) for s in result["assistant_payload"]["sections"]
             if s["status"] == "ok"]
    trace = result["tool_execution"]
    error = trace["stop_reason"] not in {"completed","needs_input"}
    return {"tasks":tasks,"needs_input":trace["stop_reason"]=="needs_input",
            "trace":trace,"content":result["assistant_payload"]["content"],
            "error": trace["stop_reason"] if error else None}

def aggregate(rows):
    groups = {}
    for arm in ("A","B"):
        arm_rows = [r for r in rows if r["arm"]==arm]
        metrics = {}
        for group in ("all", *dict.fromkeys(c["group"] for c in CASES)):
            rs = arm_rows if group=="all" else [r for r in arm_rows if r["group"]==group]
            metrics[group] = {
                "rows":len(rs),"exact_task_matches":sum(r["scores"]["exact_task_match"] for r in rs),
                "exact_task_match_rate":sum(r["scores"]["exact_task_match"] for r in rs)/len(rs) if rs else None,
                "mean_task_recall":statistics.mean([r["scores"]["task_recall"] for r in rs if r["scores"]["task_recall"] is not None]) if any(r["scores"]["task_recall"] is not None for r in rs) else None,
                "errors":sum(bool(r.get("error")) for r in rs),
            }
        latencies = sorted(r["elapsed_ms"] for r in arm_rows)
        groups[arm] = {"by_group":metrics,
                       "elapsed_p50_ms":statistics.median(latencies) if latencies else None,
                       "elapsed_p95_ms":latencies[min(len(latencies)-1,int(.95*len(latencies)))] if latencies else None,
                       "provider_total_tokens":sum(r.get("usage",{}).get("total_tokens",0) for r in arm_rows),
                       "usage_rows":sum(bool(r.get("usage")) for r in arm_rows)}
    paired = {}
    for r in rows:
        paired.setdefault((r["case_id"],r["repeat"]),{})[r["arm"]] = r
    delta = [int(p["B"]["scores"]["exact_task_match"])-int(p["A"]["scores"]["exact_task_match"])
             for p in paired.values() if len(p)==2]
    return {"arms":groups,"paired_rows":len(delta),
            "B_wins":sum(d>0 for d in delta),"A_wins":sum(d<0 for d in delta),
            "ties":sum(d==0 for d in delta)}

async def main(args):
    from langchain_core.callbacks import AsyncCallbackHandler
    from app.ai.nodes.chat import chat_nodes
    from langchain_openai import ChatOpenAI
    class Usage(AsyncCallbackHandler):
        def __init__(self):
            self.usage = {}
        async def on_llm_end(self, response, **kwargs):
            for generation in response.generations:
                for item in generation:
                    meta = getattr(item.message,"usage_metadata",None) or {}
                    for k in ("input_tokens","output_tokens","total_tokens"):
                        self.usage[k] = self.usage.get(k,0)+int(meta.get(k,0))
    output = Path(args.output)
    output.parent.mkdir(parents=True,exist_ok=True)
    fingerprint = hashlib.sha256(json.dumps(CASES,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    source_files = ["app/services/chat/function_calling.py", "app/services/chat/function_calling_adapter.py",
                    "app/services/chat/_routing.py", "app/services/chat/handlers/_intent_classifier.py",
                    "experiments/chatbot/function_calling_cases.py"]
    source_hashes = {p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in source_files}
    report = {"version":"function-calling-orchestration-ab-v2", "model":LLM_MODEL,
              "dataset_sha256":fingerprint,"base_revision":subprocess.check_output(["git","rev-parse","HEAD"],text=True).strip(),
              "boundary":"Live LLM routing + shared synthetic business fixtures. No real RAG/DB/UI or answer-faithfulness evaluation.",
              "repeats":args.repeats,"source_sha256":source_hashes,"rows":[]}
    if args.resume and output.exists():
        previous = json.loads(output.read_text())
        if previous["dataset_sha256"] != fingerprint or previous["model"] != LLM_MODEL or previous.get("source_sha256") != source_hashes:
            raise ValueError("resume dataset/model mismatch")
        report = previous
    completed = {(r["repeat"],r["case_id"],r["arm"]) for r in report["rows"]}
    model = ResponsesModel(model=LLM_MODEL,api_key=settings.openai_api_key or "")
    try:
        for repeat in range(args.repeats):
            for index,case in enumerate(CASES):
                if not args.start <= index < args.start + args.limit:
                    continue
                for arm in (("A","B") if (repeat+index)%2==0 else ("B","A")):
                    if (repeat,case["id"],arm) in completed:
                        continue
                    usage = Usage()
                    started = time.perf_counter()
                    row = {"case_id":case["id"],"group":case["group"],"repeat":repeat,"arm":arm}
                    try:
                        if arm=="A":
                            llm = ChatOpenAI(model=LLM_MODEL,api_key=settings.openai_api_key,
                                             callbacks=[usage],max_retries=0,timeout=45)
                            with patch.object(chat_nodes,"_llm",lambda:llm):
                                # Compatibility sync reads the actual h._llm patch point.
                                from app.services.chat import chat_handlers as h
                                with patch.object(h,"_llm",lambda:llm):
                                    result = await asyncio.wait_for(baseline(case),120)
                            row["usage"] = usage.usage
                        else:
                            result = await asyncio.wait_for(candidate(case,model),120)
                            row["usage"] = result.get("trace",{}).get("usage",{})
                        row.update(result)
                    except Exception as exc:
                        row.update(tasks=[],needs_input=False,error=type(exc).__name__)
                    row["elapsed_ms"] = round((time.perf_counter()-started)*1000,3)
                    row["scores"] = score(case,row["tasks"],row.get("error"),row["needs_input"])
                    report["rows"].append(row)
                    report["summary"] = aggregate(report["rows"])
                    output.write_text(json.dumps(report,ensure_ascii=False,indent=2))
                    print(f'{repeat+1}/{args.repeats} {case["id"]} {arm} exact={row["scores"]["exact_task_match"]} error={row.get("error")}',flush=True)
    finally:
        await model.close()
    print(json.dumps(report["summary"],ensure_ascii=False),flush=True)

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--repeats",type=int,default=2)
    p.add_argument("--start",type=int,default=0)
    p.add_argument("--limit",type=int,default=16)
    p.add_argument("--resume",action="store_true")
    p.add_argument("--output",default="docs/evidence/2026-11-23-function-calling-ab.json")
    asyncio.run(main(p.parse_args()))
