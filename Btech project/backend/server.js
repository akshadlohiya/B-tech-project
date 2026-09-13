const express = require('express');
const http = require('http');
const { Server } = require('socket.io');
const cors = require('cors');
const os = require('os');
const dgram = require('dgram');

const database = require('./database');
const analytics = require('./analytics');

const app = express();
app.use(cors());
app.use(express.json());

const server = http.createServer(app);
const io = new Server(server, {
  cors: {
    origin: '*',
    methods: ['GET', 'POST'],
  },
});

let tagPositions = {};

/**
 * Central Ingestion Pipeline:
 * Analyzes coordinates and saves (tag, name, x, y, z, time) to SQLite database
 */
async function processIncomingTelemetry(rawPayload) {
  const tag = rawPayload.tag || rawPayload.tagId || rawPayload.tag_id;
  if (!tag) return null;

  // 1. Analyze / resolve coordinates (x, y, z)
  const enriched = analytics.analyzeTelemetry(rawPayload);
  enriched.tag = tag;
  enriched.tagId = tag;

  // 2. Update memory cache
  tagPositions[tag] = enriched;

  // 3. Save clean record to SQLite: (tag, name, x, y, z, time)
  try {
    const saved = await database.saveLocation(enriched);
    enriched.time = saved ? saved.time : new Date().toISOString();
  } catch (err) {
    console.error('Database save error:', err.message);
  }

  // 4. Broadcast live to website
  io.emit('location_update', enriched);
  return enriched;
}

// -----------------------------------------------------------------------------
// HTTP REST API ENDPOINTS
// -----------------------------------------------------------------------------

// Server health check
app.get('/health', async (req, res) => {
  const total = await database.getRecordCount().catch(() => 0);
  res.json({
    status: 'ok',
    device: 'Raspberry Pi 4 RTLS Server',
    total_database_records: total,
    active_tags: Object.keys(tagPositions).length,
    timestamp: new Date().toISOString(),
  });
});

// View all raw database records: [{ id, tag, name, x, y, z, time }]
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
app.get('/api/tags', async (req, res) => {
  try {
    const dbTags = await database.getLatestTags();
    const merged = { ...tagPositions };
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
    res.json(tagPositions);
  }
});

// Coordinate history for a tag: [{ tag, name, x, y, z, time }]
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
app.get('/api/analytics', async (req, res) => {
  try {
    const total = await database.getRecordCount();
    res.json({
      total_history_records: total,
      active_tags: Object.keys(tagPositions).length,
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
// WEBSOCKET (SOCKET.IO) HANDLERS
// -----------------------------------------------------------------------------

io.on('connection', (socket) => {
  console.log(`🔌 Web Client Connected: ${socket.id}`);
  socket.emit('initial_state', tagPositions);

  socket.on('update_location', async (data) => {
    await processIncomingTelemetry(data);
  });

  socket.on('disconnect', () => {
    console.log(`❌ Client Disconnected: ${socket.id}`);
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
    // Ignore invalid packets
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
const HOST = '0.0.0.0';

server.listen(PORT, HOST, () => {
  const ips = getLocalIpAddresses();
  console.log(`====================================================`);
  console.log(`🚀 RTLS Warehouse Server running!`);
  console.log(`   - Local:    http://localhost:${PORT}`);
  ips.forEach((ip) => {
    console.log(`   - Network:  http://${ip}:${PORT}`);
  });
  console.log(`   - Database: SQLite (tag_locations: tag, name, x, y, z, time)`);
  console.log(`====================================================`);
});