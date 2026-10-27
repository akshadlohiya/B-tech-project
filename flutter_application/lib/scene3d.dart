import 'dart:math' as math;
import 'package:flutter/material.dart';
import 'util.dart';

/// Orbit camera + perspective projection (replaces three.js / OrbitControls).
/// World axes match the web app: x = east, y = up, z = north.
class Cam {
  double yaw = 0.8, pitch = 0.55, dist = 40;
  double maxDist = 120;
  static const fov = 50 * math.pi / 180;

  Size size = Size.zero;
  late double _px, _py, _pz; // eye
  late double _fx, _fy, _fz; // forward
  late double _rx, _ry, _rz; // right
  late double _ux, _uy, _uz; // up
  late double _focal;

  void update(Size s) {
    size = s;
    pitch = pitch.clamp(0.05, math.pi / 2 - 0.05);
    dist = dist.clamp(3.0, maxDist);
    final cp = math.cos(pitch);
    _px = dist * cp * math.sin(yaw);
    _py = dist * math.sin(pitch);
    _pz = dist * cp * math.cos(yaw);
    final fl = math.sqrt(_px * _px + _py * _py + _pz * _pz);
    _fx = -_px / fl; _fy = -_py / fl; _fz = -_pz / fl;
    // right = forward x worldUp(0,1,0)
    var rx = _fy * 0 - _fz * 1, ry = _fz * 0 - _fx * 0, rz = _fx * 1 - _fy * 0;
    final rl = math.sqrt(rx * rx + ry * ry + rz * rz);
    rx /= rl; ry /= rl; rz /= rl;
    _rx = rx; _ry = ry; _rz = rz;
    // up = right x forward
    _ux = _ry * _fz - _rz * _fy;
    _uy = _rz * _fx - _rx * _fz;
    _uz = _rx * _fy - _ry * _fx;
    // fov spans the narrower side so a portrait phone still sees the whole floor
    _focal = (math.min(s.width, s.height) / 2) / math.tan(fov / 2);
  }

  /// Distance along the view axis (for painter's-algorithm sorting).
  double depth(double x, double y, double z) =>
      (x - _px) * _fx + (y - _py) * _fy + (z - _pz) * _fz;

  /// Pixels per metre at a given depth.
  double scaleAt(double depth) => _focal / math.max(depth, 0.1);

  Offset? project(double x, double y, double z) {
    final dx = x - _px, dy = y - _py, dz = z - _pz;
    final d = dx * _fx + dy * _fy + dz * _fz;
    if (d < 0.2) return null;
    final sx = dx * _rx + dy * _ry + dz * _rz;
    final sy = dx * _ux + dy * _uy + dz * _uz;
    return Offset(size.width / 2 + _focal * sx / d, size.height / 2 - _focal * sy / d);
  }
}

typedef LiveTag = ({J data, List<double> pos});

/// Draws the whole digital twin: floor, zones, walls, anchors, live tags,
/// LOS/NLOS range lines, trails and Kalman/AI overlays.
class ScenePainter extends CustomPainter {
  ScenePainter({
    required this.cam,
    required this.map,
    required this.tags,
    required this.readings,
    required this.trails,
    required this.truthTrails,
    required this.selected,
    required this.showRangeLines,
    required this.showRaw,
    required this.showTrails,
    required this.showTruePath,
    required this.showGhost,
    required Listenable repaint,
  }) : super(repaint: repaint);

  final Cam cam;
  final J map;
  final List<LiveTag> tags;
  final Map<String, J> readings;
  final Map<String, List<List<double>>> trails, truthTrails;
  final ({String type, String id})? selected;
  final bool showRangeLines, showRaw, showTrails, showTruePath, showGhost;

