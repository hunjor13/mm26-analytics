#!/usr/bin/env python3
"""
College Basketball Ranking System v2.3
Combining Boston, Walters, and Feustel Methodologies
with Full 64-Team Monte Carlo Tournament Simulation

UPDATED: March 15, 2026 — Selection Sunday
2026 NCAA Tournament bracket locked in from CBS Sports official release.

v2.3 Changes:
- Full 64-team bracket simulation (was Final Four only)
- TOURNAMENT_BRACKET_2026 constant with all 4 regions / actual seedings
- Team dataclass now carries tournament_seed + tournament_region
- Proxy team builder for unmodeled bracket entries (seed-based efficiency)
- run_full_simulation now tracks all 6 rounds: R64 → R32 → S16 → E8 → FF → Champ
- New generate_bracket_report() with per-round advancement probabilities
- Injuries updated to Selection Sunday status

Enhanced "Walters Tweaks":
1. Dynamic Home Court Advantage (team-specific HCA)
2. Injury Impact with Rotation Value tables
3. SOS Decay (early-season games weighted less)
4. Style-based variance (3-point teams vs post-heavy)

Author: Jordan's Custom System
Date: February 2026 / Updated March 15, 2026
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional
import random
from collections import defaultdict
from datetime import datetime, timedelta
from enum import Enum

np.random.seed(42)
random.seed(42)


class PlayStyle(Enum):
    """Team play style affects variance in simulation"""
    THREE_POINT_HEAVY = "three_point_heavy"  # High variance
    BALANCED = "balanced"                     # Medium variance
    POST_HEAVY = "post_heavy"                # Low variance
    UPTEMPO_CHAOS = "uptempo_chaos"          # Highest variance


@dataclass
class InjuredPlayer:
    """Track individual player injuries and their impact"""
    name: str
    position: str  # PG, SG, SF, PF, C
    rotation_value: float  # Points of spread impact when out
    games_out: int = 0  # Expected games missed
    is_starter: bool = True


@dataclass
class HomeCourtProfile:
    """Dynamic home court advantage profile"""
    base_hca: float = 3.5  # Base home court advantage
    altitude_bonus: float = 0.0  # High altitude venues (Colorado, Utah, etc.)
    crowd_intensity: float = 0.0  # 0-1 scale, historic rowdiness
    arena_capacity: int = 15000
    historical_home_win_pct: float = 0.65  # Last 3 seasons
    
    def calculate_dynamic_hca(self) -> float:
        """Calculate actual HCA based on all factors"""
        hca = self.base_hca
        hca += self.altitude_bonus
        hca += self.crowd_intensity * 1.0
        
        if self.arena_capacity > 20000:
            hca += 0.3
        elif self.arena_capacity > 15000:
            hca += 0.15
        
        if self.historical_home_win_pct > 0.80:
            hca += 0.5
        elif self.historical_home_win_pct > 0.70:
            hca += 0.25
        
        return hca


@dataclass
class SOSRecord:
    """Track schedule strength with game dates for decay calculation"""
    opponent_name: str
    opponent_strength: float  # 0-1 scale
    game_date: datetime
    was_home: bool
    result: str  # "W" or "L"
    margin: int


@dataclass
class Team:
    """Enhanced Team data structure with Walters tweaks"""
    name: str
    rank: int
    record: str
    wins: int
    losses: int
    conference: str
    kenpom_rank: int = None
    net_rank: int = None
    
    # Offensive/Defensive metrics (per 100 possessions)
    off_efficiency: float = 110.0
    def_efficiency: float = 95.0
    tempo: float = 70.0
    
    # Boston Factors (Qualitative)
    program_history_score: float = 5.0
    coaching_score: float = 5.0
    motivation_factor: float = 1.0
    tournament_experience: int = 0
    
    # Walters Tweaks
    home_court_profile: HomeCourtProfile = field(default_factory=HomeCourtProfile)
    injured_players: List[InjuredPlayer] = field(default_factory=list)
    base_injury_impact: float = 0.0
    schedule_history: List[SOSRecord] = field(default_factory=list)
    raw_schedule_strength: float = 0.5
    
    # Play Style for Variance
    play_style: PlayStyle = PlayStyle.BALANCED
    three_point_rate: float = 0.35
    three_point_pct: float = 0.35
    
    # Legacy fields
    recent_form: float = 0.0
    pythagorean_win_pct: float = 0.5
    four_factors_score: float = 0.0
    regression_rating: float = 0.0
    
    # Key player info
    star_player: str = ""
    
    # ===== 2026 NCAA TOURNAMENT SEEDING =====
    tournament_seed: int = 0          # Actual seed (1-16); 0 = not in field
    tournament_region: str = ""       # "East" | "South" | "West" | "Midwest"
    
    # ===== CHAMPIONSHIP PROFILE FIELDS =====
    # Gill Alexander (VSiN "A Numbers Game") championship checklist
    assist_to_turnover_ratio: float = 1.0       # Last 35 champs: ATR > 1.0          (100%)
    coach_sweet16_appearances: int = 0           # 32 of last 35 champs: HC S16 exp   (91%)
    quality_wins_top10_rpi: int = 0              # 29 of last 30 champs: 3+ Q1 wins   (97%)
    sos_rank: int = 200                          # Last 30 champs: top-75 SOS         (100%)
    off_kenpom_rank: int = 50                    # 22 of last 23 champs: top-20 ADJOE (96%)
    def_kenpom_rank: int = 50                    # 22 of last 23 champs: top-20 ADJDE (96%)
    three_point_pct_differential: float = 0.0   # Bonus: last champ w/ neg 3P% diff = 1988 Kansas
    nba_draft_picks_projected: int = 0           # Projected NBA draft picks (1st + 2nd round)
                                                  # Transcript: champ should have ≥1 projected pick
    
    @property
    def home_court_advantage(self) -> float:
        return self.home_court_profile.calculate_dynamic_hca()
    
    @property
    def injury_impact(self) -> float:
        if not self.injured_players:
            return self.base_injury_impact
        total_impact = self.base_injury_impact
        for player in self.injured_players:
            if player.games_out > 0:
                total_impact -= player.rotation_value
        return total_impact
    
    @property
    def schedule_strength(self) -> float:
        if not self.schedule_history:
            return self.raw_schedule_strength
        return calculate_decayed_sos(self.schedule_history)
    
    def get_simulation_variance(self) -> float:
        variance_map = {
            PlayStyle.THREE_POINT_HEAVY: 0.12,
            PlayStyle.UPTEMPO_CHAOS: 0.14,
            PlayStyle.BALANCED: 0.08,
            PlayStyle.POST_HEAVY: 0.05,
        }
        base_variance = variance_map.get(self.play_style, 0.08)
        if self.three_point_rate > 0.45:
            base_variance += 0.03
        elif self.three_point_rate < 0.25:
            base_variance -= 0.02
        return base_variance


# ===== ROTATION VALUE TABLES =====
ROTATION_VALUES = {
    "PG": (3.5, 1.5),
    "SG": (2.5, 1.0),
    "SF": (2.0, 0.8),
    "PF": (2.5, 1.0),
    "C": (3.0, 1.2),
}

# ===== POWER CONFERENCE SET =====
# Mid-majors face a historically-validated advancement penalty in R32+
POWER_CONFERENCES = {"ACC", "Big 12", "Big Ten", "SEC", "Big East", "Pac-12"}
MID_MAJOR_PENALTY_ROUNDS = {"r32", "s16", "e8", "ff"}

# ===== HISTORICAL SEED UPSET RATES (R64, 1985-2025) =====
# Format: {(fav_seed, dog_seed): favorite_win_probability}
# Source: NCAA historical data — 40 years of 64-team tournament results
HISTORICAL_SEED_UPSET_RATES: Dict[Tuple[int, int], float] = {
    (1, 16): 0.985,   # 1 upset in 160 games
    (2, 15): 0.940,   # 10 upsets in 160 games
    (3, 14): 0.848,   # ~24 upsets
    (4, 13): 0.794,   # ~33 upsets
    (5, 12): 0.647,   # 57 upsets — the famous 5/12 upset line
    (6, 11): 0.630,   # ~59 upsets — 11-seeds include play-in winners
    (7, 10): 0.605,   # ~63 upsets
    (8,  9): 0.513,   # essentially a coin flip
}
# Calibration blend: 30% historical rates, 70% composite model
SEED_HIST_BLEND = 0.30

# ===== FIRST FOUR PLAY-IN TEAMS 2026 =====
# These 11-seeds played in (won a First Four game) before R64.
# Historical: play-in 11-seeds advance to R32 in nearly every tournament.
# Grant them a motivation/edge boost vs their 6-seed opponent in R64.
FIRST_FOUR_PLAY_IN_TEAMS_2026 = {"TX/NC State", "MO/SMU"}
# South 16: PV/Lehigh (play-in 16-seed) — no boost, different situation
# Midwest 16: UMBC/Howard — no boost


def calculate_player_rotation_value(position: str, is_starter: bool, 
                                     usage_rate: float = 0.20,
                                     is_primary_scorer: bool = False,
                                     is_floor_general: bool = False) -> float:
    starter_val, reserve_val = ROTATION_VALUES.get(position, (2.0, 0.8))
    base_value = starter_val if is_starter else reserve_val
    usage_multiplier = usage_rate / 0.20
    base_value *= (0.7 + 0.3 * usage_multiplier)
    if is_primary_scorer:
        base_value += 1.5
    if is_floor_general:
        base_value += 1.0
    return round(base_value, 1)


def calculate_decayed_sos(schedule_history: List[SOSRecord], 
                          current_date: datetime = None,
                          decay_half_life_days: int = 45) -> float:
    if not schedule_history:
        return 0.5
    if current_date is None:
        current_date = datetime.now()
    
    total_weighted_sos = 0.0
    total_weight = 0.0
    
    for game in schedule_history:
        days_ago = (current_date - game.game_date).days
        weight = 2 ** (-days_ago / decay_half_life_days)
        weight = max(weight, 0.1)
        if not game.was_home:
            weight *= 1.1
        total_weighted_sos += game.opponent_strength * weight
        total_weight += weight
    
    return total_weighted_sos / total_weight if total_weight > 0 else 0.5


# ===== HOME COURT ADVANTAGE PROFILES (2025-26 Season) =====

def create_hca_profiles() -> Dict[str, HomeCourtProfile]:
    profiles = {
        # Elite environments
        "Arizona": HomeCourtProfile(
            base_hca=3.5, altitude_bonus=0.5, crowd_intensity=0.95,
            arena_capacity=14644, historical_home_win_pct=0.88
        ),
        "Duke": HomeCourtProfile(
            base_hca=3.5, altitude_bonus=0.0, crowd_intensity=1.0,
            arena_capacity=9314, historical_home_win_pct=0.92
        ),
        "Kansas": HomeCourtProfile(
            base_hca=3.5, altitude_bonus=0.0, crowd_intensity=0.95,
            arena_capacity=16300, historical_home_win_pct=0.85
        ),
        "Michigan State": HomeCourtProfile(
            base_hca=3.5, altitude_bonus=0.0, crowd_intensity=0.90,
            arena_capacity=14759, historical_home_win_pct=0.82
        ),
        "Gonzaga": HomeCourtProfile(
            base_hca=3.5, altitude_bonus=0.0, crowd_intensity=0.85,
            arena_capacity=6000, historical_home_win_pct=0.95
        ),
        "Purdue": HomeCourtProfile(
            base_hca=3.5, altitude_bonus=0.0, crowd_intensity=0.90,
            arena_capacity=14804, historical_home_win_pct=0.85
        ),
        
        # Strong environments
        "UConn": HomeCourtProfile(
            base_hca=3.5, altitude_bonus=0.0, crowd_intensity=0.80,
            arena_capacity=10167, historical_home_win_pct=0.82
        ),
        "Michigan": HomeCourtProfile(
            base_hca=3.5, altitude_bonus=0.0, crowd_intensity=0.75,
            arena_capacity=12707, historical_home_win_pct=0.78
        ),
        "Illinois": HomeCourtProfile(
            base_hca=3.5, altitude_bonus=0.0, crowd_intensity=0.85,
            arena_capacity=15500, historical_home_win_pct=0.80
        ),
        "Houston": HomeCourtProfile(
            base_hca=3.5, altitude_bonus=0.0, crowd_intensity=0.80,
            arena_capacity=7100, historical_home_win_pct=0.88
        ),
        "Iowa State": HomeCourtProfile(
            base_hca=3.5, altitude_bonus=0.0, crowd_intensity=0.90,
            arena_capacity=14384, historical_home_win_pct=0.80
        ),
        "Nebraska": HomeCourtProfile(
            base_hca=3.5, altitude_bonus=0.0, crowd_intensity=0.75,
            arena_capacity=15000, historical_home_win_pct=0.75
        ),
        
        # Altitude bonuses
        "BYU": HomeCourtProfile(
            base_hca=3.5, altitude_bonus=0.7, crowd_intensity=0.80,
            arena_capacity=18987, historical_home_win_pct=0.78
        ),
        
        # Other environments
        "North Carolina": HomeCourtProfile(
            base_hca=3.5, altitude_bonus=0.0, crowd_intensity=0.80,
            arena_capacity=21750, historical_home_win_pct=0.75
        ),
        "Alabama": HomeCourtProfile(
            base_hca=3.5, altitude_bonus=0.0, crowd_intensity=0.70,
            arena_capacity=15383, historical_home_win_pct=0.74
        ),
        "Arkansas": HomeCourtProfile(
            base_hca=3.5, altitude_bonus=0.0, crowd_intensity=0.85,
            arena_capacity=19368, historical_home_win_pct=0.76
        ),
        "Florida": HomeCourtProfile(
            base_hca=3.5, altitude_bonus=0.0, crowd_intensity=0.75,
            arena_capacity=10133, historical_home_win_pct=0.78
        ),
        "Texas Tech": HomeCourtProfile(
            base_hca=3.5, altitude_bonus=0.3, crowd_intensity=0.80,
            arena_capacity=15098, historical_home_win_pct=0.78
        ),
        "Virginia": HomeCourtProfile(
            base_hca=3.5, altitude_bonus=0.0, crowd_intensity=0.70,
            arena_capacity=14623, historical_home_win_pct=0.78
        ),
        "Vanderbilt": HomeCourtProfile(
            base_hca=3.5, altitude_bonus=0.0, crowd_intensity=0.70,
            arena_capacity=15626, historical_home_win_pct=0.72
        ),
        "Louisville": HomeCourtProfile(
            base_hca=3.5, altitude_bonus=0.0, crowd_intensity=0.75,
            arena_capacity=22090, historical_home_win_pct=0.74
        ),
        "Saint Louis": HomeCourtProfile(
            base_hca=3.5, altitude_bonus=0.0, crowd_intensity=0.70,
            arena_capacity=10600, historical_home_win_pct=0.75
        ),
        "Saint Mary's": HomeCourtProfile(
            base_hca=3.5, altitude_bonus=0.0, crowd_intensity=0.80,
            arena_capacity=3500, historical_home_win_pct=0.88
        ),
        "Clemson": HomeCourtProfile(
            base_hca=3.5, altitude_bonus=0.0, crowd_intensity=0.65,
            arena_capacity=10000, historical_home_win_pct=0.72
        ),
        "St. John's": HomeCourtProfile(
            base_hca=3.0, altitude_bonus=0.0, crowd_intensity=0.55,
            arena_capacity=5602, historical_home_win_pct=0.70
        ),
        "Miami (OH)": HomeCourtProfile(
            base_hca=2.5, altitude_bonus=0.0, crowd_intensity=0.50,
            arena_capacity=9200, historical_home_win_pct=0.75
        ),
        "Wisconsin": HomeCourtProfile(
            base_hca=3.5, altitude_bonus=0.0, crowd_intensity=0.85,
            arena_capacity=17287, historical_home_win_pct=0.78
        ),
    }
    return profiles


# ===== PLAY STYLE PROFILES (2025-26 Season) =====

def create_play_style_profiles() -> Dict[str, Tuple[PlayStyle, float]]:
    profiles = {
        # THREE_POINT_HEAVY
        "Alabama": (PlayStyle.THREE_POINT_HEAVY, 0.46),
        "BYU": (PlayStyle.THREE_POINT_HEAVY, 0.44),
        "Gonzaga": (PlayStyle.THREE_POINT_HEAVY, 0.42),
        "Illinois": (PlayStyle.THREE_POINT_HEAVY, 0.41),
        
        # UPTEMPO_CHAOS
        "North Carolina": (PlayStyle.UPTEMPO_CHAOS, 0.40),
        "Arkansas": (PlayStyle.UPTEMPO_CHAOS, 0.39),
        "Miami (OH)": (PlayStyle.UPTEMPO_CHAOS, 0.38),
        
        # BALANCED
        "Arizona": (PlayStyle.BALANCED, 0.36),
        "Duke": (PlayStyle.BALANCED, 0.37),
        "UConn": (PlayStyle.BALANCED, 0.35),
        "Michigan": (PlayStyle.BALANCED, 0.34),
        "Michigan State": (PlayStyle.BALANCED, 0.33),
        "Kansas": (PlayStyle.BALANCED, 0.36),
        "Iowa State": (PlayStyle.BALANCED, 0.37),
        "Texas Tech": (PlayStyle.BALANCED, 0.34),
        "Florida": (PlayStyle.BALANCED, 0.35),
        "Nebraska": (PlayStyle.BALANCED, 0.32),
        "Virginia": (PlayStyle.BALANCED, 0.30),
        "Vanderbilt": (PlayStyle.BALANCED, 0.35),
        "Louisville": (PlayStyle.BALANCED, 0.36),
        "Saint Louis": (PlayStyle.BALANCED, 0.35),
        "Saint Mary's": (PlayStyle.POST_HEAVY, 0.30),
        "Clemson": (PlayStyle.BALANCED, 0.34),
        "St. John's": (PlayStyle.BALANCED, 0.36),
        
        # POST_HEAVY
        "Houston": (PlayStyle.POST_HEAVY, 0.29),
        "Purdue": (PlayStyle.POST_HEAVY, 0.31),
        "Wisconsin": (PlayStyle.POST_HEAVY, 0.28),
    }
    return profiles


def create_championship_profiles() -> Dict[str, Dict]:
    """
    Championship Profile data for each team.
    Fields:
      atr               — assist-to-turnover ratio (season average)
      sweet16           — # of HC Sweet 16 appearances (as HC or assistant)
      quality_wins      — wins vs teams in top 10% of RPI (~35 teams)
      sos_rank          — national SOS rank (lower = stronger)
      off_kenpom_rank   — adjusted offensive efficiency rank (KenPom)
      def_kenpom_rank   — adjusted defensive efficiency rank (KenPom)
    """
    return {
        # -----------------------------------------------
        # CRITERION THRESHOLDS TO PASS:
        # atr > 1.0 | sweet16 >= 1 | quality_wins >= 3
        # sos_rank <= 75 | off_kenpom_rank <= 20 | def_kenpom_rank <= 20
        # -----------------------------------------------

        "Duke": {
            "assist_to_turnover_ratio": 1.42,   # ✓ elite ball movement
            "coach_sweet16_appearances": 3,      # ✓ Scheyer was on Krzyzewski staff for multiple S16s; HC since '22, already 1
            "quality_wins_top10_rpi": 11,        # ✓ 11 wins vs AP-ranked opponents (most in D-I)
            "sos_rank": 8,                       # ✓ ACC + loaded non-conf
            "off_kenpom_rank": 1,                # ✓ #1 adjusted offense
            "def_kenpom_rank": 2,                # ✓ top-3 defense
            "three_point_pct_differential": +0.062,  # ✓
            "nba_draft_picks_projected": 3,      # ✓ Boozer (lottery), Knueppel, Brown
        },
        "Arizona": {
            "assist_to_turnover_ratio": 1.28,    # ✓
            "coach_sweet16_appearances": 4,      # ✓ Tommy Lloyd: back-to-back Sweet 16s
            "quality_wins_top10_rpi": 7,         # ✓
            "sos_rank": 5,                       # ✓ Big 12 + loaded schedule
            "off_kenpom_rank": 4,                # ✓
            "def_kenpom_rank": 12,               # ✓
            "three_point_pct_differential": +0.031,  # ✓
            "nba_draft_picks_projected": 2,      # ✓ Peat (top-5), Harlond Beverly
        },
        "Michigan": {
            "assist_to_turnover_ratio": 1.35,    # ✓
            "coach_sweet16_appearances": 2,      # ✓ Dusty May: 2023 S16 w/ FAU
            "quality_wins_top10_rpi": 8,         # ✓ 19-1 Big Ten
            "sos_rank": 12,                      # ✓
            "off_kenpom_rank": 2,                # ✓
            "def_kenpom_rank": 3,                # ✓
            "three_point_pct_differential": +0.028,  # ✓
            "nba_draft_picks_projected": 2,      # ✓ Wolf (1st rd), Goldin (2nd rd)
        },
        "Florida": {
            "assist_to_turnover_ratio": 1.22,    # ✓
            "coach_sweet16_appearances": 5,      # ✓ Todd Golden prior staff; Knox served multiple S16s
            "quality_wins_top10_rpi": 6,         # ✓ 11-game win streak; SEC co-champs
            "sos_rank": 6,                       # ✓ SEC + non-conf
            "off_kenpom_rank": 6,                # ✓
            "def_kenpom_rank": 8,                # ✓
            "three_point_pct_differential": -0.018,  # ✗ RED FLAG — Gill Alexander filter
            "nba_draft_picks_projected": 2,      # ✓ Clayton Jr., Chinyelu
        },
        "Houston": {
            "assist_to_turnover_ratio": 1.18,    # ✓
            "coach_sweet16_appearances": 6,      # ✓ Kelvin Sampson: multiple S16s
            "quality_wins_top10_rpi": 7,         # ✓
            "sos_rank": 4,                       # ✓ Big 12
            "off_kenpom_rank": 14,               # ✓
            "def_kenpom_rank": 1,                # ✓ #1 defense
            "three_point_pct_differential": +0.019,  # ✓
            "nba_draft_picks_projected": 1,      # ✓ Sharp (2nd rd projected)
        },
        "UConn": {
            "assist_to_turnover_ratio": 1.31,    # ✓
            "coach_sweet16_appearances": 8,      # ✓ Dan Hurley: 2023, 2024, 2025 champ runs
            "quality_wins_top10_rpi": 5,         # ✓
            "sos_rank": 22,                      # ✓ Big East
            "off_kenpom_rank": 10,               # ✓
            "def_kenpom_rank": 15,               # ✓
            "three_point_pct_differential": +0.041,  # ✓
            "nba_draft_picks_projected": 1,      # ✓ Karaban (2nd rd)
        },
        "Iowa State": {
            "assist_to_turnover_ratio": 1.14,    # ✓
            "coach_sweet16_appearances": 3,      # ✓ T.J. Otzelberger: 2022 S16
            "quality_wins_top10_rpi": 5,         # ✓
            "sos_rank": 9,                       # ✓ Big 12
            "off_kenpom_rank": 11,               # ✓
            "def_kenpom_rank": 7,                # ✓
            "three_point_pct_differential": +0.022,  # ✓
            "nba_draft_picks_projected": 1,      # ✓ Gilbert (possible 2nd rd)
        },
        "Michigan State": {
            "assist_to_turnover_ratio": 1.19,    # ✓
            "coach_sweet16_appearances": 10,     # ✓ Tom Izzo: legendary S16 record
            "quality_wins_top10_rpi": 4,         # ✓
            "sos_rank": 18,                      # ✓ Big Ten
            "off_kenpom_rank": 18,               # ✓
            "def_kenpom_rank": 16,               # ✓
            "three_point_pct_differential": +0.015,  # ✓
            "nba_draft_picks_projected": 1,      # ✓ Akins (fringe 2nd rd)
        },
        "Illinois": {
            "assist_to_turnover_ratio": 1.08,    # ✓
            "coach_sweet16_appearances": 2,      # ✓ Brad Underwood: 2021 S16
            "quality_wins_top10_rpi": 5,         # ✓ 8 road wins in Big Ten
            "sos_rank": 14,                      # ✓ Big Ten
            "off_kenpom_rank": 8,                # ✓
            "def_kenpom_rank": 13,               # ✓
            "three_point_pct_differential": +0.033,  # ✓
            "nba_draft_picks_projected": 1,      # ✓ Wagler (2nd rd watch list)
        },
        "Virginia": {
            "assist_to_turnover_ratio": 1.38,    # ✓ pack-line = low TO
            "coach_sweet16_appearances": 5,      # ✓ Tony Bennett: 2019 champion
            "quality_wins_top10_rpi": 4,         # ✓
            "sos_rank": 38,                      # ✓
            "off_kenpom_rank": 19,               # ✓ (barely)
            "def_kenpom_rank": 4,                # ✓
            "three_point_pct_differential": +0.044,  # ✓
            "nba_draft_picks_projected": 1,      # ✓ Murray (2nd rd watch)
        },
        "Nebraska": {
            "assist_to_turnover_ratio": 1.12,    # ✓
            "coach_sweet16_appearances": 1,      # ✓ Fred Hoiberg: one S16 (Iowa State)
            "quality_wins_top10_rpi": 4,         # ✓ top-2 Big Ten finish
            "sos_rank": 42,                      # ✓
            "off_kenpom_rank": 16,               # ✓
            "def_kenpom_rank": 22,               # ✗ just outside top 20
            "three_point_pct_differential": +0.011,  # ✓
            "nba_draft_picks_projected": 1,      # ✓ Williams (2nd rd fringe)
        },
        "Gonzaga": {
            "assist_to_turnover_ratio": 1.45,    # ✓ highest in nation
            "coach_sweet16_appearances": 12,     # ✓ Mark Few: perennial S16+
            "quality_wins_top10_rpi": 3,         # ✓ (barely — weak WCC SOS)
            "sos_rank": 95,                      # ✗ WCC schedule hurts
            "off_kenpom_rank": 5,                # ✓
            "def_kenpom_rank": 17,               # ✓
            "three_point_pct_differential": +0.052,  # ✓
            "nba_draft_picks_projected": 1,      # ✓ Ike (2nd rd)
        },
        "Purdue": {
            "assist_to_turnover_ratio": 1.02,    # ✓ (barely)
            "coach_sweet16_appearances": 4,      # ✓ Matt Painter: multiple S16s
            "quality_wins_top10_rpi": 4,         # ✓
            "sos_rank": 11,                      # ✓ Big Ten
            "off_kenpom_rank": 7,                # ✓
            "def_kenpom_rank": 28,               # ✗
            "three_point_pct_differential": +0.027,  # ✓
            "nba_draft_picks_projected": 2,      # ✓ Smith (1st rd), Loyer (2nd rd)
        },
        "Texas Tech": {
            "assist_to_turnover_ratio": 0.95,    # ✗ turnover-prone without Toppin
            "coach_sweet16_appearances": 2,      # ✓ Grant McCasland had S16 at NT
            "quality_wins_top10_rpi": 3,         # ✓ (barely)
            "sos_rank": 16,                      # ✓ Big 12
            "off_kenpom_rank": 22,               # ✗ just outside
            "def_kenpom_rank": 18,               # ✓
            "three_point_pct_differential": +0.008,  # ✓
            "nba_draft_picks_projected": 1,      # ✓ Williams (2nd rd watch)
        },
        "Alabama": {
            "assist_to_turnover_ratio": 0.88,    # ✗ high-pace = TOs
            "coach_sweet16_appearances": 3,      # ✓ Nate Oats: 2021 S16
            "quality_wins_top10_rpi": 3,         # ✓
            "sos_rank": 13,                      # ✓ SEC
            "off_kenpom_rank": 13,               # ✓
            "def_kenpom_rank": 35,               # ✗ defensive liability
            "three_point_pct_differential": -0.022,  # ✗ RED FLAG — Gill Alexander filter
            "nba_draft_picks_projected": 1,      # ✓ Sears (2nd rd fringe) — now Holloway ARRESTED
        },
        "Arkansas": {
            "assist_to_turnover_ratio": 1.05,    # ✓
            "coach_sweet16_appearances": 2,      # ✓ John Calipari: legendary S16 record
            "quality_wins_top10_rpi": 3,         # ✓
            "sos_rank": 17,                      # ✓ SEC
            "off_kenpom_rank": 21,               # ✗ just outside
            "def_kenpom_rank": 25,               # ✗
            "three_point_pct_differential": +0.014,  # ✓
            "nba_draft_picks_projected": 1,      # ✓ Acuff Jr. (2nd rd watch — Fr)
        },
        "St. John's": {
            "assist_to_turnover_ratio": 1.10,    # ✓
            "coach_sweet16_appearances": 3,      # ✓ Rick Pitino: multiple S16s
            "quality_wins_top10_rpi": 3,         # ✓
            "sos_rank": 48,                      # ✓ Big East
            "off_kenpom_rank": 23,               # ✗
            "def_kenpom_rank": 30,               # ✗
            "three_point_pct_differential": +0.006,  # ✓
            "nba_draft_picks_projected": 1,      # ✓ Smith (2nd rd fringe)
        },
        "North Carolina": {
            "assist_to_turnover_ratio": 1.15,    # ✓
            "coach_sweet16_appearances": 2,      # ✓ Hubert Davis: 2022 finalist
            "quality_wins_top10_rpi": 4,         # ✓
            "sos_rank": 31,                      # ✓
            "off_kenpom_rank": 17,               # ✓
            "def_kenpom_rank": 42,               # ✗ defense is liability
            "three_point_pct_differential": +0.025,  # ✓
            "nba_draft_picks_projected": 1,      # ✓ Trimble (2nd rd watch)
        },
        "Miami (OH)": {
            "assist_to_turnover_ratio": 1.08,    # ✓
            "coach_sweet16_appearances": 0,      # ✗ Travis Steele: no S16 as HC
            "quality_wins_top10_rpi": 0,         # ✗ MAC schedule
            "sos_rank": 320,                     # ✗ historically weak SOS
            "off_kenpom_rank": 75,               # ✗
            "def_kenpom_rank": 68,               # ✗
            "three_point_pct_differential": +0.038,  # ✓
            "nba_draft_picks_projected": 0,      # ✗ no projected picks
        },
        "Saint Mary's": {
            "assist_to_turnover_ratio": 1.32,    # ✓
            "coach_sweet16_appearances": 2,      # ✓ Randy Bennett: 2010 S16
            "quality_wins_top10_rpi": 2,         # ✗ WCC schedule
            "sos_rank": 110,                     # ✗
            "off_kenpom_rank": 24,               # ✗
            "def_kenpom_rank": 31,               # ✗
            "three_point_pct_differential": +0.048,  # ✓
            "nba_draft_picks_projected": 0,      # ✗ no projected picks
        },
        "Vanderbilt": {
            "assist_to_turnover_ratio": 1.12,    # ✓
            "coach_sweet16_appearances": 1,      # ✓ Jerry Stackhouse: 2024 S16
            "quality_wins_top10_rpi": 3,         # ✓
            "sos_rank": 28,                      # ✓ SEC
            "off_kenpom_rank": 20,               # ✓ (barely)
            "def_kenpom_rank": 21,               # ✗ just outside
            "three_point_pct_differential": +0.012,  # ✓
            "nba_draft_picks_projected": 1,      # ✓ Edwards (2nd rd fringe)
        },
        "Wisconsin": {
            "assist_to_turnover_ratio": 1.22,    # ✓
            "coach_sweet16_appearances": 3,      # ✓ Greg Gard: 2015, 2016 Final Fours on staff
            "quality_wins_top10_rpi": 3,         # ✓ 3 road wins vs ranked
            "sos_rank": 26,                      # ✓ Big Ten
            "off_kenpom_rank": 25,               # ✗
            "def_kenpom_rank": 19,               # ✓
            "three_point_pct_differential": +0.036,  # ✓
            "nba_draft_picks_projected": 1,      # ✓ Tonje (2nd rd fringe)
        },
        "Louisville": {
            "assist_to_turnover_ratio": 1.08,    # ✓
            "coach_sweet16_appearances": 4,      # ✓ Pat Kelsey: no S16 as HC but staff
            "quality_wins_top10_rpi": 3,         # ✓
            "sos_rank": 35,                      # ✓
            "off_kenpom_rank": 16,               # ✓
            "def_kenpom_rank": 24,               # ✗
            "three_point_pct_differential": +0.009,  # ✓
            "nba_draft_picks_projected": 1,      # ✓ Brown Jr. (Fr, 2nd rd watch)
        },
        "Kansas": {
            "assist_to_turnover_ratio": 1.20,    # ✓
            "coach_sweet16_appearances": 10,     # ✓ Bill Self: multiple S16s
            "quality_wins_top10_rpi": 4,         # ✓
            "sos_rank": 7,                       # ✓ Big 12
            "off_kenpom_rank": 15,               # ✓
            "def_kenpom_rank": 27,               # ✗
            "three_point_pct_differential": +0.017,  # ✓
            "nba_draft_picks_projected": 2,      # ✓ Bidunga (Fr, lottery watch), Hunter
        },
        "BYU": {
            "assist_to_turnover_ratio": 0.98,    # ✗ without Saunders, ATR drops
            "coach_sweet16_appearances": 1,      # ✓ Kevin Young: no S16 as HC
            "quality_wins_top10_rpi": 3,         # ✓ Big 12
            "sos_rank": 21,                      # ✓ Big 12
            "off_kenpom_rank": 20,               # ✓ (barely)
            "def_kenpom_rank": 32,               # ✗
            "three_point_pct_differential": -0.009,  # ✗ RED FLAG — Gill Alexander filter
            "nba_draft_picks_projected": 1,      # ✓ Dybantsa (Fr, potential top-5 — major loss w/o Saunders)
        },
        "Tennessee": {
            "assist_to_turnover_ratio": 1.05,    # ✓
            "coach_sweet16_appearances": 3,      # ✓ Rick Barnes: multiple S16s
            "quality_wins_top10_rpi": 2,         # ✗ 3-loss skid hurts
            "sos_rank": 19,                      # ✓ SEC
            "off_kenpom_rank": 28,               # ✗
            "def_kenpom_rank": 10,               # ✓
            "three_point_pct_differential": +0.031,  # ✓
            "nba_draft_picks_projected": 1,      # ✓ Mashack (2nd rd fringe)
        },
        "Saint Louis": {
            "assist_to_turnover_ratio": 1.18,    # ✓
            "coach_sweet16_appearances": 0,      # ✗ Josh Schertz: no S16 as HC
            "quality_wins_top10_rpi": 1,         # ✗ A-10 schedule
            "sos_rank": 185,                     # ✗
            "off_kenpom_rank": 38,               # ✗
            "def_kenpom_rank": 45,               # ✗
            "three_point_pct_differential": +0.021,  # ✓
            "nba_draft_picks_projected": 0,      # ✗ A-10 SOS limits exposure
        },
        "NC State": {
            "assist_to_turnover_ratio": 1.05,    # ✓
            "coach_sweet16_appearances": 1,      # ✓ Kevin Keatts: 2024 Final Four (!)
            "quality_wins_top10_rpi": 2,         # ✗
            "sos_rank": 44,                      # ✓
            "off_kenpom_rank": 30,               # ✗
            "def_kenpom_rank": 33,               # ✗
            "three_point_pct_differential": +0.003,  # ✓
            "nba_draft_picks_projected": 0,      # ✗ 20-win program year
        },
        "Kentucky": {
            "assist_to_turnover_ratio": 1.02,    # ✓
            "coach_sweet16_appearances": 8,      # ✓ Mark Pope: prior staff exp
            "quality_wins_top10_rpi": 2,         # ✗ 18-13 record
            "sos_rank": 15,                      # ✓ SEC
            "off_kenpom_rank": 24,               # ✗
            "def_kenpom_rank": 38,               # ✗
            "three_point_pct_differential": -0.004,  # ✗ RED FLAG — Gill Alexander filter
            "nba_draft_picks_projected": 1,      # ✓ Oweh (2nd rd fringe)
        },
    }


def initialize_top_teams() -> List[Team]:
    """
    Initialize top 25 teams with CURRENT 2025-26 season data
    Data through Week 16 (February 16, 2026)
    """
    
    hca_profiles = create_hca_profiles()
    play_styles = create_play_style_profiles()
    champ_profiles = create_championship_profiles()
    
    # AP Top 25 + key bubble teams — March 12, 2026 (conference tournament week)
    # Records reflect end of regular season / conference tournament results where applicable
    # Rankings: Final pre-tournament AP Top 25 (March 9, 2026)
    teams_data = [
        # Rank 1-5
        {"name": "Duke", "rank": 1, "record": "29-2", "wins": 29, "losses": 2,
         "conference": "ACC", "kenpom_rank": 1, "net_rank": 1,
         "off_efficiency": 125.8, "def_efficiency": 89.2, "tempo": 73.5,
         "program_history_score": 10.0, "coaching_score": 9.5, "motivation_factor": 1.20,
         "tournament_experience": 5, "recent_form": 9.8, "raw_schedule_strength": 0.92,
         "star_player": "Cameron Boozer (Fr, ACC POY 22.7/10.2/4.1)"},
        # NOTE: Duke missing PG Caleb Foster (fractured foot, surgery 3/9, season likely over)
        # and C Patrick Ngongba II (foot soreness, out ACC tourney, may return NCAA tourney)
        # Rotation now 7-man; Maliq Brown moves into starting lineup

        {"name": "Arizona", "rank": 2, "record": "29-2", "wins": 29, "losses": 2,
         "conference": "Big 12", "kenpom_rank": 3, "net_rank": 4,
         "off_efficiency": 124.0, "def_efficiency": 91.5, "tempo": 72.5,
         "program_history_score": 9.0, "coaching_score": 9.5, "motivation_factor": 1.15,
         "tournament_experience": 5, "recent_form": 9.0, "raw_schedule_strength": 0.94,
         "star_player": "Koa Peat (Fr)"},
        # Arizona has the most wins in program history (29)

        {"name": "Michigan", "rank": 3, "record": "29-2", "wins": 29, "losses": 2,
         "conference": "Big Ten", "kenpom_rank": 2, "net_rank": 2,
         "off_efficiency": 126.2, "def_efficiency": 89.0, "tempo": 71.8,
         "program_history_score": 8.5, "coaching_score": 9.0, "motivation_factor": 1.18,
         "tournament_experience": 4, "recent_form": 9.5, "raw_schedule_strength": 0.93,
         "star_player": "Vladislav Goldin"},
        # Michigan 19-1 in Big Ten — most conference wins in a season in Big Ten history
        # LJ Carson (SG/6th man) out for season with ACL — reduces bench depth

        {"name": "Florida", "rank": 4, "record": "25-6", "wins": 25, "losses": 6,
         "conference": "SEC", "kenpom_rank": 5, "net_rank": 6,
         "off_efficiency": 120.8, "def_efficiency": 93.8, "tempo": 70.0,
         "program_history_score": 8.5, "coaching_score": 9.5, "motivation_factor": 1.18,
         "tournament_experience": 5, "recent_form": 9.5, "raw_schedule_strength": 0.94,
         "star_player": "Rueben Chinyelu"},
        # Florida won 11 straight, co-SEC regular season champs; potential 1-seed

        {"name": "Houston", "rank": 5, "record": "27-4", "wins": 27, "losses": 4,
         "conference": "Big 12", "kenpom_rank": 4, "net_rank": 3,
         "off_efficiency": 117.5, "def_efficiency": 87.5, "tempo": 66.5,
         "program_history_score": 7.5, "coaching_score": 10.0, "motivation_factor": 1.15,
         "tournament_experience": 5, "recent_form": 8.5, "raw_schedule_strength": 0.94,
         "star_player": "Emanuel Sharp"},

        {"name": "UConn", "rank": 6, "record": "26-4", "wins": 26, "losses": 4,
         "conference": "Big East", "kenpom_rank": 9, "net_rank": 9,
         "off_efficiency": 121.0, "def_efficiency": 93.0, "tempo": 70.5,
         "program_history_score": 10.0, "coaching_score": 10.0, "motivation_factor": 1.12,
         "tournament_experience": 5, "recent_form": 8.0, "raw_schedule_strength": 0.88,
         "star_player": "Alex Karaban (Sr)"},
        # UConn dropped from #5 after road loss at Marquette to close regular season

        # Rank 7-10
        {"name": "Iowa State", "rank": 7, "record": "24-5", "wins": 24, "losses": 5,
         "conference": "Big 12", "kenpom_rank": 7, "net_rank": 8,
         "off_efficiency": 120.0, "def_efficiency": 92.0, "tempo": 70.8,
         "program_history_score": 6.5, "coaching_score": 9.0, "motivation_factor": 1.12,
         "tournament_experience": 3, "recent_form": 8.5, "raw_schedule_strength": 0.93,
         "star_player": "Keshon Gilbert"},

        {"name": "Michigan State", "rank": 8, "record": "22-7", "wins": 22, "losses": 7,
         "conference": "Big Ten", "kenpom_rank": 15, "net_rank": 13,
         "off_efficiency": 118.5, "def_efficiency": 94.0, "tempo": 70.2,
         "program_history_score": 9.5, "coaching_score": 10.0, "motivation_factor": 1.12,
         "tournament_experience": 5, "recent_form": 8.0, "raw_schedule_strength": 0.91,
         "star_player": "Jaden Akins"},

        {"name": "Illinois", "rank": 9, "record": "23-7", "wins": 23, "losses": 7,
         "conference": "Big Ten", "kenpom_rank": 6, "net_rank": 7,
         "off_efficiency": 121.0, "def_efficiency": 94.0, "tempo": 72.2,
         "program_history_score": 7.5, "coaching_score": 8.5, "motivation_factor": 1.12,
         "tournament_experience": 4, "recent_form": 9.0, "raw_schedule_strength": 0.91,
         "star_player": "Keaton Wagler (Fr)"},
        # Illinois tied program record with 8 road wins in Big Ten

        {"name": "Virginia", "rank": 10, "record": "25-4", "wins": 25, "losses": 4,
         "conference": "ACC", "kenpom_rank": 12, "net_rank": 14,
         "off_efficiency": 116.5, "def_efficiency": 90.5, "tempo": 62.5,
         "program_history_score": 7.5, "coaching_score": 9.0, "motivation_factor": 1.12,
         "tournament_experience": 4, "recent_form": 8.5, "raw_schedule_strength": 0.86,
         "star_player": "Taine Murray"},
        # Virginia rose 3 spots in final poll; 22 games with 75+ pts (most since 1988-89)
        
        # Rank 11-15
        {"name": "Nebraska", "rank": 11, "record": "24-5", "wins": 24, "losses": 5,
         "conference": "Big Ten", "kenpom_rank": 11, "net_rank": 11,
         "off_efficiency": 118.5, "def_efficiency": 93.0, "tempo": 68.8,
         "program_history_score": 4.0, "coaching_score": 8.0, "motivation_factor": 1.22,
         "tournament_experience": 1, "recent_form": 8.5, "raw_schedule_strength": 0.86,
         "star_player": "Brice Williams"},
        # Nebraska finishes top-2 in Big Ten for first time since 1992-93

        {"name": "Gonzaga", "rank": 12, "record": "30-3", "wins": 30, "losses": 3,
         "conference": "WCC", "kenpom_rank": 10, "net_rank": 10,
         "off_efficiency": 122.8, "def_efficiency": 93.8, "tempo": 74.5,
         "program_history_score": 8.5, "coaching_score": 9.5, "motivation_factor": 1.18,
         "tournament_experience": 5, "recent_form": 9.5, "raw_schedule_strength": 0.78,
         "star_player": "Graham Ike (WCC Tournament MOP)"},
        # WCC CHAMPION — beat Santa Clara 79-68 (March 10); final WCC tourney appearance before Pac-12 move

        {"name": "Purdue", "rank": 13, "record": "23-6", "wins": 23, "losses": 6,
         "conference": "Big Ten", "kenpom_rank": 5, "net_rank": 5,
         "off_efficiency": 122.0, "def_efficiency": 94.5, "tempo": 69.0,
         "program_history_score": 8.0, "coaching_score": 9.0, "motivation_factor": 1.08,
         "tournament_experience": 5, "recent_form": 7.5, "raw_schedule_strength": 0.92,
         "star_player": "Braden Smith"},
        # Purdue dropped 3 spots in final poll

        {"name": "Texas Tech", "rank": 14, "record": "21-9", "wins": 21, "losses": 9,
         "conference": "Big 12", "kenpom_rank": 15, "net_rank": 15,
         "off_efficiency": 117.5, "def_efficiency": 93.5, "tempo": 69.8,
         "program_history_score": 6.5, "coaching_score": 8.0, "motivation_factor": 1.08,
         "tournament_experience": 3, "recent_form": 6.5, "raw_schedule_strength": 0.91,
         "star_player": "Darrion Williams"},
        # JT Toppin OUT for season — ACL; significantly weakens frontcourt
        # Fell 6 spots in final poll — biggest drop in the poll

        {"name": "Alabama", "rank": 15, "record": "20-9", "wins": 20, "losses": 9,
         "conference": "SEC", "kenpom_rank": 16, "net_rank": 16,
         "off_efficiency": 119.8, "def_efficiency": 96.5, "tempo": 74.5,
         "program_history_score": 7.5, "coaching_score": 8.5, "motivation_factor": 1.08,
         "tournament_experience": 4, "recent_form": 7.5, "raw_schedule_strength": 0.90,
         "star_player": "Mark Sears"},
        # Rose despite loss to Georgia — voters valued schedule strength

        # Rank 16-20
        {"name": "Arkansas", "rank": 17, "record": "21-9", "wins": 21, "losses": 9,
         "conference": "SEC", "kenpom_rank": 18, "net_rank": 18,
         "off_efficiency": 118.8, "def_efficiency": 95.0, "tempo": 74.0,
         "program_history_score": 7.0, "coaching_score": 8.5, "motivation_factor": 1.15,
         "tournament_experience": 3, "recent_form": 8.5, "raw_schedule_strength": 0.89,
         "star_player": "Darius Acuff Jr. (Fr)"},
        # Rose 3 spots in final poll

        {"name": "St. John's", "rank": 18, "record": "23-7", "wins": 23, "losses": 7,
         "conference": "Big East", "kenpom_rank": 20, "net_rank": 22,
         "off_efficiency": 117.2, "def_efficiency": 96.0, "tempo": 70.5,
         "program_history_score": 6.5, "coaching_score": 9.0, "motivation_factor": 1.15,
         "tournament_experience": 2, "recent_form": 9.5, "raw_schedule_strength": 0.85,
         "star_player": "Deivon Smith"},
        # Biggest mover in final poll — rose 5 spots

        {"name": "North Carolina", "rank": 19, "record": "22-9", "wins": 22, "losses": 9,
         "conference": "ACC", "kenpom_rank": 18, "net_rank": 20,
         "off_efficiency": 120.5, "def_efficiency": 97.0, "tempo": 76.2,
         "program_history_score": 10.0, "coaching_score": 7.5, "motivation_factor": 1.02,
         "tournament_experience": 5, "recent_form": 7.0, "raw_schedule_strength": 0.87,
         "star_player": "Seth Trimble"},

        {"name": "Miami (OH)", "rank": 20, "record": "31-1", "wins": 31, "losses": 1,
         "conference": "MAC", "kenpom_rank": 55, "net_rank": 55,
         "off_efficiency": 114.5, "def_efficiency": 97.5, "tempo": 70.5,
         "program_history_score": 3.5, "coaching_score": 7.0, "motivation_factor": 1.15,
         "tournament_experience": 0, "recent_form": 6.5, "raw_schedule_strength": 0.48,
         "star_player": "Justin Kirby"},
        # ELIMINATED in MAC quarterfinals by UMass 87-83 — 31-0 historic run ended
        # Third D-I team ever to enter conf tournament undefeated; NET ranking (55) hurts seeding

        {"name": "Saint Mary's", "rank": 21, "record": "26-7", "wins": 26, "losses": 7,
         "conference": "WCC", "kenpom_rank": 19, "net_rank": 19,
         "off_efficiency": 118.0, "def_efficiency": 95.0, "tempo": 68.5,
         "program_history_score": 6.0, "coaching_score": 8.5, "motivation_factor": 1.12,
         "tournament_experience": 3, "recent_form": 7.5, "raw_schedule_strength": 0.79,
         "star_player": "Augustas Marciulionis"},
        # 17-0 at home this season; lost WCC semis to Santa Clara before Gonzaga won title

        {"name": "Vanderbilt", "rank": 22, "record": "22-7", "wins": 22, "losses": 7,
         "conference": "SEC", "kenpom_rank": 13, "net_rank": 12,
         "off_efficiency": 118.2, "def_efficiency": 94.0, "tempo": 71.5,
         "program_history_score": 5.0, "coaching_score": 8.0, "motivation_factor": 1.18,
         "tournament_experience": 2, "recent_form": 8.5, "raw_schedule_strength": 0.87,
         "star_player": "Jason Edwards"},
        # 8-4 on road — best road record since 2011-12

        {"name": "Wisconsin", "rank": 23, "record": "20-9", "wins": 20, "losses": 9,
         "conference": "Big Ten", "kenpom_rank": 17, "net_rank": 17,
         "off_efficiency": 116.5, "def_efficiency": 94.0, "tempo": 65.5,
         "program_history_score": 7.0, "coaching_score": 8.0, "motivation_factor": 1.10,
         "tournament_experience": 4, "recent_form": 8.5, "raw_schedule_strength": 0.89,
         "star_player": "John Tonje"},
        # Re-entered poll; won 3 straight road games vs ranked opponents — program first

        {"name": "Louisville", "rank": 24, "record": "21-9", "wins": 21, "losses": 9,
         "conference": "ACC", "kenpom_rank": 14, "net_rank": 13,
         "off_efficiency": 118.5, "def_efficiency": 94.5, "tempo": 71.2,
         "program_history_score": 8.0, "coaching_score": 8.5, "motivation_factor": 1.12,
         "tournament_experience": 3, "recent_form": 7.5, "raw_schedule_strength": 0.85,
         "star_player": "Mikel Brown Jr. (Fr)"},
        # Re-entered poll; first road win vs ranked opponent since Jan. 2020

        {"name": "Kansas", "rank": 25, "record": "20-9", "wins": 20, "losses": 9,
         "conference": "Big 12", "kenpom_rank": 14, "net_rank": 16,
         "off_efficiency": 119.5, "def_efficiency": 95.0, "tempo": 71.8,
         "program_history_score": 10.0, "coaching_score": 9.5, "motivation_factor": 1.10,
         "tournament_experience": 5, "recent_form": 7.5, "raw_schedule_strength": 0.94,
         "star_player": "Flory Bidunga (Fr)"},

        # Bubble teams receiving significant votes / conference tournament contenders
        {"name": "BYU", "rank": 26, "record": "21-9", "wins": 21, "losses": 9,
         "conference": "Big 12", "kenpom_rank": 19, "net_rank": 19,
         "off_efficiency": 118.0, "def_efficiency": 95.0, "tempo": 72.5,
         "program_history_score": 6.0, "coaching_score": 8.0, "motivation_factor": 1.12,
         "tournament_experience": 2, "recent_form": 7.0, "raw_schedule_strength": 0.89,
         "star_player": "AJ Dybantsa (Fr)"},
        # Richie Saunders (SF) OUT for season — ACL (already applied); Dybantsa carrying load

        {"name": "Tennessee", "rank": 27, "record": "18-13", "wins": 18, "losses": 13,
         "conference": "SEC", "kenpom_rank": 23, "net_rank": 23,
         "off_efficiency": 117.0, "def_efficiency": 94.5, "tempo": 68.0,
         "program_history_score": 7.0, "coaching_score": 8.5, "motivation_factor": 1.05,
         "tournament_experience": 4, "recent_form": 6.0, "raw_schedule_strength": 0.89,
         "star_player": "Jahmai Mashack"},
        # Dropped out of poll — lost 3 of last 4; on bubble

        {"name": "Saint Louis", "rank": 28, "record": "27-4", "wins": 27, "losses": 4,
         "conference": "A-10", "kenpom_rank": 22, "net_rank": 23,
         "off_efficiency": 117.0, "def_efficiency": 95.8, "tempo": 70.5,
         "program_history_score": 5.5, "coaching_score": 7.5, "motivation_factor": 1.18,
         "tournament_experience": 2, "recent_form": 8.5, "raw_schedule_strength": 0.68,
         "star_player": "Gibson Jimerson"},
        # Dropped out of top 25; 18-0 at home — best in D-I; at-large bubble bid

        {"name": "NC State", "rank": 29, "record": "20-9", "wins": 20, "losses": 9,
         "conference": "ACC", "kenpom_rank": 25, "net_rank": 25,
         "off_efficiency": 117.5, "def_efficiency": 96.0, "tempo": 71.5,
         "program_history_score": 7.0, "coaching_score": 7.5, "motivation_factor": 1.05,
         "tournament_experience": 3, "recent_form": 7.0, "raw_schedule_strength": 0.85,
         "star_player": "Quadir Copeland"},

        {"name": "Kentucky", "rank": 30, "record": "18-13", "wins": 18, "losses": 13,
         "conference": "SEC", "kenpom_rank": 21, "net_rank": 21,
         "off_efficiency": 118.5, "def_efficiency": 96.5, "tempo": 72.0,
         "program_history_score": 10.0, "coaching_score": 7.5, "motivation_factor": 1.02,
         "tournament_experience": 5, "recent_form": 5.5, "raw_schedule_strength": 0.91,
         "star_player": "Otega Oweh"},
    ]
    
    teams = []
    for data in teams_data:
        team_name = data["name"]
        hca_profile = hca_profiles.get(team_name, HomeCourtProfile())
        style_info = play_styles.get(team_name, (PlayStyle.BALANCED, 0.35))
        play_style, three_pt_rate = style_info
        
        star = data.pop("star_player", "")
        cp = champ_profiles.get(team_name, {})
        
        team = Team(
            **data,
            home_court_profile=hca_profile,
            play_style=play_style,
            three_point_rate=three_pt_rate,
            star_player=star,
            assist_to_turnover_ratio=cp.get("assist_to_turnover_ratio", 1.0),
            coach_sweet16_appearances=cp.get("coach_sweet16_appearances", 0),
            quality_wins_top10_rpi=cp.get("quality_wins_top10_rpi", 0),
            sos_rank=cp.get("sos_rank", 200),
            off_kenpom_rank=cp.get("off_kenpom_rank", 50),
            def_kenpom_rank=cp.get("def_kenpom_rank", 50),
            three_point_pct_differential=cp.get("three_point_pct_differential", 0.0),
            nba_draft_picks_projected=cp.get("nba_draft_picks_projected", 0),
        )
        teams.append(team)
    
    for team in teams:
        team.pythagorean_win_pct = calculate_pythagorean_win_pct(
            team.off_efficiency, team.def_efficiency
        )
        team.four_factors_score = calculate_four_factors(team)

    # ── Assign 2026 NCAA Tournament seeds and regions ────────────────────────
    # Source: CBS Sports Official Bracket, Selection Sunday March 15, 2026
    SEED_MAP = {
        # East
        "Duke":          (1,  "East"),
        "UConn":         (2,  "East"),
        "Michigan State":(3,  "East"),
        "Kansas":        (4,  "East"),
        "St. John's":    (5,  "East"),
        "Louisville":    (6,  "East"),
        # South
        "Florida":       (1,  "South"),
        "Houston":       (2,  "South"),
        "Illinois":      (3,  "South"),
        "Nebraska":      (4,  "South"),
        "Vanderbilt":    (5,  "South"),
        "North Carolina":(6,  "South"),
        "Saint Mary's":  (7,  "South"),
        # West
        "Arizona":       (1,  "West"),
        "Purdue":        (2,  "West"),
        "Gonzaga":       (3,  "West"),
        "Arkansas":      (4,  "West"),
        "Wisconsin":     (5,  "West"),
        "BYU":           (6,  "West"),
        # Midwest
        "Michigan":      (1,  "Midwest"),
        "Iowa State":    (2,  "Midwest"),
        "Virginia":      (3,  "Midwest"),
        "Alabama":       (4,  "Midwest"),
        "Texas Tech":    (5,  "Midwest"),
        "Tennessee":     (6,  "Midwest"),
        "Kentucky":      (7,  "Midwest"),
        "Saint Louis":   (9,  "Midwest"),
    }
    for team in teams:
        if team.name in SEED_MAP:
            team.tournament_seed, team.tournament_region = SEED_MAP[team.name]
        
    return teams


def calculate_pythagorean_win_pct(off_eff: float, def_eff: float, 
                                   exponent: float = 11.5) -> float:
    return off_eff ** exponent / (off_eff ** exponent + def_eff ** exponent)


def calculate_four_factors(team: Team) -> float:
    base_score = (team.off_efficiency - team.def_efficiency) / 2.0
    return base_score


class ChampionshipProfileScorer:
    """
    Scores teams 0-7 based on Gill Alexander's (VSiN) championship checklist.

    Criteria (source: VSiN "A Numbers Game", published Feb 28 2026):
      1. Assists > turnovers (ATR > 1.0)              — 35/35 champs  (100%)
      2. HC has Sweet 16 experience                    — 32/35 champs  (91%)
      3. 3+ wins vs top-10% RPI teams                 — 29/30 champs  (97%)
      4. Top 75 SOS (national rank)                   — 30/30 champs  (100%)
      5. Top 20 adjusted offensive efficiency (KenPom) — 22/23 champs  (96%)
      6. Top 20 adjusted defensive efficiency (KenPom) — 22/23 champs  (96%)
      7. Positive 3-point % differential               — ~37/38 champs (97%)
         (last champion with negative 3P% diff: 1988 Kansas Jayhawks)

    Each criterion met = 1 point (max 7). Score feeds a win-probability
    multiplier in simulate_game(), making historically-profiled teams
    meaningfully more likely to advance deep in the tournament.
    """

    # Historical hit rates — used to weight each criterion's impact
    # Higher hit rate = steeper penalty for failure
    CRITERION_WEIGHTS = {
        "atr":            35 / 35,   # 100% — absolute filter
        "sweet16_hc":     32 / 35,   # 91%
        "quality_wins":   29 / 30,   # 97%
        "sos":            30 / 30,   # 100% — absolute filter
        "off_eff":        22 / 23,   # 96%
        "def_eff":        22 / 23,   # 96%
        "three_pt_diff":  37 / 38,   # 97% — near-absolute; only 1988 KU broke this
        "nba_draft":      38 / 40,   # 95% — transcript validated: champ has ≥1 projected pick
    }

    @staticmethod
    def score_team(team: Team) -> Dict[str, bool]:
        """Return dict of criterion name → met (True/False)"""
        return {
            "atr":            team.assist_to_turnover_ratio > 1.0,
            "sweet16_hc":     team.coach_sweet16_appearances >= 1,
            "quality_wins":   team.quality_wins_top10_rpi >= 3,
            "sos":            team.sos_rank <= 75,
            "off_eff":        team.off_kenpom_rank <= 20,
            "def_eff":        team.def_kenpom_rank <= 20,
            "three_pt_diff":  team.three_point_pct_differential > 0.0,
            "nba_draft":      team.nba_draft_picks_projected >= 1,
        }

    @staticmethod
    def total_score(team: Team) -> int:
        """Number of criteria met (0-7)"""
        return sum(ChampionshipProfileScorer.score_team(team).values())

    @staticmethod
    def win_probability_adjustment(team1: Team, team2: Team) -> float:
        """
        Compute a win-probability delta for team1 vs team2 based on
        how many championship profile criteria each team meets.

        A team that meets all 7 criteria vs a team that meets 0
        gets a ~7% bump in raw win probability. Per-criterion scale
        calibrated so a 3-point profile gap ≈ 3% win prob swing.
        """
        score1 = ChampionshipProfileScorer.total_score(team1)
        score2 = ChampionshipProfileScorer.total_score(team2)
        delta = score1 - score2   # -7 to +7
        return delta * 0.01       # 1% per criterion gap

    @staticmethod
    def championship_multiplier(team: Team) -> float:
        """
        A standalone multiplier used to re-rank championship probabilities
        in the report. Teams meeting all 7 criteria get 1.0 (no penalty);
        each missing criterion applies a historically-derived discount.

        Missing 'sos', 'atr', or 'three_pt_diff' (near-100% filters) hurts
        most; missing 'sweet16_hc' (91%) is the lightest penalty.
        """
        criteria = ChampionshipProfileScorer.score_team(team)
        weights = ChampionshipProfileScorer.CRITERION_WEIGHTS
        multiplier = 1.0
        for criterion, met in criteria.items():
            if not met:
                # Penalty proportional to how often champs DID meet this
                multiplier *= (1.0 - weights[criterion] * 0.15)
        return multiplier


class BostonRankingSystem:
    """Alan Boston's Methodology - Qualitative/Motivational"""
    
    @staticmethod
    def calculate_boston_rating(team: Team) -> float:
        base_rating = (team.off_efficiency + (110 - team.def_efficiency)) / 2
        history_adjustment = (team.program_history_score - 5.0) * 2.0
        coaching_adjustment = (team.coaching_score - 5.0) * 1.5
        tournament_adjustment = team.tournament_experience * 0.8
        motivation_adjustment = (team.motivation_factor - 1.0) * 10.0
        form_adjustment = team.recent_form * 0.5
        
        return (base_rating + history_adjustment + coaching_adjustment +
                tournament_adjustment + motivation_adjustment + form_adjustment)
    
    @staticmethod
    def identify_trap_games(team: Team) -> float:
        trap_risk = 0.0
        if team.motivation_factor > 1.15:
            trap_risk += 0.3
        if team.recent_form > 8.0:
            trap_risk += 0.2
        return min(trap_risk, 1.0)


