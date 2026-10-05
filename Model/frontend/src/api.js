// Backend REST + tiny URL router for the mapping platform.
export const API = 'http://localhost:3000';
export const SOCKET_URL = API;

const json = (r) => { if (!r.ok) return r.json().then((j) => { throw new Error(j.error || r.status); }); return r.json(); };

export const listMaps = () => fetch(`${API}/api/maps`).then(json);
export const createMap = (name) => fetch(`${API}/api/maps`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name }) }).then(json);
export const getMap = (key) => fetch(`${API}/api/maps/${key}`).then(json).then((m) => ({
  ...m,
  anchors: m.anchors || [], walls: m.walls || [], zones: m.zones || [], tags: m.tags || [],
  floor: m.floor || { id: 'f_floor1', label: 'Floor', sizeX: 30, sizeZ: 30, ceilingHeight: 5 },
}));
export const saveMap = (key, map) => fetch(`${API}/api/maps/${key}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(map) }).then(json);
export const deleteMap = (key) => fetch(`${API}/api/maps/${key}`, { method: 'DELETE' }).then(json);

// Routing is just query params: ?map=KEY&mode=view|edit  (no map => manager).
export const parseRoute = () => {
  const p = new URLSearchParams(window.location.search);
  return { map: p.get('map'), mode: p.get('mode') || 'view' };
};
export const goTo = ({ map, mode }) => {
  const p = new URLSearchParams();
  if (map) p.set('map', map);
  if (mode) p.set('mode', mode);
  window.location.search = p.toString();
};
export const shareLink = (key) => `${window.location.origin}${window.location.pathname}?map=${key}`;
