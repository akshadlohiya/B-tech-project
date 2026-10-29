import 'dart:math' as math;
import 'package:flutter/material.dart';
import 'api.dart';
import 'util.dart';

/// 2D top-down floorplan editor (port of Editor2D.jsx). World is metres;
/// -z (north) is up on screen, matching the 3D view from above. One finger
/// edits, two fingers pan/zoom.

const _tools = [
  ('select', 'Select / Move', Icons.near_me_outlined),
  ('wall', 'Wall', Icons.horizontal_rule),
  ('zone', 'Area', Icons.crop_square),
  ('anchor', 'Anchor', Icons.sensors),
  ('tag', 'Tag', Icons.label_outline),
  ('delete', 'Delete', Icons.delete_outline),
];

class _Hit {
  _Hit(this.type, this.id, {this.pt = 0, this.idx = 0});
  final String type; // anchor | zone | wall | wallpt | tag | waypoint
  final String id;
  final int pt, idx;
}

class Editor2D extends StatefulWidget {
  const Editor2D({super.key, required this.mapKey});
  final String mapKey;
  @override
  State<Editor2D> createState() => _Editor2DState();
}

class _Editor2DState extends State<Editor2D> {
  J? _map;
  String? _err;
  String _tool = 'select';
  ({String type, String id})? _sel;
  bool _saving = false;

  // view transform
  double _scale = 10, _cx = 0, _cz = 0;
  Size _size = Size.zero;
  bool _fitted = false;

  // interaction
  final Map<int, Offset> _ptrs = {};
  bool _multi = false;
  Offset _downPos = Offset.zero, _panLast = Offset.zero;
  bool _moved = false, _panning = false;
  _Hit? _drag;
  Offset _dragStartW = Offset.zero; // world (x, z)
  dynamic _snap;
  ({double x, double z})? _wallStart, _cursor;
  ({({double x, double z}) a, ({double x, double z}) b})? _zoneDraw;
  double _pinchD0 = 1, _pinchS0 = 1;
  Offset _pinchW0 = Offset.zero;

  @override
  void initState() {
    super.initState();
    Api.getMap(widget.mapKey).then((m) {
      if (mounted) setState(() => _map = m);
    }).catchError((e) {
      if (mounted) setState(() => _err = '$e');
    });
  }

  // ---- transforms ----------------------------------------------------------
  ({double x, double z}) _s2w(Offset o) =>
      (x: round1((o.dx - _size.width / 2) / _scale + _cx), z: round1((o.dy - _size.height / 2) / _scale + _cz));

  void _fit() {
    final f = _map!['floor'] as J;
    final sx = nd(f['sizeX'], 30) + 8, sz = nd(f['sizeZ'], 30) + 8;
    _scale = math.min(_size.width / sx, _size.height / sz);
    _cx = 0;
    _cz = 0;
  }

  // ---- model edits (mutate in place, then setState) ----------------------
  void _mut(void Function(J m) fn) => setState(() => fn(_map!));

  void _addAnchor(double x, double z) => _mut((m) {
        final list = listOf(m, 'anchors');
        final id = nextId(list, 'A');
        (m['anchors'] as List).add({'id': id, 'label': id, 'x': x, 'y': nd((m['floor'] as J)['ceilingHeight'], 5) - 0.4, 'z': z, 'antennaDelayBiasM': 0.1, 'provenance': 'guessed'});
        _sel = (type: 'anchor', id: id);
      });

  void _addTag(double x, double z) => _mut((m) {
        final id = nextId(listOf(m, 'tags'), 'T');
        (m['tags'] as List).add({
          'id': id, 'name': 'Tag $id', 'role': 'asset', 'battery': 100, 'y': 0.5, 'speed': 1.2, 'allowedZones': [],
          'waypoints': [[x, z], [x + 4, z], [x + 4, z + 4], [x, z + 4], [x, z]],
          'pauseAtWaypointSec': 1, 'loop': true,
        });
        _sel = (type: 'tag', id: id);
      });