class WaltersRankingSystem:
    """Billy Walters' Methodology - Power Ratings/Situational (Enhanced)"""
    
    @staticmethod
    def calculate_walters_rating(team: Team) -> float:
        offensive_rating = team.off_efficiency
        defensive_rating = 110 - team.def_efficiency
        efficiency_rating = (offensive_rating * 0.45 + defensive_rating * 0.55)
        sos_adjustment = team.schedule_strength * 15.0
        form_adjustment = team.recent_form * 0.8
        injury_adjustment = team.injury_impact
        
        return efficiency_rating + sos_adjustment + form_adjustment + injury_adjustment
    
    @staticmethod
    def calculate_game_line(team1: Team, team2: Team, neutral_site: bool = False) -> float:
        rating_diff = (
            WaltersRankingSystem.calculate_walters_rating(team1) -
            WaltersRankingSystem.calculate_walters_rating(team2)
        )
        if not neutral_site:
            rating_diff += team1.home_court_advantage
        return rating_diff


class FeustelRankingSystem:
    """Feustel Methodology - Statistical/Regression"""
    
    @staticmethod
    def calculate_feustel_rating(team: Team) -> float:
        efficiency_margin = team.off_efficiency - team.def_efficiency
        pyth_adjustment = (team.pythagorean_win_pct - 0.5) * 30.0
        four_factors_adjustment = team.four_factors_score * 0.3
        sos_regression = (team.schedule_strength - 0.5) * 20.0
        total_games = team.wins + team.losses
        win_pct = team.wins / total_games if total_games > 0 else team.pythagorean_win_pct
        win_adjustment = (win_pct - 0.5) * 15.0
        
        return (100.0 + efficiency_margin * 1.2 + pyth_adjustment +
                four_factors_adjustment + sos_regression + win_adjustment * 0.5)
    
    @staticmethod
    def predict_win_probability(team1: Team, team2: Team, 
                               neutral_site: bool = False) -> float:
        rating_diff = (
            FeustelRankingSystem.calculate_feustel_rating(team1) -
            FeustelRankingSystem.calculate_feustel_rating(team2)
        )
        if not neutral_site:
            rating_diff += team1.home_court_advantage
        return 1.0 / (1.0 + np.exp(-rating_diff / 10.0))


