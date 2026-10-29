// ==============================================================================
// Unified RTLS Backend Server:
// - Multi-Map Indoor Mapping Platform & Digital Twin REST / Socket.io Hub
// - SQLite Persistent Location History (tag_locations: tag, name, x, y, z, time)
// - Real-time Analytics & Zone Geofencing
// - Multi-channel Ingestion: HTTP REST, Socket.io, and UDP (Ports 3000 & 5005)
// ==============================================================================

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const os = require('os');
const dgram = require('dgram');
const express = require('express');
const http = require('http');
const { Server } = require('socket.io');
const cors = require('cors');

const database = require('./database');
const analytics = require('./analytics');

const app = express();
app.use(cors());
app.use(express.json({ limit: '4mb' }));

// -----------------------------------------------------------------------------
// MAP STORAGE & SITE CONFIG
// -----------------------------------------------------------------------------

const MAPS_DIR = path.join(__dirname, 'maps');
const SEED_PATH = path.join(__dirname, '..', 'config', 'site.json');
fs.mkdirSync(MAPS_DIR, { recursive: true });

const mapPath = (key) => path.join(MAPS_DIR, `${key}.json`);
const genKey = () => crypto.randomBytes(5).toString('hex'); // 10 hex chars

function readMap(key) {
  try { return JSON.parse(fs.readFileSync(mapPath(key), 'utf-8')); }
  catch { return null; }
}
function writeMap(key, obj) {
  fs.writeFileSync(mapPath(key), JSON.stringify(obj, null, 2), 'utf-8');
}
function listMaps() {
  return fs.readdirSync(MAPS_DIR).filter((f) => f.endsWith('.json')).map((f) => {
    const m = readMap(f.replace(/\.json$/, '')) || {};
    return {
      key: m.key,
      name: m.meta?.name || m.key,
      anchors: (m.anchors || []).length,
      tags: (m.tags || []).length,
      floor: m.floor?.label || '',
      updatedAt: m.meta?.updatedAt || null,
      producer: m.meta?.producer || null,   // set when something other than the gateway feeds it
    };
  }).filter((m) => m.key);
}

function validMap(m) {
  return m && m.schema === 'uwb.site/1' && Array.isArray(m.anchors) &&
    Array.isArray(m.tags) && Array.isArray(m.walls) && Array.isArray(m.zones) && m.floor;
}

function seedDemo() {
  if (readMap('demo')) return;
  let seed;
  try { seed = JSON.parse(fs.readFileSync(SEED_PATH, 'utf-8')); }
  catch { return; }
  seed.key = 'demo';
  seed.meta = { ...(seed.meta || {}), name: seed.meta?.name || 'Demo Warehouse', updatedAt: Date.now() };
  writeMap('demo', seed);
  console.log('Seeded demo map from config/site.json');
}
seedDemo();

function blankMap(name) {
  const demo = readMap('demo') || {};
  return {
    schema: 'uwb.site/1',
    key: undefined,
    meta: { name: name || 'Untitled Map', units: 'meters', updatedAt: Date.now() },
    floor: { id: 'f_floor1', label: 'Ground Floor', sizeX: 30, sizeZ: 30, ceilingHeight: 5, provenance: 'guessed' },
    anchors: [],
    walls: [],
    zones: [],
    tags: [],
    ranging: demo.ranging || {
      mode: 'DS-TWR', updateRateHz: 5, sequentialPerAnchor: true, speedOfLightMps: 299702547,
      assumedTagHeightM: 0.6, losNoiseStdM: 0.08, nlosNoiseStdM: 0.3, nlosBiasMinM: 0.25,
      nlosBiasMaxM: 1.2, maxRangeM: 60, dropProbLos: 0.01, dropProbNlos: 0.15,
      power: { rxPowerLosDbm: -80, rxPowerPerMeterDbm: -0.9, nlosRxDropDbm: -12, fpToRxDeltaLosDbm: -3, nlosFpExtraAttenDbm: -10 },
    },
  };
}

// -----------------------------------------------------------------------------
// MAPS REST API
// -----------------------------------------------------------------------------

app.get('/api/maps', (_req, res) => res.json(listMaps()));

app.post('/api/maps', (req, res) => {
  const key = genKey();
  const m = blankMap(req.body && req.body.name);
  m.key = key;
  writeMap(key, m);
  console.log(`Created map ${key} ("${m.meta.name}")`);
  io.emit('maps_changed', { key, at: Date.now() });   // gateway starts running it
  res.json({ key, map: m });
});

app.get('/api/maps/:key', (req, res) => {
  const m = readMap(req.params.key);
  if (!m) return res.status(404).json({ error: 'map not found' });
  res.json(m);
});

