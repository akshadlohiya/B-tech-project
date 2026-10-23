import React from 'react';
import { parseRoute } from './api';
import MapManager from './MapManager';
import Viewer3D from './Viewer3D';
import Editor2D from './Editor2D';
import ClassicWarehouse from './ClassicWarehouse';
import './index.css';

// Query-param routing:
//   (no map)              -> map library
//   ?mode=classic         -> classic 3D warehouse simulation (WASD mover, industrial shelving, etc.)
//   ?map=KEY              -> live 3D digital twin viewer
//   ?map=KEY&mode=edit    -> 2D floorplan editor
export default function App() {
  const { map, mode } = parseRoute();
  if (mode === 'classic') return <ClassicWarehouse />;
  if (!map) return <MapManager />;
  if (mode === 'edit') return <Editor2D mapKey={map} />;
  return <Viewer3D mapKey={map} />;
}
