# 🗄️ RTLS SQLite Database Engine

This directory contains the database schema and access layer for the Real-Time Location System (RTLS).

---

## 📋 Schema Overview

The database uses a clean, focused schema storing only the essential tag positioning data:

```sql
CREATE TABLE tag_locations (
  id    INTEGER PRIMARY KEY AUTOINCREMENT,
  tag   TEXT NOT NULL,
  name  TEXT,
  x     REAL NOT NULL,
  y     REAL DEFAULT 0.5,
  z     REAL NOT NULL,
  time  DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### Columns:
- `id`: Auto-incrementing primary key
- `tag`: Unique tag ID (e.g. `Tag_A`, `Tag_Pi`, `ESP32_01`)
- `name`: Human-readable label (e.g. `Warehouse Forklift`, `Raspberry Pi 4`)
- `x`, `y`, `z`: 3D Cartesian coordinates in meters
- `time`: Timestamp when coordinate was recorded

---

## 🌐 Access via HTTP REST API

When the server runs on the Raspberry Pi (`http://192.168.1.40:3000`):

- **View all raw records**: `GET http://192.168.1.40:3000/api/database`
- **View latest tag coordinates**: `GET http://192.168.1.40:3000/api/tags`
- **View history for a specific tag**: `GET http://192.168.1.40:3000/api/history/:tagId`
- **Insert tag location**: `POST http://192.168.1.40:3000/api/telemetry`
