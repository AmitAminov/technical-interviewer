"""AI logic: thorough correct answers must outscore short vague answers."""
from __future__ import annotations

from app.core.scoring import compute_overall
from app.llm.scorer import evaluate_answer, heuristic_evaluate
from app.schemas import QuestionBankItem

ITEM = QuestionBankItem(
    id="quality-1",
    role="Data Scientist",
    topic="Model evaluation",
    difficulty="Mid-level",
    question_text="How would you evaluate a binary classification model?",
    expected_points=[
        "precision and recall",
        "ROC curve and AUC",
        "class imbalance",
        "threshold selection",
        "cross-validation",
    ],
)

GOOD_ANSWER = (
    "First, I would look at precision and recall rather than raw accuracy, "
    "because with class imbalance accuracy is misleading. For example, with a "
    "1% positive rate a majority-class predictor scores 99% accuracy. I would "
    "plot the ROC curve and compute the AUC to compare models across "
    "operating points, and then do explicit threshold selection based on the "
    "cost of false positives versus false negatives — that is a business "
    "trade-off, not a purely statistical one. To estimate generalization "
    "robustly I would use stratified cross-validation and report the variance "
    "across folds. In practice I also monitor the metric in production, since "
    "the data distribution drifts; however, offline evaluation comes first."
)

BAD_ANSWER = "You just check if the model is good with accuracy I guess."


def test_good_answer_strictly_outscores_bad(offline_provider):
    good_metrics, _ = evaluate_answer(ITEM, GOOD_ANSWER, "Data Scientist", [],
                                      offline_provider)
    bad_metrics, _ = evaluate_answer(ITEM, BAD_ANSWER, "Data Scientist", [],
                                     offline_provider)
    good = compute_overall(good_metrics, "Data Scientist", 0)
    bad = compute_overall(bad_metrics, "Data Scientist", 0)
    assert good > bad, "thorough correct answer must score strictly higher"
    assert good - bad >= 1.0, "gap should be substantial ({0} vs {1})".format(good, bad)
    assert good_metrics.correctness > bad_metrics.correctness
    assert good_metrics.depth > bad_metrics.depth


def test_feedback_names_covered_and_missing_points(offline_provider):
    _, good_fb = evaluate_answer(ITEM, GOOD_ANSWER, "Data Scientist", [],
                                 offline_provider)
    assert "precision and recall" in good_fb
    _, bad_fb = evaluate_answer(ITEM, BAD_ANSWER, "Data Scientist", [],
                                offline_provider)
    assert "Missing expected points" in bad_fb


def test_heuristic_monotone_in_expected_point_coverage():
    """Matching strictly more expected points never lowers any metric."""
    base = "I would evaluate the model carefully considering several aspects of it."
    additions = [
        " I would use precision and recall as headline metrics.",
        " I would plot the ROC curve and compute AUC.",
        " Class imbalance must be handled, e.g. by stratification.",
        " Threshold selection depends on the error costs.",
        " Cross-validation gives a robust estimate.",
    ]
    prev = None
    text = base
    for add in additions:
        text = text + add
        metrics, _ = heuristic_evaluate(ITEM.expected_points, text)
        if prev is not None:
            for name in prev.model_dump():
                assert getattr(metrics, name) >= getattr(prev, name), name
        prev = metrics
    assert prev.correctness == 5, "full coverage reaches max correctness"


def test_full_coverage_beats_partial_coverage(offline_provider):
    partial = (
        "I would use precision and recall as the main evaluation metrics for "
        "the classifier and report both of them together with the counts."
    )
    full = partial + (
        " I would also plot the ROC curve and compute the AUC, account for "
        "class imbalance, run cross-validation, and tune threshold selection."
    )
    pm, _ = evaluate_answer(ITEM, partial, "Data Scientist", [], offline_provider)
    fm, _ = evaluate_answer(ITEM, full, "Data Scientist", [], offline_provider)
    assert fm.correctness > pm.correctness
    assert compute_overall(fm, "Data Scientist", 0) > compute_overall(pm, "Data Scientist", 0)
