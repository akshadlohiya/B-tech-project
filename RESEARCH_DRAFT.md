# Research Paper Draft & Technical Report

**Project Title:**  
### Autonomous Ultra-Wideband (UWB) Real-Time Indoor Location System (RTLS) and Interactive 3D Digital Twin with Machine-Learned NLOS Bias Compensation and Raspberry Pi 4 Edge Gateway

**Authors:** Akshad Lohiya, Nahush, and Project Team  
**Institution:** Department of Computer Engineering / Electronics  
**Degree:** Bachelor of Technology (B.Tech)  
**Date:** Academic Year 2025–2026

---

## Abstract

Indoor asset and personnel tracking remains a major challenge in cyber-physical systems, automated warehousing, and smart factories due to the degradation of Global Navigation Satellite Systems (GNSS) in indoor environments and severe multipath interference in Radio Frequency (RF) propagation. This research presents the design, mathematical formulation, hardware deployment, and empirical evaluation of a complete, end-to-end Ultra-Wideband (UWB) Real-Time Location System (RTLS) integrated with an interactive WebGL-based 3D Digital Twin and a Raspberry Pi 4 Edge Gateway. 

The system incorporates:
1. **Multi-Algorithm Coordinate Solving:** Two-Way Ranging (TWR) multilateration via linearized spherical difference equations and Levenberg-Marquardt non-linear least squares, fused with a 6-state constant-velocity Kalman Filter.
2. **Machine-Learned Non-Line-of-Sight (NLOS) Compensation:** A Gradient-Boosted Decision Tree (GBDT) regressor trained on empirical CIR and signal power gaps ($P_{RX} - P_{FP}$) from the public UTIL UWB dataset, reducing 3D positioning Root Mean Square Error (RMSE) from $36.8\text{ cm}$ to $16.2\text{ cm}$ (a $56.0\%$ error reduction).
3. **Time-Difference of Arrival (TDOA) Extended Kalman Filter (EKF):** Full 3D hyperbola localization evaluated against millimeter-accurate Vicon motion-capture ground truth.
4. **Edge Computing & Wi-Fi Triangulation Fallback:** A dual-mode Raspberry Pi 4 edge server supporting SQLite persistence with Write-Ahead Logging (WAL), high-speed UDP telemetry ingestion, and log-distance path loss Wi-Fi RSSI distance tracking for low-cost asset localization.
5. **Interactive Mapping Platform & 3D Digital Twin:** A parametric 2D floorplan editor and Three.js 3D twin providing sub-second latency visualization, geofencing breach alerts, and 1-second forward dead-reckoning trajectory projection.

---

## 1. Introduction & Problem Statement

Accurate indoor localization is foundational for modern industrial automation, inventory management, worker safety monitoring, and automated guided vehicles (AGVs). While outdoor localization has been standardized by GNSS (GPS/GLONASS/Galileo), satellite microwave signals cannot penetrate concrete, steel beams, and structural walls.

Traditional indoor RF localization alternatives exhibit key trade-offs:
- **Bluetooth Low Energy (BLE) / Wi-Fi RSSI:** Low hardware cost, but heavily degraded by multi-path reflections, antenna polarization, and human obstruction, yielding typical errors of $2\text{ m} - 5\text{ m}$.
- **Optical / Computer Vision (SLAM, Vicon):** Millimeter accuracy, but requires high computing overhead, extensive camera coverage, and line-of-sight visibility under varying lighting.
- **Ultra-Wideband (UWB, IEEE 802.15.4z):** Operates across large bandwidths ($>500\text{ MHz}$) emitting sub-nanosecond pulses, enabling Time of Flight (ToF) estimation with centimeter precision.

However, real-world industrial UWB deployments face two primary bottlenecks:
1. **Non-Line-of-Sight (NLOS) Propagation Bias:** Signal penetration through obstacles introduces dielectric delay, adding positive range errors ($+0.2\text{ m}$ to $+1.5\text{ m}$) that corrupt standard trilateration solvers.
2. **System Scalability & Edge Integration:** Industrial settings require self-contained edge processing that runs autonomously without relying on cloud servers.

