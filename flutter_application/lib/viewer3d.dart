import 'dart:math' as math;
import 'package:flutter/material.dart';
import 'package:flutter/scheduler.dart';
import 'package:flutter/services.dart';
import 'api.dart';
import 'editor2d.dart';
import 'live_feed.dart';
import 'scene3d.dart';
import 'util.dart';

typedef Sel = ({String type, String id});

/// Live 3D view of a map, addressed by key (port of Viewer3D.jsx).
class Viewer3D extends StatefulWidget {
  const Viewer3D({super.key, required this.mapKey});
  final String mapKey;
  @override
  State<Viewer3D> createState() => _Viewer3DState();
}

class _Viewer3DState extends State<Viewer3D> with SingleTickerProviderStateMixin {
  J? _map;
  String? _err;
  late final LiveFeed _feed;
  final _cam = Cam();
  final _frame = ValueNotifier<int>(0);
  late final Ticker _ticker;
  Duration _last = Duration.zero;
  final Map<String, List<double>> _disp = {}; // smoothed on-screen tag positions

  bool showRangeLines = true, showRaw = false, showTrails = true, showTruePath = false, showAccuracy = false, showGhost = true;
  Sel? _sel;
  double _startDist = 40;

  @override
  void initState() {
    super.initState();
    _feed = LiveFeed(widget.mapKey, onMapUpdated: _loadMap);
    _loadMap();
    _ticker = createTicker(_tick)..start();
  }

  @override
  void dispose() {
    _ticker.dispose();
    _feed.dispose();
    _frame.dispose();
    super.dispose();
  }

  Future<void> _loadMap() async {
    try {
      final m = await Api.getMap(widget.mapKey);
      if (!mounted) return;
      final f = m['floor'] as J;
      final half = math.max(nd(f['sizeX'], 30), nd(f['sizeZ'], 30)) / 2;
      final first = _map == null;
      setState(() {
        _map = m;
        _err = null;
        _cam.maxDist = math.max(30, half * 4);
        if (first) _cam.dist = math.max(15, half * 2.2);
      });
    } catch (e) {
      if (mounted) setState(() => _err = '$e');
    }
  }

  // Ease displayed tag positions toward the latest fix (web: lerp(delta * 6)).
  void _tick(Duration t) {
    final dt = math.min(0.1, (t - _last).inMicroseconds / 1e6);
    _last = t;
    final k = math.min(1.0, dt * 6);
    _feed.positions.forEach((id, p) {
      final pos = p['pos'];
      if (pos == null) return;
      final tx = nd(pos['x']), ty = nd(pos['y']), tz = nd(pos['z']);
      final d = _disp[id];
      if (d == null) {
        _disp[id] = [tx, ty, tz];
      } else {
        d[0] += (tx - d[0]) * k;
        d[1] += (ty - d[1]) * k;
        d[2] += (tz - d[2]) * k;
      }
    });
    _frame.value++;
  }

  List<LiveTag> _liveTags() {
    final m = _map;
    if (m == null) return const [];
    final out = <LiveTag>[];
    for (final p in _feed.positions.values) {
      final id = p['tagId'];
      if (tagCfg(m, id) == null) continue;
      final d = _disp[id];
      if (d != null) out.add((data: p, pos: d));
    }
    return out;
  }

  void _onTap(Offset at) {
    final m = _map;
    if (m == null) return;
    Sel? best;
    var bestD = 40.0;
    void probe(Offset? o, Sel s) {
      if (o == null) return;
      final d = (o - at).distance;
      if (d < bestD) { bestD = d; best = s; }
    }
    for (final a in listOf(m, 'anchors')) {
      probe(_cam.project(nd(a['x']), nd(a['y']), nd(a['z'])), (type: 'anchor', id: a['id'] as String));
    }
    for (final t in _liveTags()) {
      probe(_cam.project(t.pos[0], t.pos[1], t.pos[2]), (type: 'tag', id: t.data['tagId'] as String));
    }
    setState(() => _sel = best);
  }

