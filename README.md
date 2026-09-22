# Ballpark

A reusable numeric consensus oracle for [GenLayer](https://genlayer.com): submit a piece of text and a list of numbers to extract from it, and get back a value only once independent validators' own extractions agree *within a stated tolerance* - not byte-for-byte, which is the wrong bar for anything an LLM has to compute or round.

**Live on GenLayer's Bradbury testnet. Testnet only.**

## The problem this solves

Every other Intelligent Contract in this build (Wizard's Coin, Covenant Sentinel) reaches consensus on an LLM's output via `gl.eq_principle.strict_eq`: each validator re-runs the same prompt and the result is accepted only if it's byte-identical to the leader's. That's the right bar for a single parsed boolean (`{"release": true}` either matches or it doesn't), and it's what GenLayer's own official example (Wizard of Coin) uses.

It's the *wrong* bar the moment the question has a genuinely numeric answer. Ask five independent LLM calls to extract "the debt service coverage ratio" from the same paragraph and you may well get 1.50, 1.5, 1.499, and 1.50x back as four technically-different strings - not because any of them are wrong, but because "compute a ratio from prose" isn't perfectly reproducible token-for-token. `strict_eq` would fail consensus on all of it. Covenant Sentinel (in this same account) hits exactly this risk today in its own disclosure-extraction step, and just accepts the fragility.

Ballpark is the fix, built as its own standalone, reusable primitive rather than another one-off contract: a numeric oracle whose equivalence check is a **precise, uniform relative-tolerance band**, not exact equality on raw output.

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

```python
def leader_fn() -> str:
    return _extract_values(context, names)          # one real LLM call

def validator_fn(leaders_res) -> bool:
    if not isinstance(leaders_res, gl.vm.Return):
        return False
    mine = _extract_values(context, names)          # this validator's OWN independent LLM call
    return _values_agree(leaders_res.calldata, mine, tolerance_bps)

result_json = gl.vm.run_nondet(leader_fn, validator_fn)
```

`_values_agree` requires every requested metric to agree via `_within_tolerance` - a precise, uniform relative-tolerance check on the *raw* extracted values (`|leader - mine| / leader <= tolerance_bps`, cross-multiplied to stay in integer arithmetic). The stored `result_json` is the leader's raw extraction, unmodified - what makes that safe (rather than the "arbitrary point pick" problem below) is that `_within_tolerance` gives an exact, uniform bound: every validator-compatible value really is within `tolerance_bps` of it, for every value and every requested tolerance, no approximation. `tolerance_bps` is stored alongside `result_json` in every record precisely so that guarantee is always explicit and checkable, not an implicit property of a rounded number.

**Design note - this went through two real rejections before landing here, and the second one was caused by the fix for the first.**

*Rejection 1:* the original version compared raw extractions within a tolerance band exactly as described above, but at the time `MAX_TOLERANCE_BPS` was 10000 (100%) - wide enough that materially different extractions (e.g. `0` and `1` after scaling) could both "validate" against the same leader value. A steward review correctly flagged this. The fix applied then was two things bundled together: lowering the cap to 2000 (20%), *and* replacing the raw-value comparison with rounding both values to a number of significant figures (looser tolerance -> fewer figures) and requiring exact equality on the rounded figure instead.

*Rejection 2:* that second part was itself wrong, and a steward review caught it - the selected tolerance wasn't actually being enforced. Rounding to N significant figures does not correspond to a uniform percentage bound: the *effective* relative error it allows depends heavily on where a value falls within its own digit range. Concretely, at `MAX_TOLERANCE_BPS` (which mapped to 1 significant figure), a leader value of `10000` and a validator value of `14999` - a **50% difference** - both rounded to the same bucket and "agreed", despite the caller having selected 20%. That's not a rare edge case; it's the norm near the bottom of any digit range (the bound swings from roughly 5% near the top of a range to roughly 50% near the bottom, for 1 significant figure). `tests/test_ballpark.py::test_max_tolerance_rejects_the_reported_fifty_percent_case` reproduces this exact scenario against the *current* code and confirms it's now rejected.

The corrected design (above) keeps the 20% cap from the first fix, but reverts the comparison itself to the precise raw-value check - which is what actually makes `tolerance_bps` mean what it says, and is also the only version of this that supports *exact* boundary tests (agrees at precisely `tolerance_bps`, disagrees one unit past it - see "Testing"). A bucket size that's a function of tolerance and magnitude but not exactly proportional to the value itself was considered and rejected too: any power-of-10-style rounding scheme has this same non-uniformity baked in, and a scheme *exactly* proportional to the value being rounded self-cancels under rounding (`round(v / (v·t)) · (v·t) ≈ v` regardless of `t`, since the ratio is a constant) - there is no bucket-based fix here, only a correct comparison.

**All-or-nothing across the metric vector, still by design:** a single value outside tolerance fails the whole query, since a mismatch suggests the model genuinely misread the source text rather than just rounding differently.

**Consensus failure is a real possible outcome, not a bug to hide.** If validators' independent extractions don't land within tolerance of each other, the transaction doesn't reach `ACCEPTED` - it resolves as `UNDETERMINED` at the protocol level, same as any other GenLayer consensus failure. A contract's Python code cannot catch or paper over this mid-execution (this is enforced by the outer consensus protocol, not contract logic) - callers, and any UI built on top, need to handle it explicitly rather than assume every submitted transaction succeeds. This is the exact bug class already found and fixed this build in Covenant Sentinel's dashboard: code that treats "the transaction resolved without throwing" as "the write succeeded," when `UNDETERMINED`/`CANCELED`/timeout states resolve the same poll without being a success.

## Verified platform facts

Bradbury runs GenVM **v0.2.11** - confirmed against the real SDK build extracted for this exact deployment's pinned `py-genlayer` dependency hash, not the newer v0.3 release-candidate tooling most local tools default to (a real, previously-hit trap in this account's other projects: a v0.3-shaped deploy header silently fails to parse on v0.2.11). One concrete, non-obvious difference that mattered for this contract: **the low-level primitive names are swapped between SDK versions.** In v0.2.11 (what's actually live here), the sandboxed/recommended custom-consensus primitive is `gl.vm.run_nondet` and the raw/unsandboxed one is `gl.vm.run_nondet_unsafe`; in the v0.3 release candidate, the *same two functions* are named `run_nondet_default` and `run_nondet` respectively - i.e. `run_nondet` means the opposite thing in each version. Verified by reading `genlayer/gl/eq_principle.py` and `genlayer/gl/vm.py` directly from the version-matched extracted SDK (`gltest-direct`'s v0.2.11 cache), not from documentation or memory, specifically because this contract needed a function neither `strict_eq` nor `prompt_comparative` are examples of.