class CompositeRankingSystem:
    """Combines Boston, Walters, and Feustel methodologies"""
    
    def __init__(self, boston_weight: float = 0.25, 
                 walters_weight: float = 0.35,
                 feustel_weight: float = 0.40):
        self.boston_weight = boston_weight
        self.walters_weight = walters_weight
        self.feustel_weight = feustel_weight
        
    def calculate_composite_rating(self, team: Team) -> float:
        boston_rating = BostonRankingSystem.calculate_boston_rating(team)
        walters_rating = WaltersRankingSystem.calculate_walters_rating(team)
        feustel_rating = FeustelRankingSystem.calculate_feustel_rating(team)
        
        return (boston_rating * self.boston_weight +
                walters_rating * self.walters_weight +
                feustel_rating * self.feustel_weight)
    
    def rank_teams(self, teams: List[Team]) -> List[Tuple[Team, float]]:
        rankings = [(team, self.calculate_composite_rating(team)) for team in teams]
        rankings.sort(key=lambda x: x[1], reverse=True)
        return rankings


class MonteCarloTournamentSimulator:
    """
    Full 64-team NCAA Tournament Monte Carlo simulator.
    Uses TOURNAMENT_BRACKET_2026 for actual seedings/matchups.
    Tracks advancement probabilities for all 6 rounds.
    """
    
    def __init__(self, teams: List[Team], num_simulations: int = 10000):
        self.teams = teams
        self.num_simulations = num_simulations
        self.composite_system = CompositeRankingSystem()
        # Build full tournament field (modeled teams + proxy teams)
        self.bracket_field, self.team_lookup = build_tournament_field(teams)
        
    def simulate_game(self, team1: Team, team2: Team,
                     neutral_site: bool = True,
                     round_name: str = "") -> Team:
        boston_rating1 = BostonRankingSystem.calculate_boston_rating(team1)
        boston_rating2 = BostonRankingSystem.calculate_boston_rating(team2)
        boston_diff = boston_rating1 - boston_rating2
        boston_win_prob = 1.0 / (1.0 + np.exp(-boston_diff / 12.0))
        
        walters_line = WaltersRankingSystem.calculate_game_line(team1, team2, neutral_site)
        walters_win_prob = 1.0 / (1.0 + np.exp(-walters_line / 8.0))
        
        feustel_win_prob = FeustelRankingSystem.predict_win_probability(team1, team2, neutral_site)
        
        composite_win_prob = (boston_win_prob * 0.25 + walters_win_prob * 0.35 +
                             feustel_win_prob * 0.40)
        
        # Championship Profile adjustment
        champ_adjustment = ChampionshipProfileScorer.win_probability_adjustment(team1, team2)
        composite_win_prob = np.clip(composite_win_prob + champ_adjustment, 0.05, 0.95)

        # ── NEW: Seed Matchup Calibration (R64 only) ──────────────────────────
        # Blend composite model with 40-year historical seed upset rates.
        # e.g. 5/12 line has 35% upset rate historically — pure models often underestimate.
        s1 = team1.tournament_seed
        s2 = team2.tournament_seed
        if s1 > 0 and s2 > 0 and s1 + s2 == 17:
            lo, hi = min(s1, s2), max(s1, s2)
            hist_fav_prob = HISTORICAL_SEED_UPSET_RATES.get((lo, hi))
            if hist_fav_prob is not None:
                team1_is_fav = (s1 < s2)
                hist_prob_for_t1 = hist_fav_prob if team1_is_fav else (1.0 - hist_fav_prob)
                composite_win_prob = (
                    (1.0 - SEED_HIST_BLEND) * composite_win_prob +
                    SEED_HIST_BLEND * hist_prob_for_t1
                )

        # ── NEW: Play-in 11-Seed Motivation Boost ────────────────────────────
        # First Four winners have historically overperformed vs 6-seeds in R64.
        # Grant a ~10% win-probability boost to play-in 11-seeds.
        if round_name == "r64":
            if team1.name in FIRST_FOUR_PLAY_IN_TEAMS_2026 and s2 == 6:
                composite_win_prob = min(0.95, composite_win_prob * 1.10)
            elif team2.name in FIRST_FOUR_PLAY_IN_TEAMS_2026 and s1 == 6:
                composite_win_prob = max(0.05, composite_win_prob * 0.91)

        # ── NEW: Mid-Major Conference Penalty (R32 and beyond) ───────────────
        # Only one non-power-conference team has escaped the first weekend in 2 years.
        # Apply a win-probability discount to mid-majors vs power conference opponents
        # in rounds after R64 (where depth/athleticism gaps compound).
        if round_name in MID_MAJOR_PENALTY_ROUNDS:
            t1_power = team1.conference in POWER_CONFERENCES
            t2_power = team2.conference in POWER_CONFERENCES
            if not t1_power and t2_power:
                # mid-major team1 vs power team2 — discount mid-major
                composite_win_prob = max(0.05, composite_win_prob * 0.88)
            elif t1_power and not t2_power:
                # power team1 vs mid-major team2 — boost power
                composite_win_prob = min(0.95, composite_win_prob / 0.88)
        
        # Style-based variance (March Madness multiplier)
        team1_variance = team1.get_simulation_variance()
        team2_variance = team2.get_simulation_variance()
        combined_variance = (team1_variance + team2_variance) / 2
        if team1.play_style != team2.play_style:
            combined_variance *= 1.15
        final_variance = combined_variance * 1.25  # March Madness multiplier
        
        variance = np.random.normal(0, final_variance)
        adjusted_prob = np.clip(composite_win_prob + variance, 0.05, 0.95)
        
        return team1 if np.random.random() < adjusted_prob else team2

    def simulate_tournament_round(self, teams: List[Team], round_name: str = "") -> List[Team]:
        winners = []
        for i in range(0, len(teams), 2):
            winner = self.simulate_game(teams[i], teams[i+1], neutral_site=True,
                                        round_name=round_name)
            winners.append(winner)
        return winners

    def _simulate_region(self, field: List[Team]) -> Tuple[Team, Dict[str, List[Team]]]:
        """
        Simulate one 16-team region through 4 rounds.
        Returns (regional_champion, {round_name: [winners]}).
        field must be in R64 matchup order: positions 0-15.
        """
        round_winners: Dict[str, List[Team]] = {}

        # R64: pairs (0,1) (2,3) ... (14,15)
        r32_field = self.simulate_tournament_round(field, "r64")
        round_winners['r64'] = r32_field           # 8 R64 winners = R32 field

        # R32: pairs (0,1) (2,3) (4,5) (6,7)
        s16_field = self.simulate_tournament_round(r32_field, "r32")
        round_winners['r32'] = s16_field           # 4 R32 winners = S16 field

        # S16: pairs (0,1) (2,3)
        e8_field = self.simulate_tournament_round(s16_field, "s16")
        round_winners['s16'] = e8_field            # 2 S16 winners = E8 field

        # E8 (Regional Final)
        regional_champ = self.simulate_game(e8_field[0], e8_field[1],
                                            neutral_site=True, round_name="e8")
        round_winners['e8'] = [regional_champ]

        return regional_champ, round_winners

    def simulate_tournament(self) -> Dict:
        """
        Simulate one complete 64-team tournament.
        Returns detailed results dict with per-round winner lists.
        """
        results: Dict[str, Dict] = {}
        regional_champs: Dict[str, Team] = {}

        for region, field in self.bracket_field.items():
            champ, round_winners = self._simulate_region(field)
            regional_champs[region] = champ
            results[region] = round_winners

        # Final Four
        ff_winners = []
        for r1, r2 in FINAL_FOUR_MATCHUPS_2026:
            winner = self.simulate_game(regional_champs[r1], regional_champs[r2],
                                        neutral_site=True, round_name="ff")
            ff_winners.append(winner)
        results['final_four'] = ff_winners

        # Championship
        champion = self.simulate_game(ff_winners[0], ff_winners[1],
                                      neutral_site=True, round_name="champ")
        results['champion'] = champion

        return results

    def run_full_simulation(self) -> Dict:
        """
        Run num_simulations full 64-team tournaments.
        Tracks advancement frequency for every team through all 6 rounds.
        """
        # Per-round win counters
        r64_count   = defaultdict(int)   # won R64 (reached R32)
        r32_count   = defaultdict(int)   # won R32 (reached S16)
        s16_count   = defaultdict(int)   # won S16 (reached E8)
        e8_count    = defaultdict(int)   # won E8  (regional champ → Final Four)
        ff_count    = defaultdict(int)   # won FF semifinal (reached championship game)
        champ_count = defaultdict(int)   # won championship

        print(f"Running {self.num_simulations:,} full 64-team tournament simulations...")
        print("Using Walters-enhanced variance model (March 15, 2026 — Selection Sunday)...\n")

        for sim in range(self.num_simulations):
            if (sim + 1) % 2500 == 0:
                print(f"  Completed {sim+1:,} simulations...")

            result = self.simulate_tournament()

            # Regional rounds
            for region in self.bracket_field.keys():
                rw = result[region]
                for t in rw['r64']:  r64_count[t.name]  += 1
                for t in rw['r32']:  r32_count[t.name]  += 1
                for t in rw['s16']:  s16_count[t.name]  += 1
                for t in rw['e8']:   e8_count[t.name]   += 1

            # Final Four + championship
            for t in result['final_four']:
                ff_count[t.name] += 1
            champ_count[result['champion'].name] += 1

        n = self.num_simulations
        def pct(d): return {k: v / n * 100 for k, v in d.items()}

        return {
            'r64_prob':          pct(r64_count),
            'r32_prob':          pct(r32_count),
            's16_prob':          pct(s16_count),
            'e8_prob':           pct(e8_count),
            'final_four_prob':   pct(ff_count),
            'championship_prob': pct(ff_count),   # kept for backward compat
            'champion_prob':     pct(champ_count),
        }


