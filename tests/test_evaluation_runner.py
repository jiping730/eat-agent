from evaluation.dataset import load_suite
from evaluation.metrics import calculate_metrics
from evaluation.runner import build_report, run_deterministic


def test_builtin_evaluation_suites_are_normalized_and_unique():
    rag_cases = load_suite("rag")
    grill_cases = load_suite("grill")

    assert len(rag_cases) == 18
    assert len(grill_cases) == 64
    assert all(case.suite == "rag" for case in rag_cases)
    assert all(case.suite == "grill" for case in grill_cases)
    assert all(case.case_id for case in [*rag_cases, *grill_cases])
    assert len({case.case_id for case in [*rag_cases, *grill_cases]}) == len(rag_cases) + len(grill_cases)


def test_deterministic_runner_passes_current_rag_and_grill_fixtures():
    cases = [*load_suite("rag"), *load_suite("grill")]
    results = run_deterministic(cases, top_k=2)
    report = build_report(
        results,
        mode="deterministic",
        thresholds={
            "min_rag_recall": 0.9,
            "min_grill_accuracy": 0.9,
            "max_invalid_retrieval_rate": 0.15,
            "min_safety_pass_rate": 0.9,
        },
    )

    assert report["passed"] is True
    assert report["metrics"]["rag"]["recall_at_k"] == 1.0
    assert report["metrics"]["grill"]["action_accuracy"] == 1.0
    assert report["metrics"]["safety"]["safety_case_pass_rate"] == 1.0


def test_metrics_keep_invalid_retrieval_rate_explicit():
    results = [
        {
            "suite": "rag",
            "passed": False,
            "should_retrieve": False,
            "checks": {"should_retrieve": False},
            "details": {"retrieval_count": 1, "covered_source_count": 0},
            "expected_sources": [],
        },
        {
            "suite": "rag",
            "passed": True,
            "should_retrieve": False,
            "checks": {"should_retrieve": True},
            "details": {"retrieval_count": 0, "covered_source_count": 0},
            "expected_sources": [],
        },
    ]

    assert calculate_metrics(results)["rag"]["invalid_retrieval_rate"] == 0.5