  void _addWall(double x1, double z1, double x2, double z2) => _mut((m) {
        final id = nextId(listOf(m, 'walls'), 'W');
        (m['walls'] as List).add({'id': id, 'label': id, 'x1': x1, 'z1': z1, 'x2': x2, 'z2': z2, 'height': 3, 'blocksLos': true, 'provenance': 'guessed'});
      });

  void _addZone(({double x, double z}) a, ({double x, double z}) b) => _mut((m) {
        final id = nextId(listOf(m, 'zones'), 'Z');
        (m['zones'] as List).add({'id': id, 'label': 'Area $id', 'xmin': math.min(a.x, b.x), 'xmax': math.max(a.x, b.x), 'zmin': math.min(a.z, b.z), 'zmax': math.max(a.z, b.z), 'color': '#38bdf8'});
        _sel = (type: 'zone', id: id);
      });

  void _remove(String type, String id) => _mut((m) {
        final key = {'anchor': 'anchors', 'wall': 'walls', 'zone': 'zones', 'tag': 'tags'}[type];
        if (key != null) (m[key] as List).removeWhere((e) => e['id'] == id);
        if (_sel?.id == id) _sel = null;
      });

  // ---- hit testing -----------------------------------------------------------
  _Hit? _hitTest(({double x, double z}) w) {
    final m = _map!;
    final tol = 22 / _scale; // metres for a ~22px finger target
    double dist(double x, double z) => math.sqrt((x - w.x) * (x - w.x) + (z - w.z) * (z - w.z));

    if (_sel?.type == 'wall') {
      final wl = listOf(m, 'walls').where((x) => x['id'] == _sel!.id).firstOrNull;
      if (wl != null) {
        for (final pt in [1, 2]) {
          if (dist(nd(wl['x$pt']), nd(wl['z$pt'])) < math.max(0.4, tol)) return _Hit('wallpt', wl['id'] as String, pt: pt);
        }
      }
    }
    if (_sel?.type == 'tag') {
      final t = tagCfg(m, _sel!.id);
      if (t != null) {
        final wp = t['waypoints'] as List;
        for (var i = 0; i < wp.length; i++) {
          if (dist(nd(wp[i][0]), nd(wp[i][1])) < math.max(0.35, tol)) return _Hit('waypoint', t['id'] as String, idx: i);
        }
      }
    }
    for (final a in listOf(m, 'anchors')) {
      if (dist(nd(a['x']), nd(a['z'])) < math.max(0.6, tol)) return _Hit('anchor', a['id'] as String);
    }
    for (final t in listOf(m, 'tags')) {
      final p = (t['waypoints'] as List).first;
      if (dist(nd(p[0]), nd(p[1])) < math.max(0.7, tol)) return _Hit('tag', t['id'] as String);
    }
    for (final wl in listOf(m, 'walls')) {
      if (_segDist(w.x, w.z, nd(wl['x1']), nd(wl['z1']), nd(wl['x2']), nd(wl['z2'])) < math.max(0.3, tol * 0.7)) return _Hit('wall', wl['id'] as String);
    }
    for (final z in listOf(m, 'zones').reversed) {
      if (w.x >= nd(z['xmin']) && w.x <= nd(z['xmax']) && w.z >= nd(z['zmin']) && w.z <= nd(z['zmax'])) return _Hit('zone', z['id'] as String);
    }
    return null;
  }

  double _segDist(double px, double pz, double x1, double z1, double x2, double z2) {
    final dx = x2 - x1, dz = z2 - z1;
    final l2 = dx * dx + dz * dz;
    final t = l2 == 0 ? 0.0 : (((px - x1) * dx + (pz - z1) * dz) / l2).clamp(0.0, 1.0);
    final qx = x1 + t * dx, qz = z1 + t * dz;
    return math.sqrt((px - qx) * (px - qx) + (pz - qz) * (pz - qz));
  }

  // ---- pointer plumbing --------------------------------------------------------
  void _down(PointerDownEvent e) {
    _ptrs[e.pointer] = e.localPosition;
    if (_ptrs.length >= 2) {
      _beginMulti();
    } else {
      _beginSingle(e.localPosition);
    }
  }

