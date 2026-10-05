#!/usr/bin/env python3
"""Render a detailed UML class diagram of the UWB RTLS project (matplotlib)."""
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Polygon, Rectangle
from matplotlib.lines import Line2D

HERE = os.path.dirname(os.path.abspath(__file__))
SS = os.path.join(os.path.dirname(HERE), "SS")

NAVY   = "#1F1F7A"
HDR    = "#D6DAF3"
HDR_IF = "#CDEBDD"   # interface / abstract
HDR_MOD= "#F3E4C8"   # module (functions)
BODY   = "#FBFBFE"
GREY   = "#555555"
LINE   = "#333333"

LH = 3.0      # line height
HH = 5.6      # header height
PAD = 1.4

fig, ax = plt.subplots(figsize=(16, 9), dpi=200)
ax.set_xlim(0, 160)
ax.set_ylim(94, -7)   # inverted: y grows downward; negative y = strip above the boxes
ax.axis("off")


def klass(x, ytop, w, name, stereo, attrs, methods, hdr=HDR):
    n = len(attrs) + len(methods)
    h = HH + n * LH + 2 * PAD + 1.0
    # outer box
    ax.add_patch(FancyBboxPatch((x, ytop), w, h, boxstyle="round,pad=0.15,rounding_size=0.6",
                                linewidth=1.6, edgecolor=NAVY, facecolor=BODY, zorder=3))
    # header
    ax.add_patch(Rectangle((x, ytop), w, HH, linewidth=0, facecolor=hdr, zorder=4))
    cx = x + w / 2
    if stereo:
        ax.text(cx, ytop + 1.7, stereo, ha="center", va="center", fontsize=7.5,
                style="italic", color=GREY, zorder=5)
        ax.text(cx, ytop + 4.0, name, ha="center", va="center", fontsize=10.5,
                fontweight="bold", color=NAVY, zorder=5)
    else:
        ax.text(cx, ytop + HH / 2, name, ha="center", va="center", fontsize=11,
                fontweight="bold", color=NAVY, zorder=5)
    ax.plot([x, x + w], [ytop + HH, ytop + HH], color=NAVY, lw=1.0, zorder=5)
    y = ytop + HH + PAD + 1.0
    for a in attrs:
        ax.text(x + 1.6, y, a, ha="left", va="center", fontsize=8.2, color=LINE, zorder=5)
        y += LH
    if attrs and methods:
        ax.plot([x, x + w], [y - LH / 2 + 0.3, y - LH / 2 + 0.3], color="#AAAAAA", lw=0.8, zorder=5)
    for m in methods:
        ax.text(x + 1.6, y, m, ha="left", va="center", fontsize=8.2, color=NAVY, zorder=5)
        y += LH
    return {"x": x, "y": ytop, "w": w, "h": h,
            "L": (x, ytop + h / 2), "R": (x + w, ytop + h / 2),
            "T": (cx, ytop), "B": (cx, ytop + h),
            "TL": (x, ytop), "cx": cx}


def realize(a, b):  # a ..|> b  (dashed, hollow triangle at b)
    ax.annotate("", xy=b, xytext=a, zorder=2,
                arrowprops=dict(arrowstyle="-|>", mutation_scale=20, fc="white",
                                ec=GREY, ls="dashed", lw=1.4))