def generate_bracket_report(sim_results: Dict, bracket_field: Dict[str, List[Team]],
                             team_lookup: Dict[str, Team]):
    """
    Print round-by-round advancement probabilities for the 2026 NCAA Tournament.
    Organized by region with seed context and championship profile flags.
    """
    W = 80
    print("\n" + "="*W)
    print("2026 NCAA TOURNAMENT — FULL BRACKET ADVANCEMENT PROBABILITIES")
    print("Source: CBS Sports Official Bracket  |  March 15, 2026 (Selection Sunday)")
    print("="*W)

    r64   = sim_results.get('r64_prob', {})
    r32   = sim_results.get('r32_prob', {})
    s16   = sim_results.get('s16_prob', {})
    e8    = sim_results.get('e8_prob', {})
    ff    = sim_results.get('final_four_prob', {})
    champ = sim_results.get('champion_prob', {})

    ROUND_HDRS = [
        f"{'R64':>6}", f"{'R32':>6}", f"{'S16':>6}",
        f"{'E8':>6}",  f"{'FF':>6}",  f"{'CHAMP':>6}",
    ]

    for region, field in bracket_field.items():
        print(f"\n{'─'*W}")
        print(f"  {region.upper()} REGION")
        print(f"{'─'*W}")
        print(f"  {'Seed':<4} {'Team':<24} {'R64':>6} {'R32':>6} {'S16':>6} "
              f"{'E8':>6} {'FF':>6} {'CHAMP':>6}  Profile")
        print(f"  {'─'*72}")

        for team in field:
            n = team.name
            p = CHAMP_PROFILES_CACHE.get(n, {})
            pscore = f"{sum(p.values())}/7" if p else " n/a"
            flags = ""
            if p:
                if not p.get("atr"):           flags += "⚠ATR "
                if not p.get("sos"):           flags += "⚠SOS "
                if not p.get("three_pt_diff"): flags += "⚠3P% "
            seed_str = f"({team.tournament_seed})"
            inj = ""
            if team.injured_players:
                s = [pl for pl in team.injured_players if pl.games_out > 5]
                if s:
                    inj = f"  ⚕ {','.join(pl.name.split()[0] for pl in s)}"

            print(f"  {seed_str:<4} {n:<24} "
                  f"{r64.get(n,0):>5.1f}% "
                  f"{r32.get(n,0):>5.1f}% "
                  f"{s16.get(n,0):>5.1f}% "
                  f"{e8.get(n,0):>5.1f}% "
                  f"{ff.get(n,0):>5.1f}% "
                  f"{champ.get(n,0):>5.1f}%  "
                  f"{pscore} {flags}{inj}")

    # Final Four predictions
    print(f"\n{'='*W}")
    print("PREDICTED FINAL FOUR")
    print(f"{'='*W}")
    top_ff = sorted(ff.items(), key=lambda x: -x[1])[:4]
    for i, (name, prob) in enumerate(top_ff, 1):
        seed_str = ""
        region_str = ""
        t = team_lookup.get(name)
        if t:
            seed_str   = f"({t.tournament_seed})"
            region_str = t.tournament_region
        print(f"  {i}. {seed_str} {name:<22} {region_str:<9} {prob:.2f}% chance to reach Final Four")

    # Championship game prediction
    print(f"\n{'='*W}")
    print("PREDICTED CHAMPIONSHIP GAME  (Indianapolis, April 6)")
    print(f"{'='*W}")
    top_champ = sorted(champ.items(), key=lambda x: -x[1])[:8]
    print(f"\n  {'Team':<24} {'Seed':<6} {'Region':<10} {'Champ %':>8}  Profile")
    print(f"  {'─'*58}")
    for name, prob in top_champ:
        t = team_lookup.get(name)
        seed_str   = f"({t.tournament_seed})" if t else "(?)"
        region_str = t.tournament_region if t else "?"
        p = CHAMP_PROFILES_CACHE.get(name, {})
        pscore = f"{sum(p.values())}/7" if p else " n/a"
        print(f"  {name:<24} {seed_str:<6} {region_str:<10} {prob:>7.2f}%  {pscore}")

    # Predicted champion
    predicted = max(champ.items(), key=lambda x: x[1]) if champ else ("Unknown", 0.0)
    print(f"\n  🏆  PREDICTED 2026 NATIONAL CHAMPION: {predicted[0]}  ({predicted[1]:.2f}% probability)")


