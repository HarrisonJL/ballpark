# v0.1.0
# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }

# CovenantCheck - proves Ballpark is a real, reusable primitive by
# consuming it from a second contract, rather than only asserting
# reusability in documentation.
# Header must end in a blank line (real GenVM v0.2.11 requirement).

from genlayer import *
import datetime
import json

COMPARISONS = ("gte", "lte")


def _now() -> datetime.datetime:
    return datetime.datetime.fromisoformat(gl.message_raw['datetime'])


# Cross-contract calls are forbidden inside a nondet/eq_principle block
# (GenVM raises SystemError: 6) - not relevant to Ballpark's own ask(),
# which never calls another contract, but relevant here: this method must
# stay fully deterministic, since it's reading Ballpark's already-agreed
# state rather than running any extraction of its own. GenVM v0.2.11 also
# has no synchronous way to call another contract's WRITE method and use
# its return value in the same transaction - gl.get_contract_at(...).emit()
# is a fire-and-forget PostMessage, not a call-and-wait (confirmed
# directly against genlayer/gl/genvm_contracts.py). A view call is the
# only synchronous cross-contract path that exists, which is exactly the
# right fit here: Ballpark's validator committee already reached
# consensus on the value once, so reading that settled record
# deterministically is correct - re-running its extraction from inside a
# second contract would just duplicate work and reintroduce the byte-exact
# fragility Ballpark exists to avoid.
def _evaluate(covenants, values: dict) -> tuple[bool, dict]:
    details = {}
    all_passed = True
    for c in covenants:
        value = values.get(c.metric)
        if value is None:
            details[c.name] = "missing"
            all_passed = False
            continue
        value_bps = u256(value)
        passed = value_bps >= c.threshold_bps if c.comparison == "gte" else value_bps <= c.threshold_bps
        details[c.name] = "pass" if passed else "fail"
        if not passed:
            all_passed = False
    return all_passed, details


@allow_storage
class Covenant:
    name: str
    metric: str
    comparison: str  # "gte" or "lte"
    threshold_bps: u256


@allow_storage
class CheckResult:
    ballpark_query_id: u32
    requester: Address
    all_passed: bool
    details_json: str
    checked_at: datetime.datetime


class CovenantCheck(gl.Contract):
    owner: Address
    ballpark_address: Address
    covenants: DynArray[Covenant]
    results: DynArray[CheckResult]

    def __init__(self, ballpark_address: str) -> None:
        self.owner = gl.message.sender_address
        self.ballpark_address = Address(ballpark_address)

    @gl.public.write
    def add_covenant(self, name: str, metric: str, comparison: str, threshold_bps: u256) -> None:
        assert gl.message.sender_address == self.owner, "only the owner can add covenants"
        assert comparison in COMPARISONS, f"comparison must be one of {COMPARISONS}"
        c = self.covenants.append_new_get()
        c.name = name
        c.metric = metric
        c.comparison = comparison
        c.threshold_bps = threshold_bps

    @gl.public.write
    def check_against_ballpark_query(self, ballpark_query_id: u32) -> None:
        assert len(self.covenants) > 0, "no covenants defined yet"

        query = gl.get_contract_at(self.ballpark_address).view().get_query(ballpark_query_id)
        assert query["requester"].lower() == gl.message.sender_address.as_hex.lower(), \
            "this Ballpark query was not submitted by you"

        values = json.loads(query["result_json"])
        all_passed, details = _evaluate(self.covenants, values)

        record = self.results.append_new_get()
        record.ballpark_query_id = ballpark_query_id
        record.requester = gl.message.sender_address
        record.all_passed = all_passed
        record.details_json = json.dumps(details, sort_keys=True)
        record.checked_at = _now()

    @gl.public.view
    def get_covenants(self) -> list:
        return [
            {"name": c.name, "metric": c.metric, "comparison": c.comparison, "threshold_bps": c.threshold_bps}
            for c in self.covenants
        ]

    @gl.public.view
    def get_result(self, result_id: u32) -> dict:
        r = self.results[result_id]
        return {
            "ballpark_query_id": r.ballpark_query_id,
            "requester": r.requester.as_hex,
            "all_passed": r.all_passed,
            "details_json": r.details_json,
            "checked_at": r.checked_at.isoformat(),
        }

    @gl.public.view
    def get_state(self) -> dict:
        return {
            "ballpark_address": self.ballpark_address.as_hex,
            "covenant_count": len(self.covenants),
            "result_count": len(self.results),
        }