  void _beginMulti() {
    _multi = true;
    _drag = null;
    _panning = false;
    _zoneDraw = null;
    final pts = _ptrs.values.take(2).toList();
    _pinchD0 = math.max(1, (pts[0] - pts[1]).distance);
    _pinchS0 = _scale;
    final mid = (pts[0] + pts[1]) / 2;
    final w = _s2w(mid);
    _pinchW0 = Offset(w.x, w.z);
    setState(() {});
  }

  void _beginSingle(Offset pos) {
    if (_multi) return;
    _downPos = pos;
    _moved = false;
    _drag = null;
    _panning = false;
    final w = _s2w(pos);
    _cursor = w;
    setState(() {
      switch (_tool) {
        case 'select':
          final h = _hitTest(w);
          if (h != null) {
            _sel = (type: h.type == 'wallpt' ? 'wall' : h.type == 'waypoint' ? 'tag' : h.type, id: h.id);
            if (h.type == 'wall') {
              _panning = true; // walls are reshaped via their end handles
              _panLast = pos;
            } else {
              _drag = h;
              _dragStartW = Offset(w.x, w.z);
              _snap = _snapshot(h);
            }
          } else {
            _sel = null;
            _panning = true;
            _panLast = pos;
          }
        case 'delete':
          final h = _hitTest(w);
          if (h != null) _remove(h.type == 'wallpt' ? 'wall' : h.type == 'waypoint' ? 'tag' : h.type, h.id);
        case 'zone':
          _zoneDraw = (a: w, b: w);
      }
    });
  }

  dynamic _snapshot(_Hit h) {
    final m = _map!;
    switch (h.type) {
      case 'anchor':
        final a = listOf(m, 'anchors').firstWhere((x) => x['id'] == h.id);
        return [nd(a['x']), nd(a['z'])];
      case 'zone':
        final z = listOf(m, 'zones').firstWhere((x) => x['id'] == h.id);
        return [nd(z['xmin']), nd(z['xmax']), nd(z['zmin']), nd(z['zmax'])];
      case 'tag':
        final t = tagCfg(m, h.id)!;
        return (t['waypoints'] as List).map((p) => [nd(p[0]), nd(p[1])]).toList();
    }
    return null;
  }

  void _move(PointerMoveEvent e) {
    if (!_ptrs.containsKey(e.pointer)) return;
    _ptrs[e.pointer] = e.localPosition;
    if (_ptrs.length >= 2) {
      final pts = _ptrs.values.take(2).toList();
      final mid = (pts[0] + pts[1]) / 2;
      setState(() {
        _scale = (_pinchS0 * (pts[0] - pts[1]).distance / _pinchD0).clamp(2.0, 200.0);
        // keep the world point under the pinch centre fixed
        _cx = _pinchW0.dx - (mid.dx - _size.width / 2) / _scale;
        _cz = _pinchW0.dy - (mid.dy - _size.height / 2) / _scale;
      });
      return;
    }
    if (_multi) return;
    final pos = e.localPosition;
    if ((pos - _downPos).distance > 8) _moved = true;
    final w = _s2w(pos);
    setState(() {
      _cursor = w;
      if (_zoneDraw != null) {
        _zoneDraw = (a: _zoneDraw!.a, b: w);
      } else if (_panning) {
        _cx -= (pos.dx - _panLast.dx) / _scale;
        _cz -= (pos.dy - _panLast.dy) / _scale;
        _panLast = pos;
      } else if (_drag != null && _moved) {
        _applyDrag(_drag!, w);
      }
    });
  }

