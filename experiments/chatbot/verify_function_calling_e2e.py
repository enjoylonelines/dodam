"""Local-only real FastAPI + PostgreSQL/pgvector + OpenAI HTTP API E2E.

No dependency overrides, mocked handlers, or fixture business adapters.
HTTP uses ASGITransport; browser rendering and network disconnect aren't tested.
"""
from __future__ import annotations
import argparse
import asyncio
import json
import logging
import secrets
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

import httpx

async def main(args):
    from app.core.config import settings
    db_url = urlparse(settings.psycopg_database_url)
    if db_url.hostname not in {"127.0.0.1","localhost"} or db_url.path != "/dodam":
        raise RuntimeError("E2E restricted to local disposable dodam database")
    import psycopg
    with psycopg.connect(settings.psycopg_database_url, autocommit=True) as conn:
        # Existing restored local snapshot predates these application migrations.
        conn.execute("CREATE TABLE IF NOT EXISTS policy_tag (policy_id BIGINT NOT NULL REFERENCES policy(policy_id), tag_name VARCHAR(100) NOT NULL)")
        for migration in ("272_ai_solution_evidence_core_schema.sql","273_recommendation_execution_fence.sql","274_recommendation_execution_events.sql"):
            conn.execute(Path("db/migrations",migration).read_text())
        count=conn.execute("SELECT count(*) FROM langchain_pg_embedding").fetchone()[0]
        if count < 1:
            raise RuntimeError("existing source-backed corpus required")
    from app.main import app
    settings.chat_routing_mode="function_calling"
    # No prompt/response/token logging; durable report contains public policy answers only.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    report={"passed":False,"boundary":"Real FastAPI ASGI HTTP + local source-backed PGVector corpus + actual OpenAI. No browser/network E2E.",
            "corpus_embeddings":count,"steps":[]}
    output=Path(args.output)
    if output.exists():
        raise RuntimeError("refusing to overwrite E2E evidence")
    output.parent.mkdir(parents=True,exist_ok=True)
    def record(name, **data):
        report["steps"].append({"name":name,**data})
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2))
        print(name, data.get("status",""), flush=True)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://localhost",timeout=180) as client:
            identifier=uuid.uuid4().hex[:10]
            response=await client.post("/api/v1/auth/signup",json={
                "email":f"e2e-{identifier}@example.com",
                "password":"E2e!"+secrets.token_hex(12),"nickname":"검증"+identifier})
            if response.status_code != 201:
                record("signup",status=response.status_code,error=response.json())
                return
            data=response.json()["data"]
            client.headers["Authorization"]="Bearer "+data["access_token"]
            record("signup",status=201,user_created=True)
            response=await client.post("/api/v1/chat/sessions",json={"title":"Function Calling 로컬 검증"})
            if response.status_code != 201:
                record("create_session",status=response.status_code,error=response.json())
                return
            session_id=response.json()["data"]["chat_session_id"]
            record("create_session",status=201)
            for name,query,minimum in [
                ("single_information","무료법률상담의 지원 내용을 알려줘.",1),
                ("compound_information","무료법률상담과 에너지바우처의 지원 내용을 각각 알려줘.",2),
                ("ambiguous_reference","이거 신청 준비 알려줘.",1),
            ]:
                started=time.perf_counter()
                response=await client.post(f"/api/v1/chat/sessions/{session_id}/messages",
                                          json={"content":query,"idempotency_key":f"e2e-{identifier}-{name}"})
                body=response.json()
                if response.status_code != 201:
                    record(name,status=response.status_code,error=body)
                    return
                answer=body["data"]["assistant_message"]
                sections=answer.get("sections",[])
                record(name,status=201,elapsed_ms=round((time.perf_counter()-started)*1000,3),
                       execution_status=answer.get("execution_status"),section_count=len(sections),
                       sections=sections, content=answer.get("content"),
                       policy_selection=answer.get("policy_selection"))
                if len(sections)<minimum or answer.get("execution_status") not in {"completed","needs_input"}:
                    return
                if name=="single_information" and not any(s["status"]=="ok" and s["payload"].get("evidences") for s in sections):
                    record("single_evidence_assertion",status="failed")
                    return
                if name=="compound_information" and not (len(sections)>=2 and all(s["status"]=="ok" and s["payload"].get("evidences") for s in sections)):
                    record("compound_evidence_assertion",status="failed")
                    return
                if name=="ambiguous_reference" and not answer.get("policy_selection"):
                    record("ambiguity_assertion",status="failed")
                    return

            response=await client.get(f"/api/v1/chat/sessions/{session_id}/messages")
            history=response.json()["data"]["messages"]
            compound=[m for m in history if m.get("sections") and len(m["sections"])>=2]
            record("history_round_trip",status=response.status_code,
                   compound_preserved=bool(compound),
                   section_counts=[len(m.get("sections",[])) for m in history if m["role"]=="assistant"])
            if not compound:
                return

            # New session avoids pending resume; use the real persisted SSE path.
            response=await client.post("/api/v1/chat/sessions",json={"title":"SSE·멱등성 검증"})
            sid=response.json()["data"]["chat_session_id"]
            payload={"content":"무료법률상담 신청 방법 알려줘.","idempotency_key":f"e2e-{identifier}-sse"}
            response=await client.post(f"/api/v1/chat/sessions/{sid}/messages/stream",json=payload)
            events=[]
            for line in response.text.splitlines():
                if line.startswith("data: "):
                    events.append(json.loads(line[6:]))
            done=[e for e in events if e.get("type")=="done"]
            record("sse_done",status=response.status_code,event_types=[e.get("type") for e in events],
                   done_count=len(done),
                   sections=done[-1].get("payload",{}).get("assistant_message",{}).get("sections",[]) if done else [])
            if not done:
                return
            request_id=next((e.get("request_id") for e in events if e.get("request_id")),None)
            response=await client.post(f"/api/v1/chat/sessions/{sid}/messages/stream",json=payload)
            repeat_events=[json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
            repeat_id=next((e.get("request_id") for e in repeat_events if e.get("request_id")),None)
            record("sse_idempotency",status=response.status_code,same_request_id=request_id==repeat_id,
                   repeat_types=[e.get("type") for e in repeat_events])
            if request_id:
                response=await client.get(f"/api/v1/chat/requests/{request_id}")
                status=response.json()["data"]
                record("request_status",status=response.status_code,request_status=status.get("status"))
            report["passed"]=request_id==repeat_id
            output.write_text(json.dumps(report,ensure_ascii=False,indent=2))
            print("PASSED",report["passed"],flush=True)

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",default="docs/evidence/2026-11-23-function-calling-local-e2e.json")
    asyncio.run(main(parser.parse_args()))
