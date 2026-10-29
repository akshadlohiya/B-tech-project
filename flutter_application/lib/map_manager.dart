import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'api.dart';
import 'editor2d.dart';
import 'util.dart';
import 'viewer3d.dart';

/// Landing page: the library of maps. Create, open (view/edit), share, delete.
class MapManager extends StatefulWidget {
  const MapManager({super.key});
  @override
  State<MapManager> createState() => _MapManagerState();
}

class _MapManagerState extends State<MapManager> {
  List<J>? _maps;
  String? _err;
  final _name = TextEditingController();
  String? _copied;

  @override
  void initState() {
    super.initState();
    _refresh();
  }

  @override
  void dispose() {
    _name.dispose();
    super.dispose();
  }

  Future<void> _refresh() async {
    setState(() => _err = null);
    try {
      final m = await Api.listMaps();
      if (mounted) setState(() => _maps = m);
    } catch (e) {
      if (mounted) setState(() { _err = '$e'; _maps = null; });
    }
  }

  Future<void> _open(String key, {required bool edit}) async {
    await Navigator.push(context, MaterialPageRoute(builder: (_) => edit ? Editor2D(mapKey: key) : Viewer3D(mapKey: key)));
    _refresh();
  }

  Future<void> _create() async {
    try {
      final res = await Api.createMap(_name.text.trim().isEmpty ? 'Untitled Map' : _name.text.trim());
      _name.clear();
      if (mounted) await _open(res['key'] as String, edit: true);
    } catch (e) {
      if (mounted) toast(context, 'Create failed: $e');
    }
  }

  Future<void> _remove(String key) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: const Text('Delete map?'),
        content: Text('Delete map "$key"? This cannot be undone.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Cancel')),
          TextButton(onPressed: () => Navigator.pop(c, true), child: const Text('Delete', style: TextStyle(color: Color(0xFFFCA5A5)))),
        ],
      ),
    );
    if (ok != true) return;
    try {
      await Api.deleteMap(key);
    } catch (e) {
      if (mounted) toast(context, '$e');
    }
    _refresh();
  }

  Future<void> _copy(String key) async {
    await Clipboard.setData(ClipboardData(text: key));
    setState(() => _copied = key);
    Future.delayed(const Duration(milliseconds: 1500), () { if (mounted) setState(() => _copied = null); });
  }

  Future<void> _openByKey() async {
    final c = TextEditingController();
    final key = await showDialog<String>(
      context: context,
      builder: (d) => AlertDialog(
        title: const Text('Open shared map'),
        content: TextField(controller: c, autofocus: true, decoration: const InputDecoration(hintText: 'Map key')),
        actions: [
          TextButton(onPressed: () => Navigator.pop(d), child: const Text('Cancel')),
          TextButton(onPressed: () => Navigator.pop(d, c.text.trim()), child: const Text('View')),
        ],
      ),
    );
    if (key != null && key.isNotEmpty && mounted) _open(key, edit: false);
  }

  Future<void> _settings() async {
    final c = TextEditingController(text: Api.base);
    final saved = await showDialog<bool>(
      context: context,
      builder: (d) => AlertDialog(
        title: const Text('Server'),
        content: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
          TextField(controller: c, keyboardType: TextInputType.url, decoration: const InputDecoration(labelText: 'Backend URL', hintText: 'http://192.168.1.20:3000')),
          const SizedBox(height: 10),
          const Text(
            'Address of the machine running backend/server.js (your Pi or PC), on the same Wi-Fi as this phone. '
            'On the Android emulator the host PC is 10.0.2.2.',
            style: TextStyle(color: textMuted, fontSize: 12),
          ),
        ]),
        actions: [
          TextButton(onPressed: () => Navigator.pop(d, false), child: const Text('Cancel')),
          TextButton(onPressed: () => Navigator.pop(d, true), child: const Text('Save')),
        ],
      ),
    );
    if (saved == true) {
      await Api.setBase(c.text);
      _refresh();
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('UWB RTLS — Map Library'),
        actions: [
          IconButton(tooltip: 'Open by key', icon: const Icon(Icons.key), onPressed: _openByKey),
          IconButton(tooltip: 'Server', icon: const Icon(Icons.settings_ethernet), onPressed: _settings),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: _refresh,
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            const Text('Create indoor maps, draw floorplans, and share a key so anyone can watch live tracking.', style: TextStyle(color: textMuted)),
            const SizedBox(height: 16),
            Row(children: [
              Expanded(child: TextField(controller: _name, onSubmitted: (_) => _create(), decoration: const InputDecoration(hintText: 'New map name (e.g. Warehouse B)'))),
              const SizedBox(width: 10),
              FilledButton.icon(onPressed: _create, icon: const Icon(Icons.add), label: const Text('Create')),
            ]),
            const SizedBox(height: 20),
            if (_err != null)
              Padding(
                padding: const EdgeInsets.only(bottom: 16),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text('⚠️ Cannot reach backend at ${Api.base}\n($_err)', style: const TextStyle(color: Color(0xFFFCA5A5))),
                  const SizedBox(height: 8),
                  OutlinedButton(style: smallBtn, onPressed: _settings, child: const Text('Set server address')),
                ]),
              ),
            if (_maps == null && _err == null) const Center(child: Padding(padding: EdgeInsets.all(24), child: CircularProgressIndicator())),
            if (_maps != null && _maps!.isEmpty) const Text('No maps yet — create one above.', style: TextStyle(color: textMuted)),
            for (final m in _maps ?? const <J>[]) _card(m),
          ],
        ),
      ),
    );
  }

  Widget _card(J m) {
    final key = m['key'] as String;
    return Container(
      margin: const EdgeInsets.only(bottom: 14),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(color: cardBg.withValues(alpha: 0.6), borderRadius: BorderRadius.circular(14), border: Border.all(color: cardBorder)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('${m['name']}', style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w700)),
        const SizedBox(height: 4),
        Text.rich(TextSpan(style: const TextStyle(color: textMuted, fontSize: 13), children: [
          TextSpan(text: key, style: const TextStyle(fontFamily: 'monospace', color: accent)),
          TextSpan(text: ' · ${m['anchors']} anchors · ${m['tags']} tags${(m['floor'] ?? '') != '' ? ' · ${m['floor']}' : ''}'),
        ])),
        const SizedBox(height: 10),
        Wrap(spacing: 8, runSpacing: 8, children: [
          OutlinedButton(style: smallBtn, onPressed: () => _open(key, edit: false), child: const Text('▶ View')),
          OutlinedButton(style: smallBtn, onPressed: () => _open(key, edit: true), child: const Text('✎ Edit')),
          OutlinedButton(style: smallBtn, onPressed: () => _copy(key), child: Text(_copied == key ? '✓ Copied' : '🔗 Copy key')),
          if (key != 'demo')
            OutlinedButton(style: smallBtn.copyWith(foregroundColor: const WidgetStatePropertyAll(Color(0xFFFCA5A5))), onPressed: () => _remove(key), child: const Icon(Icons.delete_outline, size: 18)),
        ]),
      ]),
    );
  }
}
