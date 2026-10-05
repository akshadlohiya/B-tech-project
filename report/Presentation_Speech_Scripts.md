# Presentation Speech Scripts — UWB Indoor RTLS + Live 3D Digital Twin

Spoken scripts and Q&A prep for the T.Y. B.Tech project defense.

**Contents**
1. [Full Script (~40 minutes)](#part-1--full-script-40-minutes)
2. [Tight Cut (~20 minutes)](#part-2--tight-cut-20-minutes)
3. [Q&A Cheat-Sheet](#part-3--qa-cheat-sheet)

Speaker cues are in *(italics)*. Aim ~150 words/min.

---

# PART 1 — FULL SCRIPT (~40 minutes)

## SLIDE 1 — Title

"Good morning everyone. Thank you for being here. My name is Nahush, and along with my team I'll be presenting our Third Year B.Tech project titled *UWB Indoor Real-Time Location System with a Live 3D Digital Twin*.

Let me frame what that mouthful actually means in one sentence. We've built a complete system that can track exactly where people and assets are located — live, indoors — in an environment where the usual tool for location, GPS, simply does not work. And on top of that tracking engine, we've built a 3D visual 'digital twin' — a live, interactive model of the space where you can literally watch tagged items move around in real time.

This project was carried out in the Department of Computer Science and Engineering at COEP Technological University, under the guidance of Professor *(name)*. Over the course of the presentation, I'll take you from the real-world problem, through the science, the architecture, our methodology, our results, and where the project stands today. Let's begin."

*(Pause, move to agenda.)*

## SLIDE 2 — Agenda

"Here's the roadmap for the next half hour or so, so you always know where we are.

I'll start with the *problem* and *why it matters* — the motivation. Then I'll state our concrete *objectives*. After that, a *background* on how UWB positioning actually works, because that's essential to understand the rest. Then I'll cover the single hardest technical challenge in this field — something called the *Non-Line-of-Sight problem*.

From there I'll walk through our *literature survey* and the *reference dataset* we used, which leads naturally into the *research gap* — the specific shortcomings in existing work that our project sets out to fix. Then the fun part: our *proposed system*, its *architecture*, and the *methodology* in two stages. I'll spend some time on our *data-driven calibration*, which is one of our standout contributions. Then *results*, *testing*, *implementation status*, *conclusion*, and finally *limitations and future work*.

One idea per slide — so let's dive in."

## SLIDE 3 — Problem Statement

"Let's start with the problem, because everything else follows from it.

We are all used to GPS. You open a maps app outdoors and it knows where you are within a few metres. But the moment you step inside a building, GPS falls apart. GPS signals come from satellites roughly twenty thousand kilometres away, and by the time those weak signals reach the ground and try to pass through a concrete roof and walls, they're either blocked entirely or so distorted that the position is useless. So indoors, GPS is effectively blind.

Now, people have tried to fill this gap with the wireless signals we already have indoors — Wi-Fi and Bluetooth. The trouble is that these are *narrowband* technologies, and they suffer badly from something called multipath — the signal bounces off walls, floors, furniture, and arrives multiple times. The result is that Wi-Fi and Bluetooth positioning typically give you errors ranging from a metre to *tens* of metres. That's the difference between 'the item is on this shelf' and 'the item is somewhere on this floor of the building.' For many real applications, that's not good enough.

And there are many real applications. Think of a large warehouse that needs to know where every forklift and every pallet is. Think of a hospital that needs to locate a critical piece of equipment — an infusion pump or a portable ventilator — in seconds during an emergency. Think of a factory that needs to keep workers out of dangerous zones. All of these need to know *where things are, live, indoors* — and they need it accurate.

So the problem we set for ourselves was this: build an end-to-end indoor real-time location system. It has to *range* the tags — measure distances — then *solve* for position from measurements that are noisy and sometimes partially blocked, then *smooth* that position over time, and finally *visualise* it live. And — this is the crucial architectural constraint we imposed on ourselves — it must be built so that the *exact same software* runs on a simulator today, and on real hardware tomorrow, with minimal change. I'll come back to why that constraint is so important."

## SLIDE 4 — Motivation

"So if GPS, Wi-Fi, and Bluetooth all fall short indoors, what's the answer? Our answer is UWB — Ultra-Wideband.

Let me explain why UWB is fundamentally better for this. Instead of a narrow, continuous radio wave, UWB transmits *ultra-short pulses* that are spread across a very wide band of frequencies. Because these pulses are so short in time — on the order of nanoseconds — you can time their arrival extremely precisely. And precise timing is everything, because distance in these systems is measured from the time a signal takes to travel. Radio waves travel at the speed of light, so one nanosecond of timing error is about thirty centimetres of distance error. UWB's fine time resolution is what pushes accuracy down from metres to *centimetres and decimetres*.

There's a second benefit. Because the pulse is so sharp, the *first* signal to arrive — the one that took the direct path — can be distinguished from the later echoes that bounced off walls. That's called multipath rejection, and it's exactly the weakness that cripples Wi-Fi and Bluetooth. UWB largely solves it.

Now, the second half of our motivation: the digital twin. Suppose we nail the accuracy and we produce a stream of coordinates — X equals 12.4 metres, Z equals 7.1 metres. That's meaningless to a human operator. Nobody manages a warehouse by reading coordinate pairs. What operators actually need is to *see* their space — a labelled 3D floor plan with items moving around on it in real time, with zones highlighted and alerts when something goes wrong. That's what a digital twin gives you: it turns raw numbers into something legible and actionable.

Here's the contrast I'd like you to hold in your mind for the rest of the talk. A Bluetooth system tells you 'the item is *somewhere in this aisle*.' A UWB system with a good digital twin tells you '*this* pallet, at *this* exact spot, moving in *this* direction.' That's the leap we're targeting."

## SLIDE 5 — Objectives

"With that motivation, here are the seven concrete objectives we committed to. Let me go through them, because collectively they define the scope of the project.

*First*, a single, versioned data contract shared by both the simulator and the real hardware — so that the two are genuinely interchangeable. This sounds like a small thing but it's the backbone of the whole design.

*Second*, a hardware-faithful UWB simulator. Not a toy — one that models the real physics: the double-sided two-way ranging protocol, line-of-sight versus blocked signals, systematic bias, power diagnostics, and even dropped readings.

*Third*, a multilateration solver — the maths engine that takes several noisy distance measurements and computes a position — with the intelligence to *down-weight* the untrustworthy measurements based on a power-gap diagnostic from the radio chip.

*Fourth*, a constant-velocity Kalman filter, which smooths the track over time and additionally gives us velocity and a measure of uncertainty.

*Fifth*, a fully config-driven 3D digital twin — with movement trails, uncertainty rings, zone labels, and a live accuracy dashboard.

*Sixth* — and this is a research contribution — to calibrate and validate our noise and NLOS model against *real* UWB data with millimetre-accurate ground truth.

And *seventh*, to keep the eventual hardware integration down to a single drop-in file. If it takes more than that, we've failed the architecture.

Keep these seven in mind — at the end I'll show you exactly which are done."

## SLIDE 6 — Background: How UWB Positioning Works

"Before I go further, let me give you the essential background on *how* UWB actually computes a position, because the rest of the talk depends on it.

There are two broad families of methods.

The first is *ranging-based*, and specifically *Two-Way Ranging*, or TWR. The idea is intuitive: a tag and an anchor exchange messages, and by measuring the round-trip time, you compute the distance between them. Do this with several anchors around the room and you get several distances — several radii — and where those circles intersect is the tag's position. Now, there's a subtle problem: the tag's clock and the anchor's clock are never perfectly in sync, and tiny clock differences cause big distance errors. The elegant fix is *Double-Sided* Two-Way Ranging — DS-TWR — where messages go back and forth in a way that mathematically *cancels* the clock drift. The huge practical benefit is that the anchors do *not* need to be time-synchronised with each other. That massively simplifies deployment, and this is exactly the method our target hardware uses.

The second family is *TDOA* — Time Difference of Arrival. Here the anchors are all tightly synchronised with each other, and instead of measuring round trips, they compare the *arrival times* of a single signal from the tag. The difference in arrival times between pairs of anchors defines a hyperbola, and the intersections of these hyperbolas give the position. TDOA scales beautifully to a very large number of tags — because tags just transmit and don't need to converse — but it pays for that with a strict requirement for tight synchronisation between anchors.

*(Point to diagram.)* On the diagram you can see a tag with four ceiling-mounted anchors, and the range circles intersecting at the tag's location. That intersection is what our solver has to find. Keep both of these — TWR and TDOA — in mind, because our main system uses ranging, but we also built an optional TDOA track that I'll cover later."

## SLIDE 7 — The NLOS Problem

"Now we arrive at the single most important technical challenge in this entire field — and the one our project is really *about*. It's the Non-Line-of-Sight problem, or NLOS.

Here's the scenario. In an ideal world, the signal travels in a straight line from tag to anchor — that's Line-of-Sight, or LOS. But in a real warehouse full of shelving, machinery, and people, that direct path is often *blocked*. When it's blocked, the signal doesn't just vanish — it finds its way to the anchor by *bouncing* off a wall or the ceiling. And here's the key consequence: because the bounced path is *longer* than the direct path would have been, the measured distance comes out *too large*.

Now here's the insight that shapes our whole approach, and I want to emphasise it. *(Slow down.)* NLOS error is not random noise. It is a *positive bias* — the range is always reported *longer*, never shorter. And that distinction matters enormously. If it were random, zero-mean noise, you could simply average many readings and it would cancel out. But a bias doesn't cancel — you can average a million blocked readings and they'll still all be biased long. So you *cannot* filter or average your way out of NLOS. You have to *detect* it and *handle* it explicitly.

So how do we detect it? This is where the hardware helps us. The DW3000 UWB chip exposes two power measurements: the *total received power*, and the *first-path power* — the power of that very first, direct-path arrival. In a clean line-of-sight situation, most of the energy is in the first path, so these two numbers are close. But when the direct path is blocked and the signal only reaches the anchor via reflections, the first-path power collapses relative to the total. So a *large gap* between received power and first-path power is a strong tell-tale sign that this link is Non-Line-of-Sight.

*(Point to visual.)* That gap is the diagnostic we exploit. It's the signal we use to *down-weight* the bad links in our solver — to tell the maths engine, 'trust this measurement less.' Remember this power gap — it comes up again and again throughout the project."

## SLIDE 8 — Literature Survey

"With the problem clear, let me summarise the literature that informed our design. We studied five key works, and each contributed something specific.

*(Walk the table row by row.)*

Paszek and colleagues, published in Sensors in 2021, built a UWB simulator that models line-of-sight and non-line-of-sight conditions and analysed the resulting accuracy. This was essentially our *blueprint* for building a hardware-faithful simulator rather than a toy.

Next, a 2025 paper in Applied Sciences focused on NLOS-*exclusion* positioning — deliberately identifying and handling blocked measurements. They reported a root-mean-square error of 0.124 metres and roughly a 24 percent improvement. The lesson we took was clear: NLOS-aware weighting is the single biggest lever you can pull for accuracy. That directly justified where we spent our effort.

A 2024 Applied Sciences paper on real UWB deployment gave us practical guidance on anchor geometry and error budgeting — where to place anchors and what accuracy to expect.

Then the one that mattered most for validation: Zhao and colleagues, published in the International Journal of Robotics Research in 2024 — the *UTIL* dataset. This provides raw TDOA measurements, the power-difference diagnostics, and crucially, *millimetre-accurate* ground truth from a Vicon motion-capture system. That's what let us validate against reality.

And finally, a 2018 paper in the Alexandria Engineering Journal on UWB error modelling supported our overall error model.

The through-line across all of this: modelling NLOS well is where the accuracy is won or lost."

## SLIDE 9 — Reference Dataset: UTIL

"Let me spend a moment on that UTIL dataset, because it's central to one of our contributions.

UTIL comes from the Dynamic Systems Lab at the University of Toronto, published in 2024. It was collected using Decawave DWM1000 UWB modules, across four different anchor configurations, over roughly 150 minutes of drone flights.

What makes it so valuable is the *completeness* of what it records. For every measurement you get the raw TDOA values, the signal-to-noise and power-difference information — which lets you label readings as line-of-sight or non-line-of-sight — plus IMU data, altitude, and, most importantly, *millimetre-level ground truth* from a Vicon motion-capture system. It even ships with a reference Extended Kalman Filter and data parsers. In short, it's a gold-standard dataset — real hardware, in real conditions, with a near-perfect answer key.

But — and this is an important honesty point that examiners appreciate — there's a cross-radio caveat. UTIL was captured with the DWM1000 chip, and our target hardware uses the newer DW3000. Different chip, different antenna, slightly different noise characteristics. So we treat any model we fit from UTIL not as a finished truth to transplant directly onto our hardware, but as a well-founded *prior* — a strong starting point that will need re-calibration once our own hardware is running. Being clear about that boundary is part of doing this properly."

## SLIDE 10 — Research Gap

"So, having surveyed the field, what's actually *missing*? This slide is the heart of the 'why this project' question, so let me be precise.

We found three recurring shortcomings in existing simulators and systems.

*First*, and this genuinely surprised us — many existing simulators quietly *cheat*. On screen they display the measured distances, which looks impressive, but internally they send the *true, known* position straight to the display. There's no actual solving happening. There's no NLOS handling. And so the accuracy they show is *fake* — it can't be anything else, because they already knew the answer. A simulator like that teaches you nothing about how the real system will behave.

*Second*, in systems that *do* handle NLOS, the weighting constants — how much to distrust a bad link — are usually *hand-tuned*. Someone picks numbers that look reasonable. They're not fitted from real data, so there's no guarantee they reflect reality.

*Third*, the simulator and the hardware are typically built as *separate codebases*. So all the work you do validating the simulator has to be substantially redone when the hardware arrives. That makes hardware bring-up slow, risky, and expensive.

So here are our three gap-closing contributions, which map one-to-one onto those problems. *One*: a pipeline that *actually estimates* position from noisy ranges — no peeking at the truth. *Two*: a *data-driven* NLOS and noise model, fitted on real millimetre-truth data rather than guessed. And *three*: *one codebase* — the simulator and the hardware sit behind a single shared interface, so everything you validate in simulation carries straight over to hardware. These three points are, in essence, our project's original contribution."

## SLIDE 11 — Proposed System

"So here is our proposed system at a high level. The whole thing is a pipeline of four stages.

An *Anchor Source* produces the raw ranging readings. That feeds into a *Location Engine*, which does the actual position estimation. That feeds a *Backend Hub*, which relays the data. And that feeds the *Frontend Digital Twin*, which visualises everything live.

But the single most important idea on this slide is the design principle underneath it: *one codebase, sim or hardware*. Because the anchor source — whether it's our simulator or the real hardware — emits data in an *identical, versioned format*, everything downstream of it is completely *source-agnostic*. The location engine doesn't know or care whether the readings came from a simulation or from a physical tag on a warehouse floor. It just sees readings in the standard format.

*(Emphasise the callout.)* And here's the payoff of that principle, which I want to highlight. It means we could develop, test, and fully validate the *entire* system — solver, filter, calibration, visualisation, all of it — *before any hardware ever arrived*. And when the hardware does arrive, integrating it is, by design, a *single file*. That's how we turned a hardware project into something we could de-risk almost entirely in software first."

## SLIDE 12 — System Architecture

"This slide shows the same pipeline in concrete engineering terms. *(Walk the diagram left to right.)*

On the left, the `anchor-source`. This can be either the simulator or the real hardware, and either way it speaks DS-TWR — the double-sided two-way ranging I described earlier.

That flows into the `location-engine`, which is where the real computation lives — the multilateration solver *and* the Kalman filter together.

The engine's output goes to the `backend`, which is a Socket.IO relay — it broadcasts the live position stream over web sockets — and also serves an `/api/site` endpoint that provides the site configuration.

And finally the `frontend`, built with React and Three.js, renders the live 3D digital twin in the browser.

Now, the critical piece of the architecture — *(point to it)* — is this seam, the `AnchorSource` interface. On one side of the seam sits `SimAnchorSource`, our simulator. On the other side sits `HardwareAnchorSource`, the real hardware driver. Everything downstream talks only to the *interface*, not to a specific implementation. And switching between them is as simple as an environment variable: `SOURCE=sim` or `SOURCE=hardware`. This seam is what makes the 'one codebase' promise real rather than aspirational."

## SLIDE 13 — Data Contracts & Shared Site Config

"For that interchangeability to actually work, the data contracts have to be rock-solid and precisely defined. There are three that matter.

*First*, the *Reading*, versioned as `uwb.reading/1`. This is what the anchor source emits. For each anchor it carries the measured range, plus the received-power and first-path-power values I mentioned, plus flags for whether the link looks non-line-of-sight and whether the reading is valid. And I want to draw your attention to one deliberate design decision: *no ground truth is ever passed to the solver.* Even in simulation, where we obviously *know* the true position, we never leak it into the reading. That's what forces the solver to do real work and keeps our accuracy numbers honest — it directly addresses the 'cheating simulator' gap.

*Second*, the *Estimate*. This is what the engine produces: the estimated position, the velocity, the covariance — which is our measure of uncertainty — the raw pre-Kalman fix, the true position *only* in simulation for evaluation, the current zone, and any alerts.

*Third*, and tying it all together, `site.json`. This is our single source of truth, all in metres. It defines the anchors, the walls and their materials, the zones, the tag routes, and the ranging and noise model. And every single value in it is *provenance-tagged* — labelled as guessed, measured, tested, or calibrated. That means at any moment we know exactly how much to trust every number in our configuration. That discipline is what makes the calibration story I'm about to tell you credible."

## SLIDE 14 — Methodology, Part 1: Simulator and Solver

"Now let's get into the methodology — how it actually works — in two parts. First, the simulator and the solver.

The `SimAnchorSource` is deliberately *pessimistic* — it injects all the imperfections a real system would suffer, so that anything that works in simulation stands a real chance of working on hardware. Specifically, it injects: antenna-delay bias — a fixed offset every real radio has; Gaussian measurement noise; wall-occlusion logic that decides line-of-sight versus non-line-of-sight based on the geometry; and critically, a *positive-only* NLOS bias that depends on the wall material — because, remember, NLOS always makes the range *longer*. It also generates the power diagnostics and occasionally *drops* readings, just as a real system would. The tag moves along waypoints, driven by a simulated clock.

Then the solver. This is *Weighted Least Squares*. Conceptually, it searches for the position `p` that best fits all the measured ranges at once — it minimises the sum, over all anchors, of the weighted squared difference between the *predicted* distance to each anchor and the *measured* range. We solve that using the Levenberg–Marquardt algorithm from SciPy's `least_squares`. And here's where our NLOS work pays off: the *weights* down-weight the non-line-of-sight measurements according to that power gap. A link that looks blocked contributes less to the solution. We seed the search from either the centroid of the anchors or the last known position, so it converges quickly.

And the result: *(emphasise)* on a known test point, the solver recovers the true position to *better than one centimetre*. And just as importantly, it demonstrably *beats* the naive approach of trusting a biased anchor equally — which validates that the weighting actually earns its keep."

## SLIDE 15 — Methodology, Part 2: Kalman Filter and Digital Twin

"The second part of the methodology sits on top of the solver: the Kalman filter and the digital twin.

Each tag gets its own *Constant-Velocity Kalman filter*. The state we track is four numbers: position in x and z, and velocity in x and z. The filter runs a two-step cycle: it *predicts* where the tag should be after a small time step, assuming it keeps moving at its current velocity, and then it *updates* that prediction using the latest raw fix from the solver. The output is a smoothed position, a velocity estimate, and a covariance — an uncertainty ellipse. All the filter's tuning parameters live in the config file, so we can adjust its behaviour without touching code.

Now let me be honest about what the Kalman filter does and doesn't buy us — because this ties back to the NLOS insight. Because NLOS error is a *systematic bias* rather than random noise, the filter can't magically remove it, so the headline accuracy improvement is *modest* — around four to five percent. But — and this is the point — the *usability* win is large: you get smooth, non-jittery tracks instead of a jumping dot, you get a real velocity vector, and you get a principled uncertainty estimate. Those are exactly what an operator needs.

*(Gesture to screenshot.)* And here's the twin itself. You can see live tags moving; fading trails showing recent paths, with the true path overlaid in simulation for comparison; uncertainty rings that grow and shrink with confidence; zone labels; and a live accuracy dashboard — the HUD — that continuously reports Kalman-versus-raw error as mean, median, 90th percentile, and percent improvement. The anchor lines are colour-coded green for line-of-sight and red for non-line-of-sight, so you can see the geometry of trust at a glance. And there's an interactive *Edit-Map* mode with hot-reload, so you can rearrange the whole environment and watch the system respond instantly."

## SLIDE 16 — Data-Driven NLOS Calibration

"This slide is one I'm particularly proud of, because it's where we turn the research gap into a concrete contribution.

Recall the second gap: NLOS constants are usually hand-tuned. We refused to do that. Instead, we wrote a script — `calibrate_from_util.py` — that takes the real UTIL dataset and *fits* the actual range-error statistics from it. There's a nice bit of maths here: because TDOA is a *difference* of two ranges, its variance is twice the variance of a single range, so we recover the single-range standard deviation by dividing the TDOA standard deviation by the square root of two. The script then *patches those fitted values straight into* `site.json`, tagging them as `calibrated:UTIL-IJRR2024` so their provenance is recorded.

And here's the headline finding — *(slow down)* — the real data *confirmed* our core hypothesis. NLOS behaves as a *positive bias* of roughly three to forty centimetres. It is *not* extra noise. The data agreed with the physics.

*(Walk the table.)* Look at what calibration changed. Our line-of-sight noise standard deviation dropped from a guessed 0.08 metres to a fitted 0.054. Our NLOS noise, which we'd guessed at a large 0.30 metres, actually turned out to be the *same* 0.054 as line-of-sight — confirming that the extra error is bias, not noise. And the NLOS bias itself, which we'd guessed at a quarter to over a metre, was in reality a much tighter 0.026 to 0.399 metres.

And here's the beautiful part, which validates the whole architecture: because the simulator reads its entire model from the config file, applying all of this calibration was a *data change, not a code change*. We didn't touch a single line of the simulator. That's the config-driven design paying off directly."

## SLIDE 17 — Optional Track: TDOA-EKF on Real Data

"I want to briefly cover an optional, more advanced track we built — and I'll be clear that it was deliberately kept *off the critical path* of the main deliverable. Think of it as a walled-off research extension whose purpose was to *prove* we could run an Extended Kalman Filter on genuinely hardware-grade data.

There are two pieces. First, a `DatasetTdoaSource` that *replays* the real UTIL flights through our system. There's a nice detail here: the ground truth and the TDOA measurements aren't recorded at exactly the same instants, so we *interpolate* the truth to each measurement's timestamp. That one fix alone improved the effective ground-truth error from about 1.2 metres down to roughly 9 centimetres — a big correctness win from careful data handling.

Second, the `TdoaEKF` itself — a full 3D constant-velocity Extended Kalman Filter. Because TDOA's measurement model is a *difference* of distances, it's non-linear, so we *linearise* it at each step — that's what makes it 'Extended.' It has a *chi-square gate* that statistically rejects outlier measurements — which is exactly how it throws out NLOS spikes — and it *cold-starts* using Gauss–Newton without ever using the ground truth, so it's an honest test.

On top of that, we also built a *generative* TDOA simulator: we learned a two-component Gaussian mixture model of the real error distribution, which lets us generate realistic synthetic data on *any* editable layout — you can literally load a warehouse map with `?map=wh-tdoa` and it just works."

## SLIDE 18 — Results

"So, let's talk numbers. This is what all of that produces. *(Walk the table.)*

Our main range solver, on simulated line-of-sight and non-line-of-sight conditions, achieves roughly 0.6 to 0.7 metres median error on the raw weighted-multilateration fix.

Adding the constant-velocity Kalman filter improves the mean by about four to five percent — and as I explained, that number is modest precisely *because* the error is bias-dominated, but the filter adds velocity, uncertainty, and smoothness on top.

Now the real-data results, which are the ones I'd point an examiner to. On the real UTIL data, in the first two anchor constellations, our TDOA-EKF achieves roughly *0.18 to 0.20 metres RMSE* — that's measured against millimetre Vicon ground truth. In the third, more cluttered constellation, it's about 0.33 metres, with the chi-square gate dropping around three percent of readings as outliers. And our generative TDOA simulator, on a warehouse layout, gives about half a metre horizontal RMSE.

*(Emphasise the takeaway.)* But the single most important lesson from all these results is this: *bias dominates the error*. And the practical consequence of that is that *intelligent weighting and good calibration matter more than throwing a heavier, fancier filter at the problem*. That's the engineering insight this whole project earns."

*(If a live demo is possible, cue it here: "Before I move on, let me show you the system running live…")*

## SLIDE 19 — Testing and Verification

"A results table is only as trustworthy as the testing behind it, so let me show you how we verified everything.

We have *21 automated tests*, written with pytest, and *all of them pass*. And they're not superficial — they cover every claim I've made. There are tests that confirm the solver recovers a known point to under a centimetre and that it beats a biased anchor. There are tests confirming the Kalman filter genuinely reduces mean error on a noisy trajectory. There are tests confirming the calibration correctly reproduces the line-of-sight standard deviation and the positive-only NLOS bias. And there are tests for the EKF on both synthetic and real trials.

Beyond automated tests, there's the *end-to-end demo*, which is the most convincing check of all. You can watch the raw fix visibly jitter around, while the Kalman track glides smoothly through it, and the on-screen dashboard confirms in real time that the filtered error is lower than the raw error. Seeing is believing.

And finally, the *hardware-readiness check* — the one that validates our central architectural claim. We verified that swapping `SimAnchorSource` for `HardwareAnchorSource` is *the only change required*. The location engine, the backend, and the frontend are all untouched. That's the proof that 'one codebase, sim or hardware' isn't a slogan — it's a tested property of the system."

## SLIDE 20 — Implementation Status

"Here's an honest status board of the whole project. *(Walk the table.)*

Phase 1, the foundation and framework — done. The Phase 3 range multilateration solver — done. Phase 4, the Kalman filter fusion — done. Phase 5, the digital-twin upgrades — done. The UTIL calibration — done. The optional TDOA-EKF track — built. The generative TDOA simulator — built.

The one item that remains is Phase 6 — a basic AI layer for zone logic and prediction — and that was always scoped as *optional*. So every core deliverable we committed to is complete, tested, and working, and the only outstanding work is an optional enhancement. I'll say a bit more about that in future work."

## SLIDE 21 — Conclusion

"Let me bring it all together.

We set out to solve indoor location where GPS can't, and we've delivered a *complete, tested, and hardware-ready* UWB real-time location system, together with a live 3D digital twin that makes the data genuinely usable.

If you remember two things from this talk, make them our two distinctive contributions. *First*, the *one-codebase* architecture — a clean interface seam that lets the exact same software run on a simulator or on real hardware, so we validated everything in software before touching a single circuit board. *Second*, the *data-driven NLOS calibration* — we fitted our error model on real, millimetre-truth data instead of hand-tuning it, and in doing so we confirmed the key scientific point that NLOS is a positive *bias*, not noise.

And we didn't just claim these things. Our EKF is validated on real drone flights at roughly 0.18 to 0.20 metres RMSE against millimetre ground truth, and the whole system is backed by 21 passing tests and a live end-to-end demonstration."

## SLIDE 22 — Limitations and Future Work

"No project is finished, and I want to be honest about the boundaries.

On *limitations*: there's the cross-radio gap I flagged earlier — our model was calibrated on DWM1000 data, and it will need re-tuning for our DW3000 hardware. We don't yet have in-situ ground truth from an actual warehouse — only from the UTIL lab environment. Height, the z-axis, is weakly observable when the anchors are roughly co-planar, which is a fundamental geometry limitation. And the `HardwareAnchorSource` is currently a UDP stub — the interface is there, but the physical driver awaits real hardware.

On *future work*, four directions. *One*: the Phase 6 AI layer — geofencing and zone anomaly alerts, plus short-horizon trajectory prediction, which rides naturally on the velocity the Kalman filter already gives us. *Two*: the actual hardware bring-up, and re-tuning the noise and power models on the DW3000. *Three*: in-situ validation with tape-measured, NLOS-labelled traces in a real environment. And *four*: adding more, and more widely spread-out, anchors — which directly improves both height observability and overall accuracy.

None of these are blockers — they're the natural next steps that build on a solid, working foundation."

## SLIDE 23 — References / Thank You

"These are the key references that shaped the project — Paszek 2021 in Sensors; the 2024 and 2025 Applied Sciences papers; Zhao and colleagues' UTIL dataset from the 2024 IJRR; the 2018 Alexandria Engineering Journal paper; and the Makerfabs DW3000 hardware documentation.

With that, thank you all very much for your attention and your time. I'd be very happy to take any questions."

**Delivery tips (full script):**
- Slow down and make eye contact on Slide 7 (NLOS is a *bias*), Slide 10 (the gap), and Slide 16 (calibration finding) — these are your intellectual high points.
- If running long, Slide 17 (optional TDOA track) is the safest to compress.
- Slide 18 is where an examiner will probe; have the 0.18–0.20 m figure and "bias dominates" ready.

---

# PART 2 — TIGHT CUT (~20 minutes)

Drops to ~13 spoken blocks by merging slides. Cut Slide 17 (optional TDOA track) entirely unless asked. Runs ~19–20 min.

**Slide 1 — Title (30s)**
"Good morning. I'm presenting our T.Y. B.Tech project — a UWB Indoor Real-Time Location System with a live 3D Digital Twin. In one line: a system that tracks where people and assets are, live, indoors, where GPS doesn't work — and shows it on a live 3D model of the space. Guided by Professor *(name)*, in the CSE department at COEP."

**Slide 2 — Agenda (20s)**
"I'll cover the problem and motivation, our objectives, how UWB works, the core NLOS challenge, the research gap, our system and architecture, methodology, results and testing, and finally status and future work."

**Slides 3+4 — Problem & Motivation, merged (2.5 min)**
"The problem: indoors, GPS is blocked, and Wi-Fi and Bluetooth only give metre-to-tens-of-metre accuracy because they're narrowband and suffer badly from multipath. But warehouses, hospitals, and factories need to know where assets and people are, *live and precisely*.

Our answer is UWB — Ultra-Wideband. It sends ultra-short pulses across a wide band, giving nanosecond timing resolution — and since radio travels at light speed, precise timing means precise distance, down to centimetres. It also rejects multipath by isolating the first, direct-path arrival.

But raw coordinates aren't useful to a human, so we pair it with a *digital twin* — a live 3D floor plan where you watch tagged items move. The contrast: Bluetooth says 'somewhere in this aisle'; our system says 'this pallet, this exact spot.' And we built it under one rule: the same software runs on a simulator today and real hardware tomorrow."

**Slide 5 — Objectives (1 min)**
"Seven objectives, briefly: one shared data format so sim and hardware are interchangeable; a hardware-faithful simulator; a solver that down-weights bad signals; a Kalman filter for smoothing, velocity, and uncertainty; a config-driven 3D twin; calibration against real millimetre-truth data; and hardware integration down to a single file."

**Slide 6 — How UWB Works (1.5 min)**
"Two methods. *Ranging*, specifically double-sided two-way ranging, measures round-trip distance to each anchor — and its clever property is that it cancels clock drift, so anchors don't need synchronising. That's what our hardware uses. *TDOA* compares arrival times across synchronised anchors — it scales to more tags but needs tight sync. On the diagram, the range circles from several anchors intersect at the tag."

**Slide 7 — The NLOS Problem (2 min) — DON'T RUSH THIS**
"This is the core challenge. When the direct path is blocked, the signal reaches the anchor by bouncing — a longer path — so the measured range comes out *too long*.

The key insight: this is a positive *bias*, not random noise. It's always long, never short — so you *cannot* average or filter it away. You have to detect and handle it.

How do we detect it? The DW3000 chip reports both total received power and first-path power. In line-of-sight, they're close. When the path is blocked, the first-path power collapses. So a large gap between them flags a non-line-of-sight link — and that gap is what we use to down-weight bad measurements."

**Slides 8+9+10 — Literature, Dataset & Gap, merged (2.5 min)**
"From the literature: Paszek 2021 gave us the simulator blueprint; a 2025 Applied Sciences paper showed NLOS-aware weighting is the biggest accuracy lever; and the UTIL dataset from Toronto gave us real UWB data with *millimetre* Vicon ground truth to calibrate and validate against. One caveat: UTIL used an older chip, so we treat its model as a prior needing recalibration, not a transplant.

That leads to our research gap — three real problems. First, many existing simulators *cheat*: they secretly send the true position to the display, so there's no real solving and fake accuracy. Second, NLOS weighting is usually hand-tuned, not data-fitted. Third, sim and hardware are usually separate codebases, making hardware bring-up slow.

Our three contributions close exactly those: a pipeline that *actually* estimates position, a *data-driven* NLOS model, and *one codebase* behind a single interface."

**Slides 11+12 — Proposed System & Architecture, merged (2 min)**
"Our pipeline: anchor source → location engine → backend hub → frontend digital twin. The core principle is 'one codebase, sim or hardware' — because both emit an identical versioned format, everything downstream is source-agnostic. That let us fully validate the system before hardware arrived.

Concretely: the anchor source feeds the location engine — solver plus Kalman filter — which feeds a Socket.IO backend, which feeds a React and Three.js frontend. The critical seam is the `AnchorSource` interface: `SimAnchorSource` on one side, `HardwareAnchorSource` on the other, switched by a single environment variable."

**Slides 14+15 — Methodology, merged (3 min)**
"Methodology in two parts. The *simulator* injects realistic imperfections — antenna bias, Gaussian noise, wall occlusion, positive-only NLOS bias per material, power diagnostics, and dropped readings. And crucially, it *never* passes ground truth to the solver.

The *solver* is weighted least squares: it finds the position minimising the weighted squared range residuals, solved with Levenberg–Marquardt, with weights that down-weight NLOS links by the power gap. It recovers a known point to under a centimetre and beats trusting a biased anchor.

On top, each tag gets a *constant-velocity Kalman filter* — predict, then update with the raw fix — giving smooth position, velocity, and uncertainty. Because the error is bias-dominated, the accuracy gain is a modest 4–5%, but the usability win is large: smooth tracks, velocity, and confidence rings.

*(Gesture to screenshot.)* The twin shows live tags, fading trails with true-path overlay, uncertainty rings, zone labels, a live accuracy dashboard, and green/red anchor lines for line-of-sight versus blocked — plus an interactive map editor with hot-reload."

**Slide 16 — Calibration (2 min) — A KEY CONTRIBUTION**
"Here's a standout contribution. Instead of hand-tuning, our script fits real range-error statistics from the UTIL data and patches them into the config, tagged as calibrated. The finding confirmed our hypothesis: NLOS is a positive bias of 3–40 centimetres, *not* extra noise. In fact, calibrated NLOS noise came out identical to line-of-sight — 0.054 metres — proving the difference is all bias. And because the simulator reads its model from config, this was a *data* change, not a code change."

**Slide 18 — Results (1.5 min) — EXPECT PROBING HERE**
"Results: the range solver reaches 0.6–0.7 m median in simulation. Adding the Kalman filter improves the mean 4–5%. On *real* UTIL data, our TDOA-EKF hits 0.18–0.20 m RMSE against millimetre ground truth — 0.33 in the cluttered constellation. The key takeaway: *bias dominates*, so weighting and calibration matter more than a heavier filter."

**Slide 19 — Testing (1 min)**
"Everything's verified: 21 automated tests, all passing — covering the solver, Kalman filter, calibration, and EKF. In the live demo, the raw fix jitters while the Kalman track stays smooth, and the dashboard confirms filtered beats raw. And critically, swapping simulator for hardware is the *only* change — the engine is untouched."

**Slides 20+21 — Status & Conclusion, merged (1.5 min)**
"On status: the foundation, solver, Kalman fusion, twin, and calibration are all done; only the optional AI phase remains.

To conclude: we've delivered a complete, tested, hardware-ready UWB location system with a live 3D twin. Two distinctive contributions: the one-codebase architecture unifying sim and hardware, and data-driven NLOS calibration on real ground-truth data. The EKF is validated at 0.18–0.20 m RMSE, backed by 21 tests and a live demo."

**Slide 22 — Limitations & Future Work (1 min)**
"Limitations: the cross-radio gap needs recalibration on our chip; we lack in-situ warehouse ground truth; height is weakly observable with co-planar anchors; and the hardware source is still a stub. Future work: the AI phase for geofencing and prediction, hardware bring-up and re-tuning, in-situ validation, and more spread-out anchors for better height accuracy."

**Slide 23 — Thank You (15s)**
"Those are our references. Thank you for your attention — I'm happy to take questions."

**Timing summary (20-min cut):** intro/agenda ~1 min · problem→NLOS ~9 min · gap→architecture ~4.5 min · methodology→calibration ~5 min · results→close ~5 min. Trim the merged methodology block first if you're over.

---

# PART 3 — Q&A CHEAT-SHEET

For each: a **one-line lead answer**, then **backup detail** if pushed.

## On the choice of technology

**Q: Why UWB and not Wi-Fi/BLE/RFID?**
- *Lead:* "UWB's ultra-short pulses give nanosecond timing resolution and strong multipath rejection, which is what takes accuracy from metres down to centimetres — narrowband technologies physically can't do that."
- *Backup:* One nanosecond of timing error ≈ 30 cm. UWB's sharp pulse also lets you isolate the *first* (direct-path) arrival from echoes; Wi-Fi/BLE can't separate them, so multipath dominates their error.

**Q: Why DS-TWR for the main system instead of TDOA?**
- *Lead:* "DS-TWR cancels clock drift mathematically, so anchors don't need to be time-synchronised — that dramatically simplifies real deployment, which matters for our hardware."
- *Backup:* "TDOA scales better to many tags but needs tight anchor sync, a hardware burden. We still built a TDOA-EKF track to prove we could do both — but for a first deployment, ranging is the pragmatic choice."

## On the core technical claims

**Q: You say NLOS is a bias, not noise. How do you know?**
- *Lead:* "Physics predicts it — a blocked signal arrives via a longer reflected path, so the range is always reported *longer*, never shorter. And our calibration on real UTIL data confirmed it: the extra error showed up as a positive offset of 3–40 cm, while the noise σ stayed the same as line-of-sight."
- *Backup:* "That's why LOS and NLOS noise σ both came out at 0.054 m after calibration — the difference between them is entirely in the bias term, not the spread."

**Q: If the Kalman filter only improves accuracy 4–5%, why include it?**
- *Lead:* "Because the error is bias-dominated, no filter can remove much of it — but the filter isn't there for accuracy alone. It gives smooth tracks, a velocity estimate, and a principled uncertainty ellipse, which are exactly what an operator and any downstream AI need."
- *Backup:* "A Kalman filter smooths *zero-mean noise*; it can't cancel a systematic bias. Usability, velocity, and covariance are the real deliverables, and Phase 6 prediction rides on that velocity."

**Q: How do I know your simulator is realistic and not just measuring your own assumptions?**
- *Lead:* "Two safeguards. First, the simulator never leaks ground truth to the solver — the solver does real work. Second, the noise and NLOS model isn't guessed; it's *fitted from real millimetre-truth data* (UTIL), so the simulator's behaviour is anchored to reality."
- *Backup:* "And we validated the EKF on the *real* UTIL flights, not just synthetic data — 0.18–0.20 m RMSE against Vicon."

**Q: Isn't your accuracy claim invalid because you calibrated on a different chip (DWM1000 vs DW3000)?**
- *Lead:* "We're deliberately careful — we treat the UTIL-fitted model as a *prior*, not a final truth. The cross-radio gap is a stated limitation, and re-tuning on DW3000 is explicit future work."
- *Backup:* "The *architecture* transfers cleanly across chips; the *numbers* need recalibration. Our config-driven design means that recalibration is a data change, not a code change."

## On the architecture

**Q: How can you claim it's 'hardware-ready' if you have no hardware?**
- *Lead:* "Because we defined and tested the exact seam where hardware plugs in — the `AnchorSource` interface — and verified that swapping `SimAnchorSource` for `HardwareAnchorSource` is the *only* change needed; the engine, backend, and frontend are untouched."
- *Backup:* "The `HardwareAnchorSource` is a UDP stub today, so what remains is filling in that one file and re-tuning constants — not re-architecting."

**Q: Why one codebase — isn't that risky, mixing sim and real code?**
- *Lead:* "It's the opposite of risky — it means everything validated in simulation carries directly to hardware with no re-implementation, which is where most indoor-positioning projects lose time and introduce bugs."
- *Backup:* "The sim and hardware are *isolated* behind the interface; they don't mix. Only the data contract is shared, and it's versioned (`uwb.reading/1`)."

## On the maths

**Q: Explain your solver.**
- *Lead:* "Weighted least squares — it finds the position minimising the weighted sum of squared residuals between predicted and measured ranges, solved with Levenberg–Marquardt via SciPy. The weights down-weight NLOS links using the power gap."
- *Backup:* "Seeded from the anchor centroid or last position for fast convergence. Recovers a known point to <1 cm."

**Q: Why divide TDOA σ by √2 in calibration?**
- *Lead:* "Because a TDOA measurement is the *difference* of two independent range measurements, so its variance is the sum of the two — twice a single range's variance. Taking √2 out recovers the single-range σ."

**Q: What does the chi-square gate do in the EKF?**
- *Lead:* "It's a statistical outlier test — it compares each measurement's innovation against its expected covariance and rejects readings that are too improbable, which is how it discards NLOS spikes. It dropped about 3% of readings in the cluttered constellation."

## On results and limitations

**Q: Why is height (z) accuracy weak?**
- *Lead:* "It's a geometry limitation — when anchors are roughly co-planar (e.g., all ceiling-mounted at similar height), the vertical dilution of precision is poor. Spreading anchors in height fixes it, which is in our future work."

**Q: What's the single biggest lesson from this project?**
- *Lead:* "That *bias dominates* indoor UWB error — so intelligent weighting and data-driven calibration matter more than a heavier filter. That reframes where you should spend engineering effort."

**Q: What would you do differently / do next?**
- *Lead:* "Get real hardware in the loop and collect in-situ, tape-measured NLOS-labelled traces in an actual warehouse — that closes the last gap between our validated model and a deployed product."
