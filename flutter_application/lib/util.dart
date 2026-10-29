import 'dart:convert';
import 'package:flutter/material.dart';

typedef J = Map<String, dynamic>;

const bgDark = Color(0xFF0F1117);
const cardBg = Color(0xFF1E293B);
const cardBorder = Color(0xFF334155);
const textMuted = Color(0xFF94A3B8);
const accent = Color(0xFF38BDF8);

const roleColors = {
  'asset': Color(0xFFEAB308),
  'person': Color(0xFF3B82F6),
  'default': Color(0xFFA855F7),
};

double nd(dynamic v, [double def = 0]) =>
    v is num ? v.toDouble() : (double.tryParse('$v') ?? def);

double round1(double v) => (v * 10).roundToDouble() / 10;

J deepCopy(J o) => jsonDecode(jsonEncode(o)) as J;

Color hexColor(String? h, [Color def = accent]) {
  if (h == null || !h.startsWith('#') || (h.length != 7 && h.length != 4)) return def;
  var s = h.substring(1);
  if (s.length == 3) s = s.split('').map((c) => c + c).join();
  final v = int.tryParse(s, radix: 16);
  return v == null ? def : Color(0xFF000000 | v);
}

String colorHex(Color c) =>
    '#${(c.toARGB32() & 0xFFFFFF).toRadixString(16).padLeft(6, '0')}';

List<J> listOf(J m, String k) =>
    ((m[k] as List?) ?? const []).map((e) => e as J).toList();

J? tagCfg(J map, String id) {
  for (final t in listOf(map, 'tags')) {
    if (t['id'] == id) return t;
  }
  return null;
}

Color roleColor(J map, String tagId) =>
    roleColors[tagCfg(map, tagId)?['role']] ?? roleColors['default']!;

String? zoneLabel(J map, String? zoneId) {
  if (zoneId == null) return null;
  for (final z in listOf(map, 'zones')) {
    if (z['id'] == zoneId) return (z['label'] ?? zoneId) as String;
  }
  return zoneId;
}

/// A tag is out of bounds when it has an allow-list and its zone is not on it.
bool outsideAllowed(J map, J p) {
  final allowed = tagCfg(map, p['tagId'] as String)?['allowedZones'] as List?;
  return allowed != null && allowed.isNotEmpty && !allowed.contains(p['zone']);
}

String nextId(List<J> list, String prefix) {
  var mx = 0;
  for (final x in list) {
    final m = RegExp(r'\d+').firstMatch('${x['id']}');
    final n = m == null ? 0 : int.parse(m.group(0)!);
    if (n > mx) mx = n;
  }
  return '$prefix${mx + 1}';
}

void toast(BuildContext c, String msg) =>
    ScaffoldMessenger.of(c).showSnackBar(SnackBar(content: Text(msg), duration: const Duration(seconds: 2)));

ButtonStyle get smallBtn => OutlinedButton.styleFrom(
      foregroundColor: const Color(0xFFE2E8F0),
      backgroundColor: cardBg,
      side: const BorderSide(color: cardBorder),
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
    );
