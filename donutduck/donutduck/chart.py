"""Renders balance history as a trading-terminal style chart.

Matplotlib is synchronous and slow enough to stall the gateway heartbeat, so
every render goes through `asyncio.to_thread`. The Agg backend is selected
before pyplot is imported — without it matplotlib tries to find a GUI toolkit
and falls over on a headless host.
"""

from __future__ import annotations

import asyncio
import io
from datetime import datetime, timezone

import matplotlib

matplotlib.use("Agg")

import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

from .theme import (  # noqa: E402
    C_BLUE,
    C_INK,
    C_PINK,
    C_YELLOW,
    series_color_for,
)

# Blue, pink, yellow in order. Used positionally when several series share a
# chart so two players can never land on the same colour.
PALETTE = (C_BLUE, C_PINK, C_YELLOW, "#7DB3FF", "#FF8FC4", "#FFE68A")

GRID = "#2A3450"
TEXT = "#E6ECFF"
MUTED = "#8FA0C4"


def _money_tick(value: float, _pos: int) -> str:
    for limit, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(value) >= limit:
            return f"${value / limit:.1f}".rstrip("0").rstrip(".") + suffix
    return f"${value:,.0f}"


def _render(series: dict[str, list[tuple[float, float]]], title: str) -> bytes:
    """series: {label: [(unix_ts, value), ...]} sorted oldest first."""
    fig, ax = plt.subplots(figsize=(10, 5), dpi=140)
    fig.patch.set_facecolor(C_INK)
    ax.set_facecolor(C_INK)

    multi = len(series) > 1
    for index, (label, points) in enumerate(series.items()):
        if not points:
            continue
        times = [datetime.fromtimestamp(ts, timezone.utc) for ts, _ in points]
        values = [v for _, v in points]
        # Positional colours when sharing a chart; stable per-name colour when
        # a series is shown on its own.
        color = PALETTE[index % len(PALETTE)] if multi else series_color_for(label)

        ax.plot(
            times,
            values,
            color=color,
            linewidth=2.4,
            marker="o",
            markersize=4,
            markerfacecolor=C_INK,
            markeredgecolor=color,
            markeredgewidth=1.6,
            label=label,
            solid_capstyle="round",
            zorder=3,
        )
        # Soft fill under the line, like a price chart.
        ax.fill_between(times, values, min(values), color=color, alpha=0.10, zorder=2)

        # Label the latest value at the right edge.
        ax.annotate(
            _money_tick(values[-1], 0),
            xy=(times[-1], values[-1]),
            xytext=(6, 8 * (index % 2 * 2 - 1) if multi else 0),
            textcoords="offset points",
            color=color,
            fontsize=9,
            fontweight="bold",
            va="center",
            zorder=4,
        )

    ax.set_title(title, color=TEXT, fontsize=14, fontweight="bold", pad=14, loc="left")
    ax.grid(True, color=GRID, linewidth=0.7, alpha=0.7, zorder=1)
    ax.set_axisbelow(True)

    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)

    ax.tick_params(colors=MUTED, labelsize=9)
    ax.yaxis.set_major_formatter(FuncFormatter(_money_tick))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=3, maxticks=7))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b\n%H:%M"))
    fig.autofmt_xdate(rotation=0, ha="center")

    if len(series) > 1:
        legend = ax.legend(
            facecolor=C_INK, edgecolor=GRID, labelcolor=TEXT, fontsize=9, loc="upper left"
        )
        legend.get_frame().set_alpha(0.9)

    fig.text(
        0.99,
        0.02,
        "DonutDuck",
        color=MUTED,
        fontsize=8,
        ha="right",
        alpha=0.7,
    )
    fig.tight_layout()

    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", facecolor=fig.get_facecolor())
    plt.close(fig)
    buffer.seek(0)
    return buffer.getvalue()


async def render_balance_chart(
    series: dict[str, list[tuple[float, float]]], title: str = "Balance history"
) -> bytes:
    return await asyncio.to_thread(_render, series, title)
