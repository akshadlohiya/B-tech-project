-- =============================================================================
-- SQLite Schema for RTLS Warehouse Tracking
-- Stores: tag, name, coordinates (x, y, z), and time
-- =============================================================================

CREATE TABLE IF NOT EXISTS tag_locations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tag TEXT NOT NULL,
  name TEXT,
  x REAL NOT NULL,
  y REAL DEFAULT 0.5,
  z REAL NOT NULL,
  time DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_tag_time 
ON tag_locations(tag, time DESC);
