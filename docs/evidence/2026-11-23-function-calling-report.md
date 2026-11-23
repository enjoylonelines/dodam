# 도담 Function Calling 전환·A/B 결과

작성: 2026-11-23 Asia/Seoul

## 결론

Responses API 업무 도구 루프와 기존 업무 adapter, 복합 응답 저장·재조회 계약 및 프런트 표시를 구현했다. 개발용 고정 평가셋에서는 단일 업무를 유지하면서 복합 업무와 결과 의존 후속 호출을 처리했다. 지연은 증가했다. Function Calling 형식만 바꿔서 정책 답변 정확도가 향상됐다는 결과가 아니다.

## 구현·환경

- Backend: /Users/hb/Projects/bistel-mini-2-backend, develop, base ac27014485a2986c0b41588fe5eac83be63ac402
- Frontend: /Users/hb/Projects/bistel-mini-2-frontend, develop, base 50690f27ff6689c2f810509fab96afb5bc913ad1
- 기존 미커밋 검색·프런트 개선을 보존하고 같은 checkout에서 추가했다. 브랜치/워크트리 전환, commit/push, 운영 배포, .env 변경 없음.
- 기본 CHAT_ROUTING_MODE=legacy. function_calling을 명시하면 새 요청에 새 경로를 사용한다. 기존 pending 세션은 legacy resume를 유지한다.
- 업무 도구: recommend_policies / get_policy_information / compare_policies / check_policy_eligibility / get_application_preparation.
- 인증 사용자·DB·실행 문맥은 서버 주입. 모델이 제공한 정책 slug는 기존 세션/현재 결과에서 검증한다.
- 4회 순차 업무 호출 기본값, 동등 인자 반복 차단, 시간 제한, 명시적 취소 guard, 실패 시 부분 결과 유지, 숨은 legacy 재실행 없음.
- Responses store=false, SDK 자동 재시도 0, output 상한 적용. reasoning item과 call_id를 다음 요청에 보존한다.
- 정보 조회는 대상 정책으로 scope한 기존 검색을 수행한다. 추천에서는 모델이 재작성한 query 대신 원래 사용자 요청을 전달한다.
- 기존 업무 결과를 sections로 묶고 기존 card/근거/검증 경로를 재사용한다. 모델의 최종 자유 문구로 검증된 업무 결과를 덮어쓰지 않는다.
- trace는 structured_json._tool_execution으로 내부 저장한다. sections와 execution_status는 send/history 응답에도 보존한다.
- 프런트는 여러 sections의 카드·근거를 개별 표시한다. 기존 단일 결과 UI와 호환한다.

## 평가 조건

- 모델: gpt-5.4-mini.
- 같은 질문 16개 × 2회 × A/B = 64 rows / sweep.
- A: 실제 기존 의도 분류와 run_chat_legacy. 업무 Handler만 fixture adapter로 대체.
- B: 실제 Responses API Function Calling 및 서버 실행 제어. 같은 fixture business service 사용.
- 가상 정책 두 개, 사전 고정된 예상 업무·정책 조합. 실제 사용자 정보/운영 DB 사용 없음.
- 순서는 case/repeat별 A/B 교대. provider usage는 실제 반환 token metadata.
- 완전 일치: 요청된 업무와 대상 정책 집합 모두 일치하고 불필요한 업무가 없어야 한다. 보충 질문 사례는 실행하지 않고 입력 요청으로 끝나야 한다.
- 예외 행은 분모에서 제외하지 않았다. 이 평가의 '정확도'는 업무·대상 정책 선택 정확도이며, 실제 RAG 검색 품질·최종 문장 사실성·자격 판단 정확도가 아니다.
- 비교는 prompt·도구 계약·서버 guard를 포함한 시스템 A/B다. API 형식만의 인과 효과를 분리한 실험이 아니다.

## 첫 평가 보존

원시 결과: 2026-11-23-function-calling-ab.json

