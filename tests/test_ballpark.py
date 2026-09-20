"""
Deterministic tests for Ballpark using genlayer-test's Direct Mode.

Two layers, matching how the contract's own logic is layered:

1. Integration tests (via direct_deploy + real ask() calls, LLM mocked):
   the happy path, input validation, state bookkeeping, and - critically -
   that the STORED result is the canonical bucketed value, not either
   party's raw extraction (this is the exact defect a steward review
   found: the leader's raw pick was becoming the oracle output regardless
   of how loose the tolerance was).
2. Consensus-boundary tests (via direct_vm.run_validator): Direct Mode
   runs leader_fn directly and only *captures* validator_fn for later
   inspection (real per-validator voting isn't simulated in-process), so
   the bucketing/agreement logic can't be exercised by mocking the LLM
   alone - both leader and a re-run validator would hit the same canned
   response and trivially "agree". run_validator() re-invokes the REAL
   captured validator_fn with an explicit leader_result, which is the
   documented, supported way to test this - not a workaround, the actual
   intended use of the cheatcode.
"""

import json

import pytest

CTX = "Revenue was $4.2M and headcount was 120 people this quarter."


def _deploy(direct_vm, direct_deploy, owner):
    direct_vm.sender = owner
    return direct_deploy("contracts/ballpark.py")


def _mock(direct_vm, response_dict):
    direct_vm.mock_llm("extracting specific numeric figures", json.dumps(response_dict))


# --- Integration: happy path and bookkeeping -------------------------------


def test_initial_state(direct_vm, direct_deploy, direct_owner):
    bp = _deploy(direct_vm, direct_deploy, direct_owner)
    assert bp.get_state()["query_count"] == 0


def test_ask_records_a_query(direct_vm, direct_deploy, direct_owner, direct_alice):
    bp = _deploy(direct_vm, direct_deploy, direct_owner)
    _mock(direct_vm, {"revenue": 42000000, "headcount": 1200000})

    direct_vm.sender = direct_alice
    bp.ask(CTX, ["revenue", "headcount"], 500)

    state = bp.get_state()
    assert state["query_count"] == 1
    q = bp.get_query(0)
    assert q["tolerance_bps"] == 500
    assert json.loads(q["metric_names_json"]) == ["revenue", "headcount"]
    assert json.loads(q["result_json"]) == {"revenue": 42000000, "headcount": 1200000}
    assert q["requester"].lower() == (
        direct_alice if isinstance(direct_alice, str) else "0x" + direct_alice.hex()
    ).lower()


def test_ask_dedupes_metric_names_preserving_order(direct_vm, direct_deploy, direct_owner):
    bp = _deploy(direct_vm, direct_deploy, direct_owner)
    _mock(direct_vm, {"revenue": 42000000})

    bp.ask(CTX, ["revenue", "revenue", " revenue "], 500)

    q = bp.get_query(0)
    assert json.loads(q["metric_names_json"]) == ["revenue"]


def test_ask_marks_ungrounded_extraction_as_null(direct_vm, direct_deploy, direct_owner):
    bp = _deploy(direct_vm, direct_deploy, direct_owner)
    _mock(direct_vm, {"revenue": 42000000})  # headcount omitted by the model

    bp.ask(CTX, ["revenue", "headcount"], 500)

    result = json.loads(bp.get_query(0)["result_json"])
    assert result == {"revenue": 42000000, "headcount": None}


def test_ask_rejects_negative_extracted_value(direct_vm, direct_deploy, direct_owner):
    bp = _deploy(direct_vm, direct_deploy, direct_owner)
    _mock(direct_vm, {"revenue": -100})  # malformed/adversarial model output

    bp.ask(CTX, ["revenue"], 500)

    result = json.loads(bp.get_query(0)["result_json"])
    assert result == {"revenue": None}


def test_get_queries_paginates_newest_first(direct_vm, direct_deploy, direct_owner):
    bp = _deploy(direct_vm, direct_deploy, direct_owner)
    _mock(direct_vm, {"revenue": 1})
    bp.ask(CTX, ["revenue"], 0)
    direct_vm.clear_mocks()
    _mock(direct_vm, {"revenue": 2})
    bp.ask(CTX, ["revenue"], 0)

    recent = bp.get_queries(0, 10)
    assert [json.loads(q["result_json"])["revenue"] for q in recent] == [2, 1]


def test_stored_result_is_the_canonical_bucket_not_the_raw_leader_pick(
    direct_vm, direct_deploy, direct_owner
):
    # This is the exact defect a steward review found: the contract used
    # to store whatever the leader's raw extraction happened to be,
    # unmediated by the tolerance that was supposedly verified. Now the
    # stored value is the bucketed figure - a real, ugly raw extraction
    # like 15437 must come back rounded to the precision the requested
    # tolerance actually implies (500 bps -> 2 significant figures here),
    # not as 15437 itself.
    bp = _deploy(direct_vm, direct_deploy, direct_owner)
    _mock(direct_vm, {"dscr": 15437})

    bp.ask(CTX, ["dscr"], 500)

    result = json.loads(bp.get_query(0)["result_json"])
    assert result == {"dscr": 15000}


