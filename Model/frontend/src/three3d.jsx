/* eslint-disable react-refresh/only-export-components */
// 3D twin building blocks, shared by the viewer. This module intentionally
// exports both components and shared helpers/constants (detectWebGL, roleOf,
// zoneLabel, ...), so the Fast-Refresh-only rule is disabled here.
// Renders a map (floor, walls, zones, anchors) and live tags with LOS/NLOS
// range lines, plus click-to-inspect.
import React, { useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import { OrbitControls, Html, Grid, Line } from '@react-three/drei';
import * as THREE from 'three';

export const ROLE_COLOR = { asset: '#eab308', person: '#3b82f6', default: '#a855f7' };
export const overlayStyle = { position: 'absolute', inset: 0, zIndex: 20, display: 'flex', alignItems: 'center', justifyContent: 'center', flexDirection: 'column', gap: 10, textAlign: 'center', padding: 24 };
const setCursor = (c) => { document.body.style.cursor = c; };

export function detectWebGL() {
  try {
    const c = document.createElement('canvas');
    const gl = c.getContext('webgl2') || c.getContext('webgl') || c.getContext('experimental-webgl');
    return gl ? { ok: true, reason: '' } : { ok: false, reason: 'No WebGL context could be created.' };
  } catch (e) { return { ok: false, reason: e.message }; }
}

export class CanvasErrorBoundary extends React.Component {
  constructor(props) { super(props); this.state = { error: null }; }
  static getDerivedStateFromError(error) { return { error }; }
  componentDidCatch(error, info) { console.error('3D canvas error:', error, info); }
  render() {
    if (this.state.error) {
      return (
        <div style={overlayStyle}>
          <div style={{ fontSize: 20, fontWeight: 700 }}>⚠️ 3D map failed to render</div>
          <div style={{ maxWidth: 620, color: '#fca5a5', fontFamily: 'monospace', fontSize: 13, whiteSpace: 'pre-wrap' }}>{String(this.state.error?.message || this.state.error)}</div>
          <div style={{ maxWidth: 560, color: '#94a3b8', fontSize: 13 }}>Usually WebGL is disabled — enable graphics acceleration in the browser, or use Firefox.</div>
        </div>
      );
    }
    return this.props.children;
  }
}

function Anchor({ a, selected, onSelect }) {
  return (
    <mesh position={[a.x, a.y, a.z]} onClick={(e) => { e.stopPropagation(); onSelect(); }} onPointerOver={(e) => { e.stopPropagation(); setCursor('pointer'); }} onPointerOut={() => setCursor('auto')} castShadow>
      <boxGeometry args={[0.6, 0.6, 0.6]} />
      <meshStandardMaterial color={selected ? '#fde047' : '#f97316'} emissive="#f97316" emissiveIntensity={selected ? 0.6 : 0.25} metalness={0.4} roughness={0.3} />
      {selected && <mesh><boxGeometry args={[0.9, 0.9, 0.9]} /><meshBasicMaterial color="#fde047" wireframe /></mesh>}
      <Html distanceFactor={22} center position={[0, 0.95, 0]} zIndexRange={[100, 0]}><div style={{ background: 'rgba(249,115,22,0.92)', padding: '2px 8px', borderRadius: 4, fontWeight: 'bold', color: 'white', border: '1px solid white', whiteSpace: 'nowrap' }}>📡 {a.label}</div></Html>
    </mesh>
  );
}

function Wall({ w }) {
  const dx = w.x2 - w.x1, dz = w.z2 - w.z1;
  const len = Math.hypot(dx, dz);
  const isRack = w.id?.startsWith('R');
  return (
    <mesh position={[(w.x1 + w.x2) / 2, w.height / 2, (w.z1 + w.z2) / 2]} rotation={[0, Math.atan2(-dz, dx), 0]} castShadow receiveShadow>
      <boxGeometry args={[len || 0.1, w.height, isRack ? 0.6 : 0.3]} />
      <meshStandardMaterial color={isRack ? '#0ea5e9' : '#e2e8f0'} transparent={!isRack} opacity={isRack ? 1 : 0.35} metalness={0.2} roughness={0.8} />
    </mesh>
  );
}

function Zone({ z }) {
  const w = z.xmax - z.xmin, d = z.zmax - z.zmin;
  return (
    <group position={[(z.xmin + z.xmax) / 2, 0.02, (z.zmin + z.zmax) / 2]}>
      <mesh rotation={[-Math.PI / 2, 0, 0]}><planeGeometry args={[Math.abs(w), Math.abs(d)]} /><meshBasicMaterial color={z.color || '#38bdf8'} transparent opacity={0.12} side={THREE.DoubleSide} /></mesh>
      <Html distanceFactor={30} center position={[0, 0.05, 0]} zIndexRange={[10, 0]}><div style={{ color: z.color || '#38bdf8', fontWeight: 'bold', fontSize: 13, textShadow: '0 1px 3px rgba(0,0,0,0.6)', whiteSpace: 'nowrap', pointerEvents: 'none' }}>{z.label}</div></Html>
    </group>
  );
}

function Tag({ pos, name, battery, role, zone, selected, onSelect }) {
  const ref = useRef();
  const target = new THREE.Vector3(pos.x, pos.y, pos.z);
  useFrame((_s, delta) => { if (ref.current) ref.current.position.lerp(target, Math.min(1, delta * 6)); });
  const color = ROLE_COLOR[role] || ROLE_COLOR.default;
  return (
    <group ref={ref} position={[pos.x, pos.y, pos.z]} onClick={(e) => { e.stopPropagation(); onSelect(); }} onPointerOver={(e) => { e.stopPropagation(); setCursor('pointer'); }} onPointerOut={() => setCursor('auto')}>
      <mesh castShadow><cylinderGeometry args={[0.4, 0.4, 0.9, 16]} /><meshStandardMaterial color={color} metalness={0.2} roughness={0.7} /></mesh>
      <mesh position={[0, 0.65, 0]} castShadow><sphereGeometry args={[0.28, 16, 16]} /><meshStandardMaterial color={color} emissive={color} emissiveIntensity={selected ? 0.8 : 0.3} /></mesh>
      {selected && <mesh position={[0, 0.2, 0]}><sphereGeometry args={[0.75, 16, 16]} /><meshBasicMaterial color="#fde047" wireframe /></mesh>}
      <Html distanceFactor={18} center position={[0, 1.45, 0]} zIndexRange={[100, 0]}><div style={{ background: 'rgba(15,23,42,0.85)', border: `1px solid ${selected ? '#fde047' : 'rgba(56,189,248,0.5)'}`, padding: '4px 10px', borderRadius: 6, textAlign: 'center', whiteSpace: 'nowrap', color: 'white', fontSize: 13, backdropFilter: 'blur(4px)' }}><strong>{name}</strong><br /><span style={{ color: battery < 20 ? '#ef4444' : '#10b981' }}>⚡ {battery ?? '–'}%</span>{zone && <span style={{ color: '#94a3b8' }}> · {zone}</span>}</div></Html>
    </group>
  );
}

function RangeLines({ anchorsById, pos, reading }) {
  if (!reading) return null;
  return reading.ranges.map((r) => {
    const a = anchorsById[r.anchorId];
    if (!a) return null;
    const color = !r.valid ? '#64748b' : r.nlos ? '#ef4444' : '#22c55e';
    return <Line key={r.anchorId} points={[[a.x, a.y, a.z], [pos.x, pos.y + 0.5, pos.z]]} color={color} lineWidth={r.nlos ? 2.5 : 1.5} dashed={!r.valid} dashSize={0.3} gapSize={0.2} transparent opacity={r.valid ? 0.8 : 0.4} toneMapped={false} />;
  });
}

export const roleOf = (map, tagId) => (map.tags.find((x) => x.id === tagId) || {}).role || 'default';
export const zoneLabel = (map, zoneId) => zoneId ? ((map.zones || []).find((x) => x.id === zoneId) || {}).label || zoneId : null;

// Faint marker at the raw (pre-Kalman) solve + a 2σ uncertainty ring at the
// filtered position — the visible "before/after" of the Kalman filter.
function RawGhost({ p }) {
  if (!p.raw) return null;
  const y = p.pos?.y ?? 0.5;
  const r = p.cov ? Math.max(0.2, (p.cov.sx + p.cov.sz)) : 0.5;
  return (
    <group>
      <mesh position={[p.raw.x, y, p.raw.z]}>
        <sphereGeometry args={[0.22, 12, 12]} />
        <meshBasicMaterial color="#ef4444" transparent opacity={0.55} />
      </mesh>
      <mesh position={[p.pos.x, 0.03, p.pos.z]} rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[Math.max(0.1, r - 0.06), r, 32]} />
        <meshBasicMaterial color="#38bdf8" transparent opacity={0.5} side={THREE.DoubleSide} />
      </mesh>
    </group>
  );
}