  void _applyDrag(_Hit d, ({double x, double z}) w) {
    final m = _map!;
    final dx = w.x - _dragStartW.dx, dz = w.z - _dragStartW.dy;
    switch (d.type) {
      case 'anchor':
        final a = listOf(m, 'anchors').firstWhere((x) => x['id'] == d.id);
        a['x'] = round1(_snap[0] + dx);
        a['z'] = round1(_snap[1] + dz);
      case 'zone':
        final z = listOf(m, 'zones').firstWhere((x) => x['id'] == d.id);
        z['xmin'] = round1(_snap[0] + dx);
        z['xmax'] = round1(_snap[1] + dx);
        z['zmin'] = round1(_snap[2] + dz);
        z['zmax'] = round1(_snap[3] + dz);
      case 'wallpt':
        final wl = listOf(m, 'walls').firstWhere((x) => x['id'] == d.id);
        wl['x${d.pt}'] = w.x;
        wl['z${d.pt}'] = w.z;
      case 'tag':
        final t = tagCfg(m, d.id)!;
        t['waypoints'] = [for (final p in _snap as List) [round1(p[0] + dx), round1(p[1] + dz)]];
      case 'waypoint':
        final t = tagCfg(m, d.id)!;
        (t['waypoints'] as List)[d.idx] = [w.x, w.z];
    }
  }

  void _up(PointerEvent e) {
    final wasSingle = _ptrs.length == 1 && !_multi;
    _ptrs.remove(e.pointer);
    if (_ptrs.isEmpty) {
      final multi = _multi;
      _multi = false;
      if (wasSingle && !multi) _endSingle(e.localPosition, cancelled: e is PointerCancelEvent);
    } else if (_ptrs.length == 1 && _multi) {
      // keep ignoring the remaining finger until everything is lifted
    }
  }

  void _endSingle(Offset pos, {required bool cancelled}) {
    final w = _s2w(pos);
    setState(() {
      final zd = _zoneDraw;
      _drag = null;
      _panning = false;
      _zoneDraw = null;
      if (cancelled) return;
      if (zd != null) {
        if (math.sqrt(math.pow(zd.b.x - zd.a.x, 2) + math.pow(zd.b.z - zd.a.z, 2)) > 0.5) _addZone(zd.a, zd.b);
        return;
      }
      if (_moved) return;
      switch (_tool) {
        case 'anchor':
          _addAnchor(w.x, w.z);
        case 'tag':
          _addTag(w.x, w.z);
        case 'wall':
          final s = _wallStart;
          if (s == null) {
            _wallStart = w;
          } else {
            _addWall(s.x, s.z, w.x, w.z);
            _wallStart = null;
          }
      }
    });
  }

  Future<void> _save() async {
    setState(() => _saving = true);
    try {
      await Api.saveMap(widget.mapKey, _map!);
      if (!mounted) return;
      toast(context, 'Saved & applied');
      Navigator.pop(context, true);
    } catch (e) {
      if (mounted) {
        setState(() => _saving = false);
        toast(context, 'Save failed: $e');
      }
    }
  }

