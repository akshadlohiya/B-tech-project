import React, { useEffect, useRef, useState } from 'react';
import { getMap, saveMap, goTo } from './api';

// 2D top-down floorplan editor (Mappedin-style). World is metres; SVG renders a
// point (x, z) at (x, -z) so +z (north) is up. Draw walls, areas, anchors and
// tag routes; Save writes the map and the live sim/solver/twin reload.
const nextId = (list, prefix) => prefix + ((Math.max(0, ...list.map((x) => parseInt((String(x.id).match(/\d+/) || [0])[0], 10))) || 0) + 1);
const clone = (o) => structuredClone(o);

const TOOLS = [
  ['select', '⬚ Select / Move'],
  ['wall', '／ Wall'],
  ['zone', '▭ Area'],
  ['anchor', '📡 Anchor'],
  ['tag', '🏷️ Tag'],
  ['delete', '🗑 Delete'],
];

export default function Editor2D({ mapKey }) {
  const [map, setMap] = useState(null);
  const [tool, setTool] = useState('select');
  const [selected, setSelected] = useState(null);   // {type, id}
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState(null);
  const svgRef = useRef(null);
  const [wallStart, setWallStart] = useState(null);
  const drag = useRef(null);
  const [cursor, setCursor] = useState(null);        // world pos of pointer (for previews)
  const [zoneDraw, setZoneDraw] = useState(null);

  useEffect(() => { getMap(mapKey).then(setMap).catch((e) => setErr(e.message)); }, [mapKey]);

  const mutate = (fn) => setMap((m) => { const n = clone(m); fn(n); return n; });

  const toWorld = (e) => {
    const svg = svgRef.current;
    const pt = svg.createSVGPoint(); pt.x = e.clientX; pt.y = e.clientY;
    const p = pt.matrixTransform(svg.getScreenCTM().inverse());
    return { x: Math.round(p.x * 10) / 10, z: Math.round(-p.y * 10) / 10 };
  };

  // --- create / delete ---------------------------------------------------------
  const addAnchor = (x, z) => mutate((m) => { const id = nextId(m.anchors, 'A'); m.anchors.push({ id, label: id, x, y: (m.floor.ceilingHeight || 5) - 0.4, z, antennaDelayBiasM: 0.1, provenance: 'guessed' }); setSelected({ type: 'anchor', id }); });
  const addTag = (x, z) => mutate((m) => { const id = nextId(m.tags, 'T'); m.tags.push({ id, name: 'Tag ' + id, role: 'asset', battery: 100, y: 0.5, speed: 1.2, allowedZones: [], waypoints: [[x, z], [x + 4, z], [x + 4, z + 4], [x, z + 4], [x, z]], pauseAtWaypointSec: 1, loop: true }); setSelected({ type: 'tag', id }); });
  const addWall = (x1, z1, x2, z2) => mutate((m) => { const id = nextId(m.walls, 'W'); m.walls.push({ id, label: id, x1, z1, x2, z2, height: 3, blocksLos: true, provenance: 'guessed' }); });
  const addZone = (a, b) => mutate((m) => { const id = nextId(m.zones, 'Z'); m.zones.push({ id, label: 'Area ' + id, xmin: Math.min(a.x, b.x), xmax: Math.max(a.x, b.x), zmin: Math.min(a.z, b.z), zmax: Math.max(a.z, b.z), color: '#38bdf8' }); setSelected({ type: 'zone', id }); });
  const remove = (type, id) => mutate((m) => {
    if (type === 'anchor') m.anchors = m.anchors.filter((a) => a.id !== id);
    if (type === 'wall') m.walls = m.walls.filter((w) => w.id !== id);
    if (type === 'zone') m.zones = m.zones.filter((z) => z.id !== id);
    if (type === 'tag') m.tags = m.tags.filter((t) => t.id !== id);
  });

  // --- pointer plumbing --------------------------------------------------------
  const onElementDown = (e, type, id, extra) => {
    e.stopPropagation();
    if (tool === 'delete') { remove(type, id); if (selected?.id === id) setSelected(null); return; }
    setSelected({ type, id });
    if (tool === 'select') drag.current = { type, id, ...extra };
  };

  const onSvgDown = (e) => {
    const w = toWorld(e);
    if (tool === 'anchor') return addAnchor(w.x, w.z);
    if (tool === 'tag') return addTag(w.x, w.z);
    if (tool === 'wall') {
      if (!wallStart) setWallStart(w);
      else { addWall(wallStart.x, wallStart.z, w.x, w.z); setWallStart(null); }
      return;
    }
    if (tool === 'zone') { setZoneDraw({ a: w, b: w }); return; }
    if (tool === 'select') setSelected(null);
  };

  const onSvgMove = (e) => {
    const w = toWorld(e);
    setCursor(w);
    if (zoneDraw) { setZoneDraw((zd) => ({ ...zd, b: w })); return; }
    const d = drag.current;
    if (!d) return;
    mutate((m) => {
      if (d.type === 'anchor') { const a = m.anchors.find((x) => x.id === d.id); if (a) { a.x = w.x; a.z = w.z; } }
      else if (d.type === 'zone') { const z = m.zones.find((x) => x.id === d.id); if (z) { const w2 = z.xmax - z.xmin, h = z.zmax - z.zmin; z.xmin = w.x - w2 / 2; z.xmax = w.x + w2 / 2; z.zmin = w.z - h / 2; z.zmax = w.z + h / 2; } }
      else if (d.type === 'wallpt') { const wl = m.walls.find((x) => x.id === d.id); if (wl) { wl['x' + d.pt] = w.x; wl['z' + d.pt] = w.z; } }
      else if (d.type === 'tag') { const t = m.tags.find((x) => x.id === d.id); if (t) { const dx = w.x - t.waypoints[0][0], dz = w.z - t.waypoints[0][1]; t.waypoints = t.waypoints.map(([px, pz]) => [px + dx, pz + dz]); } }
      else if (d.type === 'waypoint') { const t = m.tags.find((x) => x.id === d.id); if (t && t.waypoints[d.idx]) t.waypoints[d.idx] = [w.x, w.z]; }
    });
  };

  const onSvgUp = () => {
    drag.current = null;
    if (zoneDraw) { if (Math.hypot(zoneDraw.b.x - zoneDraw.a.x, zoneDraw.b.z - zoneDraw.a.z) > 0.5) addZone(zoneDraw.a, zoneDraw.b); setZoneDraw(null); }
  };

  const save = async () => {
    setSaving(true);
    try { await saveMap(mapKey, map); goTo({ map: mapKey, mode: 'view' }); }
    catch (e) { alert('Save failed: ' + e.message); setSaving(false); }
  };

  if (err) return <div style={{ ...center, color: '#fca5a5' }}>⚠️ {err} <button style={btn} onClick={() => goTo({})}>← Maps</button></div>;
  if (!map) return <div style={center}>Loading map…</div>;

  const hx = map.floor.sizeX / 2, hz = map.floor.sizeZ / 2, pad = 4;
  const viewBox = `${-hx - pad} ${-hz - pad} ${map.floor.sizeX + 2 * pad} ${map.floor.sizeZ + 2 * pad}`;
  const P = (x, z) => `${x},${-z}`;

  return (
    <div style={{ position: 'absolute', inset: 0, display: 'flex', background: 'var(--bg-dark)', color: 'var(--text-light)' }}>
      {/* toolbar */}
      <div style={{ width: 180, padding: 16, borderRight: '1px solid var(--glass-border)', display: 'flex', flexDirection: 'column', gap: 8 }}>
        <button style={{ ...btn, marginBottom: 6 }} onClick={() => goTo({})}>← Maps</button>
        <div style={{ fontWeight: 700, fontSize: 15 }}>{map.meta.name}</div>
        <div style={{ color: '#64748b', fontSize: 12, fontFamily: 'monospace', marginBottom: 8 }}>{mapKey}</div>
        {TOOLS.map(([id, label]) => (
          <button key={id} onClick={() => { setTool(id); setWallStart(null); }} style={{ ...toolBtn, ...(tool === id ? toolActive : {}) }}>{label}</button>
        ))}
        <div style={{ marginTop: 'auto', display: 'flex', flexDirection: 'column', gap: 8 }}>
          <button style={{ ...btn, background: '#16a34a', color: 'white', border: 'none' }} onClick={save} disabled={saving}>{saving ? 'Saving…' : '💾 Save & Apply'}</button>
          <button style={btn} onClick={() => goTo({ map: mapKey, mode: 'view' })}>▶ View in 3D</button>
        </div>
      </div>

      {/* canvas */}
      <div style={{ flex: 1, position: 'relative' }}>
        <svg ref={svgRef} viewBox={viewBox} preserveAspectRatio="xMidYMid meet" style={{ width: '100%', height: '100%', cursor: tool === 'select' ? 'default' : 'crosshair', background: '#0b1220' }}
          onPointerDown={onSvgDown} onPointerMove={onSvgMove} onPointerUp={onSvgUp} onPointerLeave={onSvgUp}>
          {/* floor */}
          <rect x={-hx} y={-hz} width={map.floor.sizeX} height={map.floor.sizeZ} fill="#111c30" stroke="#334155" strokeWidth={0.1} />
          {/* grid */}
          {gridLines(hx, hz)}
          {/* zones */}
          {map.zones.map((z) => (
            <g key={z.id} onPointerDown={(e) => onElementDown(e, 'zone', z.id)} style={{ cursor: 'pointer' }}>
              <rect x={z.xmin} y={-z.zmax} width={z.xmax - z.xmin} height={z.zmax - z.zmin} fill={z.color || '#38bdf8'} fillOpacity={selected?.id === z.id ? 0.28 : 0.15} stroke={selected?.id === z.id ? '#fde047' : z.color} strokeWidth={0.15} />
              <text x={(z.xmin + z.xmax) / 2} y={-(z.zmin + z.zmax) / 2} fontSize={0.9} fill={z.color} textAnchor="middle" style={{ pointerEvents: 'none' }}>{z.label}</text>
            </g>
          ))}
          {/* walls */}
          {map.walls.map((w) => {
            const sel = selected?.id === w.id;
            return (
              <g key={w.id}>
                <line x1={w.x1} y1={-w.z1} x2={w.x2} y2={-w.z2} stroke={sel ? '#fde047' : (String(w.id).startsWith('R') ? '#0ea5e9' : '#cbd5e1')} strokeWidth={0.4} strokeLinecap="round"
                  onPointerDown={(e) => onElementDown(e, 'wall', w.id)} style={{ cursor: 'pointer' }} />
                {sel && [1, 2].map((pt) => <circle key={pt} cx={w['x' + pt]} cy={-w['z' + pt]} r={0.4} fill="#fde047" onPointerDown={(e) => onElementDown(e, 'wall', w.id, { type: 'wallpt', pt })} style={{ cursor: 'move' }} />)}
              </g>
            );
          })}
          {/* wall preview */}
          {tool === 'wall' && wallStart && cursor && <line x1={wallStart.x} y1={-wallStart.z} x2={cursor.x} y2={-cursor.z} stroke="#38bdf8" strokeWidth={0.3} strokeDasharray="0.6 0.4" />}
          {/* zone preview */}
          {zoneDraw && <rect x={Math.min(zoneDraw.a.x, zoneDraw.b.x)} y={-Math.max(zoneDraw.a.z, zoneDraw.b.z)} width={Math.abs(zoneDraw.b.x - zoneDraw.a.x)} height={Math.abs(zoneDraw.b.z - zoneDraw.a.z)} fill="#38bdf8" fillOpacity={0.2} stroke="#38bdf8" strokeWidth={0.15} />}
          {/* tag routes */}
          {map.tags.map((t) => {
            const sel = selected?.type === 'tag' && selected.id === t.id;
            const col = t.role === 'person' ? '#3b82f6' : t.role === 'asset' ? '#eab308' : '#a855f7';
            return (
              <g key={t.id}>
                <polyline points={t.waypoints.map(([x, z]) => P(x, z)).join(' ')} fill="none" stroke={col} strokeOpacity={0.5} strokeWidth={0.15} strokeDasharray="0.5 0.3" />
                {sel && t.waypoints.map(([x, z], i) => <circle key={i} cx={x} cy={-z} r={0.35} fill={col} stroke="#fde047" strokeWidth={0.1} onPointerDown={(e) => onElementDown(e, 'tag', t.id, { type: 'waypoint', idx: i })} style={{ cursor: 'move' }} />)}
                <rect x={t.waypoints[0][0] - 0.5} y={-t.waypoints[0][1] - 0.5} width={1} height={1} fill={col} stroke={sel ? '#fde047' : 'white'} strokeWidth={0.12}
                  onPointerDown={(e) => onElementDown(e, 'tag', t.id, { type: 'tag' })} style={{ cursor: 'pointer' }} />
                <text x={t.waypoints[0][0]} y={-t.waypoints[0][1] - 0.9} fontSize={0.8} fill={col} textAnchor="middle" style={{ pointerEvents: 'none' }}>{t.name}</text>
              </g>
            );
          })}
          {/* anchors */}
          {map.anchors.map((a) => (
            <g key={a.id}>
              <circle cx={a.x} cy={-a.z} r={0.6} fill="#f97316" stroke={selected?.id === a.id ? '#fde047' : 'white'} strokeWidth={0.15}
                onPointerDown={(e) => onElementDown(e, 'anchor', a.id)} style={{ cursor: 'pointer' }} />
              <text x={a.x} y={-a.z - 0.9} fontSize={0.8} fill="#f97316" textAnchor="middle" style={{ pointerEvents: 'none' }}>{a.label}</text>
            </g>
          ))}
        </svg>
        <div style={{ position: 'absolute', bottom: 10, left: 12, color: '#64748b', fontSize: 12 }}>
          {tool === 'wall' ? 'Click two points to draw a wall.' : tool === 'zone' ? 'Drag to draw an area.' : tool === 'select' ? 'Click to select; drag to move. Select a tag to edit its route.' : `Click to place ${tool}.`}
        </div>
      </div>

      {/* properties */}
      <PropsPanel map={map} mutate={mutate} selected={selected} remove={remove} setSelected={setSelected} />
    </div>
  );
}

