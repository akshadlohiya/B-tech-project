import React from 'react';
import { parseRoute } from './api';
import MapManager from './MapManager';
import Viewer3D from './Viewer3D';
import Editor2D from './Editor2D';
import './index.css';

// Query-param routing:
//   (no map)            -> map library
//   ?map=KEY            -> live 3D viewer
//   ?map=KEY&mode=edit  -> 2D floorplan editor
export default function App() {
  const { map, mode } = parseRoute();
  if (!map) return <MapManager />;
  if (mode === 'edit') return <Editor2D mapKey={map} />;
  return <Viewer3D mapKey={map} />;
}
