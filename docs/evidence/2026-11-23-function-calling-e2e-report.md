# 실제 로컬 DB·LLM API E2E 결과

## 결과

최종 원시 결과: 2026-11-23-function-calling-local-e2e-v5.json, passed=true.

- 기존 dodam-deepdive-pg 컨테이너 재시작. 로컬 127.0.0.1:55432/dodam 전용.
- 실제 FastAPI 인증·채팅 API, PostgreSQL 저장, PGVector 검색, 실제 OpenAI 호출 사용.
- 기존 source-backed 7정책/21 embedding corpus 유지. 모의 업무 adapter나 dependency override 없음.
- HTTP는 httpx ASGITransport로 앱 전체를 호출했다. 별도 TCP 서버·브라우저 클릭·네트워크 단절 E2E는 아니다.
- 검증 프로세스에서만 function_calling 모드. .env 및 운영 설정 변경 없음.

| 검증 | 결과 |
| --- | --- |
| 가상 로컬 계정 가입·채팅 세션 생성 | HTTP 201 |
| 무료법률상담 정보 조회 | completed, 1 section, 실제 검색 근거 있음 |
| 무료법률상담·에너지바우처 복합 정보 조회 | completed, 2 sections, 각 검색 근거 있음 |
| 두 정책 후 '이거 신청 준비' | needs_input, 정책 선택지 제공, 임의 신청 준비 실행 안 함 |
| 저장 후 messages 재조회 | HTTP 200, 복합 sections 보존 |
| 새 세션의 신청 방법 SSE | HTTP 200, done 1회, section 포함 |
| 같은 idempotency key 재전송 | 동일 request_id, 새 요청으로 중복 처리되지 않음 |
| request status 조회 | HTTP 200, completed |
| 수정 후 백엔드 관련 회귀 | 206 passed, 기존 경고 3종 |

## 실제 E2E에서 발견한 문제와 조치

1. 복원한 로컬 스키마에 migration 272/273/274가 없었다. 로컬에만 적용하고 policy_tag 보조 테이블을 준비했다. 원문 corpus를 다시 생성하거나 운영 DB를 변경하지 않았다.
2. policy_summary의 action_type=None이 정책 연결 테이블에 INSERT되어 실패했다. 정보 조회는 실제 정책 ID를 보존하고 null action 행을 DB에 쓰지 않도록 수정했다.
3. 정보 조회 두 건이 다음 턴 slot의 recent_policies로 남지 않았다. VIEWED를 슬롯 전용 metadata로 추가했다. DB action_type enum은 변경하지 않았다.
4. 기존 정책 후보 맥락이 없다는 이유로 특정 정책 정보 요청을 추천으로 오인한 사례가 있었다. 추천/정보 도구 설명을 분리하고, 정책명만 알고 slug를 모르는 요청은 직접 정보 도구를 호출하도록 명시했다.

초기 시도 파일을 삭제하지 않았다. local-e2e.json은 migration 누락에 따른 temporary_error, v2는 DB 저장 예외 전까지, v3는 잘못된 추천 경로, v4는 모호성의 텍스트 질문까지만 생성된 실패, v5는 보완 후 전체 검증이다.

## 해석 경계

- HTTP 저장·조회와 근거 반환이 확인된 것이며, 답변 문장 전체의 사실성이나 실제 자격 판단을 외부 검수한 결과가 아니다.
- 이전 가상 업무 A/B 수치와 실제 DB E2E를 하나의 정확도 수치로 합치지 않는다. 이전 A/B 소스는 snapshot과 원시 hash로 보존했다.
- 종료 시 SQLAlchemy의 미반납 연결 GC 경고 1건이 출력됐다. 요청 기능 검증은 통과했으나 서버 shutdown·background task/pool 정리의 추가 확인은 남는다.
- 브라우저 육안·실기기·실제 네트워크 disconnect·운영 환경은 미검증이다.
- 새 모드는 opt-in으로 유지한다. 이 결과만으로 기본 배포 경로를 바꾸지 않았다.
- 로컬 DB는 요청에 따라 켜 둔다. 테스트 계정만 생성했고 실제 사용자 계정·운영 데이터는 사용하지 않았다.
