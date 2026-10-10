"""Render measured mystery results; never alter the source trial records."""
import argparse
from collections import Counter
import json
from pathlib import Path


def render(records, first, last):
    rows = [r for r in records if first <= r['trial'] and (last is None or r['trial'] <= last)]
    out = ["# Mystery diagnosis results", "",
           "Source: `runs/mystery_trials.jsonl`. Each row is a recorded sandbox trial; wrong guesses and diagnosis errors are retained.", "",
           f"Selected trial range: {first} through {last if last is not None else 'latest'}. N = {len(rows)}.", "",
           "| Trial | Hidden fault / target | Guess / target | Top-1 | Top-3 | Target-only | Detect (s) | Diagnose (s) | memory_hit |",
           "|---|---|---|---|---|---|---|---|---|"]
    def cell(value):
        return str(value).replace('|', '\\|').replace('\n', ' ') if value is not None else 'not measured'
    def pair(value):
        return f"{value.get('fault', 'unknown')} / {value.get('target', 'unknown')}" if value else 'no diagnosis'
    for row in rows:
        correct = row.get('correct') or {}
        values = [row['trial'], pair(row.get('answer')), pair(row.get('guess')),
                  *['yes' if correct.get(k) is True else 'no' for k in ('top1', 'top3', 'target')],
                  row.get('seconds_to_detect'), row.get('seconds_to_diagnose'), row.get('memory_hit')]
        out.append('| ' + ' | '.join(cell(v) for v in values) + ' |')
    n = len(rows)
    counts = {k: sum((r.get('correct') or {}).get(k) is True for r in rows) for k in ('top1', 'top3', 'target')}
    out += ['', f"Accuracy: top-1 {counts['top1']}/{n}; top-3 {counts['top3']}/{n}; target {counts['target']}/{n}.", '',
            "This is a small sample, not an accuracy guarantee. Top-1 and top-3 require both fault and target to match. Target-only ignores the fault type.", '',
            "Memory may learn from earlier correct reveals, so these sequential trials are not independent tests of an untrained model. Diagnosis can use rules, confirmed memory, or an LLM; these totals measure the complete system, not LLM accuracy alone.", '',
            "## Wrong answers and errors", '']
    confusions = Counter((pair(r.get('answer')), pair(r.get('guess'))) for r in rows if not (r.get('correct') or {}).get('top1'))
    out.extend(f"- {actual} → {guess}: {count} trial(s)." for (actual, guess), count in sorted(confusions.items()))
    if not confusions:
        out.append('No wrong answers recorded in this selection.' if n else 'No trials recorded yet; accuracy has not been measured.')
    for row in rows:
        if row.get('error'):
            out.append(f"- Trial {row['trial']} error: {cell(row['error'])}")
    out += ['', '## Validation limits', '',
            '- Answer leakage: pending inspection of the smoke run inputs and trace; the revealed answer column is evaluation truth, not agent input.',
            '- Offline check: pending a separately identified offline run. Current blind diagnosis bypasses the LLM when offline and uses rules or confirmed memory. An offline success alone does not prove LLM cached-answer replay.',
            '- Smoke, scheduled evaluation and offline runs must be identified separately by trial range; the JSONL does not record offline mode.', '']
    return '\n'.join(out)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--first-trial', type=int, default=1)
    parser.add_argument('--last-trial', type=int)
    parser.add_argument('--input', type=Path, default=Path('runs/mystery_trials.jsonl'))
    parser.add_argument('--output', type=Path, default=Path('docs/day2/MYSTERY_RESULTS.md'))
    args = parser.parse_args()
    records = []
    if args.input.exists():
        for line in args.input.read_text(encoding='utf-8').splitlines():
            if line.strip():
                records.append(json.loads(line))
    if args.first_trial < 1 or (args.last_trial is not None and args.last_trial < args.first_trial):
        parser.error('invalid trial range')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render(records, args.first_trial, args.last_trial), encoding='utf-8')
    print(f'Written: {args.output}')
