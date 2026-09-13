const sqlite3 = require('sqlite3').verbose();
const path = require('path');

const DB_PATH = process.env.DB_PATH || path.join(__dirname, '..', 'backend', 'rtls_warehouse.db');
const db = new sqlite3.Database(DB_PATH, (err) => {
  if (err) {
    console.error('❌ Error connecting to SQLite database:', err.message);
  } else {
    console.log(`📁 Connected to SQLite database: ${DB_PATH}`);
  }
});

// Enable WAL mode for high performance
db.run('PRAGMA journal_mode = WAL;');

// Initialize clean, simple table: tag, name, coordinates (x, y, z), and time
db.serialize(() => {
  db.run(`
    CREATE TABLE IF NOT EXISTS tag_locations (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      tag TEXT NOT NULL,
      name TEXT,
      x REAL NOT NULL,
      y REAL DEFAULT 0.5,
      z REAL NOT NULL,
      time DATETIME DEFAULT CURRENT_TIMESTAMP
    )
  `);

  db.run(`
    CREATE INDEX IF NOT EXISTS idx_tag_time 
    ON tag_locations(tag, time DESC)
  `);
});

// Avoid duplicate rows within 400ms per tag to keep the database tidy
const lastSaved = {};

/**
 * Save tag location coordinates to database: (tag, name, x, y, z, time)
 */
function saveLocation(tagData) {
  return new Promise((resolve, reject) => {
    const tag = tagData.tag || tagData.tagId || tagData.tag_id;
    if (!tag) return resolve(null);

    const name = tagData.name || tag;
    const x = Number((tagData.x !== undefined ? tagData.x : 0.0).toFixed(2));
    const y = Number((tagData.y !== undefined ? tagData.y : (tagData.elev || 0.5)).toFixed(2));
    const z = Number((tagData.z !== undefined ? tagData.z : 0.0).toFixed(2));
    const now = new Date().toISOString();

    const nowMs = Date.now();
    if (lastSaved[tag] && nowMs - lastSaved[tag] < 400) {
      return resolve({ tag, name, x, y, z, time: now });
    }
    lastSaved[tag] = nowMs;

    const sql = `
      INSERT INTO tag_locations (tag, name, x, y, z, time)
      VALUES (?, ?, ?, ?, ?, ?)
    `;

    db.run(sql, [tag, name, x, y, z, now], function (err) {
      if (err) return reject(err);
      resolve({ id: this.lastID, tag, name, x, y, z, time: now });
    });
  });
}

/**
 * Get latest coordinate position for each tag
 */
function getLatestTags() {
  return new Promise((resolve, reject) => {
    const sql = `
      SELECT t.tag, t.name, t.x, t.y, t.z, t.time
      FROM tag_locations t
      INNER JOIN (
        SELECT tag, MAX(id) as max_id
        FROM tag_locations
        GROUP BY tag
      ) latest ON t.id = latest.max_id
      ORDER BY t.time DESC
    `;
    db.all(sql, [], (err, rows) => {
      if (err) return reject(err);
      resolve(rows);
    });
  });
}

/**
 * Get recent location history for a specific tag
 */
function getTagLocations(tag, limit = 50) {
  return new Promise((resolve, reject) => {
    const sql = `
      SELECT tag, name, x, y, z, time
      FROM tag_locations
      WHERE tag = ?
      ORDER BY time DESC
      LIMIT ?
    `;
    db.all(sql, [tag, limit], (err, rows) => {
      if (err) return reject(err);
      resolve(rows.reverse()); // Chronological order
    });
  });
}

/**
 * Get recent raw database entries (for website tables / exports)
 */
function getAllLocations(limit = 100) {
  return new Promise((resolve, reject) => {
    const sql = `
      SELECT id, tag, name, x, y, z, time
      FROM tag_locations
      ORDER BY id DESC
      LIMIT ?
    `;
    db.all(sql, [limit], (err, rows) => {
      if (err) return reject(err);
      resolve(rows);
    });
  });
}

/**
 * Total row count
 */
function getRecordCount() {
  return new Promise((resolve, reject) => {
    db.get('SELECT COUNT(*) as total FROM tag_locations', (err, row) => {
      if (err) return reject(err);
      resolve(row ? row.total : 0);
    });
  });
}

module.exports = {
  db,
  saveLocation,
  getLatestTags,
  getTagLocations,
  getAllLocations,
  getRecordCount,
};