  void _openOptions() {
    showModalBottomSheet(
      context: context,
      backgroundColor: cardBg,
      builder: (_) => StatefulBuilder(builder: (ctx, setSheet) {
        Widget sw(String label, bool v, void Function(bool) f) => SwitchListTile(
              dense: true,
              title: Text(label),
              value: v,
              onChanged: (x) { setState(() => f(x)); setSheet(() {}); },
            );
        return SafeArea(
          child: ListView(shrinkWrap: true, children: [
            sw('Range lines (LOS/NLOS)', showRangeLines, (v) => showRangeLines = v),
            sw('Raw fix + uncertainty (Kalman off)', showRaw, (v) => showRaw = v),
            sw('Motion trails', showTrails, (v) => showTrails = v),
            sw('True path overlay (sim)', showTruePath, (v) => showTruePath = v),
            sw('Predicted position (AI)', showGhost, (v) => showGhost = v),
            sw('Accuracy panel', showAccuracy, (v) => showAccuracy = v),
          ]),
        );
      }),
    );
  }

  void _openAlerts() {
    showModalBottomSheet(
      context: context,
      backgroundColor: cardBg,
      builder: (_) => ListenableBuilder(
        listenable: _feed,
        builder: (ctx, _) {
          final m = _map ?? {};
          final items = _feed.alerts.reversed.take(20).toList();
          return SafeArea(
            child: ListView(shrinkWrap: true, padding: const EdgeInsets.all(16), children: [
              Text('⚠ Alerts (${_feed.alerts.length})', style: const TextStyle(fontWeight: FontWeight.w700)),
              const SizedBox(height: 8),
              if (items.isEmpty) const Text('No alerts.', style: TextStyle(color: textMuted)),
              for (final a in items)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 3),
                  child: Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
                    Expanded(
                      child: Text(
                        '${tagCfg(m, '${a['tagId']}')?['name'] ?? a['tagId']}: ${a['kind'] == 'stale' ? 'no signal' : 'entered ${zoneLabel(m, a['zone'] as String?) ?? 'unmapped area'}'}',
                        style: TextStyle(fontSize: 13, color: a['kind'] == 'stale' ? const Color(0xFFFBBF24) : const Color(0xFFFCA5A5)),
                      ),
                    ),
                    Text(a['t'] is num ? TimeOfDay.fromDateTime(DateTime.fromMillisecondsSinceEpoch(((a['t'] as num) * 1000).round())).format(ctx) : '',
                        style: const TextStyle(color: Color(0xFF64748B), fontSize: 12)),
                  ]),
                ),
            ]),
          );
        },
      ),
    );
  }

  void _openAccuracy() {
    showModalBottomSheet(
      context: context,
      backgroundColor: cardBg,
      isScrollControlled: true,
      builder: (_) => ListenableBuilder(
        listenable: _feed,
        builder: (ctx, _) => SafeArea(child: _AccuracyPanel(feed: _feed, map: _map ?? {})),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final map = _map;
    return Scaffold(
      appBar: AppBar(
        titleSpacing: 0,
        title: ListenableBuilder(
          listenable: _feed,
          builder: (_, _) => Row(children: [
            Flexible(child: Text(map == null ? 'Loading…' : '${(map['meta'] as J)['name']}', overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 17))),
            const SizedBox(width: 8),
            _badge(_feed.connected),
          ]),
        ),
        actions: [
          ListenableBuilder(
            listenable: _feed,
            builder: (_, _) => IconButton(
              tooltip: 'Alerts',
              icon: Badge(isLabelVisible: _feed.alerts.isNotEmpty, label: Text('${_feed.alerts.length}'), child: const Icon(Icons.warning_amber_rounded)),
              onPressed: _openAlerts,
            ),
          ),
          if (showAccuracy) IconButton(tooltip: 'Accuracy', icon: const Icon(Icons.insights), onPressed: _openAccuracy),
          IconButton(tooltip: 'Layers', icon: const Icon(Icons.tune), onPressed: _openOptions),
          PopupMenuButton<String>(
            onSelected: (v) async {
              if (v == 'edit') {
                await Navigator.push(context, MaterialPageRoute(builder: (_) => Editor2D(mapKey: widget.mapKey)));
              } else if (v == 'share') {
                await Clipboard.setData(ClipboardData(text: widget.mapKey));
                if (context.mounted) toast(context, 'Map key copied: ${widget.mapKey}');
              }
            },
            itemBuilder: (_) => const [
              PopupMenuItem(value: 'edit', child: Text('✎ Edit map')),
              PopupMenuItem(value: 'share', child: Text('🔗 Copy map key')),
            ],
          ),
        ],
      ),
      body: _err != null
          ? Center(child: Padding(padding: const EdgeInsets.all(24), child: Text('⚠️ $_err', style: const TextStyle(fontSize: 18))))
          : map == null
              ? const Center(child: CircularProgressIndicator())
              : Stack(children: [
                  Positioned.fill(
                    child: GestureDetector(
                      onScaleStart: (_) => _startDist = _cam.dist,
                      onScaleUpdate: (d) {
                        _cam.yaw -= d.focalPointDelta.dx * 0.008;
                        _cam.pitch += d.focalPointDelta.dy * 0.008;
                        if (d.pointerCount > 1) _cam.dist = _startDist / d.scale;
                      },
                      onTapUp: (d) => _onTap(d.localPosition),
                      child: ListenableBuilder(
                        listenable: _feed,
                        builder: (_, _) => CustomPaint(
                          painter: ScenePainter(
                            cam: _cam,
                            map: map,
                            tags: _liveTags(),
                            readings: _feed.readings,
                            trails: _feed.trails,
                            truthTrails: _feed.truthTrails,
                            selected: _sel,
                            showRangeLines: showRangeLines,
                            showRaw: showRaw,
                            showTrails: showTrails,
                            showTruePath: showTruePath,
                            showGhost: showGhost,
                            repaint: _frame,
                          ),
                        ),
                      ),
                    ),
                  ),
                  Positioned(
                    left: 0, right: 0, bottom: 0,
                    child: ListenableBuilder(
                      listenable: _feed,
                      builder: (_, _) => Column(mainAxisSize: MainAxisSize.min, children: [
                        if (_sel != null) _details(map),
                        _telemetry(map),
                      ]),
                    ),
                  ),
                  Positioned(
                    left: 12, top: 8,
                    child: IgnorePointer(
                      child: Container(
                        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                        decoration: BoxDecoration(color: const Color(0xCC0F172A), borderRadius: BorderRadius.circular(6)),
                        child: const Text.rich(TextSpan(style: TextStyle(fontSize: 11, color: textMuted), children: [
                          TextSpan(text: '■', style: TextStyle(color: Color(0xFF22C55E))), TextSpan(text: ' LOS  '),
                          TextSpan(text: '■', style: TextStyle(color: Color(0xFFEF4444))), TextSpan(text: ' NLOS  '),
                          TextSpan(text: '■', style: TextStyle(color: Color(0xFF64748B))), TextSpan(text: ' dropped'),
                        ])),
                      ),
                    ),
                  ),
                ]),
    );
  }

  Widget _badge(bool on) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
        decoration: BoxDecoration(
          color: (on ? const Color(0xFF22C55E) : const Color(0xFFEF4444)).withValues(alpha: 0.18),
          borderRadius: BorderRadius.circular(20),
        ),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          Icon(Icons.circle, size: 8, color: on ? const Color(0xFF22C55E) : const Color(0xFFEF4444)),
          const SizedBox(width: 4),
          Text(on ? 'LIVE' : 'OFFLINE', style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: on ? const Color(0xFF22C55E) : const Color(0xFFEF4444))),
        ]),
      );

  Widget _telemetry(J map) {
    final tags = _liveTags().map((t) => t.data).toList();
    return Container(
      height: 112,
      color: const Color(0xE60F172A),
      child: tags.isEmpty
          ? const Center(child: Text('Waiting for tags… (start the gateway for this map)', style: TextStyle(color: textMuted, fontSize: 13)))
          : ListView(
              scrollDirection: Axis.horizontal,
              padding: const EdgeInsets.all(8),
              children: [
                for (final t in tags)
                  GestureDetector(
                    onTap: () => setState(() => _sel = (type: 'tag', id: t['tagId'] as String)),
                    child: Container(
                      width: 200,
                      margin: const EdgeInsets.only(right: 8),
                      padding: const EdgeInsets.all(10),
                      decoration: BoxDecoration(
                        color: cardBg.withValues(alpha: 0.8),
                        borderRadius: BorderRadius.circular(10),
                        border: Border.all(color: _sel?.id == t['tagId'] ? accent : cardBorder),
                      ),
                      child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
                        Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
                          Flexible(child: Text('${t['name'] ?? t['tagId']}', overflow: TextOverflow.ellipsis, style: const TextStyle(fontWeight: FontWeight.w700))),
                          Text('⚡ ${t['battery'] ?? '–'}%', style: TextStyle(fontSize: 12, color: (t['battery'] is num && t['battery'] < 20) ? const Color(0xFFEF4444) : const Color(0xFF10B981))),
                        ]),
                        _kv('Zone', '${zoneLabel(map, t['zone'] as String?) ?? '—'}${outsideAllowed(map, t) ? ' ⚠' : ''}', color: outsideAllowed(map, t) ? const Color(0xFFEF4444) : null),
                        _kv('Speed', t['vel'] != null ? '${t['vel']['speed']} m/s' : '—'),
                        _kv('Err (K/raw)', t['error'] != null ? '${(nd(t['error']) * 100).toStringAsFixed(0)} / ${(nd(t['rawError'] ?? t['error']) * 100).toStringAsFixed(0)} cm' : '—'),
                      ]),
                    ),
                  ),
              ],
            ),
    );
  }

  Widget _kv(String k, String v, {Color? color, Color? vColor}) => Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
        Text(k, style: const TextStyle(color: textMuted, fontSize: 12)),
        Flexible(child: Text(v, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: color ?? vColor ?? Colors.white))),
      ]);

  // Port of DetailsPanel (three3d.jsx).
  Widget _details(J map) {
    final sel = _sel!;
    final rows = <Widget>[];
    String title;
    if (sel.type == 'anchor') {
      final a = listOf(map, 'anchors').where((x) => x['id'] == sel.id).firstOrNull;
      if (a == null) return const SizedBox.shrink();
      title = '📡 ${a['label']}';
      final seenBy = _feed.readings.values.where((rd) => (rd['ranges'] as List).any((r) => r['anchorId'] == a['id'])).toList();
      final nlosNow = seenBy.where((rd) => (rd['ranges'] as List).firstWhere((r) => r['anchorId'] == a['id'])['nlos'] == true).length;
      rows.addAll([
        _kv('ID', '${a['id']}'),
        _kv('Position (m)', 'x ${a['x']}, y ${a['y']}, z ${a['z']}'),
        _kv('Antenna delay', '${nd(a['antennaDelayBiasM']).toStringAsFixed(2)} m'),
        _kv('Provenance', '${a['provenance'] ?? '—'}'),
        _kv('Tags ranging', '${seenBy.length} ($nlosNow NLOS)'),
      ]);
    } else {
      final p = _feed.positions[sel.id];
      final t = tagCfg(map, sel.id);
      if (p == null && t == null) return const SizedBox.shrink();
      final rd = _feed.readings[sel.id];
      title = '🏷️ ${p?['name'] ?? t?['name'] ?? sel.id}';
      rows.addAll([
        _kv('ID / role', '${sel.id} · ${t?['role'] ?? '—'}'),
        _kv('Battery', '${p?['battery'] ?? t?['battery'] ?? '–'}%'),
        _kv('Zone', zoneLabel(map, p?['zone'] as String?) ?? '—'),
        if (p?['pos'] != null) _kv('Est. position', 'x ${p!['pos']['x']}, z ${p['pos']['z']}'),
        if (p?['vel'] != null) _kv('Speed', '${p!['vel']['speed']} m/s'),
        if (p?['error'] != null) _kv('Filtered error', '${(nd(p!['error']) * 100).toStringAsFixed(0)} cm'),
        if (p?['rawError'] != null) _kv('Raw error', '${(nd(p!['rawError']) * 100).toStringAsFixed(0)} cm'),
        if (p?['residual'] != null) _kv('Solve residual', '${p!['residual']} m'),
        if (p?['nlos'] != null) _kv('NLOS correction', p!['nlos']['method'] == 'ai' ? 'AI bias model' : 'power-gap rule'),
        if (rd != null)
          for (final r in (rd['ranges'] as List)) _rangeRow(r, p?['nlos']?['bias']?[r['anchorId']]),
      ]);
    }
    return Container(
      constraints: BoxConstraints(maxHeight: MediaQuery.of(context).size.height * 0.38),
      margin: const EdgeInsets.fromLTRB(8, 0, 8, 6),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(color: const Color(0xF20F172A), borderRadius: BorderRadius.circular(12), border: Border.all(color: cardBorder)),
      child: Column(mainAxisSize: MainAxisSize.min, children: [
        Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
          Text(title, style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 15)),
          InkWell(onTap: () => setState(() => _sel = null), child: const Padding(padding: EdgeInsets.all(4), child: Icon(Icons.close, size: 18))),
        ]),
        const SizedBox(height: 6),
        Flexible(child: SingleChildScrollView(child: Column(children: rows))),
      ]),
    );
  }

  Widget _rangeRow(dynamic r, dynamic bias) {
    final valid = r['valid'] == true, nlos = r['nlos'] == true;
    final col = !valid ? const Color(0xFF64748B) : nlos ? const Color(0xFFEF4444) : const Color(0xFF22C55E);
    return Padding(
      padding: const EdgeInsets.only(top: 2),
      child: Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
        Row(children: [
          Text('${r['anchorId']} ', style: const TextStyle(fontSize: 12, color: textMuted)),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 1),
            decoration: BoxDecoration(color: col, borderRadius: BorderRadius.circular(4)),
            child: Text(!valid ? 'DROP' : nlos ? 'NLOS' : 'LOS', style: const TextStyle(fontSize: 10, color: Colors.white)),
          ),
        ]),
        Text.rich(TextSpan(style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w600), children: [
          TextSpan(text: valid ? '${nd(r['range']).toStringAsFixed(2)} m' : '—'),
          if (valid && bias is num && bias >= 0.01)
            TextSpan(text: ' −${(bias * 100).toStringAsFixed(0)} cm', style: const TextStyle(color: accent)),
        ])),
      ]),
    );
  }
}

