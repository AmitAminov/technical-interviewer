"""AI logic: decide_followup uses the item's follow-up when correctness is low
and never presses a silent candidate."""
from __future__ import annotations

from app.llm.interviewer import decide_followup
from app.schemas import MetricScores, QuestionBankItem


class MockProvider:
    """Non-offline provider returning a canned probe question."""

    name = "mock"

    def __init__(self, reply="What is the time complexity of your approach?"):
        self.reply = reply
        self.calls = 0

    def complete_text(self, system, prompt, max_tokens=800, timeout=20.0):
        self.calls += 1
        return self.reply

    def complete_json(self, system, prompt, schema_model, timeout=30.0):
        raise AssertionError("complete_json must not be used by decide_followup")


ITEM = QuestionBankItem(
    id="fu-1",
    role="Data Scientist",
    topic="Statistics",
    difficulty="Mid-level",
    question_text="Explain what a p-value is.",
    expected_points=["definition", "significance level", "common misconceptions"],
    followups=["How does the p-value relate to the significance level alpha?"],
)


def _metrics(correctness, depth=3):
    return MetricScores(
        correctness=correctness, depth=depth, clarity=3, structure=3,
        practicality=3, mathematical_rigor=3, tradeoff_awareness=3,
        communication=3,
    )


def test_low_correctness_returns_item_followup():
    provider = MockProvider()
    out = decide_followup(
        ITEM, "A p-value is a number you get from a test statistic somehow.",
        _metrics(correctness=2), provider,
    )
    assert out == ITEM.followups[0], "bank follow-up preferred when correctness low"


def test_empty_answer_returns_none():
    provider = MockProvider()
    assert decide_followup(ITEM, "", _metrics(1), provider) is None
    assert decide_followup(ITEM, "   ", _metrics(1), provider) is None
    assert decide_followup(ITEM, "um no", _metrics(1), provider) is None
    assert provider.calls == 0, "no LLM call for empty answers"


def test_substantive_incomplete_answer_gets_llm_probe():
    provider = MockProvider()
    item_no_followups = ITEM.model_copy(update={"followups": []})
    answer = (
        "A p-value is the probability of observing data at least as extreme "
        "as the sample under the null hypothesis, and small values mean the "
        "null is unlikely to produce such data by chance alone."
    )
    out = decide_followup(item_no_followups, answer, _metrics(correctness=3),
                          provider)
    assert out == provider.reply
    assert out.endswith("?")


def test_strong_answer_with_offline_provider_moves_on(offline_provider):
    answer = (
        "A p-value is the probability, computed under the null hypothesis, of "
        "obtaining a result at least as extreme as the one observed; it is "
        "compared against a significance level and is often misinterpreted as "
        "the probability the null hypothesis is true."
    )
    metrics = MetricScores(
        correctness=5, depth=5, clarity=4, structure=4, practicality=3,
        mathematical_rigor=4, tradeoff_awareness=3, communication=4,
    )
    item_no_followups = ITEM.model_copy(update={"followups": []})
    assert decide_followup(item_no_followups, answer, metrics,
                           offline_provider) is None


def test_malformed_llm_probe_is_discarded():
    provider = MockProvider(reply="THIS IS NOT A QUESTION AT ALL")
    item_no_followups = ITEM.model_copy(update={"followups": []})
    answer = ("A p-value is the probability of the observed data or something "
              "more extreme under the null hypothesis of the statistical test.")
    out = decide_followup(item_no_followups, answer, _metrics(3), provider)
    assert out is None, "non-question LLM output must be rejected"
