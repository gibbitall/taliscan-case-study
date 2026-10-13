# Code excerpts

Four short excerpts from TaliScan's private backend and data-pipeline repo, picked so an engineer can
confirm the system is real and see how the AI parts were made reliable. Each file opens with what it
shows, its source path, and the source commit. All are lightly edited for length, with cuts marked
"(trimmed)".

- [`agent_roles.md`](agent_roles.md): the Claude Code agent team that repairs records failing the quality gate, five specialist roles, dispatched by the lead agent that runs the loop, each with its own model, tool limits, and rules (the validator cannot write, the gatekeeper rejects by default). It matters because reliability came from narrow, enforced roles rather than one do-everything agent.
- [`gold_gate.py`](gold_gate.py): the gate every AI-researched product must pass before it goes live, where 8 core fields decide gold, provisional, or blocked and the code re-checks the LLM's output. It matters because nothing an LLM produces reaches the catalog on trust alone.
- [`deferral_rule.sql`](deferral_rule.sql): a Postgres trigger plus the gated code path it guards, so an agent cannot set a product aside for human review without 2+ researcher notes, a senior-reviewer note, and a gatekeeper APPROVE. It matters because when setting work aside is free, agents use it to clear their queue, so a handoff has to be earned.
- [`exposure_weighting.py`](exposure_weighting.py): how each additive's hazard is weighted by exposure route (eaten 1.0x down to surface contact 0.1x), usage frequency, and amount (a trace after "2% or less" counts 0.15x), plus hard caps (one high-hazard additive caps the score at 49, or 69 if it is only a trace). It matters because the score is a transparent rules engine whose every number can be explained.
