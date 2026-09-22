# v0.1.0
# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }

# Ballpark - a reusable numeric consensus oracle for GenLayer.
# Header must end in a blank line (real GenVM v0.2.11 requirement).

from genlayer import *
import datetime
import json

MAX_CONTEXT_LEN = 6000
MAX_METRICS = 10
MAX_TOLERANCE_BPS = u32(2000)  # 20% - a wider band stops meaning "agreement"


def _now() -> datetime.datetime:
    return datetime.datetime.fromisoformat(gl.message_raw['datetime'])


def _extract_values(context: str, metric_names: list[str]) -> str:
    # The only non-deterministic step. Every validator (leader included)
    # runs this independently; agreement is decided in ask() below by
    # _values_agree, a precise relative-tolerance check on these raw
    # numbers - not by exact string/JSON equality.
    names_list = ", ".join(metric_names)
    prompt = f"""You are extracting specific numeric figures from a piece of text, for a
system that checks whether independently-run extractions agree with each
other within a stated tolerance. Read the text below and extract ONLY
these values, if they are stated or directly computable from what is
stated:
{names_list}

--- BEGIN TEXT ---
{context}
--- END TEXT ---

Respond with ONLY a single JSON object, nothing else, no markdown fences:
a key for each requested value name, mapped to a non-negative INTEGER
equal to its real value multiplied by 10000 and rounded to the nearest
whole number (for example a ratio of 1.25 becomes 12500, and a count of
4,200 becomes 42000000). Every value must be a plain integer with no
decimal point, and non-negative, or null if that value is not stated and
cannot be computed from what is stated. Do not guess or estimate a
figure that isn't actually supported by the text."""

    result = gl.nondet.exec_prompt(prompt, response_format="json")
    out = {}
    for name in metric_names:
        v = result.get(name) if isinstance(result, dict) else None
        valid = isinstance(v, int) and not isinstance(v, bool) and v >= 0
        out[name] = v if valid else None
    return json.dumps(out, sort_keys=True)


# Earlier revision of this contract rounded values to a number of
# significant figures derived from tolerance_bps, then compared the
# rounded figures for exact equality. A steward review correctly caught
# that this doesn't actually enforce the tolerance the caller selected:
# rounding to N significant figures allows a relative error that swings
# wildly depending on where a value sits within its own digit range - at
# MAX_TOLERANCE_BPS (mapped to 1 significant figure), a leader value of
# 10000 and a validator value of 14999 (a 50% difference) both round to
# the same bucket and "agree", despite the caller having selected 20%.
# That's a real inconsistency, not a rare edge case - it's the norm near
# the bottom of any digit range. Comparing raw values against a precise,
# uniform relative-tolerance formula is the only way tolerance_bps means
# what it says at every value and at every requested tolerance.
def _within_tolerance(leader_value: int, mine_value: int, tolerance_bps: int) -> bool:
    diff = abs(leader_value - mine_value)
    if leader_value == 0:
        # Relative tolerance is undefined at zero (any nonzero mine_value
        # is an infinite relative error). Fall back to a small absolute
        # band of tolerance_bps raw bps-scaled units - with
        # MAX_TOLERANCE_BPS capped at 2000, that's at most +/-0.2 in real
        # units, not the degenerate case a much higher cap once allowed.
        return diff <= tolerance_bps
    # diff / leader_value <= tolerance_bps / 10000, cross-multiplied to
    # stay in integer arithmetic (GenVM calldata can't carry floats across
    # a nondet boundary, and exact reproducible arithmetic is the point of
    # an audit-able oracle regardless of where it runs). This is exact -
    # no digit-count-dependent approximation, so tolerance_bps means the
    # same relative bound for every value, at every requested tolerance.
    return diff * 10000 <= tolerance_bps * leader_value


def _values_agree(leader_json: str, mine_json: str, tolerance_bps: int) -> bool:
    try:
        leader = json.loads(leader_json)
        mine = json.loads(mine_json)
    except (ValueError, TypeError):
        return False
    if not isinstance(leader, dict) or not isinstance(mine, dict):
        return False
    if leader.keys() != mine.keys():
        return False
    for key, leader_value in leader.items():
        mine_value = mine[key]
        if leader_value is None or mine_value is None:
            if leader_value is not mine_value:
                return False
            continue
        if not _within_tolerance(leader_value, mine_value, tolerance_bps):
            return False
    return True


@allow_storage
class Query:
    requester: Address
    context: str
    metric_names_json: str
    tolerance_bps: u32
    result_json: str
    submitted_at: datetime.datetime


class Ballpark(gl.Contract):
    queries: DynArray[Query]

    def __init__(self) -> None:
        pass

    @gl.public.write
    def ask(self, context: str, metrics: list[str], tolerance_bps: u32) -> None:
        assert 1 <= len(context) <= MAX_CONTEXT_LEN, \
            f"context must be 1-{MAX_CONTEXT_LEN} chars"
        assert tolerance_bps <= MAX_TOLERANCE_BPS, \
            f"tolerance_bps must be <= {MAX_TOLERANCE_BPS} (20%)"

        names: list[str] = []
        for m in metrics:
            m = m.strip()
            if m and m not in names:
                names.append(m)
        assert 1 <= len(names) <= MAX_METRICS, \
            f"must request 1-{MAX_METRICS} distinct, non-empty metric names"

        # The stored result is the leader's raw extraction - but unlike
        # the earlier, rejected version, that's now safe: _within_tolerance
        # gives an exact, uniform bound (see its docstring), so "every
        # validator-compatible value is within tolerance_bps of the stored
        # figure" is a strict mathematical guarantee, not an approximation
        # that can drift depending on the value's magnitude. tolerance_bps
        # is stored alongside result_json (below) precisely so that
        # guarantee is always explicit and checkable by any reader or
        # consumer, rather than a hidden property of a rounded number.
        def leader_fn() -> str:
            return _extract_values(context, names)

        def validator_fn(leaders_res) -> bool:
            if not isinstance(leaders_res, gl.vm.Return):
                return False
            mine = _extract_values(context, names)
            return _values_agree(leaders_res.calldata, mine, tolerance_bps)

        result_json = gl.vm.run_nondet(leader_fn, validator_fn)

        record = self.queries.append_new_get()
        record.requester = gl.message.sender_address
        record.context = context
        record.metric_names_json = json.dumps(names)
        record.tolerance_bps = tolerance_bps
        record.result_json = result_json
        record.submitted_at = _now()

    @gl.public.view
    def get_query(self, query_id: u32) -> dict:
        q = self.queries[query_id]
        return {
            "requester": q.requester.as_hex,
            "context": q.context,
            "metric_names_json": q.metric_names_json,
            "tolerance_bps": q.tolerance_bps,
            "result_json": q.result_json,
            "submitted_at": q.submitted_at.isoformat(),
        }

    @gl.public.view
    def get_queries(self, offset: u32, limit: u32) -> list:
        total = len(self.queries)
        out = []
        i = total - 1 - offset
        count = 0
        while i >= 0 and count < limit:
            q = self.queries[i]
            out.append({
                "requester": q.requester.as_hex,
                "context": q.context,
                "metric_names_json": q.metric_names_json,
                "tolerance_bps": q.tolerance_bps,
                "result_json": q.result_json,
                "submitted_at": q.submitted_at.isoformat(),
            })
            i -= 1
            count += 1
        return out

    @gl.public.view
    def get_state(self) -> dict:
        return {"query_count": len(self.queries)}