## Testing

`tests/test_ballpark.py` (24 tests, `genlayer-test` Direct Mode) is split into two genuinely different layers:

1. **Integration tests** - real `ask()` calls with a mocked LLM: state bookkeeping, input validation, metric-name deduplication, null-handling for ungrounded extractions, and - directly targeting the first rejection's defect - proof that the stored `result_json` is the model's raw extraction, unrounded (see the "Design note" above for why that's safe now).
2. **Consensus-boundary tests** - via gltest's `direct_vm.run_validator(leader_result=...)` cheatcode. Direct Mode runs `leader_fn` directly and only *captures* `validator_fn` for later inspection (it doesn't simulate a real multi-validator vote in-process), so mocking the LLM alone can't exercise disagreement - both "sides" would hit the same canned response and trivially agree. `run_validator` re-invokes the real, captured `validator_fn` closure with an explicit hypothetical leader result, which is the documented, intended way to test this - not a workaround. Because the comparison is now an exact formula rather than an approximation, these are *exact* boundary tests: agreement at precisely `tolerance_bps`, disagreement one raw unit past it, at both a normal tolerance and at `MAX_TOLERANCE_BPS` - plus `test_max_tolerance_rejects_the_reported_fifty_percent_case`, which reproduces the second rejection's exact scenario against the current code.

