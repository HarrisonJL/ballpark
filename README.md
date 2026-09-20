# Ballpark

A reusable numeric consensus oracle for [GenLayer](https://genlayer.com): submit a piece of text and a list of numbers to extract from it, and get back a value only once independent validators' own extractions agree *within a stated tolerance* - not byte-for-byte, which is the wrong bar for anything an LLM has to compute or round.

**Live on GenLayer's Bradbury testnet. Testnet only.**

## The problem this solves

Every other Intelligent Contract in this build (Wizard's Coin, Covenant Sentinel) reaches consensus on an LLM's output via `gl.eq_principle.strict_eq`: each validator re-runs the same prompt and the result is accepted only if it's byte-identical to the leader's. That's the right bar for a single parsed boolean (`{"release": true}` either matches or it doesn't), and it's what GenLayer's own official example (Wizard of Coin) uses.

It's the *wrong* bar the moment the question has a genuinely numeric answer. Ask five independent LLM calls to extract "the debt service coverage ratio" from the same paragraph and you may well get 1.50, 1.5, 1.499, and 1.50x back as four technically-different strings - not because any of them are wrong, but because "compute a ratio from prose" isn't perfectly reproducible token-for-token. `strict_eq` would fail consensus on all of it. Covenant Sentinel (in this same account) hits exactly this risk today in its own disclosure-extraction step, and just accepts the fragility.

Ballpark is the fix, built as its own standalone, reusable primitive rather than another one-off contract: a numeric oracle whose equivalence check is a **canonical, bounded bucket**, not exact equality on raw output.

## How it works

`ask(context: str, metrics: list[str], tolerance_bps: u32)` - anyone can call it, no access control, no owner:

- `context`: the source text (up to 6000 chars).
- `metrics`: 1-10 distinct names of numeric values to extract (e.g. `["revenue_millions", "headcount"]`).
- `tolerance_bps`: how loose the agreement band is, capped at `MAX_TOLERANCE_BPS = 2000` (20%). `0` requires an exact match, so this subsumes `strict_eq` as a special case rather than replacing it with something incompatible.

Every value is extracted as a non-negative integer scaled by 10000 (matching Covenant Sentinel's existing bps convention, and required anyway - GenVM's calldata encoding can't carry a Python float across a nondet boundary).

### The consensus mechanism

This is built directly on `gl.vm.run_nondet` (the lower-level, fully-custom leader/validator primitive GenLayer's SDK exposes), not on any of the three built-in `eq_principle` wrappers - none of them fit:

- `strict_eq` - exact match only, the problem described above.
- `prompt_comparative` - spends an *extra* LLM call asking a model whether two answers are "equivalent" by some natural-language principle. Slower, non-deterministic in a different way, and overkill when the actual comparison is a plain arithmetic inequality.
- `prompt_non_comparative` - for subjective grading tasks (e.g. "is this a good summary"), not numeric agreement.

**Design note - this went through one real rejection before landing here.** The first version compared each validator's *raw* extraction against the leader's raw value within a relative-tolerance band, but still stored the leader's raw pick as the output regardless. A steward review correctly flagged that this doesn't actually constrain anything: at a wide tolerance, materially different extractions (e.g. `0` and `1` after scaling) could both "validate" against the same leader value, while the number that actually got written on-chain was still just whatever the leader happened to say, unmediated by the tolerance that supposedly verified it. The fix wasn't a tighter number - it was storing a different *kind* of value:

```python
def leader_fn() -> str:
    return _extract_and_bucket(context, names, tolerance_bps)   # raw extraction, then rounded onto a shared grid

def validator_fn(leaders_res) -> bool:
    if not isinstance(leaders_res, gl.vm.Return):
        return False
    mine = _extract_and_bucket(context, names, tolerance_bps)   # this validator's own independent extraction, rounded the same way
    return mine == leaders_res.calldata                          # exact equality on the canonical bucket, not the raw number

result_json = gl.vm.run_nondet(leader_fn, validator_fn)
```

`_extract_and_bucket` extracts, then rounds each value to a number of significant figures determined by `tolerance_bps` (looser tolerance -> fewer significant figures survive - see `_sig_figs_for_tolerance`). Agreement is then **exact equality on that rounded, canonical value** - not "is my raw number within X% of yours." The value that gets stored is that same canonical bucket, so what's on-chain always carries exactly the precision consensus actually verified, never more.

This closes the original defect directly: a naive "bucket size proportional to the value itself" self-cancels (`round(v / (v·t)) · (v·t) ≈ v` regardless of `t`, since the ratio is a constant - this was tried and discarded during the fix). Rounding to significant figures instead is a genuine, magnitude-based step function, so even at `MAX_TOLERANCE_BPS` a validator's `1` and a leader's `0` land in different buckets (`0` and `1` respectively) and correctly disagree - the exact case the rejection named.

**All-or-nothing across the metric vector, still by design:** a single mismatched bucket fails the whole query, since a mismatch suggests the model genuinely misread the source text rather than just rounding differently.

**Bucket-boundary straddling is a known, accepted tradeoff, not a bug.** Two raw values one unit apart (e.g. 15499 and 15500) can land in different buckets if they straddle a rounding boundary - the same thing that happens rounding a clock to the nearest minute. `tests/test_ballpark.py::test_validator_disagrees_across_a_bucket_boundary` documents this deliberately rather than trying to eliminate it, which would need materially more complex (and harder-to-audit) logic for a rare edge case.

**Consensus failure is a real possible outcome, not a bug to hide.** If validators' independently-bucketed extractions don't match, the transaction doesn't reach `ACCEPTED` - it resolves as `UNDETERMINED` at the protocol level, same as any other GenLayer consensus failure. A contract's Python code cannot catch or paper over this mid-execution (this is enforced by the outer consensus protocol, not contract logic) - callers, and any UI built on top, need to handle it explicitly rather than assume every submitted transaction succeeds. This is the exact bug class already found and fixed this build in Covenant Sentinel's dashboard: code that treats "the transaction resolved without throwing" as "the write succeeded," when `UNDETERMINED`/`CANCELED`/timeout states resolve the same poll without being a success.

## Verified platform facts

Bradbury runs GenVM **v0.2.11** - confirmed against the real SDK build extracted for this exact deployment's pinned `py-genlayer` dependency hash, not the newer v0.3 release-candidate tooling most local tools default to (a real, previously-hit trap in this account's other projects: a v0.3-shaped deploy header silently fails to parse on v0.2.11). One concrete, non-obvious difference that mattered for this contract: **the low-level primitive names are swapped between SDK versions.** In v0.2.11 (what's actually live here), the sandboxed/recommended custom-consensus primitive is `gl.vm.run_nondet` and the raw/unsandboxed one is `gl.vm.run_nondet_unsafe`; in the v0.3 release candidate, the *same two functions* are named `run_nondet_default` and `run_nondet` respectively - i.e. `run_nondet` means the opposite thing in each version. Verified by reading `genlayer/gl/eq_principle.py` and `genlayer/gl/vm.py` directly from the version-matched extracted SDK (`gltest-direct`'s v0.2.11 cache), not from documentation or memory, specifically because this contract needed a function neither `strict_eq` nor `prompt_comparative` are examples of.

## Testing

`tests/test_ballpark.py` (31 tests, `genlayer-test` Direct Mode) is split into two genuinely different layers:

1. **Integration tests** - real `ask()` calls with a mocked LLM: state bookkeeping, input validation, metric-name deduplication, null-handling for ungrounded extractions, and - directly targeting the rejected version's defect - a parametrized sweep proving the *stored* `result_json` is the bucketed value at every significant-figure threshold, never the model's raw extraction.
2. **Consensus-boundary tests** - via gltest's `direct_vm.run_validator(leader_result=...)` cheatcode. Direct Mode runs `leader_fn` directly and only *captures* `validator_fn` for later inspection (it doesn't simulate a real multi-validator vote in-process), so mocking the LLM alone can't exercise disagreement - both "sides" would hit the same canned response and trivially agree. `run_validator` re-invokes the real, captured `validator_fn` closure with an explicit hypothetical leader result, which is the documented, intended way to test this - not a workaround. This is what exercises the bucket-agreement logic itself: same-bucket agreement despite non-identical raw values, boundary-straddling disagreement, null-vs-value mismatches, partial-vector disagreement, and - explicitly - `test_max_tolerance_no_longer_lets_zero_and_one_agree`, which reproduces the exact scenario the steward rejection named and confirms it's closed.

```bash
python3.14 -m venv .venv && source .venv/bin/activate
pip install "genlayer-test[sim]==0.29.2" genvm-linter==0.11.0
genvm-lint check contracts/ballpark.py
pytest tests/ -v
```

## Composability

Any other Intelligent Contract can call in via `gl.get_contract_at(BALLPARK_ADDRESS).ask(context, metrics, tolerance_bps)` and read the result back with `get_query`/`get_queries` - no special integration, just a cross-contract call. Covenant Sentinel's own `_extract_metrics` (in the sibling `covenant-sentinel` repo) is a direct precedent for what this generalizes: it does its own inline extraction via `strict_eq`, accepting the byte-exact-match fragility described above. Ballpark is the reusable version of that same underlying need, decoupled from any one contract's domain logic.

## Deployment

See [`CONTRACT.md`](CONTRACT.md) for the live address, deploy tx, and deployer.

```bash
npm install
# DEPLOYER_PRIVATE_KEY in .env (gitignored, never commit a private key)
npm run deploy
npx tsx scripts/ask_demo.ts <contract_address>
```

## Known limitations

- **Testnet only.**
- **All-or-nothing agreement across the requested metric vector.** A query asking for 10 metrics fails entirely if even one falls outside tolerance on a given validator, by design (see "How it works") - callers who want partial credit should split into separate `ask()` calls per metric group.
- **Bucket-boundary straddling** (see "How it works") - two very close raw values can occasionally land in different buckets and disagree. Accepted as an inherent property of any quantized-agreement scheme, not solved.
- **No spam/cost control beyond the context-length and metric-count caps.** A production deployment serving untrusted callers would likely want a small fee, mirroring Wizard's Coin's fee mechanism - deliberately left out here to keep the primitive itself minimal and legible.
- **Tolerance is per-query, chosen by the caller, capped at 20% but not otherwise verified against the metric's real-world scale.** A caller requesting the maximum tolerance on a metric that genuinely needs finer precision will get a coarser (but still bounded and honestly-labeled) bucket - Ballpark enforces the *mechanism* correctly, not whether a given tolerance is a sensible choice for a given use case.
