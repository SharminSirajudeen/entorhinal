## Use with Hermes

A memory provider for [Hermes Agent](https://github.com/NousResearch/hermes-agent) (MIT). Each turn, what the user said
is ingested; before the agent answers, any assumption in the user's question that a newer fact has made untrue is
listed under the recalled context, with the newer fact and its date.

Not yet run inside a real Hermes: it is tested against the `MemoryProvider` interface read from Hermes's source
(`agent/memory_provider.py`, `agent/memory_manager.py`), with scripted test replies in place of the model.

**Install**
1. Make `life/` importable in the Python that runs Hermes (for example `PYTHONPATH=<this repo>`).
2. Copy or link `hermes_provider/` to `$HERMES_HOME/plugins/entorhinal/` (Hermes loads user providers from
   `$HERMES_HOME/plugins/<name>/`; the directory name is the provider name).
3. Set `NEBIUS_API_KEY` and `memory.provider: entorhinal` in the Hermes config.

**What it does**
- `sync_turn`: ingests the user's side of the turn only (never the assistant's text), on a background thread, queued
  behind the previous turn so facts land in order. Turns of subagents, cron and flush contexts are not ingested.
- `prefetch(query)`: runs the premise check (a thinking call) on a background thread and waits up to 6 s (Hermes allows an external
  prefetch 8 s). If the check is not done, it returns nothing for this turn; asked again, the same question finds the
  finished result. `queue_prefetch` starts the same check early.
- Nothing raises into Hermes: a failed model call loses that turn's facts or that question's report, never the turn.
- One SQLite file per profile at `$HERMES_HOME/entorhinal/memory.db`. The user can export or delete it with `Store`.

**What leaves the device**
The user's messages (for fact extraction and change detection) and, for the premise check, their stored facts and the
question, go to Nebius Token Factory with your `NEBIUS_API_KEY`. Nothing else is sent anywhere.
