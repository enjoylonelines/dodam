# 개인 저장소 검증 브랜치 공개 범위

- 개인 repository: enjoylonelines/dodam (public, owner type User, admin/push permission 확인).
- 개인 기본 develop: 0a1da16275b042db4ea98cae55aa361299a38e0a 유지.
- 신규 원격 브랜치: feature/276-function-calling-e2e. 개인 develop의 기존 검색 개선을 기반으로 Function Calling 변경을 추가한다.
- 로컬 backend develop 및 원래 origin(bistel-mini-2 팀 저장소)은 변경/푸시하지 않는다.
- frontend origin도 팀 저장소이므로 push하지 않는다. 로컬 frontend develop 50690f27ff6689c2f810509fab96afb5bc913ad1 대비 apis/chatApi.js와 app/chat/page.js의 현재 diff를 2026-11-23-dodam-frontend.patch로 개인 branch에 보존한다. 이 patch는 이번 섹션 표시 변경과 해당 파일의 선행 로컬 UI 보강을 함께 포함한다.
- .env, 계정 비밀번호, access token, 데이터베이스 dump는 공개 범위에서 제외한다.
- E2E는 기존 dodam-deepdive-pg (localhost:55432/dodam) 컨테이너를 재시작하고 source-backed 7정책/21 embedding corpus를 사용한다. 부족한 기존 migration 272/273/274 및 policy_tag만 로컬에 반영한다. 운영 DB 접속/변경 없음.
- 첫 E2E에서 누락 migration을 확인했고, 그 다음 실제 DB 저장에서 policy_summary의 action_type=None을 INSERT하는 결함을 발견했다. 정보 섹션은 null action 연결을 저장하지 않고 실제 policy ID를 보존하도록 수정했다. 이전 A/B 결과는 orchestration 평가로 유지하며 이 persistence fix를 그 결과에 소급해 주장하지 않는다.
- backend default routing은 여전히 legacy다. 검증 프로세스에서만 function_calling 모드를 명시한다. main/default 배포 브랜치나 운영 환경 설정은 수정하지 않는다.