app.put('/api/maps/:key', (req, res) => {
  const key = req.params.key;
  const m = req.body;
  if (!validMap(m)) return res.status(400).json({ error: 'invalid map (schema/floor/anchors/walls/zones/tags required)' });
  const isNew = !fs.existsSync(mapPath(key));
  m.key = key;
  m.meta = { ...(m.meta || {}), updatedAt: Date.now() };
  writeMap(key, m);
  io.to(`map:${key}`).emit('map_updated', { key, at: Date.now() });
  if (isNew) io.emit('maps_changed', { key, at: Date.now() });
  console.log(`Map ${key} saved`);
  res.json({ ok: true });
});

app.delete('/api/maps/:key', (req, res) => {
  const key = req.params.key;
  if (key === 'demo') return res.status(400).json({ error: 'cannot delete the demo map' });
  try { fs.unlinkSync(mapPath(key)); } catch { /* ignore */ }
  io.emit('maps_changed', { key, at: Date.now() });   // gateway stops running it
  res.json({ ok: true });
});

app.get('/api/site', (_req, res) => {
  const m = readMap('demo');
  if (!m) return res.status(500).json({ error: 'no demo map' });
  res.json(m);
});

// -----------------------------------------------------------------------------
// HARDWARE / EDGE TELEMETRY & PERSISTENCE REST API
// -----------------------------------------------------------------------------

// Server health check
app.get('/health', async (_req, res) => {
  const total = await database.getRecordCount().catch(() => 0);
  res.json({
    status: 'ok',
    device: 'Raspberry Pi 4 RTLS Server',
    total_database_records: total,
    active_tags: Object.keys(globalTagCache).length,
    timestamp: new Date().toISOString(),
  });
});

