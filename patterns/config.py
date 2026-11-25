"""
patterns/config.py — Central Configuration and Named Constants
==============================================================
All tolerances, ratios, thresholds, and filter parameters for:
  - Shared Geometry Engine
  - Ascending Triangle
  - Symmetrical Triangle
  - Pole and Flag
  - 44 MA Scanner
"""

# ═══════════════════════════════════════════════════════════════════════════
# 1. 44 MA SCANNER CONSTANTS (Chartink "swing-trade-by-pmpatil")
# ═══════════════════════════════════════════════════════════════════════════
# Fixed distance band: stock qualifies inside DIST_MIN <= Distance % <= DIST_MAX
DIST_MIN = -1.0  # -1.0% (Near below support band)
DIST_MAX = 3.0   # +3.0% (Clearance band: -1.0% to +3.0% only)
MA_PERIOD = 44
MA_RISING_BARS = 1  # 44 MA rising: today's MA44 > yesterday's MA44 (strictly rising slope)
MA44_PULLBACK_HIGH_SMA = True  # Chartink rule 3: Daily Low < Daily SMA(Daily High, 44)
MA44_CLOSE_ABOVE_SMA = True   # Chartink rule 4: Daily Close > Daily SMA(Daily Close, 44)
MA44_GREEN_CANDLE = True      # Chartink rule 5: Daily Close > Daily Open

# ═══════════════════════════════════════════════════════════════════════════
# 2. SHARED GEOMETRY CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════
DEFAULT_PIVOT_WINDOW = 3
DEFAULT_MIN_SEPARATION = 4
ATR_PERIOD = 14

# Tolerance definition: max(0.4% of price, 0.35 * ATR)
TOLERANCE_PRICE_PCT = 0.004   # 0.4%
TOLERANCE_ATR_MULT = 0.35     # 0.35 * ATR

# ═══════════════════════════════════════════════════════════════════════════
# 3. ASCENDING TRIANGLE CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════
ASC_MIN_DAILY_BARS = 30
ASC_MAX_DAILY_BARS = 90
ASC_MIN_WEEKLY_BARS = 15
ASC_MAX_WEEKLY_BARS = 40

# Prior trend thresholds
ASC_PRIOR_LOOKBACK_DAILY = 40
ASC_PRIOR_RALLY_LOOKBACK_DAILY = 60
ASC_PRIOR_RALLY_MIN_DAILY = 0.10  # 10%
ASC_PRIOR_RALLY_LOOKBACK_WEEKLY = 20
ASC_PRIOR_RALLY_MIN_WEEKLY = 0.15 # 15%

# Resistance flatness: slope within ±0.05% per bar normalized
ASC_RES_MAX_SLOPE_NORM = 0.0005  # 0.05% per bar

# Rising support: positive slope at least +0.05% per bar normalized, R² >= 0.6
ASC_SUP_MIN_SLOPE_NORM = 0.0005  # +0.05% per bar
ASC_SUP_MIN_R2 = 0.60
ASC_MIN_PIVOT_SEPARATION = 5

# Triangle height at start >= 3% of price
ASC_MIN_HEIGHT_PCT = 0.03

# Apex: lines converge within 1 to 15 bars after the last pattern bar
ASC_APEX_MIN_BARS = 1
ASC_APEX_MAX_BARS = 15

# Status & Breakout parameters
ASC_BREAKOUT_PRICE_BUFFER = 0.002  # Close > Resistance * (1 + 0.2%)
ASC_BREAKOUT_VOL_MULT = 1.50       # Volume >= 1.5 * 20-bar avg volume
ASC_MAX_CHASE_PCT = 0.03           # Close <= Resistance * 1.03
ASC_RETEST_LOOKBACK_MIN = 2
ASC_RETEST_LOOKBACK_MAX = 10
ASC_FORMING_BAND_PCT = 0.015       # Within 1.5% below resistance

# Risk & Targets
ASC_STOP_ATR_MULT = 0.5            # 0.5 * ATR buffer on stop-loss
ASC_MIN_RR = 3.0                   # Minimum 1:3 Risk-to-Reward (reject if below)