function PropsPanel({ map, mutate, selected, remove, setSelected }) {
  const num = (v) => (Number.isFinite(parseFloat(v)) ? parseFloat(v) : 0);
  return (
    <div style={{ width: 250, padding: 16, borderLeft: '1px solid var(--glass-border)', overflowY: 'auto' }}>
      <h3 style={{ marginTop: 0 }}>Map</h3>
      <label style={lbl}>Name<input style={inp} value={map.meta.name} onChange={(e) => mutate((m) => { m.meta.name = e.target.value; })} /></label>
      <div style={{ display: 'flex', gap: 6 }}>
        <label style={lbl}>Width<input style={inp} type="number" value={map.floor.sizeX} onChange={(e) => mutate((m) => { m.floor.sizeX = num(e.target.value); })} /></label>
        <label style={lbl}>Depth<input style={inp} type="number" value={map.floor.sizeZ} onChange={(e) => mutate((m) => { m.floor.sizeZ = num(e.target.value); })} /></label>
      </div>
      <label style={lbl}>Floor label<input style={inp} value={map.floor.label} onChange={(e) => mutate((m) => { m.floor.label = e.target.value; })} /></label>

      <h3>Selection</h3>
      {!selected && <div style={{ color: '#64748b', fontSize: 13 }}>Nothing selected.</div>}
      {selected?.type === 'anchor' && (() => { const a = map.anchors.find((x) => x.id === selected.id); if (!a) return null; return (
        <div>
          <label style={lbl}>Label<input style={inp} value={a.label} onChange={(e) => mutate((m) => { m.anchors.find((x) => x.id === a.id).label = e.target.value; })} /></label>
          <div style={{ display: 'flex', gap: 6 }}>
            <label style={lbl}>x<input style={inp} type="number" value={a.x} onChange={(e) => mutate((m) => { m.anchors.find((x) => x.id === a.id).x = num(e.target.value); })} /></label>
            <label style={lbl}>z<input style={inp} type="number" value={a.z} onChange={(e) => mutate((m) => { m.anchors.find((x) => x.id === a.id).z = num(e.target.value); })} /></label>
            <label style={lbl}>y<input style={inp} type="number" value={a.y} onChange={(e) => mutate((m) => { m.anchors.find((x) => x.id === a.id).y = num(e.target.value); })} /></label>
          </div>
          <button style={del} onClick={() => { remove('anchor', a.id); setSelected(null); }}>Delete anchor</button>
        </div>
      ); })()}
      {selected?.type === 'zone' && (() => { const z = map.zones.find((x) => x.id === selected.id); if (!z) return null; return (
        <div>
          <label style={lbl}>Label<input style={inp} value={z.label} onChange={(e) => mutate((m) => { m.zones.find((x) => x.id === z.id).label = e.target.value; })} /></label>
          <label style={lbl}>Color<input style={{ ...inp, padding: 0, height: 28 }} type="color" value={z.color} onChange={(e) => mutate((m) => { m.zones.find((x) => x.id === z.id).color = e.target.value; })} /></label>
          <button style={del} onClick={() => { remove('zone', z.id); setSelected(null); }}>Delete area</button>
        </div>
      ); })()}
      {selected?.type === 'wall' && (() => { const w = map.walls.find((x) => x.id === selected.id); if (!w) return null; return (
        <div>
          <label style={lbl}>Height (m)<input style={inp} type="number" value={w.height} onChange={(e) => mutate((m) => { m.walls.find((x) => x.id === w.id).height = num(e.target.value); })} /></label>
          <label style={{ ...lbl, flexDirection: 'row', alignItems: 'center', gap: 8 }}><input type="checkbox" checked={w.blocksLos} onChange={(e) => mutate((m) => { m.walls.find((x) => x.id === w.id).blocksLos = e.target.checked; })} />Blocks line-of-sight (NLOS)</label>
          <button style={del} onClick={() => { remove('wall', w.id); setSelected(null); }}>Delete wall</button>
        </div>
      ); })()}
      {selected?.type === 'tag' && (() => { const t = map.tags.find((x) => x.id === selected.id); if (!t) return null; return (
        <div>
          <label style={lbl}>Name<input style={inp} value={t.name} onChange={(e) => mutate((m) => { m.tags.find((x) => x.id === t.id).name = e.target.value; })} /></label>
          <label style={lbl}>Role
            <select style={inp} value={t.role} onChange={(e) => mutate((m) => { m.tags.find((x) => x.id === t.id).role = e.target.value; })}>
              <option value="asset">asset</option><option value="person">person</option><option value="default">other</option>
            </select>
          </label>
          <div style={{ display: 'flex', gap: 6 }}>
            <label style={lbl}>Speed<input style={inp} type="number" step="0.1" value={t.speed} onChange={(e) => mutate((m) => { m.tags.find((x) => x.id === t.id).speed = num(e.target.value); })} /></label>
            <label style={lbl}>Height<input style={inp} type="number" step="0.1" value={t.y} onChange={(e) => mutate((m) => { m.tags.find((x) => x.id === t.id).y = num(e.target.value); })} /></label>
          </div>
          <div style={{ fontSize: 12, color: '#64748b', margin: '6px 0' }}>{t.waypoints.length} waypoints — drag the dots to reshape the route.</div>
          <div style={{ display: 'flex', gap: 6 }}>
            <button style={btn} onClick={() => mutate((m) => { const tt = m.tags.find((x) => x.id === t.id); const [lx, lz] = tt.waypoints[tt.waypoints.length - 1]; tt.waypoints.splice(tt.waypoints.length - 1, 0, [lx + 2, lz + 2]); })}>＋ waypoint</button>
            <button style={btn} onClick={() => mutate((m) => { const tt = m.tags.find((x) => x.id === t.id); if (tt.waypoints.length > 3) tt.waypoints.splice(tt.waypoints.length - 2, 1); })}>－ waypoint</button>
          </div>
          <button style={del} onClick={() => { remove('tag', t.id); setSelected(null); }}>Delete tag</button>
        </div>
      ); })()}
    </div>
  );
}