// View all raw database records
app.get('/api/database', async (req, res) => {
  const limit = parseInt(req.query.limit, 10) || 100;
  try {
    const rows = await database.getAllLocations(limit);
    res.json(rows);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// Latest position for each tag
app.get('/api/tags', async (_req, res) => {
  try {
    const dbTags = await database.getLatestTags();
    const merged = { ...globalTagCache };
    dbTags.forEach((t) => {
      if (!merged[t.tag]) {
        merged[t.tag] = {
          tag: t.tag,
          tagId: t.tag,
          name: t.name,
          x: t.x,
          y: t.y,
          z: t.z,
          time: t.time,
        };
      }
    });
    res.json(merged);
  } catch (err) {
    res.json(globalTagCache);
  }
});

// Coordinate history for a tag
app.get('/api/history/:tagId', async (req, res) => {
  const { tagId } = req.params;
  const limit = parseInt(req.query.limit, 10) || 50;
  try {
    const history = await database.getTagLocations(tagId, limit);
    res.json({ tag: tagId, count: history.length, coordinates: history });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// Database record count & analytics
app.get('/api/analytics', async (_req, res) => {
  try {
    const total = await database.getRecordCount();
    res.json({
      total_history_records: total,
      active_tags: Object.keys(globalTagCache).length,
      db_status: 'HEALTHY',
      server_uptime_seconds: Math.floor(process.uptime()),
    });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// Ingest tag data from external nodes / ESP32
app.post(['/api/telemetry', '/api/tag-update'], async (req, res) => {
  const payload = req.body;
  if (!payload || (!payload.tag && !payload.tagId && !payload.tag_id)) {
    return res.status(400).json({ error: 'Missing tag in JSON payload' });
  }
  const enriched = await processIncomingTelemetry(payload);
  res.json({ status: 'saved', record: { tag: enriched.tag, name: enriched.name, x: enriched.x, y: enriched.y, z: enriched.z, time: enriched.time } });
});

// -----------------------------------------------------------------------------
// WEBSOCKET & CENTRAL TELEMETRY DISPATCHER
// -----------------------------------------------------------------------------

const server = http.createServer(app);
const io = new Server(server, { cors: { origin: '*', methods: ['GET', 'POST'] } });

const state = {};   // mapKey -> { positions: {tagId:...}, readings: {tagId:...}, alerts: [...] }
const forMap = (k) => (state[k] ||= { positions: {}, readings: {}, alerts: [] });
const ALERTS_KEPT = 50;
const globalTagCache = {};

/**
 * Ingestion and enrichment pipeline:
 * Enriches coordinates, saves to SQLite database, and broadcasts to clients
 */
async function processIncomingTelemetry(rawPayload) {
  const tag = rawPayload.tag || rawPayload.tagId || rawPayload.tag_id;
  if (!tag) return null;

  // Enrich with coordinate analytics, geofence zone, and alerts
  const enriched = analytics.analyzeTelemetry(rawPayload);
  enriched.tag = tag;
  enriched.tagId = tag;
  const mapKey = rawPayload.mapKey || 'demo';

  // Normalize `pos` property if missing
  if (!enriched.pos) {
    enriched.pos = { x: enriched.x, y: enriched.y, z: enriched.z };
  }

  // Update memory caches
  globalTagCache[tag] = enriched;
  forMap(mapKey).positions[tag] = enriched;

  // Save to SQLite
  try {
    const saved = await database.saveLocation(enriched);
    enriched.time = saved ? saved.time : new Date().toISOString();
  } catch (err) {
    console.error('Database save error:', err.message);
  }

  // Broadcast to room and root namespace
  io.to(`map:${mapKey}`).emit('location_update', enriched);
  io.emit('location_update', enriched);

  // If there are alerts, emit them
  if (enriched.alerts && enriched.alerts.length > 0) {
    enriched.alerts.forEach((alertMsg) => {
      const alertObj = { tagId: tag, message: alertMsg, time: enriched.time, mapKey };
      const s = forMap(mapKey);
      s.alerts.push(alertObj);
      if (s.alerts.length > ALERTS_KEPT) s.alerts.shift();
      io.to(`map:${mapKey}`).emit('alert', alertObj);
      io.emit('alert', alertObj);
    });
  }

  return enriched;
}

io.on('connection', (socket) => {
  socket.on('join_map', (key) => {
    if (!key) return;
    socket.join(`map:${key}`);
    socket.data.mapKey = key;
    const s = forMap(key);
    socket.emit('initial_state', { positions: s.positions, readings: s.readings, alerts: s.alerts });
  });

  // Client requesting initial state for all tags
  socket.emit('initial_state', globalTagCache);

  socket.on('update_location', async (data) => {
    if (!data || (!data.tagId && !data.tag)) return;
    await processIncomingTelemetry(data);
  });

  socket.on('alert', (data) => {
    if (!data || !data.tagId) return;
    const key = data.mapKey || 'demo';
    const s = forMap(key);
    s.alerts.push(data);
    if (s.alerts.length > ALERTS_KEPT) s.alerts.splice(0, s.alerts.length - ALERTS_KEPT);
    io.to(`map:${key}`).emit('alert', data);
    io.emit('alert', data);
  });

  socket.on('reading', (data) => {
    if (!data || !data.tagId) return;
    const key = data.mapKey || 'demo';
    forMap(key).readings[data.tagId] = data;
    io.to(`map:${key}`).emit('reading_update', data);
  });
});

// -----------------------------------------------------------------------------
// UDP INGESTION LISTENER (Port 5005)
// -----------------------------------------------------------------------------

const UDP_PORT = process.env.UDP_PORT || 5005;
const udpServer = dgram.createSocket('udp4');

udpServer.on('message', async (msg) => {
  try {
    const rawStr = msg.toString('utf-8').trim();
    if (rawStr.startsWith('{') && rawStr.endsWith('}')) {
      const parsed = JSON.parse(rawStr);
      await processIncomingTelemetry(parsed);
    }
  } catch (e) {
    // Ignore invalid datagrams
  }
});

udpServer.bind(UDP_PORT, () => {
  console.log(`⚡ UDP Telemetry Server listening on port ${UDP_PORT}`);
});

// -----------------------------------------------------------------------------
// BOOTSTRAP & NETWORK DISCOVERY
// -----------------------------------------------------------------------------

function getLocalIpAddresses() {
  const interfaces = os.networkInterfaces();
  const addresses = [];
  for (const name of Object.keys(interfaces)) {
    for (const iface of interfaces[name]) {
      if (iface.family === 'IPv4' && !iface.internal) {
        addresses.push(iface.address);
      }
    }
  }
  return addresses;
}

const PORT = process.env.PORT || 3000;
server.listen(PORT, '0.0.0.0', () => {
  const ips = getLocalIpAddresses();
  console.log(`====================================================`);
  console.log(`🚀 Unified UWB RTLS & Digital Twin Server Running!`);
  console.log(`   - Port:       ${PORT}`);
  console.log(`   - Local:      http://localhost:${PORT}`);
  ips.forEach((ip) => {
    console.log(`   - LAN:        http://${ip}:${PORT}`);
  });
  console.log(`   - Maps API:   http://localhost:${PORT}/api/maps`);
  console.log(`   - SQLite DB:  tag_locations (tag, name, x, y, z, time)`);
  console.log(`   - UDP Stream: 0.0.0.0:${UDP_PORT}`);
  console.log(`====================================================`);
});
