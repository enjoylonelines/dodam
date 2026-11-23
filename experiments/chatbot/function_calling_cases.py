"""Frozen synthetic orchestration cases. Not policy eligibility/answer gold labels."""
POLICIES = [
    {"policy_id": "1", "slug": "demo-birth", "policy_name": "가상 출산준비 지원"},
    {"policy_id": "2", "slug": "demo-childcare", "policy_name": "가상 보육비 지원"},
]
A, B = "demo-birth", "demo-childcare"
# Expected task = (business intent, exact policy set). Recommendation has no target.
def task(intent, *slugs):
    return [intent, sorted(slugs)]
CASES = [
    {"id":"S01","group":"single","query":"가상 출산준비 지원의 내용을 알려줘.","expected":[task("policy_summary", A)]},
    {"id":"S02","group":"single","query":"가상 출산준비 지원 신청 준비와 방법을 알려줘.","expected":[task("apply", A)]},
    {"id":"S03","group":"single","query":"가상 출산준비 지원과 가상 보육비 지원을 비교해줘.","expected":[task("compare", A, B)]},
    {"id":"S04","group":"single","query":"가상 보육비 지원의 자격을 내가 충족하는지 확인해줘.","expected":[task("eligibility", B)]},
    {"id":"C01","group":"compound","query":"가상 출산준비 지원과 가상 보육비 지원을 비교하고 두 정책 각각 신청 준비도 알려줘.","expected":[task("compare", A, B),task("apply", A),task("apply", B)]},
    {"id":"C02","group":"compound","query":"가상 출산준비 지원 내용과 내가 자격이 되는지 둘 다 확인해줘.","expected":[task("policy_summary", A),task("eligibility", A)]},
    {"id":"C03","group":"compound","query":"가상 보육비 지원의 자격을 확인하고 신청 준비도 알려줘.","expected":[task("eligibility", B),task("apply", B)]},
    {"id":"C04","group":"compound","query":"가상 출산준비 지원과 가상 보육비 지원 각각 신청 방법을 안내해줘.","expected":[task("apply", A),task("apply", B)]},
    {"id":"C05","group":"compound","query":"가상 출산준비 지원과 가상 보육비 지원의 내용을 각각 요약해줘.","expected":[task("policy_summary", A),task("policy_summary", B)]},
    {"id":"C06","group":"compound","query":"가상 출산준비 지원과 가상 보육비 지원을 비교하고 가상 보육비 지원의 자격도 확인해줘.","expected":[task("compare", A, B),task("eligibility", B)]},
    {"id":"D01","group":"dependent","query":"내 상황에 맞는 정책을 추천하고 추천 목록 첫 번째 정책의 신청 준비도 알려줘.","expected":[task("recommend"),task("apply", A)],"empty_context":True},
    {"id":"D02","group":"dependent","query":"정책을 추천해줘. 그 결과의 첫 번째와 두 번째 정책을 비교해줘.","expected":[task("recommend"),task("compare", A, B)],"empty_context":True},
    {"id":"D03","group":"dependent","query":"정책을 추천한 다음 추천 결과 두 번째 정책의 자격을 확인해줘.","expected":[task("recommend"),task("eligibility", B)],"empty_context":True},
    {"id":"N01","group":"clarification","query":"이거 신청 준비 알려줘.","expected":[],"needs_input":True},
    {"id":"N02","group":"clarification","query":"그 정책 자격을 확인해줘.","expected":[],"needs_input":True},
    {"id":"N03","group":"out_of_scope","query":"내 계정을 삭제하고 돈을 송금해줘.","expected":[],"needs_input":True},
]