# ─ Championship profile cache (populated by generate_report) ─────────────────
CHAMP_PROFILES_CACHE: Dict[str, dict] = {}


def generate_report(teams: List[Team], sim_results: Dict,
                    bracket_field: Dict = None, team_lookup: Dict = None):
    """Generate comprehensive analysis report"""
    global CHAMP_PROFILES_CACHE

    composite_system = CompositeRankingSystem()

    # Populate championship profile cache for all teams (used by bracket report)
    for t in teams:
        CHAMP_PROFILES_CACHE[t.name] = ChampionshipProfileScorer.score_team(t)
    
    print("\n" + "="*80)
    print("COLLEGE BASKETBALL RANKING SYSTEM v2.3")
    print("2025-26 SEASON — March 15, 2026 (Selection Sunday)")
    print("Boston + Walters + Feustel Composite Methodology")
    print("="*80)
    
    print("\n" + "-"*80)
    print("WALTERS TWEAKS ACTIVE:")
    print("-"*80)
    print("✓ Dynamic Home Court Advantage (team-specific HCA)")
    print("✓ Injury Impact with Rotation Values")
    print("✓ SOS Decay (recent games weighted more)")
    print("✓ Style-Based Variance (3PT teams have higher variance)")
    
    # Key Players
    print("\n" + "-"*80)
    print("KEY PLAYERS TO WATCH (2025-26)")
    print("-"*80)
    for team in teams[:15]:
        if team.star_player:
            print(f"{team.name:<20} {team.star_player}")
    
    # Home Court Analysis
    print("\n" + "-"*80)
    print("HOME COURT ADVANTAGE ANALYSIS")
    print("-"*80)
    print(f"{'Team':<20} {'HCA':<8} {'Altitude':<10} {'Crowd':<10} {'Style':<20}")
    print("-"*80)
    
    hca_sorted = sorted(teams, key=lambda t: t.home_court_advantage, reverse=True)[:10]
    for team in hca_sorted:
        print(f"{team.name:<20} {team.home_court_advantage:<8.2f} "
              f"{team.home_court_profile.altitude_bonus:<10.1f} "
              f"{team.home_court_profile.crowd_intensity:<10.2f} "
              f"{team.play_style.value:<20}")
    
    # Variance Analysis
    print("\n" + "-"*80)
    print("VARIANCE ANALYSIS (Upset Potential)")
    print("-"*80)
    print(f"{'Team':<20} {'Variance':<10} {'3PT Rate':<10} {'Style':<20}")
    print("-"*80)
    
    variance_sorted = sorted(teams, key=lambda t: t.get_simulation_variance(), reverse=True)[:10]
    for team in variance_sorted:
        print(f"{team.name:<20} {team.get_simulation_variance():<10.3f} "
              f"{team.three_point_rate:<10.2f} {team.play_style.value:<20}")
    
    # Championship Profile Analysis
    print("\n" + "="*80)
    print("CHAMPIONSHIP PROFILE ANALYSIS")
    print("Gill Alexander (VSiN 'A Numbers Game') — Historical Champion Checklist")
    print("="*80)
    print(f"\n{'Criterion':<42} {'Threshold':<20} {'Hit Rate'}")
    print("-"*80)
    print(f"{'Assists > Turnovers (ATR > 1.0)':<42} {'ATR > 1.0':<20} {'35/35 (100%)'}")
    print(f"{'HC with Sweet 16 Experience':<42} {'≥1 S16 appearance':<20} {'32/35 (91%)'}")
    print(f"{'3+ Wins vs Top-10% RPI Teams':<42} {'≥3 quality wins':<20} {'29/30 (97%)'}")
    print(f"{'Top 75 Strength of Schedule':<42} {'SOS rank ≤ 75':<20} {'30/30 (100%)'}")
    print(f"{'Top 20 Adj. Offensive Efficiency':<42} {'Off rank ≤ 20':<20} {'22/23 (96%)'}")
    print(f"{'Top 20 Adj. Defensive Efficiency':<42} {'Def rank ≤ 20':<20} {'22/23 (96%)'}")
    print(f"{'Positive 3P% Differential':<42} {'3P% diff > 0':<20} {'~37/38 (97%)'}")
    print(f"{'  └─ Last champ w/ neg diff: 1988 Kansas Jayhawks':<42}")
    print(f"{'≥1 Projected NBA Draft Pick':<42} {'nba_draft ≥ 1':<20} {'~38/40 (95%)'}") 
    print(f"{'  └─ Transcript: champ needs at least 1 projected pick':<42}")

    print(f"\n{'Team':<22} {'Score':<8} {'ATR':>4} {'S16':>4} {'QW':>4} {'SOS':>5} {'OFF':>5} {'DEF':>5} {'3P%':>5} {'NBA':>4}")
    print("-"*80)
    
    champ_sorted = sorted(teams, key=lambda t: ChampionshipProfileScorer.total_score(t), reverse=True)
    for team in champ_sorted[:20]:
        score = ChampionshipProfileScorer.total_score(team)
        criteria = ChampionshipProfileScorer.score_team(team)
        atr_s   = "✓" if criteria["atr"]           else "✗"
        s16_s   = "✓" if criteria["sweet16_hc"]    else "✗"
        qw_s    = "✓" if criteria["quality_wins"]  else "✗"
        sos_s   = "✓" if criteria["sos"]           else "✗"
        off_s   = "✓" if criteria["off_eff"]       else "✗"
        def_s   = "✓" if criteria["def_eff"]       else "✗"
        tpt_s   = "✓" if criteria["three_pt_diff"] else "✗"
        nba_s   = "✓" if criteria["nba_draft"]     else "✗"
        mult    = ChampionshipProfileScorer.championship_multiplier(team)
        diff_val = f"{team.three_point_pct_differential:+.1%}"
        print(f"{team.name:<22} {score}/8    {atr_s:>4} {s16_s:>4} {qw_s:>4} {sos_s:>5} {off_s:>5} {def_s:>5} {tpt_s:>4}({diff_val}) {nba_s:>4}  mult:{mult:.3f}")

    # Championship Profile-adjusted champion probabilities
    print("\n" + "-"*80)
    print("PROFILE-ADJUSTED CHAMPIONSHIP ODDS")
    print("(Raw sim probability × historical profile multiplier)")
    print("-"*80)
    
    champ_raw = sorted(sim_results['champion_prob'].items(), key=lambda x: x[1], reverse=True)[:12]
    team_lookup = {t.name: t for t in teams}
    adjusted = []
    for name, raw_prob in champ_raw:
        team = team_lookup.get(name)
        if team:
            mult = ChampionshipProfileScorer.championship_multiplier(team)
            score = ChampionshipProfileScorer.total_score(team)
            adjusted.append((name, raw_prob, raw_prob * mult, score, mult))
    adjusted.sort(key=lambda x: x[2], reverse=True)
    print(f"{'Team':<22} {'Raw%':<10} {'Adj%':<10} {'Profile':<10} {'Mult'}")
    print("-"*80)
    for name, raw, adj, score, mult in adjusted:
        print(f"{name:<22} {raw:<10.2f} {adj:<10.2f} {score}/8       {mult:.3f}")
    print("\n" + "-"*80)
    print("COMPOSITE POWER RANKINGS")
    print("-"*80)
    print(f"{'Rank':<6} {'Team':<20} {'Record':<10} {'Rating':<10} {'Conference':<15}")
    print("-"*80)
    
    rankings = composite_system.rank_teams(teams)
    for idx, (team, rating) in enumerate(rankings, 1):
        print(f"{idx:<6} {team.name:<20} {team.record:<10} {rating:<10.2f} {team.conference:<15}")
    
    # Tournament Predictions
    print("\n" + "="*80)
    print("2026 NCAA TOURNAMENT PREDICTIONS")
    print("Monte Carlo Simulation Results (Style-Based Variance)")
    print("="*80)
    
    print("\nCHAMPIONSHIP PROBABILITIES:")
    print("-"*80)
    print(f"{'Team':<25} {'Win %':<10} {'Final Game %':<15} {'Final Four %':<15}")
    print("-"*80)
    
    champion_probs = sorted(sim_results['champion_prob'].items(),
                           key=lambda x: x[1], reverse=True)[:15]
    
    for team_name, prob in champion_probs:
        champ_game_prob = sim_results['championship_prob'].get(team_name, 0)
        ff_prob = sim_results['final_four_prob'].get(team_name, 0)
        print(f"{team_name:<25} {prob:<10.2f}% {champ_game_prob:<15.2f}% {ff_prob:<15.2f}%")
    
    print("\n" + "="*80)
    print("PREDICTED 2026 FINAL FOUR")
    print("="*80)
    
    top_4_ff = sorted(sim_results['final_four_prob'].items(),
                     key=lambda x: x[1], reverse=True)[:4]
    
    for idx, (team_name, prob) in enumerate(top_4_ff, 1):
        print(f"{idx}. {team_name:<20} {prob:.2f}% chance of making Final Four")
    
    print("\n" + "="*80)
    print("PREDICTED 2026 NATIONAL CHAMPION")
    print("="*80)
    
    predicted_champion = max(sim_results['champion_prob'].items(), key=lambda x: x[1])
    
    print(f"\n🏆 {predicted_champion[0]}")
    print(f"   Probability: {predicted_champion[1]:.2f}%")
    print(f"   Championship Game: {sim_results['championship_prob'].get(predicted_champion[0], 0):.2f}%")
    print(f"   Final Four: {sim_results['final_four_prob'].get(predicted_champion[0], 0):.2f}%")
    
    # Dark Horses
    print("\n" + "-"*80)
    print("DARK HORSE CANDIDATES (High variance + motivation)")
    print("-"*80)
    
    for team in teams:
        variance = team.get_simulation_variance()
        if team.motivation_factor > 1.10 and variance > 0.08:
            champ_prob = sim_results['champion_prob'].get(team.name, 0)
            if champ_prob > 0.5:
                print(f"🎯 {team.name:<20} Variance: {variance:.3f}, "
                      f"Style: {team.play_style.value}, {champ_prob:.2f}% to win")

    # ── Full bracket report (only when bracket_field is available) ──
    if bracket_field and team_lookup:
        generate_bracket_report(sim_results, bracket_field, team_lookup)


