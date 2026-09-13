"""The blue / pink / yellow palette, in one place.

Every embed, chart and accent pulls from here, so retheming the whole bot is
a matter of editing this file.
"""

from __future__ import annotations

# Core three
BLUE = 0x3B82F6
PINK = 0xFF4FA3
YELLOW = 0xFFCE3B

# Supporting shades
BLUE_DEEP = 0x1D4ED8
BLUE_SOFT = 0x7DB3FF
PINK_SOFT = 0xFF8FC4
YELLOW_SOFT = 0xFFE68A
INK = 0x131A2B  # chart background

# Semantic roles
BRAND = BLUE
ACCENT = PINK
HIGHLIGHT = YELLOW
ERROR = PINK
SUCCESS = BLUE
WARNING = YELLOW

# Rotate embed colours so a channel full of DonutDuck output doesn't read as
# one flat wall of blue.
CYCLE = (BLUE, PINK, YELLOW)


def hex_str(color: int) -> str:
    """0x3B82F6 -> '#3b82f6', for matplotlib."""
    return f"#{color:06x}"


# Ready-made matplotlib strings
C_BLUE = hex_str(BLUE)
C_PINK = hex_str(PINK)
C_YELLOW = hex_str(YELLOW)
C_INK = hex_str(INK)
C_BLUE_SOFT = hex_str(BLUE_SOFT)
C_PINK_SOFT = hex_str(PINK_SOFT)
C_YELLOW_SOFT = hex_str(YELLOW_SOFT)

SERIES_COLORS = (C_BLUE, C_PINK, C_YELLOW, C_BLUE_SOFT, C_PINK_SOFT, C_YELLOW_SOFT)


def color_for(key: str) -> int:
    """Stable colour per string, so a given player or stat always looks the
    same across commands."""
    return CYCLE[sum(ord(c) for c in key) % len(CYCLE)]


def series_color_for(key: str) -> str:
    return SERIES_COLORS[sum(ord(c) for c in key) % 3]