// Fading path history. `trails` = estimated (Kalman) path per tag; `truthTrails`
// = ground-truth path (sim) for side-by-side comparison (Project Diary, 28 Jan).
function Trails({ map, trails, truthTrails, showTrails, showTruePath }) {
  return (
    <>
      {showTrails && Object.entries(trails).map(([id, pts]) => {
        if (!pts || pts.length < 2) return null;
        const base = new THREE.Color(ROLE_COLOR[roleOf(map, id)] || ROLE_COLOR.default);
        const colors = pts.map((_, i) => base.clone().multiplyScalar(0.25 + 0.75 * (i / (pts.length - 1))));
        return <Line key={id} points={pts} vertexColors={colors} lineWidth={2.5} transparent opacity={0.85} />;
      })}
      {showTruePath && Object.entries(truthTrails).map(([id, pts]) => (pts && pts.length >= 2)
        ? <Line key={'t' + id} points={pts} color="#e2e8f0" lineWidth={1.2} dashed dashSize={0.35} gapSize={0.3} transparent opacity={0.55} toneMapped={false} /> : null)}
    </>
  );
}

export function Scene({ map, positions, readings, showRangeLines, showRaw, trails, truthTrails, showTrails, showTruePath, selected, onSelect }) {
  const anchorsById = {};
  map.anchors.forEach((a) => { anchorsById[a.id] = a; });
  const half = Math.max(map.floor.sizeX, map.floor.sizeZ) / 2;
  const liveTags = Object.values(positions).filter((p) => map.tags.some((t) => t.id === p.tagId));
  return (
    <>
      <color attach="background" args={['#f8fafc']} />
      <fog attach="fog" args={['#f8fafc', 30, 90]} />
      <ambientLight intensity={0.75} />
      <spotLight position={[10, 25, 10]} angle={0.8} penumbra={1} castShadow intensity={1.8} shadow-mapSize={1024} />
      <directionalLight position={[-15, 20, -15]} intensity={0.9} />
      <Grid infiniteGrid fadeDistance={60} cellColor={'#cbd5e1'} sectionColor={'#94a3b8'} />
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.01, 0]} receiveShadow onClick={() => onSelect(null)}>
        <planeGeometry args={[map.floor.sizeX, map.floor.sizeZ]} /><meshStandardMaterial color="#64748b" roughness={0.5} metalness={0.1} />
      </mesh>
      {map.zones.map((z) => <Zone key={z.id} z={z} />)}
      {map.walls.map((w) => <Wall key={w.id} w={w} />)}
      {trails && <Trails map={map} trails={trails} truthTrails={truthTrails} showTrails={showTrails} showTruePath={showTruePath} />}
      {map.anchors.map((a) => <Anchor key={a.id} a={a} selected={selected?.type === 'anchor' && selected.id === a.id} onSelect={() => onSelect({ type: 'anchor', id: a.id })} />)}
      {liveTags.map((p) => (
        <React.Fragment key={p.tagId}>
          <Tag pos={p.pos} name={p.name} battery={p.battery} role={roleOf(map, p.tagId)} zone={zoneLabel(map, p.zone)} selected={selected?.type === 'tag' && selected.id === p.tagId} onSelect={() => onSelect({ type: 'tag', id: p.tagId })} />
          {showRangeLines && <RangeLines anchorsById={anchorsById} pos={p.pos} reading={readings[p.tagId]} />}
          {showRaw && <RawGhost p={p} />}
        </React.Fragment>
      ))}
      <OrbitControls makeDefault maxPolarAngle={Math.PI / 2 - 0.05} minDistance={3} maxDistance={half * 4} />
    </>
  );
}

