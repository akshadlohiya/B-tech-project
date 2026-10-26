import 'package:flutter/foundation.dart';
import 'package:socket_io_client/socket_io_client.dart' as sio;
import 'api.dart';
import 'util.dart';

const _trailMax = 150; // ~30 s of history at 5 Hz
const _alertsMax = 50;

/// Socket.IO subscription to one map's live room (port of Viewer3D's effect).
class LiveFeed extends ChangeNotifier {
  LiveFeed(this.mapKey, {this.onMapUpdated}) {
    final s = sio.io(
      Api.base,
      sio.OptionBuilder().setTransports(['websocket']).disableAutoConnect().build(),
    );
    _socket = s;
    s.onConnect((_) {
      connected = true;
      s.emit('join_map', mapKey);
      notifyListeners();
    });
    s.onDisconnect((_) {
      connected = false;
      notifyListeners();
    });
    s.on('initial_state', (d) {
      final m = Map<String, dynamic>.from(d as Map);
      positions = _mapOfMaps(m['positions']);
      readings = _mapOfMaps(m['readings']);
      alerts = ((m['alerts'] as List?) ?? []).map((e) => Map<String, dynamic>.from(e as Map)).toList();
      notifyListeners();
    });
    s.on('alert', (d) {
      alerts.add(Map<String, dynamic>.from(d as Map));
      if (alerts.length > _alertsMax) alerts.removeRange(0, alerts.length - _alertsMax);
      notifyListeners();
    });
    s.on('location_update', (d) {
      final p = Map<String, dynamic>.from(d as Map);
      final id = p['tagId'];
      final pos = p['pos'];
      if (id == null || pos == null) return; // ignore malformed/partial updates
      positions[id] = p;
      _push(trails, id, [nd(pos['x']), nd(pos['y']), nd(pos['z'])]);
      final truth = p['truth'];
      if (truth != null) _push(truthTrails, id, [nd(truth['x']), nd(pos['y']), nd(truth['z'])]);
      if (p['error'] != null) {
        _push(errHist, id, {'err': nd(p['error']), 'raw': nd(p['rawError'] ?? p['error'])});
      }
      notifyListeners();
    });
    s.on('reading_update', (d) {
      final r = Map<String, dynamic>.from(d as Map);
      readings[r['tagId']] = r;
      notifyListeners();
    });
    s.on('map_updated', (_) => onMapUpdated?.call());
    s.connect();
  }

  final String mapKey;
  final VoidCallback? onMapUpdated;
  late final sio.Socket _socket;

  bool connected = false;
  Map<String, J> positions = {};
  Map<String, J> readings = {};
  List<J> alerts = [];
  final Map<String, List<List<double>>> trails = {};
  final Map<String, List<List<double>>> truthTrails = {};
  final Map<String, List<Map<String, double>>> errHist = {};

  static Map<String, J> _mapOfMaps(dynamic v) => {
        for (final e in ((v as Map?) ?? const {}).entries) '${e.key}': Map<String, dynamic>.from(e.value as Map),
      };

  static void _push<T>(Map<String, List<T>> store, String id, T pt) {
    final arr = store.putIfAbsent(id, () => []);
    arr.add(pt);
    if (arr.length > _trailMax) arr.removeRange(0, arr.length - _trailMax);
  }

  @override
  void dispose() {
    _socket.dispose();
    super.dispose();
  }
}