A 완전 일치 10/32(31.25%), B 28/32(87.5%). B의 단일 업무 8/8, 복합 11/12, 후속 6/6, 모호성 1/4, 범위 밖 미실행 2/2. 단일 정책 도구에 복수 참조가 들어온 차단 4건(C05 1건, N01/N02 3건)을 실패로 포함했다.

그 후 단일 정책 수 제한을 native schema에 명시하고, 여러 정책이 존재할 때 모호한 지시어는 서버가 정책 선택을 요청하도록 보완했다. 모호성 개선은 서버 guard의 기여이며 모델의 의미 이해 개선으로 해석하지 않는다.

## 보완 후 평가

원시 결과: 2026-11-23-function-calling-ab-v2.json
Dataset SHA256: 121f60a066963f71f0510037d23726848b87cd87bd636d0f3855acadff1e82a8
재개 실행 시 모델·데이터셋·관련 source SHA256 일치를 검증했다. 최종 source hash와 결과 파일의 hash 일치 확인.

| 유형 | 문항 × 반복 / arm | 기존 A | 새 경로 B |
| --- | ---: | ---: | ---: |
| 단일 업무 | 4 × 2 = 8 | 8/8 | 8/8 |
| 복합 업무 | 6 × 2 = 12 | 0/12 | 12/12 |
| 결과 의존 후속 업무 | 3 × 2 = 6 | 0/6 | 6/6 |
| 모호한 참조에서 보충 질문 | 2 × 2 = 4 | 0/4 | 4/4 |
| 범위 밖 업무 미실행 | 1 × 2 = 2 | 2/2 | 2/2 |
| 전체 업무·정책 완전 일치 | 16 × 2 = 32 | 10/32 (31.25%) | 32/32 (100%) |

A는 복합 요청에서 일부 업무는 처리하지만 전체 업무 완수 기준에서는 실패한다. 0/12를 모든 응답이 무의미했다는 뜻으로 해석하지 않는다.
짝 비교 32쌍: B만 성공 22, A만 성공 0, 동률 10.

| 관측 지표 | A | B |
| --- | ---: | ---: |
| 전체 elapsed p50 | 1,053.8355ms | 3,424.452ms |
| 전체 elapsed p95 (소표본 nearest rank) | 1,454.786ms | 4,705.813ms |
| provider total tokens / 32 rows | 94,179 | 103,283 |
| provider usage 관측 행 | 32/32 | 32/32 |
| runtime error | 0 | 0 |

B는 도구 결과를 받아 후속 판단하는 추가 왕복으로 이 실험의 중앙 지연이 약 3.25배였다. 모델 API만의 latency가 아닌 orchestration 전체 elapsed이며 업무 서비스는 가상 fixture라 실제 배포 지연을 예측하지 않는다. 토큰 금액 환산은 하지 않았다.

## 테스트·검증

- 백엔드 관련 회귀 200 passed (신규 runtime/adapter/ambiguity 26개 포함), 4.67초.
- 평가 채점 회귀 3 passed, 0.98초. 부분 업무·잘못된 정책·과잉 업무·예외 행이 성공으로 계산되지 않는지 확인.
- 기존 테스트 경고 3종(passlib crypt deprecation, Pydantic serializer warning, AsyncMock await warning) 존재. 실패는 없음.
- 프런트 chat progress 8 passed.
- 수정한 프런트 apis/chatApi.js와 app/chat/page.js ESLint 통과.
- Next.js production build 통과.
- backend/frontend git diff --check 통과.
- 첫 sweep과 보완 sweep 모두 64 rows. 총 128 rows(각 row는 모델 호출 여러 건일 수 있음).
- 이번 모델 평가에서 사용한 업무 결과는 모두 가상 fixture. 실제 LLM 호출과 도구 프로토콜은 사용했다.

## 남은 한계와 배포 판단