  void _mapSettings() {
    final m = _map!;
    final meta = m['meta'] as J, floor = m['floor'] as J;
    showDialog(
      context: context,
      builder: (d) => AlertDialog(
        title: const Text('Map'),
        content: SingleChildScrollView(
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            _field('Name', '${meta['name'] ?? ''}', (v) => _mut((_) => meta['name'] = v), keyId: 'mname'),
            Row(children: [
              Expanded(child: _field('Width', '${floor['sizeX']}', (v) => _num(v, (n) => _mut((_) => floor['sizeX'] = n)), number: true, keyId: 'fx')),
              const SizedBox(width: 8),
              Expanded(child: _field('Depth', '${floor['sizeZ']}', (v) => _num(v, (n) => _mut((_) => floor['sizeZ'] = n)), number: true, keyId: 'fz')),
            ]),
            _field('Floor label', '${floor['label'] ?? ''}', (v) => _mut((_) => floor['label'] = v), keyId: 'fl'),
          ]),
        ),
        actions: [TextButton(onPressed: () { Navigator.pop(d); _fitted = false; setState(() {}); }, child: const Text('Done'))],
      ),
    );
  }

  // ---- UI ----------------------------------------------------------------------
  @override
  Widget build(BuildContext context) {
    if (_err != null) return Scaffold(appBar: AppBar(), body: Center(child: Text('⚠️ $_err', style: const TextStyle(color: Color(0xFFFCA5A5)))));
    final map = _map;
    if (map == null) return Scaffold(appBar: AppBar(), body: const Center(child: CircularProgressIndicator()));
    final meta = map['meta'] as J;

    return Scaffold(
      appBar: AppBar(
        titleSpacing: 0,
        title: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('${meta['name']}', style: const TextStyle(fontSize: 16), overflow: TextOverflow.ellipsis),
          Text(widget.mapKey, style: const TextStyle(fontSize: 11, fontFamily: 'monospace', color: Color(0xFF64748B))),
        ]),
        actions: [
          IconButton(tooltip: 'Map settings', icon: const Icon(Icons.tune), onPressed: _mapSettings),
          IconButton(tooltip: 'Fit to screen', icon: const Icon(Icons.fit_screen), onPressed: () => setState(_fit)),
          Padding(
            padding: const EdgeInsets.only(right: 8),
            child: FilledButton.icon(
              style: FilledButton.styleFrom(backgroundColor: const Color(0xFF16A34A)),
              onPressed: _saving ? null : _save,
              icon: const Icon(Icons.save, size: 18),
              label: Text(_saving ? 'Saving…' : 'Save'),
            ),
          ),
        ],
      ),
      body: Column(children: [
        Expanded(
          child: LayoutBuilder(builder: (ctx, c) {
            _size = Size(c.maxWidth, c.maxHeight);
            if (!_fitted) {
              _fitted = true;
              _fit();
            }
            return ClipRect(
              child: Stack(children: [
                Positioned.fill(
                  child: Listener(
                    behavior: HitTestBehavior.opaque,
                    onPointerDown: _down,
                    onPointerMove: _move,
                    onPointerUp: _up,
                    onPointerCancel: _up,
                    child: CustomPaint(
                      painter: _EditorPainter(map: map, sel: _sel, tool: _tool, scale: _scale, cx: _cx, cz: _cz, wallStart: _wallStart, cursor: _cursor, zoneDraw: _zoneDraw),
                    ),
                  ),
                ),
                Positioned(
                  left: 10, bottom: 8, right: 10,
                  child: IgnorePointer(
                    child: Text(_hint(), style: const TextStyle(color: Color(0xFF94A3B8), fontSize: 12, shadows: [Shadow(blurRadius: 4, color: Colors.black)])),
                  ),
                ),
              ]),
            );
          }),
        ),
        if (_sel != null)
          Container(
            constraints: BoxConstraints(maxHeight: MediaQuery.of(context).size.height * 0.34),
            width: double.infinity,
            padding: const EdgeInsets.all(12),
            decoration: const BoxDecoration(color: bgDark, border: Border(top: BorderSide(color: cardBorder))),
            child: SingleChildScrollView(child: _props(map)),
          ),
        Container(
          height: 54,
          decoration: const BoxDecoration(color: bgDark, border: Border(top: BorderSide(color: cardBorder))),
          child: ListView(
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 8),
            children: [
              for (final (id, label, icon) in _tools)
                Padding(
                  padding: const EdgeInsets.only(right: 6),
                  child: ChoiceChip(
                    avatar: Icon(icon, size: 16),
                    label: Text(label),
                    selected: _tool == id,
                    selectedColor: const Color(0xFF2563EB),
                    onSelected: (_) => setState(() { _tool = id; _wallStart = null; }),
                  ),
                ),
            ],
          ),
        ),
      ]),
    );
  }

  String _hint() => switch (_tool) {
        'wall' => 'Tap two points to draw a wall.',
        'zone' => 'Drag to draw an area.',
        'select' => 'Tap to select; drag to move. Two fingers pan/zoom.',
        'delete' => 'Tap an item to delete it.',
        _ => 'Tap to place $_tool.',
      };

  void _num(String v, void Function(double) f) {
    final n = double.tryParse(v);
    if (n != null) f(n);
  }

  Widget _field(String label, String value, void Function(String) onChanged, {bool number = false, String? keyId}) => Padding(
        padding: const EdgeInsets.only(bottom: 10),
        child: TextFormField(
          key: ValueKey('$keyId${_sel?.id}'),
          initialValue: value,
          keyboardType: number ? const TextInputType.numberWithOptions(decimal: true, signed: true) : TextInputType.text,
          decoration: InputDecoration(labelText: label),
          onChanged: onChanged,
        ),
      );

  Widget _delBtn(String label, String type, String id) => SizedBox(
        width: double.infinity,
        child: OutlinedButton(
          style: smallBtn.copyWith(foregroundColor: const WidgetStatePropertyAll(Color(0xFFFCA5A5))),
          onPressed: () => _remove(type, id),
          child: Text(label),
        ),
      );

  Widget _props(J map) {
    final sel = _sel!;
    switch (sel.type) {
      case 'anchor':
        final a = listOf(map, 'anchors').where((x) => x['id'] == sel.id).firstOrNull;
        if (a == null) return const SizedBox.shrink();
        return Column(children: [
          _field('Label', '${a['label']}', (v) => _mut((_) => a['label'] = v), keyId: 'al'),
          Row(children: [
            for (final k in ['x', 'z', 'y'])
              Expanded(child: Padding(
                padding: const EdgeInsets.only(right: 6),
                child: _field(k, '${a[k]}', (v) => _num(v, (n) => _mut((_) => a[k] = n)), number: true, keyId: 'a$k'),
              )),
          ]),
          _delBtn('Delete anchor', 'anchor', sel.id),
        ]);
      case 'zone':
        final z = listOf(map, 'zones').where((x) => x['id'] == sel.id).firstOrNull;
        if (z == null) return const SizedBox.shrink();
        const palette = ['#38bdf8', '#22c55e', '#eab308', '#f97316', '#ef4444', '#a855f7', '#ec4899', '#94a3b8'];
        return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          _field('Label', '${z['label']}', (v) => _mut((_) => z['label'] = v), keyId: 'zl'),
          Wrap(spacing: 8, runSpacing: 8, children: [
            for (final c in palette)
              GestureDetector(
                onTap: () => _mut((_) => z['color'] = c),
                child: Container(
                  width: 30, height: 30,
                  decoration: BoxDecoration(color: hexColor(c), shape: BoxShape.circle, border: Border.all(color: z['color'] == c ? Colors.white : Colors.transparent, width: 2)),
                ),
              ),
          ]),
          const SizedBox(height: 10),
          _delBtn('Delete area', 'zone', sel.id),
        ]);
      case 'wall':
        final w = listOf(map, 'walls').where((x) => x['id'] == sel.id).firstOrNull;
        if (w == null) return const SizedBox.shrink();
        return Column(children: [
          _field('Height (m)', '${w['height']}', (v) => _num(v, (n) => _mut((_) => w['height'] = n)), number: true, keyId: 'wh'),
          CheckboxListTile(
            dense: true,
            contentPadding: EdgeInsets.zero,
            controlAffinity: ListTileControlAffinity.leading,
            title: const Text('Blocks line-of-sight (NLOS)'),
            value: w['blocksLos'] == true,
            onChanged: (v) => _mut((_) => w['blocksLos'] = v ?? false),
          ),
          const Text('Select a wall, then drag its yellow end handles to reshape it.', style: TextStyle(color: textMuted, fontSize: 12)),
          const SizedBox(height: 8),
          _delBtn('Delete wall', 'wall', sel.id),
        ]);
      case 'tag':
        final t = tagCfg(map, sel.id);
        if (t == null) return const SizedBox.shrink();
        final wp = t['waypoints'] as List;
        return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          _field('Name', '${t['name']}', (v) => _mut((_) => t['name'] = v), keyId: 'tn'),
          Padding(
            padding: const EdgeInsets.only(bottom: 10),
            child: DropdownButtonFormField<String>(
              key: ValueKey('role${sel.id}'),
              initialValue: const ['asset', 'person', 'default'].contains(t['role']) ? t['role'] as String : 'default',
              decoration: const InputDecoration(labelText: 'Role'),
              items: const [
                DropdownMenuItem(value: 'asset', child: Text('asset')),
                DropdownMenuItem(value: 'person', child: Text('person')),
                DropdownMenuItem(value: 'default', child: Text('other')),
              ],
              onChanged: (v) => _mut((_) => t['role'] = v),
            ),
          ),
          Row(children: [
            Expanded(child: Padding(padding: const EdgeInsets.only(right: 6), child: _field('Speed', '${t['speed']}', (v) => _num(v, (n) => _mut((_) => t['speed'] = n)), number: true, keyId: 'ts'))),
            Expanded(child: _field('Height', '${t['y']}', (v) => _num(v, (n) => _mut((_) => t['y'] = n)), number: true, keyId: 'ty')),
          ]),
          Text('${wp.length} waypoints — drag the dots to reshape the route.', style: const TextStyle(fontSize: 12, color: Color(0xFF64748B))),
          const SizedBox(height: 6),
          Row(children: [
            OutlinedButton(
              style: smallBtn,
              onPressed: () => _mut((_) {
                final last = wp.last;
                wp.insert(wp.length - 1, [nd(last[0]) + 2, nd(last[1]) + 2]);
              }),
              child: const Text('＋ waypoint'),
            ),
            const SizedBox(width: 8),
            OutlinedButton(
              style: smallBtn,
              onPressed: () => _mut((_) { if (wp.length > 3) wp.removeAt(wp.length - 2); }),
              child: const Text('－ waypoint'),
            ),
          ]),
          const SizedBox(height: 8),
          _delBtn('Delete tag', 'tag', sel.id),
        ]);
    }
    return const SizedBox.shrink();
  }
}