  @override
  void paint(Canvas canvas, Size size) {
    cam.update(size);
    canvas.drawRect(Offset.zero & size, Paint()..color = const Color(0xFFF8FAFC));

    final floor = map['floor'] as J;
    final hx = nd(floor['sizeX'], 30) / 2, hz = nd(floor['sizeZ'], 30) / 2;
    _quad(canvas, [[-hx, 0, -hz], [hx, 0, -hz], [hx, 0, hz], [-hx, 0, hz]], Paint()..color = const Color(0xFF64748B));
    _grid(canvas, hx, hz);

    for (final z in listOf(map, 'zones')) {
      _zone(canvas, z);
    }
    if (showTrails) {
      trails.forEach((id, pts) => _trail(canvas, pts, roleColor(map, id)));
    }
    if (showTruePath) {
      truthTrails.forEach((id, pts) => _dashedPolyline(canvas, pts, const Color(0x8CE2E8F0), 1.2));
    }

    final anchors = {for (final a in listOf(map, 'anchors')) a['id'] as String: a};
    if (showRangeLines) {
      for (final t in tags) {
        _rangeLines(canvas, anchors, t.pos, readings[t.data['tagId']]);
      }
    }
    for (final t in tags) {
      if (showRaw) _rawGhost(canvas, t);
      if (showGhost) _aiGhost(canvas, t);
    }

    // Solid objects, far to near.
    final items = <(double, void Function())>[];
    for (final w in listOf(map, 'walls')) {
      final d = cam.depth((nd(w['x1']) + nd(w['x2'])) / 2, nd(w['height'], 3) / 2, (nd(w['z1']) + nd(w['z2'])) / 2);
      items.add((d, () => _wall(canvas, w)));
    }
    for (final a in anchors.values) {
      final sel = selected?.type == 'anchor' && selected?.id == a['id'];
      items.add((cam.depth(nd(a['x']), nd(a['y']), nd(a['z'])), () => _anchor(canvas, a, sel)));
    }
    for (final t in tags) {
      final sel = selected?.type == 'tag' && selected?.id == t.data['tagId'];
      items.add((cam.depth(t.pos[0], t.pos[1], t.pos[2]), () => _tag(canvas, t, sel)));
    }
    items.sort((a, b) => b.$1.compareTo(a.$1));
    for (final i in items) {
      i.$2();
    }
  }

  // ---- primitives ----------------------------------------------------------

  Path? _path(List<List<double>> pts) {
    final p = Path();
    for (var i = 0; i < pts.length; i++) {
      final o = cam.project(pts[i][0], pts[i][1], pts[i][2]);
      if (o == null) return null;
      i == 0 ? p.moveTo(o.dx, o.dy) : p.lineTo(o.dx, o.dy);
    }
    return p..close();
  }

  void _quad(Canvas c, List<List<double>> pts, Paint fill, [Paint? stroke]) {
    final p = _path(pts);
    if (p == null) return;
    c.drawPath(p, fill);
    if (stroke != null) c.drawPath(p, stroke);
  }

  void _line(Canvas c, List<double> a, List<double> b, Paint paint) {
    final p = cam.project(a[0], a[1], a[2]), q = cam.project(b[0], b[1], b[2]);
    if (p != null && q != null) c.drawLine(p, q, paint);
  }

  void _dashed(Canvas c, List<double> a, List<double> b, Paint paint, {double dash = 0.3, double gap = 0.2}) {
    final dx = b[0] - a[0], dy = b[1] - a[1], dz = b[2] - a[2];
    final len = math.sqrt(dx * dx + dy * dy + dz * dz);
    if (len < 1e-6) return;
    for (var s = 0.0; s < len; s += dash + gap) {
      final e = math.min(s + dash, len);
      _line(c, [a[0] + dx * s / len, a[1] + dy * s / len, a[2] + dz * s / len],
          [a[0] + dx * e / len, a[1] + dy * e / len, a[2] + dz * e / len], paint);
    }
  }

  void _dashedPolyline(Canvas c, List<List<double>> pts, Color color, double w) {
    final paint = Paint()..color = color..strokeWidth = w..style = PaintingStyle.stroke;
    for (var i = 1; i < pts.length; i++) {
      _dashed(c, pts[i - 1], pts[i], paint, dash: 0.35, gap: 0.3);
    }
  }

  void _ring(Canvas c, double x, double y, double z, double r, Color color, double w) {
    final path = Path();
    var started = false;
    for (var i = 0; i <= 32; i++) {
      final a = i / 32 * 2 * math.pi;
      final o = cam.project(x + r * math.cos(a), y, z + r * math.sin(a));
      if (o == null) return;
      started ? path.lineTo(o.dx, o.dy) : path.moveTo(o.dx, o.dy);
      started = true;
    }
    c.drawPath(path, Paint()..color = color..style = PaintingStyle.stroke..strokeWidth = w);
  }

  void _label(Canvas c, Offset at, String text, {Color bg = const Color(0xD90F172A), Color fg = Colors.white, Color? border, double size = 11, List<TextSpan>? extra}) {
    final tp = TextPainter(
      text: TextSpan(style: TextStyle(color: fg, fontSize: size, fontWeight: FontWeight.w600), text: text, children: extra),
      textDirection: TextDirection.ltr,
      textAlign: TextAlign.center,
    )..layout();
    final r = RRect.fromRectAndRadius(Rect.fromCenter(center: at, width: tp.width + 12, height: tp.height + 6), const Radius.circular(5));
    c.drawRRect(r, Paint()..color = bg);
    if (border != null) c.drawRRect(r, Paint()..color = border..style = PaintingStyle.stroke);
    tp.paint(c, at - Offset(tp.width / 2, tp.height / 2));
  }

