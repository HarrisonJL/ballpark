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
    # runs this independently; agreement is decided in ask() below on the
    # bucketed (see _bucket) result, not on this raw extraction directly.
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


# A naive "round to a size proportional to the value itself" bucket
# self-cancels: bucket_size = value * t makes value // bucket_size a fixed
# constant regardless of value's magnitude, so rounding just reconstructs
# the original value (this was the actual bug behind the rejection - the
# tolerance check compared raw values, but nothing ever coarsened what got
# stored, so the leader's exact raw pick always became the output).
# Genuine coarsening needs a magnitude-based step (how many significant
# figures survive), which is a discrete function of digit count, not a
# continuous fraction of the value.
def _digit_count(value: int) -> int:
    if value == 0:
        return 1
    count = 0
    while value > 0:
        value //= 10
        count += 1
    return count


def _sig_figs_for_tolerance(tolerance_bps: int) -> int:
    # Looser tolerance -> fewer significant figures kept in the canonical
    # bucket, since consensus only actually verified agreement at that
    # coarseness. tolerance_bps=0 is handled separately (exact, no
    # bucketing at all).
    if tolerance_bps <= 10:      # <= 0.1%
        return 5
    if tolerance_bps <= 100:     # <= 1%
        return 4
    if tolerance_bps <= 400:     # <= 4%
        return 3
    if tolerance_bps <= 1000:    # <= 10%
        return 2
    return 1                     # up to MAX_TOLERANCE_BPS (20%)


def _bucket(value: int, tolerance_bps: int) -> int:
    if tolerance_bps == 0 or value == 0:
        return value
    sig_figs = _sig_figs_for_tolerance(tolerance_bps)
    digits = _digit_count(value)
    if digits <= sig_figs:
        return value
    step = 10 ** (digits - sig_figs)
    return ((value + step // 2) // step) * step  # round half up onto the grid


def _extract_and_bucket(context: str, metric_names: list[str], tolerance_bps: int) -> str:
    raw = json.loads(_extract_values(context, metric_names))
    bucketed = {
        name: (_bucket(value, tolerance_bps) if value is not None else None)
        for name, value in raw.items()
    }
    return json.dumps(bucketed, sort_keys=True)


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

        # The stored result IS the canonical bucketed value, not either
        # party's raw extraction - a validator agrees only by landing on
        # the exact same bucket, so nothing ever gets recorded that a real
        # majority didn't reproduce at that precision. This also closes the
        # wide-tolerance case directly: even at MAX_TOLERANCE_BPS (1
        # significant figure), a validator whose raw value has a different
        # leading digit lands in a different bucket and disagrees - unlike
        # comparing raw values, where a 100%-wide band let almost anything
        # through while the leader's unmediated pick was still what got
        # stored.
        def leader_fn() -> str:
            return _extract_and_bucket(context, names, tolerance_bps)

        def validator_fn(leaders_res) -> bool:
            if not isinstance(leaders_res, gl.vm.Return):
                return False
            mine = _extract_and_bucket(context, names, tolerance_bps)
            return mine == leaders_res.calldata

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
