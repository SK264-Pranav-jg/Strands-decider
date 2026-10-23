import pytest

from support.decider import DeciderError
from support.gate import CONTEXT_CHARS, build_state, decide
from tests.fakes import answers


def with_follow_up(a: dict, score: float) -> dict:
    return a | {"follow_up": {"type": "noul", "noul": score}}


def test_in_scope_at_or_above_the_threshold():
    assert decide(answers(0.9), 0.5)["decision"] == "in_scope"
    assert decide(answers(0.5), 0.5)["decision"] == "in_scope"
    assert decide(answers(0.49), 0.5)["decision"] == "out_of_scope"


def test_follow_up_brings_a_vague_reply_in_scope():
    v = decide(with_follow_up(answers(0.25), 0.8), 0.5)
    assert (v["decision"], v["reason"]) == ("in_scope", "follow_up")
    assert v["scope"] == 0.8 and v["in_scope"] == 0.25


def test_low_follow_up_stays_out_of_scope():
    v = decide(with_follow_up(answers(0.25), 0.3), 0.5)
    assert (v["decision"], v["reason"]) == ("out_of_scope", None)


def test_without_previous_reply_there_is_no_follow_up_score():
    v = decide(answers(0.9), 0.5)
    assert v["follow_up"] is None and v["scope"] == 0.9 and v["reason"] is None


def test_malformed_answer_fails_closed():
    with pytest.raises(DeciderError):
        decide({"in_scope": {"type": "noul"}}, 0.5)


def test_state_includes_truncated_previous_reply():
    assert build_state("hi") == "Customer message: hi"
    state = build_state("yes", "x" * 1000)
    assert state.startswith("Assistant's previous reply: " + "x" * CONTEXT_CHARS + "...")
    assert state.endswith("Customer message: yes")
