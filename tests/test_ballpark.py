"""
Deterministic tests for Ballpark using genlayer-test's Direct Mode.

Two layers, matching how the contract's own logic is layered:

1. Integration tests (via direct_deploy + real ask() calls, LLM mocked):
   the happy path, input validation, state bookkeeping, and - directly
   targeting a rejected earlier revision's defect - proof that the stored
   result is the raw, verified extraction, not a further-rounded figure
   that no longer matches what tolerance_bps actually verified.
2. Consensus-boundary tests (via direct_vm.run_validator): Direct Mode
   runs leader_fn directly and only *captures* validator_fn for later
   inspection (real per-validator voting isn't simulated in-process), so
   the tolerance math itself can't be exercised by mocking the LLM alone -
   both leader and a re-run validator would hit the same canned response
   and trivially "agree". run_validator() re-invokes the REAL captured
   validator_fn with an explicit leader_result, which is the documented,
   supported way to test this - not a workaround. These are exact,
   deterministic boundary tests (agrees at exactly tolerance_bps, fails
   one unit past it) - the earlier significant-figure-rounding revision
   could never support tests this precise, since its effective tolerance
   varied depending on where a value fell within its own digit range.
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


def test_stored_result_is_the_raw_verified_value(direct_vm, direct_deploy, direct_owner):
    # An earlier revision of this contract rounded the stored value to a
    # number of significant figures - which a steward review correctly
    # flagged as not actually reflecting tolerance_bps (see _within_tolerance's
    # docstring). The stored value is now the leader's raw extraction,
    # exactly as the model returned it - the guarantee that it's within
    # tolerance_bps of every agreeing validator's own extraction lives in
    # the comparison (tested below), not in further-rounding the output.
    bp = _deploy(direct_vm, direct_deploy, direct_owner)
    _mock(direct_vm, {"dscr": 15437})

    bp.ask(CTX, ["dscr"], 500)

    result = json.loads(bp.get_query(0)["result_json"])
    assert result == {"dscr": 15437}


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
# Exact, deterministic boundary tests: leader=10000 (an arbitrary round
# base), tolerance_bps=500 (5%) implies an agreement radius of exactly
# diff <= 500 raw units - verified precisely at, and one unit past, that
# boundary.


def test_validator_agrees_within_tolerance(direct_vm, direct_deploy, direct_owner):
    bp = _deploy(direct_vm, direct_deploy, direct_owner)
    _mock(direct_vm, {"dscr": 10000})
    bp.ask(CTX, ["dscr"], 500)

    direct_vm.clear_mocks()
    _mock(direct_vm, {"dscr": 10200})  # 2% off - well inside 5%
    agree = direct_vm.run_validator(leader_result=json.dumps({"dscr": 10000}))
    assert agree is True


def test_validator_agrees_at_exact_tolerance_boundary(direct_vm, direct_deploy, direct_owner):
    bp = _deploy(direct_vm, direct_deploy, direct_owner)
    _mock(direct_vm, {"dscr": 10000})
    bp.ask(CTX, ["dscr"], 500)

    direct_vm.clear_mocks()
    _mock(direct_vm, {"dscr": 10500})  # exactly 5% off - "<=", not "<"
    agree = direct_vm.run_validator(leader_result=json.dumps({"dscr": 10000}))
    assert agree is True


def test_validator_disagrees_one_unit_past_boundary(direct_vm, direct_deploy, direct_owner):
    bp = _deploy(direct_vm, direct_deploy, direct_owner)
    _mock(direct_vm, {"dscr": 10000})
    bp.ask(CTX, ["dscr"], 500)

    direct_vm.clear_mocks()
    _mock(direct_vm, {"dscr": 10501})  # one raw unit past the boundary
    agree = direct_vm.run_validator(leader_result=json.dumps({"dscr": 10000}))
    assert agree is False


def test_validator_disagrees_well_outside_tolerance(direct_vm, direct_deploy, direct_owner):
    bp = _deploy(direct_vm, direct_deploy, direct_owner)
    _mock(direct_vm, {"dscr": 10000})
    bp.ask(CTX, ["dscr"], 500)

    direct_vm.clear_mocks()
    _mock(direct_vm, {"dscr": 12000})  # 20% off
    agree = direct_vm.run_validator(leader_result=json.dumps({"dscr": 10000}))
    assert agree is False


def test_validator_zero_tolerance_requires_exact_match(direct_vm, direct_deploy, direct_owner):
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


def test_validator_leader_zero_uses_absolute_band(direct_vm, direct_deploy, direct_owner):
    # Relative tolerance is undefined at leader_value == 0 (division by
    # zero) - the contract falls back to an absolute band of
    # tolerance_bps raw units instead.
    bp = _deploy(direct_vm, direct_deploy, direct_owner)
    _mock(direct_vm, {"dscr": 0})
    bp.ask(CTX, ["dscr"], 100)

    direct_vm.clear_mocks()
    _mock(direct_vm, {"dscr": 100})
    assert direct_vm.run_validator(leader_result=json.dumps({"dscr": 0})) is True

    direct_vm.clear_mocks()
    _mock(direct_vm, {"dscr": 101})
    assert direct_vm.run_validator(leader_result=json.dumps({"dscr": 0})) is False


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


# --- The specific case a steward review flagged: significant-figure -------
# rounding let a 50% difference "agree" at MAX_TOLERANCE_BPS (20%). These
# reproduce that exact scenario against the corrected comparison.


def test_max_tolerance_rejects_the_reported_fifty_percent_case(direct_vm, direct_deploy, direct_owner):
    bp = _deploy(direct_vm, direct_deploy, direct_owner)
    _mock(direct_vm, {"dscr": 10000})
    bp.ask(CTX, ["dscr"], 2000)  # 20% = MAX_TOLERANCE_BPS

    direct_vm.clear_mocks()
    _mock(direct_vm, {"dscr": 14999})  # ~50% off - the old bucketing bug let this "agree"
    agree = direct_vm.run_validator(leader_result=json.dumps({"dscr": 10000}))
    assert agree is False


def test_max_tolerance_agrees_at_exact_20_percent_boundary(direct_vm, direct_deploy, direct_owner):
    bp = _deploy(direct_vm, direct_deploy, direct_owner)
    _mock(direct_vm, {"dscr": 10000})
    bp.ask(CTX, ["dscr"], 2000)

    direct_vm.clear_mocks()
    _mock(direct_vm, {"dscr": 12000})  # exactly 20% off
    agree = direct_vm.run_validator(leader_result=json.dumps({"dscr": 10000}))
    assert agree is True


def test_max_tolerance_disagrees_one_unit_past_20_percent(direct_vm, direct_deploy, direct_owner):
    bp = _deploy(direct_vm, direct_deploy, direct_owner)
    _mock(direct_vm, {"dscr": 10000})
    bp.ask(CTX, ["dscr"], 2000)

    direct_vm.clear_mocks()
    _mock(direct_vm, {"dscr": 12001})
    agree = direct_vm.run_validator(leader_result=json.dumps({"dscr": 10000}))
    assert agree is False