def dep(a, b, label=""):  # a ..> b dependency (dashed open arrow)
    ax.annotate("", xy=b, xytext=a, zorder=2,
                arrowprops=dict(arrowstyle="-|>", mutation_scale=14, fc=NAVY,
                                ec=NAVY, ls="dashed", lw=1.2))
    if label:
        mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
        ax.text(mx, my - 1.4, label, ha="center", va="center", fontsize=7.5,
                style="italic", color="#3333AA", zorder=6,
                bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none"))


def diamond(pt, filled=True):
    x, y = pt; s = 1.7
    poly = Polygon([(x, y - s), (x + s, y), (x, y + s), (x - s, y)], closed=True,
                   facecolor=(NAVY if filled else "white"), edgecolor=NAVY, lw=1.3, zorder=6)
    ax.add_patch(poly)


def compose(owner_pt, child_pt, filled=True, label=""):
    ax.plot([owner_pt[0], child_pt[0]], [owner_pt[1], child_pt[1]], color=NAVY, lw=1.3, zorder=2)
    diamond(owner_pt, filled)
    if label:
        ax.text((owner_pt[0]+child_pt[0])/2 + 1.5, (owner_pt[1]+child_pt[1])/2, label,
                ha="left", va="center", fontsize=7.5, color=GREY, zorder=6)

# ============================ CLASSES =========================================
# ---- Left column: Anchor sources ----
c_iface = klass(2, 3, 34, "AnchorSource", "«interface / ABC»",
                [], ["+ cycles() : Iterator[(TagReading, truth)]"], hdr=HDR_IF)
c_sim = klass(2, 15, 34, "SimAnchorSource", "",
              ["- site : dict", "- movers : dict[str, _TagMover]", "- ranging : dict"],
              ["+ cycles()", "- _range_reading(anchor, tx,ty,tz) : AnchorRange", "- _zone_of(x, z)"])
c_hw = klass(2, 44, 34, "HardwareAnchorSource", "",
             ["- site : dict", "- sock : UDP socket"],
             ["+ cycles()", "- _parse_packet(data) : (tag, AnchorRange)"])
c_ds = klass(2, 61, 34, "DatasetTdoaSource", "",
             ["- csv_path : str", "- anchors : dict[int, Vec3]", "- _pose : PoseInterpolator"],
             ["+ events() : Iterator[TdoaEvent]", "- _load()"])
c_tsim = klass(2, 80, 34, "TdoaSimulator", "",
               ["- site : dict", "- model : GMM (tdoa_model.json)", "- materials : dict"],
               ["+ events(realtime) : Iterator[TdoaEvent]", "- _link(tag, anchor)", "- _noise(p_outlier)"])

# ---- Middle column: Data model ----
c_tr = klass(62, 5, 34, "TagReading", "«dataclass»",
             ["+ tag_id : str", "+ seq : int", "+ ranges : List[AnchorRange]",
              "+ source : str", "+ battery : int|None", "+ t : float", "+ schema : str"],
             ["+ to_dict()", "+ from_dict(d)"])
c_ar = klass(62, 44, 34, "AnchorRange", "«dataclass»",
             ["+ anchor_id : str", "+ range_m : float", "+ rx_power_dbm : float",
              "+ fp_power_dbm : float", "+ nlos : bool", "+ valid : bool", "+ t : float"],
             ["+ to_dict()"])
c_ev = klass(62, 74, 34, "TdoaEvent", "«dataclass»",
             ["+ t : float", "+ id_a : int", "+ id_b : int", "+ tdoa : float", "+ truth : Vec3"],
             [])

# ---- Right column: Location engine ----
c_le = klass(122, 4, 36, "LocationEngine", "",
             ["- site : dict", "- filters : dict[str, ConstantVelocityKF]"],
             ["+ estimate(reading, truth) : dict", "+ zone_of(x, z)", "+ load(site)"])
c_kf = klass(122, 30, 36, "ConstantVelocityKF", "",
             ["- x : state [x,z,vx,vz]", "- P : covariance", "- sigma_a, sigma_m"],
             ["+ step(px, pz, dt)"])
c_solv = klass(122, 50, 36, "solver", "«module»",
               [],
               ["+ solve_position(anchors, ranges, ...)", "+ nlos_weight(rx, fp, ...)"], hdr=HDR_MOD)
c_ekf = klass(122, 66, 36, "TdoaEKF", "",
              ["- x : state (3D CV)", "- P : covariance", "- gate : chi-square"],
              ["+ predict(dt)", "+ update(tdoa, a_A, a_B) : bool",
               "+ position() / velocity()", "+ initialize(pos)"])

# ============================ RELATIONSHIPS ===================================
# realizations (implement the interface)
realize((c_sim["cx"], c_sim["y"]), (c_iface["cx"], c_iface["y"] + c_iface["h"]))
realize((c_hw["x"] + 4, c_hw["y"]), (c_iface["x"] + 4, c_iface["y"] + c_iface["h"]))

# sources create data objects (dashed «create»)
dep(c_sim["R"], (c_tr["x"], c_tr["y"] + 8), "«create»")
dep(c_hw["R"], (c_tr["x"], c_tr["y"] + 16), "«create»")
dep(c_ds["R"], (c_ev["x"], c_ev["y"] + 8), "«create»")
dep(c_tsim["R"], (c_ev["x"], c_ev["y"] + 4), "«create»")

# TagReading aggregates AnchorRange (hollow diamond)
compose((c_tr["cx"], c_tr["y"] + c_tr["h"]), (c_ar["cx"], c_ar["y"]), filled=False, label="1..*")

# engine consumes data objects (dashed «consume»)
dep(c_le["L"], c_tr["R"], "«consume»")
dep(c_ekf["L"], c_ev["R"], "«consume»")

# engine internal structure
compose((c_le["cx"], c_le["y"] + c_le["h"]), (c_kf["cx"], c_kf["y"]), filled=True, label="per tag")
dep((c_le["R"][0], c_le["y"] + 14), (c_solv["R"][0], c_solv["y"] + 4), "«use»")

# ============================ LEGEND ==========================================
ly = -3.5
items = [(2,   "──▷  realize (implements)"),
         (58,  "--▷  dependency  (create / use / consume)"),
         (116, "◆──  composition    ◇──  aggregation")]
for lx, txt in items:
    ax.text(lx, ly, txt, ha="left", va="center", fontsize=8.2, color=NAVY,
            bbox=dict(boxstyle="round,pad=0.25", fc="#F0F0FA", ec="#CCCCDD"))

ax.set_title("UML Class Diagram — UWB RTLS Pipeline (anchor sources · data model · location engine)",
             fontsize=13, fontweight="bold", color=NAVY, pad=10)

fig.tight_layout()
fig.savefig(os.path.join(HERE, "uml_class.png"), bbox_inches="tight", facecolor="white")
fig.savefig(os.path.join(SS, "uml_class.png"), bbox_inches="tight", facecolor="white")
plt.close(fig)
print("wrote uml_class.png")
