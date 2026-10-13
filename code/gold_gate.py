# gold_gate.py
#
# What it shows: the automated gate every AI-researched product record must pass before it goes
# live. Eight core fields set the verdict (gold, provisional, or blocked), and the gate re-checks
# the LLM's output instead of trusting it: malformed fields are normalized, nutrition that is
# really per serving (not per 100 g) is thrown out, and an ingredient list the LLM itself flagged
# as invalid is cleared. Records that fall short go to the agent team for repair.
#
# Source: y2-backend/etl/wave/runner.py (WaveRunner._enforce_core_completeness and
#         WaveRunner._compute_product_status), commit df601c0c
# Excerpt, lightly edited for length.

# ... (trimmed: imports)


class WaveRunner:
    # ... (trimmed: the rest of the wave pipeline)

    def _enforce_core_completeness(self, result: Dict[str, Any], *, row: Optional[Dict[str, Any]] = None) -> None:
        """
        UNIFIED GOLD GATE - Single source of truth for all product types.

        Promotes products to "gold" status if all core fields are present.
        This is the ONLY gold gate evaluation in the system - the API layer
        simply reads the stored verdict without re-evaluation.

        ... (trimmed)
        """
        canonical = result.get("canonical_record") or {}
        gold = result.get("gold_review") or {}
        identity = canonical.get("identity") or {}
        comp = canonical.get("composition") or {}
        classification = canonical.get("classification") or {}

        # Normalize ingredients_text if it's unexpectedly a dict (from malformed LLM output)
        raw_ing = comp.get("ingredients_text")
        if isinstance(raw_ing, dict):
            normalized_ing = raw_ing.get("text") or raw_ing.get("value") or None
            comp["ingredients_text"] = normalized_ing if isinstance(normalized_ing, str) else None
            canonical["composition"] = comp

        def _has(val) -> bool:
            return val not in (None, "", [], {})

        # ... (trimmed: required_macros, the 10 nutrition fields a food label must carry)
        np100 = comp.get("nutrition_per_100") or {}

        # Nutrition sanity check: catch unconverted per-serving values
        # If macros sum > 105g per 100g and no E2 basis field, the data is per-serving not per-100g
        if np100:
            _macro_sum = sum(
                float(np100.get(k) or 0) for k in ("protein_g", "fat_g", "carb_g")
            )
            _sodium_val = float(np100.get("sodium_mg") or 0)
            _has_basis = bool(np100.get("basis"))
            if (_macro_sum > 105 and not _has_basis) or (_sodium_val > 40000 and not _has_basis):
                # Null out bad nutrition data - it's unconverted per-serving values
                comp["nutrition_per_100"] = None
                canonical["composition"] = comp
                np100 = {}

        # ... (trimmed: domain lookup, then nutrition exemptions for non-food products,
        #      single-ingredient coffee and tea, and supplement-facts panels)

        # Check ingredients QC from LLM (if present)
        # If LLM flagged ingredients as invalid, enforce the block
        ingredients_qc = result.get("ingredients_qc") or {}
        ingredients_qc_failed = ingredients_qc.get("looks_valid") is False
        ingredients_qc_reason = ingredients_qc.get("reason") or "Invalid ingredients"
        ingredients_qc_type = ingredients_qc.get("issue_type") or "unknown"

        if ingredients_qc_failed:
            # LLM determined ingredients are invalid (placeholder, too vague, etc.)
            # Ensure ingredients_text is cleared and blocking is enforced
            if _has(comp.get("ingredients_text")):
                comp["ingredients_text"] = None
                canonical["composition"] = comp

        # Compute individual field statuses
        has_brand = _has(identity.get("brand"))
        has_title = _has(identity.get("canonical_title"))
        has_gtin = _has(identity.get("gtin14"))
        has_ingredients = _has(comp.get("ingredients_text")) and not ingredients_qc_failed
        has_nutrition = nutrition_criteria_met
        has_supplement_facts = supplement_criteria_met
        has_y2_l1 = _has(classification.get("y2_l1"))
        has_y2_l2 = _has(classification.get("y2_l2"))

        # Compute product status using 3-tier logic
        status, blocking, notes_parts = self._compute_product_status(
            # ... (trimmed: passes the eight has_* flags plus exemption and ingredient-QC details)
        )

        gold["status"] = status
        gold["blocking_fields"] = blocking
        # ... (trimmed: decision notes and per-field status for the review queue)

    def _compute_product_status(
        self,
        has_brand: bool,
        has_title: bool,
        has_gtin: bool,
        has_ingredients: bool,
        has_nutrition: bool,
        has_supplement_facts: bool,
        has_y2_l1: bool,
        has_y2_l2: bool,
        # ... (trimmed: exemption and ingredient-QC details, used only for review notes)
    ) -> tuple[str, list[str], list[str]]:
        """
        Compute product status using 3-tier logic.

        ... (trimmed)

        Status tiers:
        - gold: All 8 core fields present (supplement_facts only blocks supplements)
        - provisional: Has brand, title, classification, and at least one composition field
        - blocked: Missing brand OR title OR classification OR missing ALL composition fields
        """
        # ... (trimmed: build `blocking`, the list of missing core-field paths such as
        #      "identity.gtin14", plus a review note when the LLM's ingredient QC failed)

        # Gold: all 8 core fields present
        all_fields_present = (
            has_brand
            and has_title
            and has_gtin
            and has_ingredients
            and has_nutrition
            and has_supplement_facts
            and has_y2_l1
            and has_y2_l2
        )
        if all_fields_present:
            return ("gold", [], notes_parts)

        # Blocked: missing brand OR title OR classification
        has_classification = has_y2_l1 and has_y2_l2
        if not has_brand or not has_title or not has_classification:
            return ("blocked", blocking, notes_parts)

        # Provisional: has brand + title + classification + at least one composition field
        # Note: has_supplement_facts is True/"not applicable" for non-supplements, so it
        # doesn't contribute to the provisional composition threshold. It only gates gold.
        has_at_least_one_composition = has_ingredients or has_nutrition
        if has_at_least_one_composition:
            return ("provisional", blocking, notes_parts)

        # Fall back to blocked if no composition fields at all
        return ("blocked", blocking, notes_parts)
