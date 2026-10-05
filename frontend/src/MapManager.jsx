import React, { useEffect, useState } from 'react';
import { listMaps, createMap, deleteMap, goTo, shareLink } from './api';

// Landing page: the library of maps. Create, open (view/edit), share, delete.
export default function MapManager() {
  const [maps, setMaps] = useState(null);
  const [err, setErr] = useState(null);
  const [name, setName] = useState('');
  const [copied, setCopied] = useState(null);

  const refresh = () => listMaps().then(setMaps).catch((e) => setErr(e.message));
  useEffect(() => { refresh(); }, []);

  const create = async () => {
    const res = await createMap(name.trim() || 'Untitled Map');
    goTo({ map: res.key, mode: 'edit' });
  };
  const remove = async (key) => { if (confirm(`Delete map "${key}"? This cannot be undone.`)) { await deleteMap(key); refresh(); } };
  const copy = (key) => { navigator.clipboard?.writeText(shareLink(key)); setCopied(key); setTimeout(() => setCopied(null), 1500); };

  return (
    <div style={wrap}>
      <div style={{ maxWidth: 820, margin: '0 auto', padding: '48px 24px' }}>
        <h1 style={{ fontSize: 30, marginBottom: 4 }}>UWB RTLS — Map Library</h1>
        <p style={{ color: '#94a3b8', marginBottom: 28 }}>Create indoor maps, draw floorplans, and share a key so anyone can watch live tracking.</p>

        <div style={{ display: 'flex', gap: 10, marginBottom: 28 }}>
          <input style={{ ...input, flex: 1 }} placeholder="New map name (e.g. Warehouse B)" value={name} onChange={(e) => setName(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && create()} />
          <button style={primary} onClick={create}>＋ Create map</button>
        </div>

        {err && <div style={{ color: '#fca5a5', marginBottom: 16 }}>⚠️ Cannot reach backend ({err}). Is it running on :3000?</div>}
        {!maps && !err && <div style={{ color: '#94a3b8' }}>Loading maps…</div>}

        <div style={{ display: 'grid', gap: 14 }}>
          {maps && maps.map((m) => (
            <div key={m.key} style={card}>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 18, fontWeight: 700 }}>{m.name}</div>
                <div style={{ color: '#94a3b8', fontSize: 13, marginTop: 4 }}>
                  <span style={{ fontFamily: 'monospace', color: '#38bdf8' }}>{m.key}</span> · {m.anchors} anchors · {m.tags} tags {m.floor && `· ${m.floor}`}
                </div>
              </div>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                <button style={btn} onClick={() => goTo({ map: m.key, mode: 'view' })}>▶ View</button>
                <button style={btn} onClick={() => goTo({ map: m.key, mode: 'edit' })}>✎ Edit</button>
                <button style={btn} onClick={() => copy(m.key)}>{copied === m.key ? '✓ Copied' : '🔗 Share'}</button>
                {m.key !== 'demo' && <button style={{ ...btn, color: '#fca5a5' }} onClick={() => remove(m.key)}>🗑</button>}
              </div>
            </div>
          ))}
          {maps && maps.length === 0 && <div style={{ color: '#94a3b8' }}>No maps yet — create one above.</div>}
        </div>
      </div>
    </div>
  );
}

const wrap = { position: 'absolute', inset: 0, overflow: 'auto', background: 'var(--bg-dark)', color: 'var(--text-light)' };
const card = { display: 'flex', alignItems: 'center', gap: 14, background: 'var(--glass-bg)', border: '1px solid var(--glass-border)', borderRadius: 14, padding: '16px 20px' };
const input = { background: '#0f172a', color: 'white', border: '1px solid #334155', borderRadius: 8, padding: '10px 12px', fontSize: 15 };
const btn = { background: '#1e293b', color: '#e2e8f0', border: '1px solid #334155', borderRadius: 8, padding: '8px 12px', cursor: 'pointer', fontSize: 13 };
const primary = { ...btn, background: '#2563eb', color: 'white', border: 'none', fontWeight: 600, padding: '8px 16px' };