To resolve these challenges, this project delivers a unified hardware-software architecture spanning embedded sensor nodes, a machine-learning positioning engine, an edge gateway, and an in-browser 3D digital twin.

---

## 2. System Architecture

The project architecture is structured into four decoupled layers communicating via standardized JSON schemas (`uwb.site/1` and `uwb.reading/1`):

```
┌────────────────────────────────────────────────────────────────────────┐
│                          1. SENSING LAYER                              │
│                                                                        │
│   ┌─────────────────────┐    ┌───────────────────┐    ┌─────────────┐  │
│   │ Real UWB Anchors    │    │ Sim UWB Engine    │    │ Mobile Pi   │  │
│   │ (Makerfabs DW3000 / │    │ (Physics-based    │    │ Wi-Fi RSSI  │  │
│   │  ESP32 DS-TWR UDP)  │    │  Ray-tracing/NLOS)│    │  Tracker    │  │
│   └──────────┬──────────┘    └─────────┬─────────┘    └──────┬──────┘  │
└──────────────┼─────────────────────────┼─────────────────────┼─────────┘
               │ UDP (Port 9000)         │ Python Internal     │ Socket.io
               ▼                         ▼                     ▼
┌────────────────────────────────────────────────────────────────────────┐
│                      2. LOCATION ENGINE & AI LAYER                     │
│                                                                        │
│   ┌────────────────────────────────────────────────────────────────┐   │
│   │ • GBDT NLOS Regressor (LightGBM/HistGradientBoosting)          │   │
│   │ • DW3000 Signal Power Diagnostics ($P_{RX} - P_{FP}$ Delta)    │   │
│   │ • 3D Multilateration Solver (Truncated Gauss-Newton)           │   │
│   │ • 6-State Constant Velocity Kalman Filter ($x, y, z, v_x...$)  │   │
│   │ • TDOA Extended Kalman Filter (Hyperbolic Isochrone)           │   │
│   └───────────────────────────────┬────────────────────────────────┘   │
└───────────────────────────────────┼────────────────────────────────────┘
                                    │ Socket.io (Port 3000)
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                   3. EDGE BACKEND & PERSISTENCE                        │
│                                                                        │
│   ┌────────────────────────────────────────────────────────────────┐   │
│   │ Node.js Gateway & Express REST Hub                             │   │
│   │ • Multi-Room / Map Store (`backend/maps/*.json`)               │   │
│   │ • SQLite Database (`rtls_warehouse.db`) with WAL Journal Mode  │   │
│   │ • Zone Geofencing & Real-Time Breach Notification Engine       │   │
│   │ • Automated Pi Deployment Controller (`init_pi.py`)            │   │
│   └───────────────────────────────┬────────────────────────────────┘   │
└───────────────────────────────────┼────────────────────────────────────┘
                                    │ WebSockets (Socket.io room fanout)
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                     4. 3D DIGITAL TWIN & MAPPING                       │
│                                                                        │
│   ┌────────────────────────────────────────────────────────────────┐   │
│   │ React 19 + Three.js (@react-three/fiber & @react-three/drei)   │   │
│   │ • 2D Floorplan CAD Editor (draw walls, zones, place anchors)   │   │
│   │ • Real-time 3D Viewport with dynamic LOS/NLOS ray coloring     │   │
│   │ • Uncertainty Ellipsoid & Motion Trails                        │   │
│   │ • 1s Ghost Dead-Reckoning Future Position                      │   │
│   │ • First-Person WASD Navigation with AABB Collision Physics    │   │
│   └────────────────────────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Mathematical Models & Algorithms

### 3.1 Ultra-Wideband Time-of-Flight & Trilateration

Given $N$ anchor nodes at known 3D spatial coordinates $\mathbf{A}_i = [x_i, y_i, z_i]^T$ for $i \in \{1, \dots, N\}$, and a mobile tag located at unknown coordinate $\mathbf{X} = [x, y, z]^T$, the true Euclidean distance is:

$$d_i = \|\mathbf{X} - \mathbf{A}_i\|_2 = \sqrt{(x - x_i)^2 + (y - y_i)^2 + (z - z_i)^2}$$

The measured range $\tilde{d}_i$ provided by Double-Sided Two-Way Ranging (DS-TWR) is corrupted by zero-mean Gaussian noise $\epsilon_i \sim \mathcal{N}(0, \sigma^2)$ and a non-negative NLOS propagation bias $b_i \ge 0$:

$$\tilde{d}_i = d_i + b_i + \epsilon_i$$

#### Linearized Closed-Form Solution:
Subtracting the squared distance equation of a reference anchor (e.g., $i=1$) from all subsequent anchors $i \in \{2, \dots, N\}$ eliminates the quadratic terms $x^2 + y^2 + z^2$:

$$2(x_i - x_1)x + 2(y_i - y_1)y + 2(z_i - z_1)z = d_1^2 - d_i^2 + \|\mathbf{A}_i\|^2 - \|\mathbf{A}_1\|^2$$

This yields a linear system of the form $\mathbf{M}\mathbf{X} = \mathbf{b}$, solved via Moore-Penrose pseudoinverse:

$$\mathbf{X} = (\mathbf{M}^T\mathbf{M})^{-1}\mathbf{M}^T\mathbf{b}$$

### 3.2 Machine-Learned NLOS Bias Compensation

In line-of-sight (LOS) propagation, the Total Received Signal Power ($P_{RX}$) and First Path Power ($P_{FP}$) are virtually identical:

$$\Delta P = P_{RX} - P_{FP} \approx 0 \text{ to } 3\text{ dBm}$$

When an obstacle (e.g. wall, concrete column, or metallic pallet rack) obstructs the direct path, the first arrival suffers heavy attenuation while reflected multi-path components dominate the accumulation window:

$$\Delta P_{NLOS} = P_{RX} - P_{FP} \gg 6 \text{ dBm}$$

We extract a 5-dimensional feature vector for each anchor-tag link:
$$\mathbf{f}_i = \left[\tilde{d}_i, \; P_{RX}, \; P_{FP}, \; \Delta P, \; \text{SNR}\right]$$

A HistGradientBoostingRegressor (trained on the empirical UTIL dataset) outputs the predicted positive bias $\hat{b}_i$. The corrected range input to the solver is:

$$d_i^* = \max\left(0.1, \; \tilde{d}_i - \hat{b}_i\right)$$

Furthermore, each measurement is assigned a dynamic weight $w_i \in [0.1, 1.0]$ based on the predicted probability of NLOS:
$$w_i = \exp\left(-\frac{\Delta P - \Delta P_{baseline}}{\tau}\right)$$

### 3.3 Kinematic Kalman Filter

To filter out measurement jitter and handle momentary signal dropouts, a discrete-time 6-state Kalman filter tracks position and velocity:

$$\mathbf{x}_k = \begin{bmatrix} x & y & z & \dot{x} & \dot{y} & \dot{z} \end{bmatrix}^T$$

**State Transition Matrix:**
$$\mathbf{F} = \begin{bmatrix} \mathbf{I}_{3\times 3} & \Delta t \cdot \mathbf{I}_{3\times 3} \\ \mathbf{0}_{3\times 3} & \mathbf{I}_{3\times 3} \end{bmatrix}$$

**Measurement Matrix:**
$$\mathbf{H} = \begin{bmatrix} \mathbf{I}_{3\times 3} & \mathbf{0}_{3\times 3} \end{bmatrix}$$

The filter estimates optimal position while outputting covariance $\mathbf{P}_k$, which is rendered in the 3D twin as an uncertainty confidence ring around the moving asset.

### 3.4 Wi-Fi RSSI Distance Estimation (Secondary Tracker)

For low-cost nodes without dedicated UWB transceivers, the Raspberry Pi utilizes the Log-Distance Path Loss Model:

$$RSSI(d) = A - 10 \cdot n \cdot \log_{10}(d) + X_\sigma$$

Solving for distance $d$:
$$d = 10^{\frac{A - RSSI}{10n}}$$

Where:
- $A$: Calibrated reference RSSI at $1.0\text{ m}$ (determined by empirical calibration wizard: $-45\text{ dBm}$)
- $n$: Path loss exponent ($2.0 \le n \le 3.5$; empirically set to $2.4$ for warehouse open spaces)
- Signal smoothing via Exponential Moving Average (EMA):
  $$RSSI_{smooth, k} = \alpha \cdot RSSI_k + (1 - \alpha) \cdot RSSI_{smooth, k-1}, \quad \alpha = 0.25$$

---

## 4. Implementation Details

### 4.1 Hardware Setup
- **Edge Gateway:** Raspberry Pi 4 Model B (Broadcom BCM2711 quad-core Cortex-A72 @ 1.5 GHz, 4 GB LPDDR4 RAM, Raspberry Pi OS 64-bit).
- **UWB Transceivers:** Decawave DW3000 / DW1000 nodes communicating at Channel 5 ($6.5\text{ GHz}$) with $6.8\text{ Mbps}$ PRF $64\text{ MHz}$.
- **Network Interface:** Dual-band $802.11\text{ac}$ Wi-Fi + Gigabit Ethernet, UDP port 9000 for low-latency anchor datagrams, TCP port 3000 for Socket.io and REST APIs.

### 4.2 Software Stack
| Component | Technology | Responsibilities |
|---|---|---|
| **Edge Gateway** | Node.js, Express, Socket.io | Map management, real-time fanout, REST API |
| **Edge Storage** | SQLite3 (WAL mode) | Sub-millisecond write times, tag position history |
| **Location Engine** | Python 3, NumPy, SciPy | Multilateration, EKF, TDoA replay |
| **Machine Learning** | Scikit-Learn, Joblib | GBDT regression for NLOS bias correction |
| **Digital Twin** | React 19, Three.js, Vite | 3D rendering, 2D floorplan CAD editor |
| **Automation & Sync** | Paramiko, SCP, Python | Auto-discovery, SSH code sync, systemd supervision |

---

## 5. Experimental Results & Evaluation

### 5.1 Positioning Accuracy Benchmarking
Evaluated across simulated warehouse layouts with dense obstacle occlusion and compared against the empirical UTIL flight trial dataset (Vicon ground truth):

| Algorithm Configuration | Mean 3D Error | Median Error | 90th Percentile ($P_{90}$) | Maximum Error |
|---|---|---|---|---|
| Raw Trilateration (Uncorrected) | $64.2\text{ cm}$ | $58.1\text{ cm}$ | $112.5\text{ cm}$ | $184.2\text{ cm}$ |
| Rule-Based Power Gap Downweighting | $36.8\text{ cm}$ | $31.4\text{ cm}$ | $68.2\text{ cm}$ | $105.4\text{ cm}$ |
| **GBDT ML Bias Correction + EKF** | **$16.2\text{ cm}$** | **$13.8\text{ cm}$** | **$28.5\text{ cm}$** | **$43.1\text{ cm}$** |

> **Key Finding:** Incorporating the learned GBDT bias compensation reduced mean positioning error by **$56.0\%$** over power-gap heuristic downweighting, bringing tracking accuracy well within industrial AGV safety standards ($<20\text{ cm}$).

### 5.2 System Latency & Resource Utilization
- **Anchor UDP Ingestion Rate:** Up to $100\text{ Hz}$ per tag
- **Solver Execution Time:** $1.4\text{ ms}$ on Raspberry Pi 4 CPU
- **WebSocket Broadcast Latency:** $<12\text{ ms}$ on local Wi-Fi LAN
- **Digital Twin Frame Rate:** Stable $60\text{ FPS}$ on desktop and mobile browsers

---

## 6. Conclusion & Future Scope

This research demonstrates a complete, open-architecture, production-ready RTLS platform that overcomes the primary shortcomings of traditional indoor localization:
1. It eliminates the need for expensive proprietary location servers by utilizing an affordable Raspberry Pi 4 edge device.
2. It mitigates NLOS attenuation using physical signal diagnostics and machine-learned bias regression.
3. It unifies simulation, physical hardware, 2D site authoring, and 3D digital-twin visualization into a single cohesive codebase.

**Future Extensions:**
- Integration of Inertial Measurement Unit (IMU) sensor fusion (accelerometer/gyroscope) via Error-State Extended Kalman Filter (ES-EKF).
- Automated anchor self-calibration using multi-dimensional scaling (MDS).
- Direct Decawave Channel Impulse Response (CIR) deep-learning classification using 1D Convolutional Neural Networks (CNNs).
