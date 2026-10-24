# Model comparison: the same agent on three Claude models

Agent A was built and evaluated on Claude Sonnet 5.5. This study asks whether a cheaper model does the same job, and what goes wrong when it does not.

## Method

- **Everything except the model was held fixed:** the 15 known-answer cases, five repeats each, the system prompt, the tools, the data and the rule-based grading, all at commit [2107708](https://github.com/aleexorlov/finance-ops-agents/commit/2107708).
- **One change from run 4 applies to every model:** answers may now use up to 2,048 output tokens, up from 1,024. On a trial question, Haiku 5.5 wrote a correct answer that ran past the old limit and was cut off. In the full runs below, no answer went over 1,024 tokens; Haiku 5.5's longest final answer was 964.
- **The runs were made on 24 October 2026**, one model after another.
- **Costs use list prices checked that day** (in [`harness.py`](../src/finance_ops/evals/harness.py)), with the system prompt and tools marked for prompt caching.

```bash
python -m finance_ops.evals --model claude-haiku-5-5
python -m finance_ops.evals.compare evals/results/<run>.json ...
```

## Results

| Model | Passed | Withheld by the figure check | Consistent cases | Turns | Tool calls | Median seconds | Cost of 75 runs | Cost per passing answer |
|---|---|---|---|---|---|---|---|---|
| Claude Sonnet 5.5 ([results](../evals/results/20261024T151101Z.md)) | 75/75 (100%) | 0 | 15/15 | 2.5 | 3.1 | 5.6 | $0.56 | $0.0075 |
| Claude Haiku 5.5 ([results](../evals/results/20261024T150648Z-claude-haiku-5-5.md)) | 74/75 (98.7%) | 0 | 14/15 | 2.7 | 3.0 | 4.8 | $0.04 | $0.0005 |
| Claude Haiku 4.5 ([results](../evals/results/20261024T150900Z-claude-haiku-4-5-20251001.md)) | 64/75 (85.3%) | 7 | 11/15 | 2.5 | 2.7 | 4.5 | $0.80 | $0.0125 |

Every model passed 5 of 5 on the other 11 cases. The four cases where they differed:

| Case | Sonnet 5.5 | Haiku 5.5 | Haiku 4.5 |
|---|---|---|---|
| `invoice-jump` | 5/5 | 5/5 | 1/5 |
| `invoice-matches` | 5/5 | 5/5 | 3/5 |
| `stale-feed` | 5/5 | 4/5 | 4/5 |
| `usage-gap` | 5/5 | 5/5 | 1/5 |

## What the failures were

Each failing answer was read by hand.

- **Haiku 4.5 missed a billing error (4 runs of `invoice-jump`).** Asked why an invoice went up, it explained the increase as a plan upgrade plus higher usage, and never called `reconcile_invoice`, although the system prompt says to reconcile the later invoice. Every figure it gave was real, so the figure check had nothing to stop. The answer was incomplete in the way that matters most: the invoice was £1,637.36 too high.
- **Haiku 4.5 did its own arithmetic (7 withheld answers).** It stated figures no tool returned: overage credits as allowance subtracted from usage (2,112,612), remaining allowance (4,831,911), the month-on-month difference (144,169 credits, 12%) and daily averages (about 39,000 a day). The figures checked by hand were correct. They were withheld because the design has the tools do the arithmetic, and the check cannot tell a correct sum from an invented number. The answers were safe, but the user would have got nothing.
- **Haiku 5.5 forecast unrecorded usage (1 run of `stale-feed`).** It said "the true total is higher" for a month whose feed stops early. This is the same unsupported forecast Sonnet 5.5 made once in run 4, and the same rule caught it.

## Findings

1. **Haiku 5.5 did the job of Sonnet 5.5 at about a fifteenth of the cost per passing answer** ($0.0005 against $0.0075), with one more failure in 75. Its answers were longer (a median final answer of 268 output tokens against 219), which is why the output cap was raised.
2. **Haiku 4.5 was the most expensive model per passing answer**, even though its list price is below Sonnet 5.5's. It never used the prompt cache: across 75 runs it recorded no cache reads or writes, so every turn paid the full input price for the system prompt and tools (710,173 uncached input tokens, against 90,297 for Sonnet 5.5 and 102,535 for Haiku 5.5). Its documented minimum cacheable prompt is 4,096 tokens, against 512 for the 5.5 models, and this prompt is about 4,160 tokens as Haiku 5.5 counts it. The most likely explanation is that it falls just under the minimum for Haiku 4.5, which counts tokens differently. That has not been confirmed with a token count.
3. **The figure check turned a weaker model's habits into withheld answers, not wrong ones.** Seven of Haiku 4.5's eleven failures were withheld before a user could see them. The four it could not stop had only real figures and a wrong conclusion. Only the grading rules and the instruction to reconcile cover that kind of failure.
4. **Cheaper is a choice to test, not to assume.** On this agent, the newest small model was the best value and the previous one the worst. A price list alone would have predicted neither.

## Claude Opus 5.5: run incomplete

The Opus 5.5 run ([results](../evals/results/20261024T151328Z-claude-opus-5-5.md)) stopped partway: 13 of its 75 runs failed with an API error because the account ran out of credit, so it is left out of the comparison. The comparison script now counts these API errors separately from model failures.

Of the 62 runs that completed, 60 passed. Reading the two failures found a problem in the evaluation in each case, not in the answer:

- **A grading rule failed a correct answer.** The `misbilled-invoice` rules reject "was billed correctly", which is meant to catch an answer that clears the invoice. Opus correctly found the overcharge, then added that "the platform fee of 999.00 GBP was billed correctly".
- **The figure check withheld a correct answer over a date.** It exempts dates written as dates, but "21, 22 and 23 September" left a bare "21" that no tool returned.

Neither has been changed yet. Fixing them after seeing a result means re-running every model, as runs 3 and 4 did.

## Limitations

- **One run of 75 per model.** A difference of one or two runs, such as Sonnet 5.5 against Haiku 5.5, is within what a repeat could change.
- **One agent, one dataset, 15 known cases, no held-out set.** This shows how the models handle the situations the cases plant, not open-ended accuracy.
- **Grading is rule-based.** The Opus failures above show it can fail a correct answer.
- **Latency is from one machine and one afternoon.** Treat the median seconds as indicative only.