`tests/test_covenant_check.py` (6 tests) covers everything Direct Mode genuinely can verify for the composability contract - access control, covenant bookkeeping, comparison validation, and the precondition that must fail *before* ever reaching the cross-contract call. The cross-contract read itself is structurally untestable in Direct Mode (see "Composability") and is instead verified live on Bradbury - see `CONTRACT.md`.

```bash
python3.14 -m venv .venv && source .venv/bin/activate
pip install "genlayer-test[sim]==0.29.2" genvm-linter==0.11.0
genvm-lint check contracts/ballpark.py
genvm-lint check contracts/covenant_check.py
pytest tests/ -v
```

## Composability

`contracts/covenant_check.py` is a second, deployed contract that actually consumes Ballpark - not just a README claim. It's the disclosure-checking half of Covenant Sentinel's own logic (in the sibling `covenant-sentinel` repo), rebuilt to read an already-agreed Ballpark result instead of duplicating its own `strict_eq`-based extraction:

```python
query = gl.get_contract_at(self.ballpark_address).view().get_query(ballpark_query_id)
values = json.loads(query["result_json"])
# ... compare each covenant's metric against its threshold, deterministically
```

**Why a view call, not a write call to `ask()` directly.** GenVM v0.2.11 has no synchronous way to call another contract's write method and use its return value in the same transaction - confirmed by reading `genlayer/gl/genvm_contracts.py` directly: `gl.get_contract_at(...).emit(...)` sends a fire-and-forget `PostMessage` (`__call__(...) -> None`), not a call-and-wait. A synchronous `.view()` call is the only cross-contract path that returns a real value inline, which is also the *correct* fit here: Ballpark's committee already reached consensus on the number once, so a second contract reading that settled record deterministically is right - re-running the extraction from inside `CovenantCheck` would just duplicate work and reintroduce the exact byte-exact-match fragility Ballpark exists to avoid. This also means cross-contract calls are only usable outside a `run_nondet`/`eq_principle` block (GenVM raises `SystemError: 6` if attempted inside one - also confirmed directly, not assumed) - not a constraint that affects this design, since `check_against_ballpark_query` never touches an LLM itself.

See [`CONTRACT.md`](CONTRACT.md) for the live `CovenantCheck` address and a real transaction reading a real Ballpark query cross-contract - not simulated, and (see "Testing") not something Direct Mode can even exercise, since it has no local routing for cross-contract calls without GLSim.

## Deployment

See [`CONTRACT.md`](CONTRACT.md) for the live address, deploy tx, and deployer.

```bash
npm install
# DEPLOYER_PRIVATE_KEY in .env (gitignored, never commit a private key)
npm run deploy
npx tsx scripts/ask_demo.ts <contract_address>

# CovenantCheck (composability demo) - defaults to the live Ballpark address
npx tsx scripts/deploy_covenant_check.ts
npx tsx scripts/covenant_check_demo.ts <covenant_check_address> <ballpark_query_id>
```

## Known limitations

- **Testnet only.**
- **All-or-nothing agreement across the requested metric vector.** A query asking for 10 metrics fails entirely if even one falls outside tolerance on a given validator, by design (see "How it works") - callers who want partial credit should split into separate `ask()` calls per metric group.
- **No spam/cost control beyond the context-length and metric-count caps.** A production deployment serving untrusted callers would likely want a small fee, mirroring Wizard's Coin's fee mechanism - deliberately left out here to keep the primitive itself minimal and legible.
- **The stored value carries no rounding of its own** - a consumer that wants to avoid displaying (say) 5 significant figures of a number only verified to 20% precision needs to do that rounding itself, using the stored `tolerance_bps`. Ballpark guarantees the *bound* (`result` is within `tolerance_bps` of every agreeing validator's own extraction), not a particular display precision - see the "Design note" above for why baking rounding into the contract itself doesn't actually work.
