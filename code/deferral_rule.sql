-- deferral_rule.sql
--
-- What it shows: the database backstop that stops an AI agent from setting a product aside for
-- human review (a "deferral") before the research is done. Postgres refuses any deferral that
-- did not come through the one gated code path, and any without evidence of 2+ research rounds.
-- The gated path (quoted below the trigger) also requires a senior-reviewer note and an APPROVE
-- from the reject-by-default gatekeeper agent.
--
-- Source: y2-backend/sql/018_protect_deferral.sql, commit d87e9081
--         y2-backend/tooling/loop/fixer.py, commit 8b398716 (application side, quoted)
-- Excerpt, lightly edited for length.

-- 018_protect_deferral.sql
-- Deferral Gatekeeper: DB-level defense against unreviewed deferrals.
--
-- Two layers of protection on INSERT into deferred_items:
--   Layer 1: Session variable (app.deferral_authorized) must be set by authorize_and_defer()
--   Layer 2: Product must have >= 2 fixer_notes in the DB (anti-bypass)
--
-- New columns track gatekeeper provenance on each deferral.

-- ─── New columns ────────────────────────────────────────────────────────────────

ALTER TABLE deferred_items
    ADD COLUMN IF NOT EXISTS gatekeeper_approved BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS research_rounds_completed INT DEFAULT 0,
    ADD COLUMN IF NOT EXISTS gatekeeper_reasoning TEXT;

-- ─── Trigger function ───────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION protect_deferral_insert()
RETURNS TRIGGER AS $$
DECLARE
    note_count INT;
BEGIN
    -- Layer 1: Session variable must be set by authorize_and_defer()
    IF current_setting('app.deferral_authorized', true) IS DISTINCT FROM 'true' THEN
        RAISE EXCEPTION 'Cannot insert into deferred_items directly. Use authorize_and_defer().';
    END IF;

    -- Layer 2: Validate actual fixer_notes exist in DB (anti-bypass).
    -- Even if the session variable is set via raw SQL, the product must have
    -- genuine research evidence in the form of >= 2 fixer_notes.
    -- Check products table first.
    SELECT COUNT(*) INTO note_count
    FROM products
    WHERE barcode = NEW.entity_id
      AND canonical_record->'fixer_notes' IS NOT NULL
      AND jsonb_array_length(canonical_record->'fixer_notes') >= 2;

    IF note_count = 0 THEN
        -- Check products_pipeline table
        SELECT COUNT(*) INTO note_count
        FROM products_pipeline
        WHERE product_id = NEW.entity_id
          AND canonical_record->'fixer_notes' IS NOT NULL
          AND jsonb_array_length(canonical_record->'fixer_notes') >= 2;
    END IF;

    IF note_count = 0 AND NEW.research_rounds_completed < 2 THEN
        RAISE EXCEPTION 'Product % has insufficient research (need >= 2 fixer_notes in DB). Cannot defer.', NEW.entity_id;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ─── Trigger ────────────────────────────────────────────────────────────────────

DROP TRIGGER IF EXISTS protect_deferral ON deferred_items;

CREATE TRIGGER protect_deferral
    BEFORE INSERT ON deferred_items
    FOR EACH ROW
    EXECUTE FUNCTION protect_deferral_insert();


-- ─── Application side, quoted from tooling/loop/fixer.py ──────────────────────
-- The session flag checked above is set in exactly one place, authorize_and_defer(),
-- which runs only when the gatekeeper agent returns APPROVE.
--
--   # These functions implement defense-in-depth against unreviewed deferrals.
--   # Flow: check_deferral_prerequisites() -> run_deferral_gatekeeper() -> authorize_and_defer()
--
-- From check_deferral_prerequisites(), the hard gate run before the gatekeeper is spawned:
--
--       if len(researcher_notes) < 2:
--           return PrerequisiteResult(
--               can_defer=False,
--               reason=(
--                   f"Need >= 2 researcher-level notes, found {len(researcher_notes)}. "
--                   f"Dispatch more fixer rounds before deferring."
--               ),
--               # ... (trimmed)
--           )
--
--       if len(senior_notes) < 1:
--           return PrerequisiteResult(
--               can_defer=False,
--               reason=(
--                   f"Need >= 1 senior-level note, found {len(senior_notes)}. "
--                   f"Dispatch a fixer-senior sweep before deferring."
--               ),
--               # ... (trimmed)
--           )
--
-- From process_gatekeeper_result(), which reads the gatekeeper agent's JSON verdict:
--
--       if not result or "verdict" not in result:
--           logger.warning("Could not parse gatekeeper output for %s, defaulting to REJECT", entity_id)
--           return {
--               "verdict": "REJECT",
--               "reasoning": "Gatekeeper output could not be parsed. Defaulting to REJECT.",
--               # ... (trimmed)
--           }
--
--       verdict = result.get("verdict", "REJECT").upper()
--       # ... (trimmed)
--       if verdict == "APPROVE":
--           # ... (trimmed)
--               authorize_and_defer(
--                   # ... (trimmed: entity, loop, and the gatekeeper's reasoning)
--               )
--
-- From authorize_and_defer():
--
--       # Defense-in-depth: re-check prerequisites
--       prereq = check_deferral_prerequisites(entity_id)
--       if not prereq.can_defer:
--           raise RuntimeError(
--               f"Deferral prerequisites not met for {entity_id}: {prereq.reason}"
--           )
--       # ... (trimmed)
--               # Authorize through the DB trigger
--               cur.execute('SET LOCAL "app.deferral_authorized" = \'true\'')
--               # ... (trimmed: one INSERT INTO deferred_items, same transaction)
