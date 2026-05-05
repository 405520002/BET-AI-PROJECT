"""Render a player's PR axes as a polar/radar PNG using matplotlib.

Public API:
    render_player_radar(player: dict, axes: list[dict]) -> bytes
"""
from __future__ import annotations

import io

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.font_manager import FontProperties
from pathlib import Path

CJK = FontProperties(fname=str(Path(__file__).parent / "fonts" / "NotoSansTC-Regular.otf"))

_COLOR_BATTER = "#1f77b4"
_COLOR_PITCHER = "#d62728"


def render_player_radar(player: dict, axes: list[dict]) -> bytes:
    """Render a player's PR axes as a polar/radar PNG.

    Args:
        player: Player info dict with keys: name_zh, uniform_no, team,
                position_zh, role, etc.
        axes: List of dicts with 'name' (str) and 'value' (int 0-100).
              Length must be between 4 and 14.

    Returns:
        PNG image bytes.
    """
    N = len(axes)
    values = [a["value"] for a in axes]

    angles = np.linspace(0, 2 * np.pi, N, endpoint=False).tolist()

    # Close the polygon
    angles.append(angles[0])
    values.append(values[0])

    color = _COLOR_PITCHER if player["role"] == "pitcher" else _COLOR_BATTER

    fig = plt.figure(figsize=(8, 8))
    ax = fig.add_subplot(111, projection="polar")

    ax.plot(angles, values, color=color, linewidth=2)
    ax.fill(angles, values, color=color, alpha=0.3)

    # Reference rings
    ax.set_ylim(0, 100)
    ax.set_yticks([25, 50, 75, 100])
    ax.set_yticklabels(["25", "50", "75", "100"], fontproperties=CJK)

    # Axis labels
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels([a["name"] for a in axes], fontproperties=CJK, fontsize=10)

    # Title
    ax.set_title(
        f"{player['name_zh']} #{player['uniform_no']} ({player['position_zh']}) - 中職百分位 (PR)",
        fontproperties=CJK,
        fontsize=14,
        pad=20,
    )

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()
