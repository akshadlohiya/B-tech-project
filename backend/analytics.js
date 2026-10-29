/**
 * Real-Time RTLS Analytics & Trilateration Engine
 * Calculates coordinates, detects warehouse zones, and monitors anomalies.
 */

const BASE_LAT = 43.8615;
const BASE_LON = -78.9469;

// Fixed Anchor positions in local 3D warehouse coordinate frame (meters)
const ANCHORS = {
  R1: { x: -12.4, y: 0.5, z: 15.0, lat: 43.861635, lon: -78.947087, elev: 0.0 },
  R2: { x: 17.6, y: 0.5, z: 15.0, lat: 43.861635, lon: -78.946712, elev: 0.0 },
  R3: { x: -12.4, y: 3.7, z: -15.0, lat: 43.861365, lon: -78.947087, elev: 4.0 },
  R4: { x: 17.6, y: 3.7, z: -15.0, lat: 43.861365, lon: -78.946712, elev: 4.0 },
};

/**
 * Convert GPS lat/lon/elev to local warehouse coordinate system (x, y, z)
 */
function gpsToLocal(lat, lon, elev) {
  const x = (lon - BASE_LON) * 80000;
  const z = -(lat - BASE_LAT) * 111111;
  const y = (elev || 0) * 0.8 + 0.5;
  return { x: Number(x.toFixed(2)), y: Number(y.toFixed(2)), z: Number(z.toFixed(2)) };
}

/**
 * Convert local warehouse coordinate system (x, y, z) to GPS lat/lon/elev
 */
function localToGps(x, y, z) {
  const lon = BASE_LON + x / 80000;
  const lat = BASE_LAT - z / 111111;
  const elev = Math.max(0, (y - 0.5) / 0.8);
  return { lat, lon, elev };
}

/**
 * 3D Multilateration / Trilateration from anchor distances
 * Solves for (x, y, z) given distance measurements to R1, R2, R3, R4
 */
function solveTrilateration(distances) {
  const r1 = distances.R1;
  const r2 = distances.R2;
  const r3 = distances.R3;

  if (r1 === undefined || r2 === undefined || r3 === undefined) {
    return null;
  }

  const p1 = ANCHORS.R1;
  const p2 = ANCHORS.R2;
  const p3 = ANCHORS.R3;

  // Linearized trilateration using Anchor 1 as reference
  // 2*(x2 - x1)*x + 2*(z2 - z1)*z = r1^2 - r2^2 - (x1^2 - x2^2) - (z1^2 - z2^2)
  const A = 2 * (p2.x - p1.x);
  const B = 2 * (p2.z - p1.z);
  const C = Math.pow(r1, 2) - Math.pow(r2, 2) - Math.pow(p1.x, 2) + Math.pow(p2.x, 2) - Math.pow(p1.z, 2) + Math.pow(p2.z, 2);

  const D = 2 * (p3.x - p1.x);
  const E = 2 * (p3.z - p1.z);
  const F = Math.pow(r1, 2) - Math.pow(r3, 2) - Math.pow(p1.x, 2) + Math.pow(p3.x, 2) - Math.pow(p1.z, 2) + Math.pow(p3.z, 2);

  const denom = A * E - B * D;
  if (Math.abs(denom) < 0.0001) {
    return null;
  }

  let x = (C * E - F * B) / denom;
  let z = (C * D - A * F) / -denom;

  // Clamp within warehouse dimensions (-14m to 14m)
  x = Math.max(-13.8, Math.min(13.8, x));
  z = Math.max(-13.8, Math.min(13.8, z));
  const y = 0.5;

  return { x: Number(x.toFixed(2)), y, z: Number(z.toFixed(2)) };
}

/**
 * Determine warehouse zone / geofence
 */
function detectZone(x, y, z) {
  if (y > 2.0 && z < 0) {
    return 'Mezzanine Level 2';
  }
  if (x > 10 && x < 14 && z > 0 && z < 8) {
    return 'Access Ramp';
  }
  if (x > -8.5 && x < -1.5 && z > -10.5 && z < 10.5) {
    return 'Storage Racks West (Aisle A)';
  }
  if (x > 1.5 && x < 8.5 && z > -10.5 && z < 10.5) {
    return 'Storage Racks East (Aisle B)';
  }
  if (x >= -1.5 && x <= 1.5 && z >= -12 && z <= 12) {
    return 'Central Transit Lane';
  }
  if (z > 10) {
    return 'South Loading Dock';
  }
  if (z < -10) {
    return 'North Staging Area';
  }
  return 'General Floor';
}

/**
 * Process and enrich raw incoming telemetry from any node or UWB tag
 */
function analyzeTelemetry(rawPayload) {
  const enriched = { ...rawPayload };

  // 1. Resolve (x, y, z) coordinates
  let localPos = null;
  if (enriched.x !== undefined && enriched.z !== undefined) {
    localPos = {
      x: Number(enriched.x),
      y: enriched.y !== undefined ? Number(enriched.y) : (enriched.elev || 0.5),
      z: Number(enriched.z),
    };
  } else if (enriched.lat !== undefined && enriched.lon !== undefined) {
    localPos = gpsToLocal(enriched.lat, enriched.lon, enriched.elev);
  } else if (enriched.distances) {
    localPos = solveTrilateration(enriched.distances);
  }

  if (!localPos) {
    localPos = { x: 0, y: 0.5, z: 0 };
  }

  enriched.x = localPos.x;
  enriched.y = localPos.y;
  enriched.z = localPos.z;

  // 2. Ensure lat/lon/elev are populated for map rendering
  if (enriched.lat === undefined || enriched.lon === undefined) {
    const gps = localToGps(enriched.x, enriched.y, enriched.z);
    enriched.lat = gps.lat;
    enriched.lon = gps.lon;
    enriched.elev = gps.elev;
  }

  // 3. Compute distance to anchors if missing
  if (!enriched.distances) {
    enriched.distances = {};
    for (const [key, anchor] of Object.entries(ANCHORS)) {
      const dist = Math.sqrt(
        Math.pow(enriched.x - anchor.x, 2) +
        Math.pow(enriched.y - anchor.y, 2) +
        Math.pow(enriched.z - anchor.z, 2)
      );
      enriched.distances[key] = Number(dist.toFixed(2));
    }
  }

  // 4. Geofencing zone detection
  enriched.zone = detectZone(enriched.x, enriched.y, enriched.z);

  // 5. Battery and anomaly alerts
  const alerts = [];
  if (enriched.battery !== undefined && enriched.battery < 20) {
    alerts.push({ type: 'LOW_BATTERY', message: `Battery critically low: ${enriched.battery}%` });
  }
  if (Math.abs(enriched.x) > 14 || Math.abs(enriched.z) > 14) {
    alerts.push({ type: 'PERIMETER_BREACH', message: `Tag near warehouse boundary: (${enriched.x}, ${enriched.z})` });
  }

  enriched.alerts = alerts;
  return enriched;
}

module.exports = {
  ANCHORS,
  gpsToLocal,
  localToGps,
  solveTrilateration,
  detectZone,
  analyzeTelemetry,
};