// ---- painter ---------------------------------------------------------------------

class _EditorPainter extends CustomPainter {
  _EditorPainter({required this.map, required this.sel, required this.tool, required this.scale, required this.cx, required this.cz, this.wallStart, this.cursor, this.zoneDraw});
  final J map;
  final ({String type, String id})? sel;
  final String tool;
  final double scale, cx, cz;
  final ({double x, double z})? wallStart, cursor;
  final ({({double x, double z}) a, ({double x, double z}) b})? zoneDraw;

  late Size _size;
  Offset w2s(double x, double z) => Offset(_size.width / 2 + (x - cx) * scale, _size.height / 2 + (z - cz) * scale);

  void _text(Canvas c, String s, Offset at, Color col, {double size = 11}) {
    final tp = TextPainter(text: TextSpan(text: s, style: TextStyle(color: col, fontSize: size)), textDirection: TextDirection.ltr)..layout();
    tp.paint(c, at - Offset(tp.width / 2, tp.height / 2));
  }

  void _dashedLine(Canvas c, List<Offset> pts, Paint p, {double dash = 8, double gap = 5}) {
    final path = Path()..moveTo(pts.first.dx, pts.first.dy);
    for (final o in pts.skip(1)) {
      path.lineTo(o.dx, o.dy);
    }
    for (final m in path.computeMetrics()) {
      for (var d = 0.0; d < m.length; d += dash + gap) {
        c.drawPath(m.extractPath(d, math.min(d + dash, m.length)), p);
      }
    }
  }