function gridLines(hx, hz) {
  const lines = [];
  for (let x = Math.ceil(-hx / 5) * 5; x <= hx; x += 5) lines.push(<line key={'gx' + x} x1={x} y1={-hz} x2={x} y2={hz} stroke="#1e293b" strokeWidth={0.05} />);
  for (let z = Math.ceil(-hz / 5) * 5; z <= hz; z += 5) lines.push(<line key={'gz' + z} x1={-hx} y1={-z} x2={hx} y2={-z} stroke="#1e293b" strokeWidth={0.05} />);
  return lines;
}

const center = { position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 12, background: 'var(--bg-dark)', color: 'var(--text-light)' };
const btn = { background: '#1e293b', color: '#e2e8f0', border: '1px solid #334155', borderRadius: 6, padding: '7px 10px', cursor: 'pointer', fontSize: 13 };
const toolBtn = { ...btn, textAlign: 'left' };
const toolActive = { background: '#2563eb', color: 'white', borderColor: '#2563eb', fontWeight: 600 };
const del = { ...btn, color: '#fca5a5', width: '100%', marginTop: 10 };
const lbl = { display: 'flex', flexDirection: 'column', gap: 4, fontSize: 12, color: '#94a3b8', marginBottom: 10, flex: 1 };
const inp = { background: '#0f172a', color: 'white', border: '1px solid #334155', borderRadius: 6, padding: '6px 8px', fontSize: 13 };
