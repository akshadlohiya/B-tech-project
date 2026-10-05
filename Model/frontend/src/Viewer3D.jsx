import React, { useCallback, useEffect, useState } from 'react';
import { io } from 'socket.io-client';
import { Canvas } from '@react-three/fiber';
import { SOCKET_URL, getMap, goTo, shareLink } from './api';
import { detectWebGL, CanvasErrorBoundary, Scene, DetailsPanel, overlayStyle, zoneLabel } from './three3d';

// Read-only live view of a map, addressed by key. Anyone with the key + server
// can watch live tracking here.
export default function Viewer3D({ mapKey }) {
  const [map, setMap] = useState(null);
  const [err, setErr] = useState(null);
  const [isConnected, setIsConnected] = useState(false);
  const [positions, setPositions] = useState({});
  const [readings, setReadings] = useState({});
  const [showRangeLines, setShowRangeLines] = useState(true);
  const [showRaw, setShowRaw] = useState(false);
  const [showTrails, setShowTrails] = useState(true);
  const [showTruePath, setShowTruePath] = useState(false);
  const [showAccuracy, setShowAccuracy] = useState(true);
  const [trails, setTrails] = useState({});
  const [truthTrails, setTruthTrails] = useState({});
  const [errHist, setErrHist] = useState({});
  const [selected, setSelected] = useState(null);
  const [webgl] = useState(detectWebGL);
  const [copied, setCopied] = useState(false);

  const loadMap = useCallback(() => getMap(mapKey).then(setMap).catch((e) => setErr(e.message)), [mapKey]);
  useEffect(() => { loadMap(); }, [loadMap]);

  useEffect(() => {
    const socket = io(SOCKET_URL);
    socket.on('connect', () => { setIsConnected(true); socket.emit('join_map', mapKey); });
    socket.on('disconnect', () => setIsConnected(false));
    socket.on('initial_state', (s) => { setPositions(s.positions || {}); setReadings(s.readings || {}); });
    socket.on('location_update', (d) => {
      if (!d || !d.tagId || !d.pos) return;   // ignore malformed/partial updates
      setPositions((p) => ({ ...p, [d.tagId]: d }));
      setTrails((tr) => appendPt(tr, d.tagId, [d.pos.x, d.pos.y, d.pos.z]));
      if (d.truth) setTruthTrails((tr) => appendPt(tr, d.tagId, [d.truth.x, d.pos.y, d.truth.z]));
      if (d.error != null) setErrHist((eh) => appendPt(eh, d.tagId, { err: d.error, raw: d.rawError ?? d.error }));
    });
    socket.on('reading_update', (d) => setReadings((p) => ({ ...p, [d.tagId]: d })));
    socket.on('map_updated', () => loadMap());
    return () => socket.disconnect();
  }, [mapKey, loadMap]);

  const tags = Object.values(positions).filter((p) => (map?.tags || []).some((t) => t.id === p.tagId));
  const copyShare = () => { navigator.clipboard?.writeText(shareLink(mapKey)); setCopied(true); setTimeout(() => setCopied(false), 1500); };

  return (
    <>
      <div className="hud-overlay" style={{ zIndex: 10 }}>
        <div className="hud-header">
          <h1>{map ? map.meta.name : 'Loading…'}</h1>
          <div className={`status-badge ${isConnected ? 'connected' : 'disconnected'}`}><div className="status-dot"></div>{isConnected ? 'LIVE' : 'OFFLINE'}</div>
        </div>
        <div className="info-row"><span className="info-label">Map key</span><span className="info-value" style={{ fontFamily: 'monospace' }}>{mapKey}</span></div>
        <div className="info-row"><span className="info-label">Active Tags</span><span className="info-value">{tags.length}</span></div>
        <div className="info-row"><span className="info-label">Anchors</span><span className="info-value">{map ? map.anchors.length : '–'}</span></div>
        <label className="info-row" style={{ marginTop: 8, cursor: 'pointer' }}><span className="info-label">Range lines (LOS/NLOS)</span><input type="checkbox" checked={showRangeLines} onChange={(e) => setShowRangeLines(e.target.checked)} /></label>
        <label className="info-row" style={{ cursor: 'pointer' }}><span className="info-label">Raw fix + uncertainty (Kalman off)</span><input type="checkbox" checked={showRaw} onChange={(e) => setShowRaw(e.target.checked)} /></label>
        <label className="info-row" style={{ cursor: 'pointer' }}><span className="info-label">Motion trails</span><input type="checkbox" checked={showTrails} onChange={(e) => setShowTrails(e.target.checked)} /></label>
        <label className="info-row" style={{ cursor: 'pointer' }}><span className="info-label">True path overlay (sim)</span><input type="checkbox" checked={showTruePath} onChange={(e) => setShowTruePath(e.target.checked)} /></label>
        <label className="info-row" style={{ cursor: 'pointer' }}><span className="info-label">Accuracy panel</span><input type="checkbox" checked={showAccuracy} onChange={(e) => setShowAccuracy(e.target.checked)} /></label>
        <div style={{ display: 'flex', gap: 8, marginTop: 12, flexWrap: 'wrap' }}>
          <button style={btn} onClick={() => goTo({})}>← Maps</button>
          <button style={btn} onClick={() => goTo({ map: mapKey, mode: 'edit' })}>✎ Edit</button>
          <button style={btn} onClick={copyShare}>{copied ? '✓ Copied' : '🔗 Share'}</button>
        </div>
        <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: 12 }}>
          <span style={{ color: '#22c55e' }}>■</span> LOS&nbsp;<span style={{ color: '#ef4444' }}>■</span> NLOS&nbsp;<span style={{ color: '#64748b' }}>■</span> dropped<br />Click any anchor or tag for details.
        </p>
      </div>

      <DetailsPanel map={map} selected={selected} positions={positions} readings={readings} onClose={() => setSelected(null)} />

      <div className="telemetry-panel" style={{ zIndex: 10 }}>
        <h3>Live Ranging</h3>
        {tags.length === 0 && <div className="telemetry-tag-dist">Waiting for tags… (start the gateway for this map)</div>}
        {tags.map((t) => (
          <div key={t.tagId} className="telemetry-tag-card" style={{ cursor: 'pointer', border: selected?.id === t.tagId ? '1px solid #38bdf8' : undefined }} onClick={() => setSelected({ type: 'tag', id: t.tagId })}>
            <div className="telemetry-tag-header"><span>{t.name}</span><span style={{ fontSize: '0.8rem', color: t.battery < 20 ? '#ef4444' : '#10b981' }}>⚡ {t.battery ?? '–'}%</span></div>
            <div className="telemetry-tag-dist"><span>Zone</span><span>{zoneLabel(map || { zones: [] }, t.zone) || '—'}</span></div>
            <div className="telemetry-tag-dist"><span>Speed</span><span>{t.vel ? `${t.vel.speed} m/s` : '—'}</span></div>
            <div className="telemetry-tag-dist"><span>Error (Kalman / raw)</span><span>{t.error != null ? `${(t.error * 100).toFixed(0)} / ${((t.rawError ?? t.error) * 100).toFixed(0)} cm` : '—'}</span></div>
          </div>
        ))}
      </div>

      {showAccuracy && <AccuracyHUD errHist={errHist} map={map} />}

      {!webgl.ok && <div style={overlayStyle}><div style={{ fontSize: 20, fontWeight: 700 }}>⚠️ WebGL is not available</div><div style={{ maxWidth: 560, color: '#94a3b8' }}>Enable graphics acceleration in the browser, or use Firefox. ({webgl.reason})</div></div>}
      {err && <div style={overlayStyle}><div style={{ fontSize: 20, fontWeight: 700 }}>⚠️ {err}</div><button style={btn} onClick={() => goTo({})}>← Back to maps</button></div>}

      <div className="map-container" style={{ position: 'absolute', top: 0, left: 0, width: '100%', height: '100%' }}>
        <CanvasErrorBoundary>
          <Canvas shadows camera={{ position: [18, 16, 22], fov: 50 }} gl={{ antialias: true, powerPreference: 'default', failIfMajorPerformanceCaveat: false }}>
            {map && <Scene map={map} positions={positions} readings={readings} showRangeLines={showRangeLines} showRaw={showRaw} trails={trails} truthTrails={truthTrails} showTrails={showTrails} showTruePath={showTruePath} selected={selected} onSelect={setSelected} />}
          </Canvas>
        </CanvasErrorBoundary>
      </div>
    </>
  );
}