  // ---- scene pieces --------------------------------------------------------

  void _grid(Canvas c, double hx, double hz) {
    final p = Paint()..color = const Color(0x66CBD5E1)..strokeWidth = 0.7;
    for (var x = (-hx / 5).ceil() * 5.0; x <= hx; x += 5) {
      _line(c, [x, 0.01, -hz], [x, 0.01, hz], p);
    }
    for (var z = (-hz / 5).ceil() * 5.0; z <= hz; z += 5) {
      _line(c, [-hx, 0.01, z], [hx, 0.01, z], p);
    }
  }

  void _zone(Canvas c, J z) {
    final col = hexColor(z['color'] as String?);
    final x0 = nd(z['xmin']), x1 = nd(z['xmax']), z0 = nd(z['zmin']), z1 = nd(z['zmax']);
    _quad(c, [[x0, 0.02, z0], [x1, 0.02, z0], [x1, 0.02, z1], [x0, 0.02, z1]], Paint()..color = col.withValues(alpha: 0.18));
    final o = cam.project((x0 + x1) / 2, 0.05, (z0 + z1) / 2);
    if (o != null) {
      final tp = TextPainter(
        text: TextSpan(text: '${z['label']}', style: TextStyle(color: col, fontSize: 12, fontWeight: FontWeight.bold, shadows: const [Shadow(blurRadius: 3, color: Color(0x99000000))])),
        textDirection: TextDirection.ltr,
      )..layout();
      tp.paint(c, o - Offset(tp.width / 2, tp.height / 2));
    }
  }

  void _wall(Canvas c, J w) {
    final x1 = nd(w['x1']), z1 = nd(w['z1']), x2 = nd(w['x2']), z2 = nd(w['z2']);
    final h = nd(w['height'], 3);
    final len = math.sqrt((x2 - x1) * (x2 - x1) + (z2 - z1) * (z2 - z1));
    final rack = '${w['id']}'.startsWith('R');
    final half = (rack ? 0.6 : 0.3) / 2;
    final nx = len < 1e-6 ? 0.0 : -(z2 - z1) / len * half;
    final nz = len < 1e-6 ? half : (x2 - x1) / len * half;
    // corners: a0,a1 = end1 (-/+ normal), b0,b1 = end2
    List<double> pt(double x, double z, double s, double y) => [x + nx * s, y, z + nz * s];
    final b = [pt(x1, z1, -1, 0), pt(x1, z1, 1, 0), pt(x2, z2, 1, 0), pt(x2, z2, -1, 0)];
    final t = [pt(x1, z1, -1, h), pt(x1, z1, 1, h), pt(x2, z2, 1, h), pt(x2, z2, -1, h)];
    final sel = selected?.type == 'wall' && selected?.id == w['id'];
    final base = rack ? const Color(0xFF0EA5E9) : const Color(0xFFE2E8F0);
    final alpha = rack ? 1.0 : 0.38;
    final fill = Paint()..color = base.withValues(alpha: alpha);
    final edge = Paint()
      ..color = (rack ? const Color(0xFF0369A1) : const Color(0xFF94A3B8)).withValues(alpha: 0.9)
      ..style = PaintingStyle.stroke
      ..strokeWidth = sel ? 2 : 0.8;
    for (var i = 0; i < 4; i++) {
      final j = (i + 1) % 4;
      _quad(c, [b[i], b[j], t[j], t[i]], fill, edge);
    }
    _quad(c, t, Paint()..color = base.withValues(alpha: math.min(1, alpha + 0.1)), edge);
  }

  void _anchor(Canvas c, J a, bool sel) {
    final x = nd(a['x']), y = nd(a['y']), z = nd(a['z']);
    final o = cam.project(x, y, z);
    if (o == null) return;
    final px = math.max(8.0, 0.6 * cam.scaleAt(cam.depth(x, y, z)));
    final r = Rect.fromCenter(center: o, width: px, height: px);
    final col = sel ? const Color(0xFFFDE047) : const Color(0xFFF97316);
    c.drawRRect(RRect.fromRectAndRadius(r, const Radius.circular(2)), Paint()..color = col);
    c.drawRRect(RRect.fromRectAndRadius(r.inflate(sel ? 4 : 0), const Radius.circular(3)),
        Paint()..color = sel ? const Color(0xFFFDE047) : Colors.white..style = PaintingStyle.stroke..strokeWidth = sel ? 2 : 1);
    _label(c, o - Offset(0, px / 2 + 11), '📡 ${a['label']}', bg: const Color(0xEBF97316), border: Colors.white, size: 10);
  }

