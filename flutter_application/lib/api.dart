import 'dart:convert';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';
import 'util.dart';

/// REST client for the RTLS hub (backend/server.js).
///
/// The web build derived the server from `window.location.hostname`; a phone
/// has no such thing, so the server URL is user-configurable and persisted.
class Api {
  // 10.0.2.2 is the host PC as seen from the Android emulator.
  static String base = 'http://10.0.2.2:3000';
  static const _prefKey = 'server_url';

  static Future<void> load() async {
    final p = await SharedPreferences.getInstance();
    base = p.getString(_prefKey) ?? base;
  }

  static Future<void> setBase(String url) async {
    var u = url.trim();
    if (u.isEmpty) return;
    if (!u.startsWith('http://') && !u.startsWith('https://')) u = 'http://$u';
    while (u.endsWith('/')) {
      u = u.substring(0, u.length - 1);
    }
    base = u;
    final p = await SharedPreferences.getInstance();
    await p.setString(_prefKey, u);
  }

  static const _timeout = Duration(seconds: 8);
  static Uri _u(String path) => Uri.parse('$base$path');

  static dynamic _decode(http.Response r) {
    final body = r.body.isEmpty ? null : jsonDecode(r.body);
    if (r.statusCode < 200 || r.statusCode >= 300) {
      throw Exception((body is Map ? body['error'] : null) ?? 'HTTP ${r.statusCode}');
    }
    return body;
  }

  static const _hdr = {'Content-Type': 'application/json'};

  static Future<List<J>> listMaps() async =>
      ((_decode(await http.get(_u('/api/maps')).timeout(_timeout)) as List)).map((e) => e as J).toList();

  static Future<J> createMap(String name) async =>
      _decode(await http.post(_u('/api/maps'), headers: _hdr, body: jsonEncode({'name': name})).timeout(_timeout)) as J;

  static Future<J> getMap(String key) async {
    final m = _decode(await http.get(_u('/api/maps/$key')).timeout(_timeout)) as J;
    m['anchors'] ??= [];
    m['walls'] ??= [];
    m['zones'] ??= [];
    m['tags'] ??= [];
    m['meta'] ??= <String, dynamic>{'name': key};
    m['floor'] ??= {'id': 'f_floor1', 'label': 'Floor', 'sizeX': 30, 'sizeZ': 30, 'ceilingHeight': 5};
    return m;
  }

  static Future<void> saveMap(String key, J map) async {
    _decode(await http.put(_u('/api/maps/$key'), headers: _hdr, body: jsonEncode(map)).timeout(_timeout));
  }

  static Future<void> deleteMap(String key) async {
    _decode(await http.delete(_u('/api/maps/$key')).timeout(_timeout));
  }
}