# --- Integration: input validation ------------------------------------------


def test_ask_rejects_empty_context(direct_vm, direct_deploy, direct_owner):
    bp = _deploy(direct_vm, direct_deploy, direct_owner)
    with pytest.raises(Exception):
        bp.ask("", ["revenue"], 500)


def test_ask_rejects_too_many_metrics(direct_vm, direct_deploy, direct_owner):
    bp = _deploy(direct_vm, direct_deploy, direct_owner)
    with pytest.raises(Exception):
        bp.ask(CTX, [f"m{i}" for i in range(11)], 500)


def test_ask_rejects_no_metrics(direct_vm, direct_deploy, direct_owner):
    bp = _deploy(direct_vm, direct_deploy, direct_owner)
    with pytest.raises(Exception):
        bp.ask(CTX, [], 500)


def test_ask_rejects_tolerance_over_20_percent(direct_vm, direct_deploy, direct_owner):
    bp = _deploy(direct_vm, direct_deploy, direct_owner)
    with pytest.raises(Exception):
        bp.ask(CTX, ["revenue"], 2001)


# --- Consensus boundary: the real validator_fn, via run_validator ----------


def test_validator_agrees_when_raw_values_round_to_the_same_bucket(
    direct_vm, direct_deploy, direct_owner
):
    # 15000 and 15499 are not byte-identical, but at 500 bps (2 sig figs)
    # they round to the same bucket (15000) - this is the actual point of
    # a tolerance oracle: "close enough" counts, without the stored output
    # ever claiming more precision than was really verified.
    bp = _deploy(direct_vm, direct_deploy, direct_owner)
    _mock(direct_vm, {"dscr": 15000})
    bp.ask(CTX, ["dscr"], 500)

    direct_vm.clear_mocks()
    _mock(direct_vm, {"dscr": 15499})
    agree = direct_vm.run_validator(leader_result=json.dumps({"dscr": 15000}))
    assert agree is True


def test_validator_disagrees_across_a_bucket_boundary(direct_vm, direct_deploy, direct_owner):
    # 15499 and 15500 differ by a single raw unit (a rounding difference
    # nobody would call "material"), but they straddle the 2-sig-fig grid
    # line (15000 vs 16000) and so land in different buckets. This is a
    # known, accepted property of any bucketed/quantized agreement scheme
    # (the same thing happens rounding a clock to the nearest minute) -
    # documented here deliberately, not treated as a bug.
    bp = _deploy(direct_vm, direct_deploy, direct_owner)
    _mock(direct_vm, {"dscr": 15499})
    bp.ask(CTX, ["dscr"], 500)

    direct_vm.clear_mocks()
    _mock(direct_vm, {"dscr": 15500})
    agree = direct_vm.run_validator(leader_result=json.dumps({"dscr": 15000}))
    assert agree is False


def test_validator_zero_tolerance_requires_exact_raw_match(direct_vm, direct_deploy, direct_owner):
    # tolerance_bps=0 skips bucketing entirely (the bucket of a value at
    # zero tolerance is the value itself), so it subsumes strict equality
    # as a special case.
    bp = _deploy(direct_vm, direct_deploy, direct_owner)
    _mock(direct_vm, {"dscr": 15000})
    bp.ask(CTX, ["dscr"], 0)

    direct_vm.clear_mocks()
    _mock(direct_vm, {"dscr": 15001})
    agree = direct_vm.run_validator(leader_result=json.dumps({"dscr": 15000}))
    assert agree is False


def test_validator_zero_tolerance_agrees_on_exact_match(direct_vm, direct_deploy, direct_owner):
    bp = _deploy(direct_vm, direct_deploy, direct_owner)
    _mock(direct_vm, {"dscr": 15000})
    bp.ask(CTX, ["dscr"], 0)

    direct_vm.clear_mocks()
    _mock(direct_vm, {"dscr": 15000})
    agree = direct_vm.run_validator(leader_result=json.dumps({"dscr": 15000}))
    assert agree is True


def test_validator_small_values_are_never_bucketed(direct_vm, direct_deploy, direct_owner):
    # Values with fewer digits than the tolerance's significant-figure
    # count pass through _bucket unchanged - there's no free pass for
    # small numbers just because they're short.
    bp = _deploy(direct_vm, direct_deploy, direct_owner)
    _mock(direct_vm, {"dscr": 4})
    bp.ask(CTX, ["dscr"], 500)

    direct_vm.clear_mocks()
    _mock(direct_vm, {"dscr": 5})
    agree = direct_vm.run_validator(leader_result=json.dumps({"dscr": 4}))
    assert agree is False


def test_validator_disagrees_when_only_one_side_has_null(direct_vm, direct_deploy, direct_owner):
    bp = _deploy(direct_vm, direct_deploy, direct_owner)
    _mock(direct_vm, {"dscr": 15000})
    bp.ask(CTX, ["dscr"], 500)

    direct_vm.clear_mocks()
    _mock(direct_vm, {"dscr": None})
    agree = direct_vm.run_validator(leader_result=json.dumps({"dscr": 15000}))
    assert agree is False


