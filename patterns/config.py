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
DEFAULT_PIVOT_WINDOW = 2
DEFAULT_MIN_SEPARATION = 3
ATR_PERIOD = 14

# Tolerance definition: max(0.6% of price, 0.50 * ATR)
TOLERANCE_PRICE_PCT = 0.006   # 0.6%
TOLERANCE_ATR_MULT = 0.50     # 0.50 * ATR

# ═══════════════════════════════════════════════════════════════════════════
# 3. ASCENDING TRIANGLE CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════
ASC_MIN_DAILY_BARS = 20
ASC_MAX_DAILY_BARS = 90
ASC_MIN_WEEKLY_BARS = 12
ASC_MAX_WEEKLY_BARS = 95

# Prior trend thresholds
ASC_PRIOR_LOOKBACK_DAILY = 40
ASC_PRIOR_RALLY_LOOKBACK_DAILY = 60
ASC_PRIOR_RALLY_MIN_DAILY = 0.08  # 8%
ASC_PRIOR_RALLY_LOOKBACK_WEEKLY = 20
ASC_PRIOR_RALLY_MIN_WEEKLY = 0.12 # 12%

# Resistance flatness: slope within ±0.10% per bar normalized
ASC_RES_MAX_SLOPE_NORM = 0.0010  # 0.10% per bar

# Rising support: positive slope at least +0.05% per bar normalized, R² >= 0.50
ASC_SUP_MIN_SLOPE_NORM = 0.0005  # +0.05% per bar
ASC_SUP_MIN_R2 = 0.50
ASC_MIN_PIVOT_SEPARATION = 3

# Triangle height at start >= 3% of price
ASC_MIN_HEIGHT_PCT = 0.03

# Apex: lines converge within 0 to 25 bars after the last pattern bar
ASC_APEX_MIN_BARS = 0
ASC_APEX_MAX_BARS = 25

# Status & Breakout parameters
ASC_BREAKOUT_PRICE_BUFFER = 0.002  # Close > Resistance * (1 + 0.2%)
ASC_BREAKOUT_VOL_MULT = 1.25       # Volume >= 1.25 * 20-bar avg volume
ASC_MAX_CHASE_PCT = 0.035          # Close <= Resistance * 1.035
ASC_RETEST_LOOKBACK_MIN = 2
ASC_RETEST_LOOKBACK_MAX = 10
ASC_FORMING_BAND_PCT = 0.020       # Within 2.0% below resistance (BO Zone)

# Risk & Targets
ASC_STOP_ATR_MULT = 0.5            # 0.5 * ATR buffer on stop-loss
ASC_MIN_RR = 2.0                   # Minimum 1:2.0 Risk-to-Reward

# ═══════════════════════════════════════════════════════════════════════════
# 4. SYMMETRICAL TRIANGLE CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════
SYM_MIN_DAILY_BARS = 20
SYM_MAX_DAILY_BARS = 90
SYM_MIN_WEEKLY_BARS = 12
SYM_MAX_WEEKLY_BARS = 95

# Slopes
SYM_RES_MAX_SLOPE_NORM = -0.0004  # <= -0.04% per bar (descending)
SYM_SUP_MIN_SLOPE_NORM = 0.0004   # >= +0.04% per bar (ascending)
SYM_MIN_R2 = 0.50

# Apex bounds: breakout between 40% and 95% of distance to apex
SYM_APEX_PROGRESS_MIN = 0.40
SYM_APEX_PROGRESS_MAX = 0.95

# Contraction & dry-up measured across the coil before breakout bars
SYM_RANGE_CONTRACTION_MAX = 0.85   # Last third coil range <= 85% of first third
SYM_VOLUME_DRYUP_MAX = 0.95        # Coil late volume < 95% of early volume

# Base height >= 4% of price
SYM_MIN_BASE_HEIGHT_PCT = 0.04

# Status & Breakout parameters
SYM_BREAKOUT_PRICE_BUFFER = 0.002  # Close > Upper line * (1 + 0.2%)
SYM_BREAKOUT_VOL_MULT = 1.20       # Volume >= 1.20 * 20-bar avg volume
SYM_MAX_CHASE_PCT = 0.035          # Close <= Upper line * 1.035
SYM_RETEST_LOOKBACK_MIN = 2
SYM_RETEST_LOOKBACK_MAX = 8
SYM_FORMING_BAND_PCT = 0.020       # Within 2.0% below upper line (BO Zone)

# Risk & Targets
SYM_STOP_ATR_MULT = 0.5
SYM_MIN_RR = 2.0                   # Minimum 1:2.0 Risk-to-Reward

# ═══════════════════════════════════════════════════════════════════════════
# 5. POLE AND FLAG CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════
# Daily parameters
FLAG_DAILY_POLE_MIN_RISE = 0.10    # >= 10% rise
FLAG_DAILY_POLE_MIN_BARS = 2
FLAG_DAILY_POLE_MAX_BARS = 10
FLAG_POLE_GREEN_RATIO = 0.60       # >= 60% green bars
FLAG_POLE_VOL_MULT = 1.30          # Volume >= 1.3 * 20-bar avg before pole

FLAG_DAILY_FLAG_MIN_BARS = 5
FLAG_DAILY_FLAG_MAX_BARS = 20
FLAG_MAX_RETRACE = 0.50            # Flag retrace <= 50% of pole

# Flag shape: parallel downward or tight horizontal channel
FLAG_SLOPE_NORM_MIN = -0.008       # -0.8% per bar
FLAG_SLOPE_NORM_MAX = 0.0008       # +0.08% per bar
FLAG_MIN_R2 = 0.40
FLAG_MAX_SLOPE_DIFF_NORM = 0.0018  # Parallel check: difference <= 0.18% per bar

FLAG_VOL_CONTRACTION_MAX = 0.85    # Flag consolidation avg vol < 85% of pole avg vol
FLAG_BREAKOUT_PRICE_BUFFER = 0.002 # Close > upper line * 1.002
FLAG_BREAKOUT_VOL_MULT = 1.30      # Volume >= 1.3 * 20-bar avg
FLAG_MAX_CHASE_PCT = 0.03          # Close <= upper line * 1.03
FLAG_RETEST_LOOKBACK_MIN = 2
FLAG_RETEST_LOOKBACK_MAX = 8
FLAG_FORMING_BAND_PCT = 0.020      # Within 2% below upper flag line
FLAG_MIN_RR = 2.0                  # Minimum 1:2.0 Risk-to-Reward

# Weekly parameters
FLAG_WEEKLY_POLE_MIN_RISE = 0.15   # >= 15% rise
FLAG_WEEKLY_POLE_MIN_BARS = 2
FLAG_WEEKLY_POLE_MAX_BARS = 8
FLAG_WEEKLY_FLAG_MIN_BARS = 3
FLAG_WEEKLY_FLAG_MAX_BARS = 10