# ═══════════════════════════════════════════════════════════════════════════
# 4. SYMMETRICAL TRIANGLE CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════
SYM_MIN_DAILY_BARS = 30
SYM_MAX_DAILY_BARS = 90
SYM_MIN_WEEKLY_BARS = 15
SYM_MAX_WEEKLY_BARS = 40

# Slopes
SYM_RES_MAX_SLOPE_NORM = -0.0005  # <= -0.05% per bar (descending)
SYM_SUP_MIN_SLOPE_NORM = 0.0005   # >= +0.05% per bar (ascending)
SYM_MIN_R2 = 0.60

# Apex bounds: breakout between 50% and 85% of distance to apex
SYM_APEX_PROGRESS_MIN = 0.50
SYM_APEX_PROGRESS_MAX = 0.85

# Contraction: last third range <= 75% of first third (25% smaller)
SYM_RANGE_CONTRACTION_MAX = 0.75
# Volume dry-up: last third volume < 85% of first third
SYM_VOLUME_DRYUP_MAX = 0.85

# Base height >= 4% of price
SYM_MIN_BASE_HEIGHT_PCT = 0.04

# Status & Breakout parameters
SYM_BREAKOUT_PRICE_BUFFER = 0.002  # Close > Upper line * (1 + 0.2%)
SYM_BREAKOUT_VOL_MULT = 1.25       # Volume >= 1.25 * 20-bar avg volume
SYM_MAX_CHASE_PCT = 0.03           # Close <= Upper line * 1.03
SYM_RETEST_LOOKBACK_MIN = 2
SYM_RETEST_LOOKBACK_MAX = 8
SYM_FORMING_BAND_PCT = 0.015       # Within 1.5% below upper line

# Risk & Targets
SYM_STOP_ATR_MULT = 0.5
SYM_MIN_RR = 2.5                   # Minimum 1:2.5 Risk-to-Reward (reject if below)

# ═══════════════════════════════════════════════════════════════════════════
# 5. POLE AND FLAG CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════
# Daily parameters
FLAG_DAILY_POLE_MIN_RISE = 0.12    # >= 12% rise
FLAG_DAILY_POLE_MIN_BARS = 5
FLAG_DAILY_POLE_MAX_BARS = 15
FLAG_POLE_GREEN_RATIO = 0.60       # >= 60% green bars
FLAG_POLE_VOL_MULT = 1.30          # Volume >= 1.3 * 20-bar avg before pole

FLAG_DAILY_FLAG_MIN_BARS = 5
FLAG_DAILY_FLAG_MAX_BARS = 20
FLAG_MAX_RETRACE = 0.50            # Flag retrace <= 50% of pole

# Flag shape: parallel lines sloping down or sideways
FLAG_SLOPE_NORM_MIN = -0.004       # -0.4% per bar
FLAG_SLOPE_NORM_MAX = 0.001        # +0.1% per bar
FLAG_MIN_R2 = 0.50
FLAG_MAX_SLOPE_DIFF_NORM = 0.0015  # Parallel check: difference <= 0.15% per bar

FLAG_VOL_CONTRACTION_MAX = 0.80    # Flag avg vol < 80% of pole avg vol
FLAG_BREAKOUT_PRICE_BUFFER = 0.002 # Close > upper line * 1.002
FLAG_BREAKOUT_VOL_MULT = 1.30      # Volume >= 1.3 * 20-bar avg
FLAG_MAX_CHASE_PCT = 0.03          # Close <= upper line * 1.03
FLAG_RETEST_LOOKBACK_MIN = 2
FLAG_RETEST_LOOKBACK_MAX = 8
FLAG_FORMING_BAND_PCT = 0.020      # Within 2% below upper flag line
FLAG_MIN_RR = 2.0                  # Minimum 1:2.0 Risk-to-Reward

# Weekly parameters
FLAG_WEEKLY_POLE_MIN_RISE = 0.20   # >= 20% rise
FLAG_WEEKLY_POLE_MIN_BARS = 3
FLAG_WEEKLY_POLE_MAX_BARS = 8
FLAG_WEEKLY_FLAG_MIN_BARS = 3
FLAG_WEEKLY_FLAG_MAX_BARS = 10