const btn = { background: '#1e293b', color: '#e2e8f0', border: '1px solid #334155', borderRadius: 6, padding: '6px 10px', cursor: 'pointer', fontSize: 13 };
const TRAIL_MAX = 150;   // ~30 s of history at 5 Hz

// Append to a per-tag history buffer (points, or {err,raw} samples), capped.
function appendPt(store, id, pt) {
  const arr = (store[id] || []).concat([pt]);
  if (arr.length > TRAIL_MAX) arr.splice(0, arr.length - TRAIL_MAX);
  return { ...store, [id]: arr };
}

const stats = (xs) => {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b);
  const mean = s.reduce((a, b) => a + b, 0) / s.length;
  return { mean, median: s[Math.floor(s.length * 0.5)], p90: s[Math.floor(s.length * 0.9)] };
};

function Sparkline({ vals, color }) {
  if (vals.length < 2) return null;
  const w = 120, h = 26, max = Math.max(0.5, ...vals);
  const pts = vals.map((v, i) => `${(i / (vals.length - 1)) * w},${h - (v / max) * h}`).join(' ');
  return <svg width={w} height={h} style={{ display: 'block' }}><polyline points={pts} fill="none" stroke={color} strokeWidth="1.5" /></svg>;
}

// Live accuracy analytics: per-tag raw-vs-Kalman error and a system-wide summary.
function AccuracyHUD({ errHist, map }) {
  const tagIds = Object.keys(errHist);
  const allFilt = [], allRaw = [];
  tagIds.forEach((id) => (errHist[id] || []).forEach((e) => { allFilt.push(e.err); allRaw.push(e.raw); }));
  const F = stats(allFilt), R = stats(allRaw);
  if (!F) return null;
  const nameOf = (id) => (map?.tags.find((t) => t.id === id) || {}).name || id;
  const pct = R ? Math.round(100 * (R.mean - F.mean) / R.mean) : 0;
  return (
    <div className="accuracy-panel">
      <div className="details-head" style={{ marginBottom: 8 }}><span>📊 Accuracy (live)</span></div>
      <div className="telemetry-tag-dist"><span style={{ color: '#94a3b8' }}>Kalman vs raw (mean)</span><span style={{ color: '#4ade80', fontWeight: 700 }}>{(F.mean * 100).toFixed(0)} / {(R.mean * 100).toFixed(0)} cm</span></div>
      <div className="telemetry-tag-dist"><span style={{ color: '#94a3b8' }}>Kalman median · p90</span><span style={{ color: 'white' }}>{(F.median * 100).toFixed(0)} · {(F.p90 * 100).toFixed(0)} cm</span></div>
      <div className="telemetry-tag-dist"><span style={{ color: '#94a3b8' }}>Improvement</span><span style={{ color: pct >= 0 ? '#4ade80' : '#fca5a5' }}>{pct >= 0 ? '+' : ''}{pct}%</span></div>
      <div style={{ borderTop: '1px solid var(--glass-border)', margin: '8px 0' }} />
      {tagIds.map((id) => {
        const h = errHist[id] || [];
        const f = stats(h.map((e) => e.err));
        if (!f) return null;
        return (
          <div key={id} style={{ marginBottom: 6 }}>
            <div className="telemetry-tag-dist"><span>{nameOf(id)}</span><span style={{ color: '#4ade80' }}>{(f.mean * 100).toFixed(0)} cm</span></div>
            <Sparkline vals={h.slice(-60).map((e) => e.err)} color="#4ade80" />
          </div>
        );
      })}
      <div style={{ fontSize: 11, color: '#64748b', marginTop: 4 }}>green = Kalman-filtered error over time · lower is better</div>
    </div>
  );
}
