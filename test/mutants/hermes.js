// The Hermes memory provider, hermes_provider/__init__.py.
'use strict';
const pytest = require('../pytest.js');
const F = 'hermes_provider/__init__.py', T = 'tests/test_hermes_provider.py';
const GOLDEN = 'test_golden1_hooks_leave_commute_stale_and_prefetch_names_it';
const FAILING = 'test_a_failing_model_call_degrades_to_empty_text_and_later_turns_still_ingest';
const NOWRITE = 'test_blank_turns_and_non_primary_contexts_write_nothing';
const REUSE = 'test_prefetch_gives_up_at_the_wait_and_the_same_question_reuses_the_job';
const SYNC = 'if not self._writes or not user_content.strip():';
const SURFACE = 'test_static_surface_and_registration';
module.exports = [
  { from:'hermes: unavailable without the key', file:F, find:'return bool(os.environ.get("NEBIUS_API_KEY"))', replace:'return True',
    ...pytest(T, 'test_availability_follows_the_key') },
  { from:'hermes: store under the profile hermes_home', file:F, find:'Path(kwargs["hermes_home"]) / NAME',
    replace:'Path(".hermes-default") / NAME', ...pytest(T, 'test_store_lives_under_the_profile_home_and_profiles_do_not_share') },
  { from:'hermes: non-primary contexts do not write', file:F, find:'self._writes = kwargs.get("agent_context", "primary") == "primary"',
    replace:'self._writes = True', ...pytest(T, NOWRITE) },
  { from:'hermes: sync_turn honours the write switch', file:F, find:SYNC, replace:'if not user_content.strip():', ...pytest(T, NOWRITE) },
  { from:'hermes: blank turns are skipped', file:F, find:SYNC, replace:'if not self._writes:', ...pytest(T, NOWRITE) },
  { from:'hermes: only the user side is ingested', file:F, find:'[{"role": "user", "content": user_content}]',
    replace:'[{"role": "user", "content": user_content}, {"role": "assistant", "content": assistant_content}]',
    ...pytest(T, 'test_only_the_users_words_are_ingested') },
  { from:'hermes: session index continues from the store', file:F, find:'self._next_idx = 1 + max((', replace:'self._next_idx = 0 * max((',
    ...pytest(T, 'test_second_session_continues_ids_from_the_store') },
  { from:'hermes: session index advances each turn', file:F, find:'        self._next_idx += 1\n', replace:'', ...pytest(T, GOLDEN) },
  { from:'hermes: a turn waits for the previous ingest', file:F, find:'        _after(prev)\n        try:', replace:'        try:',
    ...pytest(T, 'test_turns_ingest_in_order_even_when_the_first_is_slow') },
  { from:'hermes: ingest uses the injected chat', file:F, find:'memory.ingest(self._store, session, self._chat)',
    replace:'memory.ingest(self._store, session)', ...pytest(T, GOLDEN) },
  { from:'hermes: a failed ingest is swallowed', file:F, find:'        except Exception:  # a failed model call',
    replace:'        except KeyboardInterrupt:  # a failed model call', ...pytest(T, FAILING) },
  { from:'hermes: the check waits for the ingest', file:F, find:'        _after(ingest)  # the premise check', replace:'        pass  # the premise check',
    ...pytest(T, 'test_check_waits_for_the_ingest_before_it_reads_the_store') },
  { from:'hermes: the check uses the injected chat', file:F, find:'query.check_premises(self._store, question, self._chat)',
    replace:'query.check_premises(self._store, question)', ...pytest(T, GOLDEN) },
  { from:'hermes: a failed check is swallowed', file:F, find:'        except Exception:\n            log.warning("entorhinal premise',
    replace:'        except KeyboardInterrupt:\n            log.warning("entorhinal premise', ...pytest(T, FAILING) },
  { from:'hermes: prefetch waits for the check', file:F, find:'thread.join(self._wait)', replace:'thread.join(0)',
    ...pytest(T, 'test_prefetch_waits_for_a_slow_check_within_the_wait') },
  { from:'hermes: the same question reuses its job', file:F, find:'if self._job and self._job[0] == key:', replace:'if False:',
    ...pytest(T, REUSE) },
  { from:'hermes: a new turn invalidates the cached check', file:F, find:'key = (question, self._sync)', replace:'key = (question, None)',
    ...pytest(T, 'test_a_new_turn_or_question_starts_a_new_check') },
  { from:'hermes: the text gives the reason', file:F, find:' (why: {s["reason"]})', replace:'', ...pytest(T, GOLDEN) },
  { from:'hermes: the text names the newer fact', file:F, find:'{query.show(s["invalidated_by"], self._store)}',
    replace:'{s["invalidated_by"]}', ...pytest(T, GOLDEN) },
  { from:'hermes: one new provider per load', file:F, find:'ctx.register_memory_provider(StaleAwareMemory())',
    replace:'ctx.register_memory_provider(register.__dict__.setdefault("p", StaleAwareMemory()))', ...pytest(T, SURFACE) },
  { from:'hermes: no tool schemas', file:F, find:'return []  # the check rides', replace:'return [{"name": "x"}]  # the check rides',
    ...pytest(T, SURFACE) },
  { from:'hermes: name matches plugin.yaml', file:F, find:'NAME = "entorhinal"', replace:'NAME = "entorhinal-memory"', ...pytest(T, SURFACE) },
];
