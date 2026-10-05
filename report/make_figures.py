#!/usr/bin/env python3
"""Generate the architecture diagram and accuracy bar chart for the presentation."""
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

HERE = os.path.dirname(os.path.abspath(__file__))
SS = os.path.join(os.path.dirname(HERE), "SS")

BLUE   = "#2A2AA8"
BLUEDK = "#1F1F7A"
LIGHT  = "#E9E9F4"
GREEN  = "#22A06B"
AMBER  = "#E08A1E"
GREY   = "#555555"

# ------------------------------------------------------------------ ARCHITECTURE
def architecture():
    fig, ax = plt.subplots(figsize=(11, 3.6), dpi=200)
    ax.set_xlim(0, 100); ax.set_ylim(0, 40); ax.axis("off")

    boxes = [
        (2,  "Anchor Source", ["sim OR real hardware", "DS-TWR ranges +", "power diagnostics"]),
        (27, "Location Engine", ["multilateration (WLS)", "+ NLOS down-weighting", "+ Kalman filter"]),
        (52, "Backend Hub", ["Node.js + Socket.IO", "relay + serves", "/api/site"]),
        (77, "Digital Twin", ["React + Three.js", "live tags, trails,", "zones, accuracy HUD"]),
    ]
    w, h, y = 21, 18, 12
    centers = []
    for x, title, lines in boxes:
        box = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.6,rounding_size=1.5",
                             linewidth=2, edgecolor=BLUEDK, facecolor=LIGHT)
        ax.add_patch(box)
        ax.text(x + w/2, y + h - 3.4, title, ha="center", va="center",
                fontsize=14, fontweight="bold", color=BLUEDK)
        for i, ln in enumerate(lines):
            ax.text(x + w/2, y + h - 7.5 - i*3.2, ln, ha="center", va="center",
                    fontsize=9.5, color="#222222")
        centers.append((x, x + w))

    labels = ["readings", "estimate", "pos / vel / cov"]
    for (l, r), lab in zip(zip([c[1] for c in centers[:-1]], [c[0] for c in centers[1:]]), labels):
        arr = FancyArrowPatch((l + 0.5, y + h/2), (r - 0.5, y + h/2),
                              arrowstyle="-|>", mutation_scale=22, linewidth=2.4, color=BLUE)
        ax.add_patch(arr)
        ax.text((l + r)/2, y + h/2 + 2.4, lab, ha="center", va="center",
                fontsize=9, style="italic", color=GREY)

    # interface seam note under the first box
    ax.text(12.5, 6.5, "AnchorSource interface:\nSimAnchorSource  ↔  HardwareAnchorSource",
            ha="center", va="center", fontsize=9, color=GREEN, fontweight="bold")
    ax.annotate("", xy=(12.5, 11.5), xytext=(12.5, 9.2),
                arrowprops=dict(arrowstyle="-", color=GREEN, linewidth=1.2))

    ax.text(50, 37.5, "One codebase, sim or hardware  —  identical versioned data format",
            ha="center", va="center", fontsize=12, fontweight="bold", color=BLUE)

    fig.tight_layout(pad=0.3)
    for ext, path in [("png", os.path.join(HERE, "architecture.png"))]:
        fig.savefig(path, bbox_inches="tight", facecolor="white")
    fig.savefig(os.path.join(SS, "architecture.png"), bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("wrote architecture.png")

# ------------------------------------------------------------------ ACCURACY BAR
def accuracy():
    labels = ["Range solver\n(raw)", "+ Kalman\nfilter",
              "TDOA-EKF\nUTIL const1/2", "TDOA-EKF\nUTIL const3",
              "Generative\nTDOA sim"]
    values = [0.65, 0.62, 0.19, 0.33, 0.50]
    colors = [AMBER, "#C9781A", GREEN, "#7FB77E", BLUE]
    annot  = ["~0.6-0.7 m", "~4-5% ↓", "best: 0.18-0.20 m", "cluttered", "warehouse"]

    fig, ax = plt.subplots(figsize=(9, 4.6), dpi=200)
    bars = ax.bar(labels, values, color=colors, edgecolor="#333333", linewidth=0.8, width=0.62)
    for b, v, a in zip(bars, values, annot):
        ax.text(b.get_x() + b.get_width()/2, v + 0.012, f"{v:.2f} m",
                ha="center", va="bottom", fontsize=11, fontweight="bold", color="#222222")
        ax.text(b.get_x() + b.get_width()/2, v/2, a, ha="center", va="center",
                fontsize=8.5, color="white", fontweight="bold", rotation=0)

    ax.set_ylabel("Position error  (m)", fontsize=12, fontweight="bold", color=BLUEDK)
    ax.set_title("Positioning accuracy across pipelines  (lower is better)",
                 fontsize=13, fontweight="bold", color=BLUE, pad=12)
    ax.set_ylim(0, 0.8)
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    ax.tick_params(axis="x", labelsize=10)
    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)
    # divider: sim vs real-data
    ax.axvline(1.5, color=GREY, linestyle=":", linewidth=1.2)
    ax.text(0.5, 0.76, "simulated", ha="center", fontsize=9, style="italic", color=GREY)
    ax.text(3.0, 0.76, "real UTIL data / learned", ha="center", fontsize=9, style="italic", color=GREY)

    fig.tight_layout()
    fig.savefig(os.path.join(HERE, "accuracy_chart.png"), bbox_inches="tight", facecolor="white")
    fig.savefig(os.path.join(SS, "accuracy_chart.png"), bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("wrote accuracy_chart.png")

if __name__ == "__main__":
    architecture()
    accuracy()