def test_validator_agrees_when_both_sides_null(direct_vm, direct_deploy, direct_owner):
    bp = _deploy(direct_vm, direct_deploy, direct_owner)
    _mock(direct_vm, {"dscr": None})
    bp.ask(CTX, ["dscr"], 500)

    direct_vm.clear_mocks()
    _mock(direct_vm, {"dscr": None})
    agree = direct_vm.run_validator(leader_result=json.dumps({"dscr": None}))
    assert agree is True


def test_validator_requires_all_metrics_to_agree(direct_vm, direct_deploy, direct_owner):
    # One metric within tolerance is not enough if another isn't - a
    # partial mismatch across the requested vector still fails the whole
    # query, since it suggests the model genuinely misread the source text
    # rather than just rounding differently.
    bp = _deploy(direct_vm, direct_deploy, direct_owner)
    _mock(direct_vm, {"revenue": 42000000, "headcount": 1200000})
    bp.ask(CTX, ["revenue", "headcount"], 500)

    direct_vm.clear_mocks()
    # revenue matches exactly, headcount is wildly off
    _mock(direct_vm, {"revenue": 42000000, "headcount": 9999999})
    leader_result = json.dumps({"revenue": 42000000, "headcount": 1200000})
    agree = direct_vm.run_validator(leader_result=leader_result)
    assert agree is False


# --- The specific case a steward review flagged: max tolerance was too weak -


def test_max_tolerance_no_longer_lets_zero_and_one_agree(direct_vm, direct_deploy, direct_owner):
    # The rejected version compared raw values with a relative-tolerance
    # check and a zero special-case that degenerated at MAX tolerance:
    # leader=0 and a validator reporting 1 both "validated". Bucketing
    # closes this outright - bucket(0, *) is always 0, and 1 has fewer
    # digits than any sig-fig count so it's never rounded down to 0.
    bp = _deploy(direct_vm, direct_deploy, direct_owner)
    _mock(direct_vm, {"dscr": 0})
    bp.ask(CTX, ["dscr"], 2000)  # MAX_TOLERANCE_BPS

    direct_vm.clear_mocks()
    _mock(direct_vm, {"dscr": 1})
    agree = direct_vm.run_validator(leader_result=json.dumps({"dscr": 0}))
    assert agree is False


def test_max_tolerance_still_rejects_different_orders_of_magnitude(
    direct_vm, direct_deploy, direct_owner
):
    bp = _deploy(direct_vm, direct_deploy, direct_owner)
    _mock(direct_vm, {"dscr": 50000})
    bp.ask(CTX, ["dscr"], 2000)

    direct_vm.clear_mocks()
    _mock(direct_vm, {"dscr": 15000})  # a little over 3x smaller
    agree = direct_vm.run_validator(leader_result=json.dumps({"dscr": 50000}))
    assert agree is False


def test_max_tolerance_still_agrees_on_genuinely_close_values(
    direct_vm, direct_deploy, direct_owner
):
    # Even at the loosest allowed tolerance (1 significant figure), values
    # within ~10% of each other that round to the same leading digit
    # still agree - the band isn't so loose it rejects everything either.
    # Leader's raw 52000 buckets to 50000 (what leader_fn actually
    # returns) - that bucketed value, not the raw 52000, is what a real
    # leader_result would be.
    bp = _deploy(direct_vm, direct_deploy, direct_owner)
    _mock(direct_vm, {"dscr": 52000})
    bp.ask(CTX, ["dscr"], 2000)

    direct_vm.clear_mocks()
    _mock(direct_vm, {"dscr": 48000})
    agree = direct_vm.run_validator(leader_result=json.dumps({"dscr": 50000}))
    assert agree is True


# --- Pure bucketing thresholds, exercised through the public write path ----


@pytest.mark.parametrize(
    "raw,tolerance_bps,expected",
    [
        (15437, 0, 15437),       # exact: no bucketing at all
        (15437, 10, 15437),      # <=0.1% -> 5 sig figs, 5-digit value unchanged
        (154370, 10, 154370),    # 6-digit value, 5 sig figs -> rounds to 10s
        (15437, 100, 15440),     # <=1% -> 4 sig figs
        (15437, 400, 15400),     # <=4% -> 3 sig figs
        (15437, 401, 15000),     # >4% -> 2 sig figs
        (15437, 1000, 15000),    # <=10% -> 2 sig figs
        (15437, 1001, 20000),    # >10% -> 1 sig fig
        (15437, 2000, 20000),    # MAX_TOLERANCE_BPS -> 1 sig fig
    ],
)
def test_bucket_thresholds_via_stored_result(
    direct_vm, direct_deploy, direct_owner, raw, tolerance_bps, expected
):
    bp = _deploy(direct_vm, direct_deploy, direct_owner)
    _mock(direct_vm, {"x": raw})
    bp.ask(CTX, ["x"], tolerance_bps)
    result = json.loads(bp.get_query(0)["result_json"])
    assert result == {"x": expected}
