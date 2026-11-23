# 도담 Function Calling 전환과 A/B 검증

## 목표와 결정
사용자 승인: 상담 유연성을 중심으로 설계·구현 후 정확도와 유연성 A/B까지 수행한다. 정확도 향상은 사전 가정하지 않는다. develop ac27014485a2986c0b41588fe5eac83be63ac402에서 기존 미커밋 검색 개선을 보존한다. 운영 배포·기본 경로 변경·git push는 범위 밖이다.

## 설계
기존 direct router(A)를 유지한다. 선택 가능한 Responses API 기반 순차 업무 도구 루프(B)를 추가한다. 정책 정보, 비교, 추천, 자격 확인, 신청 준비를 기존 handler/lifecycle의 어댑터로 실행한다. 인증 identity는 서버에서 주입한다. 모델이 입력한 정책 참조는 기존 세션/현재 실행의 실제 결과 목록에서 검증하며 미확인 정책은 기존 resolver로 검색하도록 query만 받는다. 도구 결과는 서버가 구성한 sections로 보존하고 모델 최종 문구로 업무 결과를 대체하지 않는다.

기존 pending/프로필 확인은 legacy resume 경로를 유지한다. v1은 한 턴 안의 복합 요청을 대상으로 한다. 여러 턴에 걸친 미완료 복합 목표의 자동 재개는 별도 범위로 남긴다. 새 루프 내부는 자동 재실행하지 않는다. 기존 ChatRequest idempotency와 business lifecycle을 재사용하되 프로세스 중단 후 중간 tool transcript를 이어 실행하는 durable resume는 v1에 포함하지 않는다.

## 실행 경계
최대 업무 실행 4회, 순차 실행, 동일 도구/인자 fingerprint 재사용, 전체 시간 제한, 모델 output 상한. 명시적 취소 확인을 모델·업무 호출 직전과 결과 후 수행한다. 연결 단절은 취소와 구분한다. 업무 도구 실패 후 legacy 전체 요청 재실행을 하지 않는다. 오류·한도 종료 시 이미 검증된 부분 결과만 제공한다. 실패를 성공 섹션으로 기록하지 않는다. 모델 API store=false, SDK 자동 retry=0. 키와 실제 개인 정보는 기록하지 않는다.

## 평가 설계 (구현 전에 고정)
A는 기존 run_chat/classifier와 단일 handler 라우팅, B는 신규 Responses 도구 루프다. 같은 모델, 질문, 맥락, 고정 정책 fixture 업무 결과를 사용한다. 이 비교는 실제 LLM orchestration + deterministic fixture business adapter 평가이며 실제 RAG/DB/전체 서비스 품질 평가가 아니다. A의 handler와 B의 adapter는 동일한 fixture service 함수를 호출한다. 도구 반환 결과로만 content를 구성하여 허위 모델 요약이 성공으로 계산되지 않게 한다.

평가 질문은 단일/복합/동적 후속/모호성/범위 밖으로 나누고 기대 업무 및 정책을 사전에 고정한다. 고정 입력 16개 × 각 arm 2회=64 rows를 목표로 하며, 시간·토큰은 API가 반환한 usage와 전체 실행 시간으로 기록한다. 실행 순서는 case/repeat별 A/B 교대한다. API 오류 행은 제외하지 않고 별도 집계한다. paired difference와 유형별 결과를 보고한다. 소규모 개발 평가로 통계적 일반화·운영 SLA·정책 자격 정확도를 주장하지 않는다.

모의 모델 회귀: 미등록 도구, 잘못된 인자, 조작된 정책 ID, 중복 호출, 호출 예산, timeout, 명시적 취소, 부분 실패, reasoning item/call_id round trip, 기존 pending resume, sections 저장·재조회. 실제 서비스 연결 smoke는 격리 환경에서 별도 수행할 수 있을 때만 보고한다.

## 종료 기준
관련 회귀 통과, 실제 모델 A/B 원시 결과와 집계 생성, 단일 업무·복합 업무·정책 참조 정확도·오류·사용량 분리 보고, 배포 전 남은 한계 기록. 성능이 나쁘거나 동률이어도 결과를 보존하고 자동 채택하지 않는다.
