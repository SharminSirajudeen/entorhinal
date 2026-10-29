// The read path: check_premises and answer in life/query.py.
'use strict';
const pytest = require('../pytest.js');
const F = 'life/query.py', T = 'tests/test_query.py';
const G1 = 'test_golden1_flags_commute_and_answer_cites_the_date';
const CATCH = 'except (ValueError, KeyError, TypeError, AttributeError):';
const COST = 'return Answer(text, report, cost + llm.price(SUPER, usage))';
module.exports = [
  { from:'query: S8 ignores status (any fact may be flagged stale)', file:F, find:'stale_by_id = {f.id: f for f in store.stale()}',
    replace:'stale_by_id = {f.id: f for f in store.timeline()}', ...pytest(T, G1) },
  { from:'query: only OUTDATED is flagged', file:F, find:'if i.get("verdict") == "OUTDATED"',
    replace:'if i.get("verdict") != "SAFE"', ...pytest(T, 'test_unresolved_and_safe_are_not_flagged') },
  { from:'query: replacing fact comes from the Store', file:F, find:'"invalidated_by": stale_by_id[i["fact_id"]].invalidated_by,',
    replace:'"invalidated_by": i.get("invalidated_by"),', ...pytest(T, G1) },
  { from:'query: reason falls back to the Store', file:F, find:'i.get("reason") or stale_by_id[i["fact_id"]].reason',
    replace:'i.get("reason")', ...pytest(T, 'test_reason_defaults_to_the_stores_reason') },
  { from:'query: stale line names what replaced the fact', file:F, find:'    if fact.status == "active":\n        return head\n',
    replace:'    return head\n', ...pytest(T, G1) },
  { from:'query: stale line carries the replacing fact date', file:F, find:'when = f" ({newer.time})" if newer else ""',
    replace:'when = ""', ...pytest(T, G1) },
  { from:'query: memory text covers stale facts', file:F, find:'for f in store.timeline())', replace:'for f in store.active())',
    ...pytest(T, G1) },
  { from:'query: S8 runs with thinking on', file:F, find:'"content": task}], think=True,', replace:'"content": task}], think=False,',
    ...pytest(T, G1) },
  { from:'query: S9 runs with thinking off', file:F, find:'think=False, max_tokens=2000', replace:'think=True, max_tokens=2000',
    ...pytest(T, G1) },
  { from:'query: S9 keeps the 3-step note', file:F, find:'"content": ANSWER_NOTE}', replace:'"content": ""}',
    ...pytest(T, G1) },
  { from:'query: S9 is told the premise report', file:F, find:'[Premise check]\\n{report_text(report, store)}',
    replace:'[Premise check]\\n', ...pytest(T, 'test_golden3_answers_for_abu_dhabi') },
  { from:'query: report states when nothing is outdated', file:F, find:'if not report.stale:', replace:'if False:',
    ...pytest(T, 'test_golden2_flags_nothing') },
  { from:'query: cost includes the premise check', file:F, find:COST,
    replace:'return Answer(text, report, llm.price(SUPER, usage))', ...pytest(T, G1) },
  { from:'query: cost includes the answer call', file:F, find:COST,
    replace:'return Answer(text, report, cost)', ...pytest(T, G1) },
  { from:'query: unparseable JSON gives an empty report', file:F, find:CATCH,
    replace:'except (KeyError, TypeError, AttributeError):',
    ...pytest(T, 'test_real_malformed_reply_gives_empty_report_and_answer_still_runs') },
  { from:'query: missing key gives an empty report', file:F, find:CATCH,
    replace:'except (ValueError, TypeError, AttributeError):', ...pytest(T, 'test_unusable_reply_gives_empty_report') },
  { from:'query: wrong-typed JSON gives an empty report', file:F, find:CATCH,
    replace:'except (ValueError, KeyError, AttributeError):', ...pytest(T, 'test_unusable_reply_gives_empty_report') },
  { from:'query: non-object item gives an empty report', file:F, find:CATCH,
    replace:'except (ValueError, KeyError, TypeError):', ...pytest(T, 'test_unusable_reply_gives_empty_report') },
  { from:'query: a cut-off premise check is billed', file:'life/query.py', find:'        return PremiseReport([], []), sum(costs)',
    replace:'        return PremiseReport([], []), 0.0', ...pytest(T, 'test_truncated_reply_gives_empty_report_and_answer_runs') },
];