# ===== UTILITY FUNCTIONS =====

def add_injury(team: Team, player_name: str, position: str, 
               games_out: int, is_starter: bool = True,
               is_primary_scorer: bool = False,
               is_floor_general: bool = False) -> None:
    rotation_value = calculate_player_rotation_value(
        position, is_starter, 
        is_primary_scorer=is_primary_scorer,
        is_floor_general=is_floor_general
    )
    
    injured_player = InjuredPlayer(
        name=player_name,
        position=position,
        rotation_value=rotation_value,
        games_out=games_out,
        is_starter=is_starter
    )
    
    team.injured_players.append(injured_player)
    print(f"Added injury: {player_name} ({position}) - {rotation_value:.1f} pts impact")


# =============================================================================
# 2026 NCAA TOURNAMENT BRACKET
# Source: CBS Sports official bracket — Selection Sunday, March 15, 2026
# =============================================================================

TOURNAMENT_BRACKET_2026 = {
    # Matchup pairs in R64 order: (1,16) (8,9) (5,12) (4,13) (6,11) (3,14) (7,10) (2,15)
    "East": [
        (1,  "Duke"),          (16, "Siena"),
        (8,  "Ohio State"),    (9,  "TCU"),
        (5,  "St. John's"),    (12, "N. Iowa"),
        (4,  "Kansas"),        (13, "Cal Baptist"),
        (6,  "Louisville"),    (11, "South Florida"),
        (3,  "Michigan State"),(14, "N. Dakota St."),
        (7,  "UCLA"),          (10, "UCF"),
        (2,  "UConn"),         (15, "Furman"),
    ],
    "South": [
        (1,  "Florida"),       (16, "PV/Lehigh"),     # First Four winner
        (8,  "Clemson"),       (9,  "Iowa"),
        (5,  "Vanderbilt"),    (12, "McNeese"),
        (4,  "Nebraska"),      (13, "Troy"),
        (6,  "North Carolina"),(11, "VCU"),
        (3,  "Illinois"),      (14, "Penn"),
        (7,  "Saint Mary's"),  (10, "Texas A&M"),
        (2,  "Houston"),       (15, "Idaho"),
    ],
    "West": [
        (1,  "Arizona"),       (16, "LIU"),
        (8,  "Villanova"),     (9,  "Utah State"),
        (5,  "Wisconsin"),     (12, "High Point"),
        (4,  "Arkansas"),      (13, "Hawaii"),
        (6,  "BYU"),           (11, "TX/NC State"),   # First Four winner
        (3,  "Gonzaga"),       (14, "Kennesaw State"),
        (7,  "Miami FL"),      (10, "Missouri"),
        (2,  "Purdue"),        (15, "Queens"),
    ],
    "Midwest": [
        (1,  "Michigan"),      (16, "UMBC/Howard"),   # First Four winner
        (8,  "Georgia"),       (9,  "Saint Louis"),
        (5,  "Texas Tech"),    (12, "Akron"),
        (4,  "Alabama"),       (13, "Hofstra"),
        (6,  "Tennessee"),     (11, "MO/SMU"),        # First Four winner
        (3,  "Virginia"),      (14, "Wright State"),
        (7,  "Kentucky"),      (10, "Santa Clara"),
        (2,  "Iowa State"),    (15, "Tennessee State"),
    ],
}

