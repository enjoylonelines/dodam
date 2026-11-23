from experiments.chatbot.evaluate_function_calling_ab import score, aggregate
from experiments.chatbot.function_calling_cases import CASES

def test_compound_requires_all_tasks_and_rejects_extra_policy():
    c = next(c for c in CASES if c["id"] == "C01")
    assert not score(c, c["expected"][:1], None, False)["exact_task_match"]
    assert score(c, c["expected"], None, False)["exact_task_match"]
    wrong = [*c["expected"], ["apply", ["invented-policy"]]]
    assert not score(c, wrong, None, False)["exact_task_match"]

def test_error_rows_and_unsupported_clarification_do_not_count_as_success():
    c = next(c for c in CASES if c["id"] == "N01")
    assert not score(c, [], "provider_error", True)["exact_task_match"]
    assert not score(c, [], None, False)["exact_task_match"]
    assert score(c, [], None, True)["exact_task_match"]
    assert not score(c, [["apply", ["demo-birth"]]], None, True)["exact_task_match"]

def test_aggregator_keeps_failure_rows_in_denominator():
    c = CASES[0]
    rows = []
    for arm, error in [("A", None), ("B", "provider_error")]:
        rows.append({"case_id":c["id"],"group":c["group"],"repeat":0,"arm":arm,
                     "scores":score(c,c["expected"] if not error else [],error,False),
                     "error":error,"elapsed_ms":100,"usage":{}})
    result=aggregate(rows)
    assert result["arms"]["B"]["by_group"]["all"]["rows"] == 1
    assert result["arms"]["B"]["by_group"]["all"]["errors"] == 1
    assert result["A_wins"] == 1