  void _tag(Canvas c, LiveTag t, bool sel) {
    final x = t.pos[0], y = t.pos[1], z = t.pos[2];
    final d = cam.depth(x, y, z);
    final color = roleColor(map, t.data['tagId'] as String);
    final bottom = cam.project(x, y - 0.45, z), top = cam.project(x, y + 0.45, z), head = cam.project(x, y + 0.65, z);
    if (bottom == null || top == null || head == null) return;
    final s = cam.scaleAt(d);
    c.drawLine(bottom, top, Paint()..color = color..strokeWidth = math.max(5, 0.8 * s)..strokeCap = StrokeCap.round);
    c.drawCircle(head, math.max(3.5, 0.28 * s), Paint()..color = Color.lerp(color, Colors.white, 0.35)!);
    if (sel) {
      c.drawCircle(Offset.lerp(bottom, top, 0.5)!, math.max(14, 0.75 * s), Paint()..color = const Color(0xFFFDE047)..style = PaintingStyle.stroke..strokeWidth = 2);
    }
    final battery = t.data['battery'];
    final low = battery is num && battery < 20;
    final zone = zoneLabel(map, t.data['zone'] as String?);
    _label(
      c,
      head - Offset(0, math.max(3.5, 0.28 * s) + 20),
      '${t.data['name'] ?? t.data['tagId']}',
      border: sel ? const Color(0xFFFDE047) : const Color(0x8038BDF8),
      extra: [
        TextSpan(text: '  ⚡${battery ?? '–'}%', style: TextStyle(color: low ? const Color(0xFFEF4444) : const Color(0xFF10B981))),
        if (zone != null) TextSpan(text: ' · $zone', style: const TextStyle(color: textMuted)),
      ],
    );
  }

  void _rangeLines(Canvas c, Map<String, J> anchors, List<double> pos, J? reading) {
    if (reading == null) return;
    for (final r in (reading['ranges'] as List? ?? const [])) {
      final a = anchors[r['anchorId']];
      if (a == null) continue;
      final valid = r['valid'] == true, nlos = r['nlos'] == true;
      final col = !valid ? const Color(0xFF64748B) : nlos ? const Color(0xFFEF4444) : const Color(0xFF22C55E);
      final paint = Paint()
        ..color = col.withValues(alpha: valid ? 0.8 : 0.4)
        ..strokeWidth = nlos ? 2.5 : 1.5
        ..style = PaintingStyle.stroke;
      final from = [nd(a['x']), nd(a['y']), nd(a['z'])], to = [pos[0], pos[1] + 0.5, pos[2]];
      valid ? _line(c, from, to, paint) : _dashed(c, from, to, paint);
    }
  }

  void _trail(Canvas c, List<List<double>> pts, Color base) {
    if (pts.length < 2) return;
    for (var i = 1; i < pts.length; i++) {
      final k = 0.25 + 0.75 * (i / (pts.length - 1));
      _line(c, pts[i - 1], pts[i],
          Paint()..color = Color.fromRGBO((base.r * 255 * k).round(), (base.g * 255 * k).round(), (base.b * 255 * k).round(), 0.85)..strokeWidth = 2.5..strokeCap = StrokeCap.round);
    }
  }

  void _rawGhost(Canvas c, LiveTag t) {
    final raw = t.data['raw'];
    if (raw == null) return;
    final y = t.pos[1];
    final cov = t.data['cov'];
    final r = cov is Map ? math.max(0.2, nd(cov['sx']) + nd(cov['sz'])) : 0.5;
    final o = cam.project(nd(raw['x']), y, nd(raw['z']));
    if (o != null) c.drawCircle(o, 5, Paint()..color = const Color(0x8CEF4444));
    _ring(c, t.pos[0], 0.03, t.pos[2], r, const Color(0x8038BDF8), 2);
  }

  void _aiGhost(Canvas c, LiveTag t) {
    final g = t.data['ghost'];
    if (g == null) return;
    final col = roleColor(map, t.data['tagId'] as String);
    final gx = nd(g['x']), gz = nd(g['z']), y = t.pos[1];
    final r = math.max(0.15, nd(g['r'], 0.3));
    final o = cam.project(gx, y, gz);
    if (o != null) c.drawCircle(o, 6, Paint()..color = col.withValues(alpha: 0.35));
    _ring(c, gx, 0.04, gz, r, col.withValues(alpha: 0.45), 2);
    _dashed(c, [t.pos[0], y, t.pos[2]], [gx, y, gz], Paint()..color = col.withValues(alpha: 0.6)..strokeWidth = 1.2..style = PaintingStyle.stroke, dash: 0.2, gap: 0.15);
  }

  @override
  bool shouldRepaint(ScenePainter old) => true; // driven by `repaint` ticks
}