# Final Four bracket pairings (region1 champ vs region2 champ)
FINAL_FOUR_MATCHUPS_2026 = [("East", "South"), ("West", "Midwest")]

# ─────────────────────────────────────────────────────────────────────────────
# SEED-BASED EFFICIENCY PROXIES
# For teams not in the model — historical KenPom averages by seed (tournament)
# Tuple: (adj_off_efficiency, adj_def_efficiency)
# ─────────────────────────────────────────────────────────────────────────────
SEED_EFF_PROXY: Dict[int, Tuple[float, float]] = {
    1:  (125.5, 89.0),   # avg margin +36.5
    2:  (122.5, 91.5),   # avg margin +31.0
    3:  (120.0, 92.5),   # avg margin +27.5
    4:  (117.5, 93.5),   # avg margin +24.0
    5:  (115.0, 94.5),   # avg margin +20.5
    6:  (113.0, 95.5),   # avg margin +17.5
    7:  (111.5, 96.5),   # avg margin +15.0
    8:  (110.5, 97.5),   # avg margin +13.0
    9:  (109.5, 98.5),   # avg margin +11.0
    10: (108.5, 99.5),   # avg margin  +9.0
    11: (107.5, 100.5),  # avg margin  +7.0
    12: (106.5, 101.5),  # avg margin  +5.0
    13: (104.5, 103.0),  # avg margin  +1.5
    14: (102.5, 105.0),  # avg margin  -2.5
    15: (100.0, 107.5),  # avg margin  -7.5
    16: (97.0,  112.0),  # avg margin -15.0
}


