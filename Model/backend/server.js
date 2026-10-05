// WebSocket + REST hub for the UWB RTLS mapping platform.
//
// Maps are standalone documents, each addressed by an unguessable key, stored one
// JSON per map under backend/maps/. A map IS a site config (schema uwb.site/1)
// plus a key and a display name — so the simulator, solver and 3D twin all keep
// reading the same shape they already understand.
//
// Live tracking is per-map: producers (the gateway) tag every message with a
// mapKey, and the hub fans it out only to the Socket.IO room for that map. A
// viewer opening ?map=KEY joins that room and sees the map's live tracking — the
// map is fully independent of the codebase, shareable by key.
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const express = require('express');
const http = require('http');
const { Server } = require('socket.io');
const cors = require('cors');

const app = express();
app.use(cors());
app.use(express.json({ limit: '4mb' }));

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
    };
  }).filter((m) => m.key);
}

// Validate the essential shape shared with the Python side.
function validMap(m) {
  return m && m.schema === 'uwb.site/1' && Array.isArray(m.anchors) &&
    Array.isArray(m.tags) && Array.isArray(m.walls) && Array.isArray(m.zones) && m.floor;
}

// Seed a demo map from config/site.json on first run.
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

// A blank map for "create new".
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

// --- REST: maps ---------------------------------------------------------------
app.get('/api/maps', (_req, res) => res.json(listMaps()));

app.post('/api/maps', (req, res) => {
  const key = genKey();
  const m = blankMap(req.body && req.body.name);
  m.key = key;
  writeMap(key, m);
  console.log(`Created map ${key} ("${m.meta.name}")`);
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
  m.key = key;
  m.meta = { ...(m.meta || {}), updatedAt: Date.now() };
  writeMap(key, m);
  io.to(`map:${key}`).emit('map_updated', { key, at: Date.now() });
  console.log(`Map ${key} saved`);
  res.json({ ok: true });
});

app.delete('/api/maps/:key', (req, res) => {
  const key = req.params.key;
  if (key === 'demo') return res.status(400).json({ error: 'cannot delete the demo map' });
  try { fs.unlinkSync(mapPath(key)); } catch { /* ignore */ }
  res.json({ ok: true });
});

// Back-compat alias: the "site" is just the demo map.
app.get('/api/site', (_req, res) => {
  const m = readMap('demo');
  if (!m) return res.status(500).json({ error: 'no demo map' });
  res.json(m);
});

const server = http.createServer(app);
const io = new Server(server, { cors: { origin: '*', methods: ['GET', 'POST'] } });

// Per-map latest state, so a fresh viewer gets an immediate snapshot.
const state = {};   // mapKey -> { positions: {tagId:...}, readings: {tagId:...} }
const forMap = (k) => (state[k] ||= { positions: {}, readings: {} });

io.on('connection', (socket) => {
  socket.on('join_map', (key) => {
    if (!key) return;
    socket.join(`map:${key}`);
    socket.data.mapKey = key;
    const s = forMap(key);
    socket.emit('initial_state', { positions: s.positions, readings: s.readings });
  });

  // Producer messages carry mapKey; fan out only to that map's room.
  socket.on('update_location', (data) => {
    if (!data || !data.tagId) return;
    const key = data.mapKey || 'demo';
    forMap(key).positions[data.tagId] = data;
    io.to(`map:${key}`).emit('location_update', data);
  });

  socket.on('reading', (data) => {
    if (!data || !data.tagId) return;
    const key = data.mapKey || 'demo';
    forMap(key).readings[data.tagId] = data;
    io.to(`map:${key}`).emit('reading_update', data);
  });
});

const PORT = process.env.PORT || 3000;
server.listen(PORT, () => {
  console.log(`RTLS hub running on port ${PORT}`);
  console.log(`Maps API at http://localhost:${PORT}/api/maps`);
});