// ---- accuracy HUD -------------------------------------------------------------

({double mean, double median, double p90})? _stats(List<double> xs) {
  if (xs.isEmpty) return null;
  final s = [...xs]..sort();
  return (mean: s.reduce((a, b) => a + b) / s.length, median: s[(s.length * 0.5).floor()], p90: s[(s.length * 0.9).floor()]);
}

class _AccuracyPanel extends StatelessWidget {
  const _AccuracyPanel({required this.feed, required this.map});
  final LiveFeed feed;
  final J map;

  @override
  Widget build(BuildContext context) {
    final hist = feed.errHist;
    final allF = <double>[], allR = <double>[];
    for (final h in hist.values) {
      for (final e in h) { allF.add(e['err']!); allR.add(e['raw']!); }
    }
    final f = _stats(allF), r = _stats(allR);
    if (f == null) {
      return const Padding(padding: EdgeInsets.all(24), child: Text('No accuracy data yet (needs error fields from the location engine).', style: TextStyle(color: textMuted)));
    }
    final pct = r == null || r.mean == 0 ? 0 : (100 * (r.mean - f.mean) / r.mean).round();
    Widget row(String k, String v, [Color? c]) => Padding(
          padding: const EdgeInsets.symmetric(vertical: 2),
          child: Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
            Text(k, style: const TextStyle(color: textMuted, fontSize: 13)),
            Text(v, style: TextStyle(fontWeight: FontWeight.w700, color: c ?? Colors.white)),
          ]),
        );
    return ListView(shrinkWrap: true, padding: const EdgeInsets.all(16), children: [
      const Text('📊 Accuracy (live)', style: TextStyle(fontWeight: FontWeight.w700)),
      const SizedBox(height: 8),
      row('Kalman vs raw (mean)', '${(f.mean * 100).toStringAsFixed(0)} / ${(r!.mean * 100).toStringAsFixed(0)} cm', const Color(0xFF4ADE80)),
      row('Kalman median · p90', '${(f.median * 100).toStringAsFixed(0)} · ${(f.p90 * 100).toStringAsFixed(0)} cm'),
      row('Improvement', '${pct >= 0 ? '+' : ''}$pct%', pct >= 0 ? const Color(0xFF4ADE80) : const Color(0xFFFCA5A5)),
      const Divider(color: cardBorder),
      for (final e in hist.entries)
        if (_stats(e.value.map((x) => x['err']!).toList()) case final s?)
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              row('${tagCfg(map, e.key)?['name'] ?? e.key}', '${(s.mean * 100).toStringAsFixed(0)} cm', const Color(0xFF4ADE80)),
              SizedBox(
                height: 28, width: 140,
                child: CustomPaint(painter: _Spark(e.value.reversed.take(60).toList().reversed.map((x) => x['err']!).toList())),
              ),
            ]),
          ),
      const Text('green = Kalman-filtered error over time · lower is better', style: TextStyle(fontSize: 11, color: Color(0xFF64748B))),
    ]);
  }
}

class _Spark extends CustomPainter {
  _Spark(this.vals);
  final List<double> vals;
  @override
  void paint(Canvas c, Size s) {
    if (vals.length < 2) return;
    final mx = math.max(0.5, vals.reduce(math.max));
    final p = Path();
    for (var i = 0; i < vals.length; i++) {
      final o = Offset(i / (vals.length - 1) * s.width, s.height - vals[i] / mx * s.height);
      i == 0 ? p.moveTo(o.dx, o.dy) : p.lineTo(o.dx, o.dy);
    }
    c.drawPath(p, Paint()..color = const Color(0xFF4ADE80)..style = PaintingStyle.stroke..strokeWidth = 1.5);
  }

  @override
  bool shouldRepaint(_Spark old) => true;
}