1. 기존 로컬 .env의 PostgreSQL loopback 55432에 연결을 시도했으나 connection refused였다. 실제 DB/RAG/lifecycle/브라우저를 잇는 전체 E2E는 미실행이며, 다른 프로젝트 컨테이너를 변경하지 않았다.
2. 업무 adapter는 단위/회귀 테스트로 확인했다. 실제 검색·추천·자격 판단 모델까지 포함한 운영 품질 또는 비용 절감을 주장하지 않는다.
3. 같은 개발 평가셋을 보고 한 번 보완한 결과다. 독립 holdout 또는 실제 사용자 분포에 대한 일반화는 검증하지 않았다. 32/32는 32개 독립 질문이 아니라 16개 질문의 2회 반복이다.
4. pending 복합 목표를 여러 턴에 걸쳐 자동 재개하는 기능은 미구현이다. pending은 기존 resume를 사용한다.
5. 프로세스 종료 후 중간 native transcript를 복원하는 durable resume와 요청 간 business-call idempotency ledger는 미구현이다. 동일 실행 안의 중복 호출 차단과 기존 ChatRequest/lifecycle 기능까지만 적용한다.
6. 모호성 guard는 제한된 지시어 규칙이다. 모든 한국어 참조를 해결하는 보장은 없다.
7. 브라우저 육안 검증은 미실행. 프런트 build/lint와 progress 테스트까지만 확인했다.
8. 신규 기본 경로 전환과 운영 배포는 보류한다. 현재 결과는 한 턴 복합 상담 orchestration의 개발 검증 근거다. 실제 격리 DB에서 단일/복합/보충 질문/취소/새로고침 재조회 E2E를 확인한 뒤 기본 경로를 전환하는 것이 적절하다.

## 이후 실제 DB E2E 보강 (같은 날 후속 작업)

사용자의 추가 지시로 기존 로컬 dodam-deepdive-pg를 켜고 실제 API·RAG·LLM·저장을 확인했다. 이전의 DB 미실행 설명은 위 A/B 완료 시점의 상태다. 후속 E2E 원시 결과와 개인 publication 문서를 함께 읽어야 한다.

실제 DB 경로에서 정보 조회의 null action_type INSERT와 정보 조회 결과가 다음 턴 정책 문맥에 남지 않는 결함을 발견했다. DB action enum은 변경하지 않고, 정보 조회의 실제 정책 ID를 보존하며 VIEWED는 슬롯 메타데이터에만 기록하도록 보강했다. 특정 정책명만 있고 기존 후보 문맥이 없을 때 추천으로 오인하는 사례는 도구 설명을 명확히 하여 수정했다. 이 후속 수정에 이전 A/B의 32/32를 소급 적용하지 않는다.

A/B v2에서 사용한 두 파일은 experiments/chatbot/snapshots/function_calling_ab_v2/에 보존했다. JSON source_sha256과 snapshot 두 파일의 SHA256이 일치한다. 현재 운영 후보 코드와 당시 실험 코드를 혼동하지 않는다.

## 재현

Backend에서:
- .venv/bin/python -m experiments.chatbot.evaluate_function_calling_ab --repeats 2 --output <새로운 결과 경로>
- 기존 결과에 --resume를 사용할 때는 source hashes가 일치해야 한다.
- 테스트 파일: test_chat_function_calling.py / test_chat_function_calling_adapter.py / test_chat_function_calling_ambiguity.py / test_function_calling_ab_scoring.py 및 기존 chat 회귀.
- 애플리케이션에서 명시적으로 CHAT_ROUTING_MODE=function_calling 설정 시 선택 가능. 원복은 legacy. 실제 운영 설정은 이번 작업에서 변경하지 않았다.

포트폴리오 문구:
“도담의 상담 라우터에 Responses API Function Calling 기반 업무 조합 경로를 추가했습니다. 가상 업무 결과를 공유하는 16문항·방식별 2회 실제 모델 평가에서 복합 요청 완수는 0/12에서 12/12, 단일 업무는 8/8로 유지됐습니다. 모호성 처리는 서버 검증을 보강했으며 중앙 지연은 1.05초에서 3.42초로 증가했습니다. 실제 상담 답변의 사실성이나 운영 성능 평가는 별도입니다.”