  @override
  void paint(Canvas canvas, Size size) {
    _size = size;
    canvas.drawRect(Offset.zero & size, Paint()..color = const Color(0xFF0B1220));
    final f = map['floor'] as J;
    final hx = nd(f['sizeX'], 30) / 2, hz = nd(f['sizeZ'], 30) / 2;
    final fr = Rect.fromPoints(w2s(-hx, hz), w2s(hx, -hz));
    canvas.drawRect(fr, Paint()..color = const Color(0xFF111C30));
    canvas.drawRect(fr, Paint()..color = const Color(0xFF334155)..style = PaintingStyle.stroke);
    final grid = Paint()..color = const Color(0xFF1E293B);
    for (var x = (-hx / 5).ceil() * 5.0; x <= hx; x += 5) {
      canvas.drawLine(w2s(x, -hz), w2s(x, hz), grid);
    }
    for (var z = (-hz / 5).ceil() * 5.0; z <= hz; z += 5) {
      canvas.drawLine(w2s(-hx, z), w2s(hx, z), grid);
    }

    for (final z in listOf(map, 'zones')) {
      final col = hexColor(z['color'] as String?);
      final s = sel?.type == 'zone' && sel?.id == z['id'];
      final r = Rect.fromPoints(w2s(nd(z['xmin']), nd(z['zmax'])), w2s(nd(z['xmax']), nd(z['zmin'])));
      canvas.drawRect(r, Paint()..color = col.withValues(alpha: s ? 0.28 : 0.15));
      canvas.drawRect(r, Paint()..color = s ? const Color(0xFFFDE047) : col..style = PaintingStyle.stroke..strokeWidth = s ? 2.5 : 1.5);
      _text(canvas, '${z['label']}', r.center, col, size: 12);
    }

    for (final w in listOf(map, 'walls')) {
      final s = sel?.type == 'wall' && sel?.id == w['id'];
      final rack = '${w['id']}'.startsWith('R');
      final a = w2s(nd(w['x1']), nd(w['z1'])), b = w2s(nd(w['x2']), nd(w['z2']));
      canvas.drawLine(a, b, Paint()..color = s ? const Color(0xFFFDE047) : rack ? const Color(0xFF0EA5E9) : const Color(0xFFCBD5E1)..strokeWidth = math.max(3, 0.4 * scale)..strokeCap = StrokeCap.round);
      if (s) {
        for (final p in [a, b]) {
          canvas.drawCircle(p, math.max(10, 0.4 * scale), Paint()..color = const Color(0xFFFDE047));
        }
      }
    }

    final ws = wallStart, cu = cursor;
    if (tool == 'wall' && ws != null && cu != null) {
      _dashedLine(canvas, [w2s(ws.x, ws.z), w2s(cu.x, cu.z)], Paint()..color = accent..strokeWidth = 2..style = PaintingStyle.stroke);
      canvas.drawCircle(w2s(ws.x, ws.z), 5, Paint()..color = accent);
    }
    final zd = zoneDraw;
    if (zd != null) {
      final r = Rect.fromPoints(w2s(zd.a.x, zd.a.z), w2s(zd.b.x, zd.b.z));
      canvas.drawRect(r, Paint()..color = accent.withValues(alpha: 0.2));
      canvas.drawRect(r, Paint()..color = accent..style = PaintingStyle.stroke..strokeWidth = 1.5);
    }

    for (final t in listOf(map, 'tags')) {
      final s = sel?.type == 'tag' && sel?.id == t['id'];
      final col = roleColors[t['role']] ?? roleColors['default']!;
      final wp = (t['waypoints'] as List).map((p) => w2s(nd(p[0]), nd(p[1]))).toList();
      if (wp.length > 1) _dashedLine(canvas, wp, Paint()..color = col.withValues(alpha: 0.55)..strokeWidth = 2..style = PaintingStyle.stroke);
      if (s) {
        for (final p in wp) {
          canvas.drawCircle(p, math.max(8, 0.35 * scale), Paint()..color = col);
          canvas.drawCircle(p, math.max(8, 0.35 * scale), Paint()..color = const Color(0xFFFDE047)..style = PaintingStyle.stroke..strokeWidth = 1.5);
        }
      }
      final p0 = wp.first, h = math.max(9.0, 0.5 * scale);
      canvas.drawRect(Rect.fromCenter(center: p0, width: h * 2, height: h * 2), Paint()..color = col);
      canvas.drawRect(Rect.fromCenter(center: p0, width: h * 2, height: h * 2), Paint()..color = s ? const Color(0xFFFDE047) : Colors.white..style = PaintingStyle.stroke..strokeWidth = 1.5);
      _text(canvas, '${t['name']}', p0 - Offset(0, h + 9), col);
    }

    for (final a in listOf(map, 'anchors')) {
      final s = sel?.type == 'anchor' && sel?.id == a['id'];
      final o = w2s(nd(a['x']), nd(a['z'])), r = math.max(8.0, 0.6 * scale);
      canvas.drawCircle(o, r, Paint()..color = const Color(0xFFF97316));
      canvas.drawCircle(o, r, Paint()..color = s ? const Color(0xFFFDE047) : Colors.white..style = PaintingStyle.stroke..strokeWidth = s ? 2.5 : 1.5);
      _text(canvas, '${a['label']}', o - Offset(0, r + 9), const Color(0xFFF97316));
    }
  }

  @override
  bool shouldRepaint(_EditorPainter old) => true;
}