function Row({ k, v }) { return <div className="telemetry-tag-dist"><span style={{ color: '#94a3b8' }}>{k}</span><span style={{ color: 'white', fontWeight: 600 }}>{v}</span></div>; }

export function DetailsPanel({ map, selected, positions, readings, onClose }) {
  if (!selected || !map) return null;
  if (selected.type === 'anchor') {
    const a = map.anchors.find((x) => x.id === selected.id);
    if (!a) return null;
    const seenBy = Object.values(readings).filter((rd) => rd.ranges.some((r) => r.anchorId === a.id));
    const nlosNow = seenBy.filter((rd) => rd.ranges.find((r) => r.anchorId === a.id)?.nlos).length;
    return (
      <div className="details-panel">
        <div className="details-head"><span>📡 {a.label}</span><button onClick={onClose}>✕</button></div>
        <Row k="ID" v={a.id} /><Row k="Position (m)" v={`x ${a.x}, y ${a.y}, z ${a.z}`} />
        <Row k="Antenna delay" v={`${(a.antennaDelayBiasM ?? 0).toFixed(2)} m`} /><Row k="Provenance" v={a.provenance || '—'} />
        <Row k="Tags ranging" v={`${seenBy.length} (${nlosNow} NLOS)`} />
      </div>
    );
  }
  const p = positions[selected.id];
  const t = map.tags.find((x) => x.id === selected.id);
  const rd = readings[selected.id];
  if (!p && !t) return null;
  return (
    <div className="details-panel">
      <div className="details-head"><span>🏷️ {p?.name || t?.name || selected.id}</span><button onClick={onClose}>✕</button></div>
      <Row k="ID / role" v={`${selected.id} · ${t?.role || '—'}`} /><Row k="Battery" v={`${p?.battery ?? t?.battery ?? '–'}%`} />
      <Row k="Zone" v={zoneLabel(map, p?.zone) || '—'} />
      {p?.pos && <Row k="Est. position" v={`x ${p.pos.x}, z ${p.pos.z}`} />}
      {p?.vel && <Row k="Speed" v={`${p.vel.speed} m/s`} />}
      {p?.error != null && <Row k="Filtered error" v={`${(p.error * 100).toFixed(0)} cm`} />}
      {p?.rawError != null && <Row k="Raw error" v={`${(p.rawError * 100).toFixed(0)} cm`} />}
      {p?.residual != null && <Row k="Solve residual" v={`${p.residual} m`} />}
      {rd && <div style={{ marginTop: 6 }}>{rd.ranges.map((r) => (
        <div key={r.anchorId} className="telemetry-tag-dist">
          <span>{r.anchorId} <span style={{ fontSize: '0.7rem', padding: '1px 5px', borderRadius: 4, color: 'white', background: !r.valid ? '#64748b' : r.nlos ? '#ef4444' : '#22c55e' }}>{!r.valid ? 'DROP' : r.nlos ? 'NLOS' : 'LOS'}</span></span>
          <span>{r.valid ? `${r.range.toFixed(2)} m` : '—'}</span>
        </div>
      ))}</div>}
    </div>
  );
}
