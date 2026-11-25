"""
patterns package — Geometry, Ascending Triangle, Symmetrical Triangle, Pole & Flag
"""

from patterns.config import (
    DIST_MIN,
    DIST_MAX,
    TOLERANCE_PRICE_PCT,
    TOLERANCE_ATR_MULT,
    ASC_MIN_RR,
    SYM_MIN_RR,
    FLAG_MIN_RR,
)
from patterns.geometry import (
    atr,
    atr_series,
    confirmed_pivots,
    fit_line_through_pivots,
    touches_on_line,
    line_value,
    compute_tolerance,
    resample_to_weekly,
)
from patterns.ascending_triangle import (
    detect_ascending_triangle,
    get_ascending_triangle_debug,
)
from patterns.symmetrical_triangle import (
    detect_symmetrical_triangle,
    get_symmetrical_triangle_debug,
)
from patterns.pole_and_flag import (
    detect_pole_and_flag,
    get_pole_and_flag_debug,
)

__all__ = [
    "DIST_MIN",
    "DIST_MAX",
    "TOLERANCE_PRICE_PCT",
    "TOLERANCE_ATR_MULT",
    "ASC_MIN_RR",
    "SYM_MIN_RR",
    "FLAG_MIN_RR",
    "atr",
    "atr_series",
    "confirmed_pivots",
    "fit_line_through_pivots",
    "touches_on_line",
    "line_value",
    "compute_tolerance",
    "resample_to_weekly",
    "detect_ascending_triangle",
    "get_ascending_triangle_debug",
    "detect_symmetrical_triangle",
    "get_symmetrical_triangle_debug",
    "detect_pole_and_flag",
    "get_pole_and_flag_debug",
]