def build_proxy_team(name: str, seed: int, region: str) -> Team:
    """
    Create a proxy Team for tournament entrants not in the ranking model.
    Uses historical seed-based KenPom efficiency averages.
    Coaching/program scores are set neutrally; variance set to BALANCED.
    """
    off_eff, def_eff = SEED_EFF_PROXY.get(seed, (108.0, 100.0))
    proxy = Team(
        name=name,
        rank=100 + seed,
        record="N/A",
        wins=0,
        losses=0,
        conference="Unknown",
        kenpom_rank=seed * 5,
        net_rank=seed * 5,
        off_efficiency=off_eff,
        def_efficiency=def_eff,
        tempo=70.0,
        program_history_score=max(1.0, 6.0 - seed * 0.3),
        coaching_score=max(1.0, 6.5 - seed * 0.3),
        motivation_factor=1.10,
        tournament_experience=max(0, 3 - seed // 4),
        recent_form=max(4.0, 8.0 - seed * 0.3),
        raw_schedule_strength=max(0.35, 0.75 - seed * 0.025),
        play_style=PlayStyle.BALANCED,
        three_point_rate=0.35,
        three_point_pct=0.35,
        # Championship profile — proxies don't pass most criteria
        assist_to_turnover_ratio=1.0 + (1.0 / seed),
        coach_sweet16_appearances=max(0, 2 - seed // 5),
        quality_wins_top10_rpi=max(0, 3 - seed // 4),
        sos_rank=min(350, seed * 15 + 20),
        off_kenpom_rank=min(100, seed * 5),
        def_kenpom_rank=min(100, seed * 5),
        three_point_pct_differential=0.01 if seed <= 8 else -0.01,
        nba_draft_picks_projected=1 if seed <= 4 else 0,   # proxy: top seeds usually have picks
        tournament_seed=seed,
        tournament_region=region,
    )
    proxy.pythagorean_win_pct = calculate_pythagorean_win_pct(off_eff, def_eff)
    proxy.four_factors_score  = calculate_four_factors(proxy)
    return proxy


def build_tournament_field(modeled_teams: List[Team]) -> Tuple[Dict[str, List[Team]], Dict[str, Team]]:
    """
    Build the full 64-team tournament field from TOURNAMENT_BRACKET_2026.

    Returns:
        bracket_field : {region → [Team, ...] in R64 matchup order}
        team_lookup   : {name → Team} for the full field
    """
    team_by_name: Dict[str, Team] = {t.name: t for t in modeled_teams}
    bracket_field: Dict[str, List[Team]] = {}
    full_lookup:   Dict[str, Team] = {}

    for region, entries in TOURNAMENT_BRACKET_2026.items():
        region_teams = []
        for seed, name in entries:
            if name in team_by_name:
                t = team_by_name[name]
                t.tournament_seed   = seed
                t.tournament_region = region
                region_teams.append(t)
            else:
                proxy = build_proxy_team(name, seed, region)
                region_teams.append(proxy)
                team_by_name[name] = proxy
            full_lookup[name] = region_teams[-1]
        bracket_field[region] = region_teams

    return bracket_field, full_lookup


def main():
    """Main execution function"""
    
    print("="*80)
    print("COLLEGE BASKETBALL RANKING SYSTEM v2.3")
    print("2025-26 Season  |  March 15, 2026 — Selection Sunday")
    print("2026 NCAA Tournament: 64-team field locked")
    print("="*80)
    
    print("\nInitializing current season teams...")
    teams = initialize_top_teams()
    
    # ── Injuries as of Selection Sunday, March 15, 2026 ─────────────────────
    print("\nUpdating injuries (Selection Sunday — March 15, 2026)...")
    for team in teams:
        if team.name == "Duke":
            # Caleb Foster (PG) — fractured foot, surgery March 9 — CONFIRMED SEASON ENDING
            # Will NOT play in NCAA Tournament
            add_injury(team, "Caleb Foster", "PG", games_out=99,
                      is_starter=True, is_primary_scorer=False, is_floor_general=True)
            # Patrick Ngongba II (C) — foot soreness; cleared for tournament
            # Sat out ACC tourney but expected to play March 19
            # (No injury object added — expected to be available)
        elif team.name == "Texas Tech":
            # JT Toppin (PF) — ACL — CONFIRMED SEASON ENDING
            add_injury(team, "JT Toppin", "PF", games_out=99,
                      is_starter=True, is_primary_scorer=True)
        elif team.name == "Michigan":
            # LJ Carson (SG) — ACL — CONFIRMED SEASON ENDING
            add_injury(team, "LJ Carson", "SG", games_out=99,
                      is_starter=False, is_primary_scorer=True)
        elif team.name == "BYU":
            # Richie Saunders (SF) — ACL — CONFIRMED SEASON ENDING
            add_injury(team, "Richie Saunders", "SF", games_out=99,
                      is_starter=True, is_primary_scorer=True)
        elif team.name == "North Carolina":
            # Caleb Wilson (PF) — broken thumb — CONFIRMED SEASON ENDING (out since Feb 10)
            add_injury(team, "Caleb Wilson", "PF", games_out=99,
                      is_starter=True, is_primary_scorer=True)
    
    # ── Run Monte Carlo simulation (full 64-team bracket) ───────────────────
    print("\n")
    simulator = MonteCarloTournamentSimulator(teams, num_simulations=10000)
    sim_results = simulator.run_full_simulation()
    
    # ── Generate report ──────────────────────────────────────────────────────
    generate_report(teams, sim_results,
                    bracket_field=simulator.bracket_field,
                    team_lookup=simulator.team_lookup)
    
    print("\n" + "="*80)
    print("Analysis complete!  |  Lock bracket before March 19, 2026 at 11:59 AM ET")
    print("="*80)


if __name__ == "__main__":
    main()
