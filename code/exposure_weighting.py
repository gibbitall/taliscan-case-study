# exposure_weighting.py
#
# What it shows: how an additive's hazard is weighted by real-world exposure before it touches
# the score (how it reaches the body, how often the product is used, how much is in it), and the
# hard caps that keep a high-hazard additive from being averaged away by good nutrition.
#
# Source: y2-backend/pipelines/food/additive_scoring.py, commit 997beb9b
#         y2-backend/config/exposure_routes.yml, commit 71ecfe88 (route map, quoted in part)
# Excerpt, lightly edited for length.

# ... (trimmed: module docstring, imports, logging, and the config path)

# ─── Tier numeric mapping (for multiplier math) ───────────────────────────────

_TIER_TO_NUM = {"high": 4, "moderate": 3, "low": 2, "safe": 1, "unknown": 2}

# ─── Route multipliers ────────────────────────────────────────────────────────

_ROUTE_MULTIPLIER = {
    "ingested": 1.0,
    "mucosal": 0.9,
    "dermal_daily": 0.7,
    "dermal_rinseoff": 0.4,
    "dermal_residual": 0.3,
    "inhaled": 0.6,
    "surface_contact_inhaled": 0.5,
    "surface_contact": 0.1,
}

# config/exposure_routes.yml maps each L1 category to a route (quoted in part):
#   skin_care: dermal_daily
#   hair_care: dermal_rinseoff
#   oral_care: mucosal
#   household_cleaners: surface_contact_inhaled
#   laundry_care: dermal_residual

# ─── Cadence multipliers ──────────────────────────────────────────────────────

_CADENCE_MULTIPLIER = {
    "daily": 1.0,
    "frequent": 0.8,
    "occasional": 0.5,
    "rare": 0.2,
}

# ─── Concentration multipliers (from ingredient position) ─────────────────────

_CONCENTRATION_MULTIPLIER = {
    "high": 1.0,
    "medium": 0.7,
    "low": 0.4,
    "trace": 0.15,
}

# ... (trimmed: config lookups _get_route_for_l1() and _get_cadence_for_l2(); an unknown
#      category falls back to the "ingested" route, the safest assumption)

def concentration_tier_from_position(
    position: int,
    after_2pct_marker: bool,
) -> str:
    """Determine concentration tier from ingredient list position.

    ... (trimmed)
    """
    if after_2pct_marker:
        return "trace"
    if position <= 3:
        return "high"
    if position <= 8:
        return "medium"
    return "low"


def compute_effective_tier(
    intrinsic_hazard: str,
    product_l1: str,
    product_l2: str,
    ingredient_position: int,
    after_2pct_marker: bool,
) -> str:
    """Compute the context-adjusted effective risk tier for an additive.

    ... (trimmed)
    """
    if intrinsic_hazard == "safe":
        return "safe"

    base = _TIER_TO_NUM.get(intrinsic_hazard, 2)

    route = _get_route_for_l1(product_l1)
    route_mult = _ROUTE_MULTIPLIER.get(route, 1.0)

    cadence = _get_cadence_for_l2(product_l2)
    cadence_mult = _CADENCE_MULTIPLIER.get(cadence, 0.5)

    conc = concentration_tier_from_position(ingredient_position, after_2pct_marker)
    conc_mult = _CONCENTRATION_MULTIPLIER.get(conc, 0.4)

    # Weighted product: how much real-world risk does this represent?
    effective_score = base * route_mult * cadence_mult * conc_mult

    # Map back to tier
    if effective_score >= 3.0:
        return "high"
    if effective_score >= 2.0:
        return "moderate"
    if effective_score >= 1.0:
        return "low"
    return "safe"

# ... (trimmed: within-band deduction constants and evidence-strength weights)

def apply_additive_cap(
    base_score: int,
    effective_tiers: list[str],
    intrinsic_hazards: list[str] | None = None,
    # ... (trimmed: trace markers, evidence strengths, and a legacy flag)
) -> int:
    """Apply additive-based score caps with continuous within-band deductions.

    ... (trimmed)
    """
    if not effective_tiers:
        return base_score

    high_count = effective_tiers.count("high")
    moderate_count = effective_tiers.count("moderate")
    low_count = effective_tiers.count("low")
    has_moderate = moderate_count > 0

    # ... (trimmed: count INTRINSIC high and moderate additives, and note whether each
    #      high one appears at bulk level or only as a trace after "2% or less")

    # --- Cap logic ---
    # Existing effective-tier caps (food + non-food): unchanged behavior.
    caps: list[int] = []
    if high_count >= 1:
        caps.append(49)
    if high_count >= 2:
        caps.append(35)
    if has_moderate:
        caps.append(69)

    # V1 framework caps (all domains): operate on INTRINSIC hazard to catch
    # evidence-graded concerns that dose-math would otherwise zero out.
    # Uniform caps across food/personal/home.
    if intrinsic_hazards is not None:
        if any_intrinsic_high_at_bulk:
            caps.append(49)                   # single HIGH-intrinsic at bulk
        if any_intrinsic_high_at_trace:
            caps.append(69)                   # single HIGH-intrinsic at trace
        if intrinsic_high_count >= 2:
            caps.append(35)                   # multi HIGH-intrinsic stacking
        if intrinsic_moderate_count >= 3:
            caps.append(59)                   # MODERATE stacking

    cap = min(caps) if caps else None

    # ... (trimmed: evidence-weighted deductions within the capped band; sets `deduction`)

    # Apply cap first, then deduction
    if cap is not None:
        score = min(base_score, cap)
    else:
        score = base_score
    score -= deduction

    return max(0, score)
