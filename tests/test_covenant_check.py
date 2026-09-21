"""
Deterministic tests for CovenantCheck using genlayer-test's Direct Mode.

Direct Mode has no routing for cross-contract calls (CallContract has no
hook unless GLSim is wired up - confirmed by reading gltest's
wasi_mock.py directly) - so check_against_ballpark_query's actual
cross-contract read can't be exercised here. What's covered instead is
everything Direct Mode genuinely can verify: access control, covenant
bookkeeping, and the precondition that must fail *before* the
cross-contract call is ever reached. The cross-contract mechanic itself
is verified live against the real deployed Ballpark contract on Bradbury
(see scripts/check_ballpark_query.ts / the project README).
"""

import pytest

BALLPARK_ADDRESS = "0x2d061E63d10EcC6aeeB9f82d232fAEA9F932e6DA"


def _deploy(direct_vm, direct_deploy, owner):
    direct_vm.sender = owner
    return direct_deploy("contracts/covenant_check.py", ballpark_address=BALLPARK_ADDRESS)


def test_initial_state(direct_vm, direct_deploy, direct_owner):
    cc = _deploy(direct_vm, direct_deploy, direct_owner)
    state = cc.get_state()
    assert state["covenant_count"] == 0
    assert state["result_count"] == 0
    assert state["ballpark_address"].lower() == BALLPARK_ADDRESS.lower()


def test_owner_can_add_covenant(direct_vm, direct_deploy, direct_owner):
    cc = _deploy(direct_vm, direct_deploy, direct_owner)
    cc.add_covenant("min_dscr", "dscr", "gte", 12500)

    covenants = cc.get_covenants()
    assert len(covenants) == 1
    assert covenants[0]["name"] == "min_dscr"
    assert covenants[0]["metric"] == "dscr"
    assert covenants[0]["comparison"] == "gte"
    assert covenants[0]["threshold_bps"] == 12500


def test_only_owner_can_add_covenant(direct_vm, direct_deploy, direct_owner, direct_alice):
    cc = _deploy(direct_vm, direct_deploy, direct_owner)
    direct_vm.sender = direct_alice
    with pytest.raises(Exception):
        cc.add_covenant("min_dscr", "dscr", "gte", 12500)


def test_add_covenant_rejects_invalid_comparison(direct_vm, direct_deploy, direct_owner):
    cc = _deploy(direct_vm, direct_deploy, direct_owner)
    with pytest.raises(Exception):
        cc.add_covenant("min_dscr", "dscr", "equals", 12500)


def test_check_rejects_when_no_covenants_defined(direct_vm, direct_deploy, direct_owner):
    # This assert must fire before the cross-contract call to Ballpark is
    # ever reached, so it's safe to exercise via Direct Mode.
    cc = _deploy(direct_vm, direct_deploy, direct_owner)
    with pytest.raises(Exception):
        cc.check_against_ballpark_query(0)


def test_multiple_covenants_accumulate(direct_vm, direct_deploy, direct_owner):
    cc = _deploy(direct_vm, direct_deploy, direct_owner)
    cc.add_covenant("min_dscr", "dscr", "gte", 12500)
    cc.add_covenant("max_leverage", "leverage", "lte", 40000)

    covenants = cc.get_covenants()
    assert len(covenants) == 2
    assert [c["name"] for c in covenants] == ["min_dscr", "max_leverage"]
