import React, { useEffect, useRef, useState, useMemo } from 'react';
import { io } from 'socket.io-client';
import { Canvas, useFrame } from '@react-three/fiber';
import { OrbitControls, Html, Box, Grid, Line } from '@react-three/drei';
import * as THREE from 'three';
import './index.css';
const SOCKET_URL = import.meta.env.VITE_BACKEND_URL || (typeof window !== 'undefined' && window.location.hostname ? `${window.location.protocol}//${window.location.hostname}:3000` : 'http://localhost:3000');
const BASE_LAT = 43.8615;
const BASE_LON = -78.9469;
const gpsToLocal = (lat, lon, elev) => {
	const x = (lon - BASE_LON) * 80000;
	const z = -(lat - BASE_LAT) * 111111; 
	const y = (elev || 0) * 0.8 + 0.5;
	return [x, y, z];
}
const useKeyboard = () => {
	const keys = useRef({ w: false, a: false, s: false, d: false });
	useEffect(() => {
		const handleDown = (e) => {
			if(e.key === 'w' || e.key === 'W') keys.current.w = true;
			if(e.key === 'a' || e.key === 'A') keys.current.a = true;
			if(e.key === 's' || e.key === 'S') keys.current.s = true;
			if(e.key === 'd' || e.key === 'D') keys.current.d = true;
		}
		const handleUp = (e) => {
			if(e.key === 'w' || e.key === 'W') keys.current.w = false;
			if(e.key === 'a' || e.key === 'A') keys.current.a = false;
			if(e.key === 's' || e.key === 'S') keys.current.s = false;
			if(e.key === 'd' || e.key === 'D') keys.current.d = false;
		}
		window.addEventListener('keydown', handleDown);
		window.addEventListener('keyup', handleUp);
		return () => { window.removeEventListener('keydown', handleDown); window.removeEventListener('keyup', handleUp); }
	}, []);
	return keys;
}
const PlayerMover = ({ targetId, allTags }) => {
	const keys = useKeyboard();
	const posRef = useRef(new THREE.Vector3(0, 0.5, 0));
	const meshRef = useRef();
	const lineRef = useRef();
	useFrame((state, delta) => {
		const speed = 10 * delta; 
		let nx = posRef.current.x;
		let nz = posRef.current.z;
		if (keys.current.w) nz -= speed;
		if (keys.current.s) nz += speed;
		if (keys.current.a) nx -= speed;
		if (keys.current.d) nx += speed;
		const hitLeft = (nx > -8.5 && nx < -1.5) && (nz > -10.5 && nz < 10.5);
		const hitRight = (nx > 1.5 && nx < 8.5) && (nz > -10.5 && nz < 10.5);
		const hitOuterWall = (nx < -14 || nx > 14 || nz < -14 || nz > 14);
		let hitSolidRampX = false;
		let hitSolidRampZ = false;
		const nativelyOnRamp = (posRef.current.x > 10 && posRef.current.x < 14 && posRef.current.z > 0 && posRef.current.z < 8);
		if (nativelyOnRamp) {
			if (nx <= 10 || nx >= 14) hitSolidRampX = true;
		} else {
			if (nx > 10 && nx < 14 && posRef.current.z > 0 && posRef.current.z < 8) {
				hitSolidRampX = true;
			}
			if (posRef.current.x > 10 && posRef.current.x < 14 && nz > 0 && nz < 8) {
				 if (posRef.current.z >= 8) {
				 } else if (posRef.current.z <= 0 && posRef.current.y > 2.0) {
				 } else {
					 hitSolidRampZ = true; 
				 }
			}
		}
		const hitWallX = hitOuterWall || hitLeft || hitRight || hitSolidRampX;
		if (!hitWallX) posRef.current.x = nx;
		let hitGuardRail = false;
		if (posRef.current.z <= 0 && posRef.current.y > 2.0 && nz > 0) {
			if (posRef.current.x <= 10 || posRef.current.x >= 14) hitGuardRail = true;
		}
		const hitWallZ = hitOuterWall || hitLeft || hitRight || hitSolidRampZ || hitGuardRail;
		if (!hitWallZ) posRef.current.z = nz;
		if (posRef.current.x > 10 && posRef.current.x < 14 && posRef.current.z > 0 && posRef.current.z < 8) {
			let elevation = ((8 - posRef.current.z) / 8) * 4.0;
			posRef.current.y = 0.5 + Math.max(0, Math.min(4.0, elevation));
		} else if (posRef.current.z <= 0 && posRef.current.y > 2.0) {
			posRef.current.y = 4.5;
		} else {
			posRef.current.y = 0.5;
		}
		if (meshRef.current) {
			meshRef.current.position.copy(posRef.current);
			if (keys.current.w) meshRef.current.rotation.y = Math.PI;
			if (keys.current.s) meshRef.current.rotation.y = 0;
			if (keys.current.a) meshRef.current.rotation.y = -Math.PI/2;
			if (keys.current.d) meshRef.current.rotation.y = Math.PI/2;
		}
		if (lineRef.current) {
			if (targetId && allTags[targetId]) {
				const tInfo = allTags[targetId];
				const tPos = gpsToLocal(tInfo.lat, tInfo.lon, tInfo.elev);
				const dist = Math.sqrt((posRef.current.x - tPos[0])**2 + (posRef.current.y - tPos[1])**2 + (posRef.current.z - tPos[2])**2).toFixed(2);
				const hud = document.getElementById('mover-target-dist');
				if(hud) hud.innerText = dist + 'm';
				lineRef.current.visible = true;
				lineRef.current.geometry.setPositions([
					posRef.current.x, posRef.current.y + 0.5, posRef.current.z,
					tPos[0], tPos[1] + 0.5, tPos[2]
				]);
			} else {
				lineRef.current.visible = false;
				const hud = document.getElementById('mover-target-dist');
				if(hud) hud.innerText = '--';
			}
		}
	});
	return (
		<group>
			<group ref={meshRef} position={[0, 0.5, 0]}>
				<mesh castShadow position={[0, 0, 0]}>
					<cylinderGeometry args={[0.5, 0.5, 1, 16]} />
					<meshStandardMaterial color="#22c55e" metalness={0.2} roughness={0.8} />
				</mesh>
				<mesh castShadow position={[0, 0.5, 0]}>
					<sphereGeometry args={[0.4, 16, 16]} />
					<meshStandardMaterial color="#86efac" />
				</mesh>
				<mesh castShadow position={[0, 0, 0.4]}>
					<boxGeometry args={[0.6, 0.6, 0.4]} />
					<meshStandardMaterial color="#14532d" />
				</mesh>
				<Html distanceFactor={15} center position={[0, 1.4, 0]} className="r3f-html-label" zIndexRange={[100, 0]}>
					<div style={{ background: 'rgba(34, 197, 94, 0.95)', padding: '4px 10px', borderRadius: '6px', textAlign: 'center', color: 'white', fontSize: '13px', fontWeight:'bold', boxShadow: '0 4px 6px rgba(0,0,0,0.3)', border: '1px solid white' }}>
						👤 YOU (Mover)
					</div>
				</Html>
			</group>
			<Line 
				ref={lineRef}
				points={[[0,0,0], [0,0,0]]} 
				color="#4ade80"
				lineWidth={4}
				dashed={false}
				toneMapped={false}
			/>
		</group>
	)
}
const UwbTag = ({ tag }) => {
	const targetPos = gpsToLocal(tag.lat, tag.lon, tag.elev);
	const meshRef = useRef();
	useFrame((state, delta) => {
		if (meshRef.current) {
			meshRef.current.position.lerp(new THREE.Vector3(...targetPos), delta * 4);
		}
	});
	return (
		<group ref={meshRef} position={targetPos}>
			{tag.name === 'Forklift' && (
				<group scale={1.2}>
					<mesh position={[0, -0.1, 0]} castShadow><boxGeometry args={[1, 0.6, 1.5]} /><meshStandardMaterial color="#eab308" /></mesh>
					<mesh position={[0, 0.5, 0.3]} castShadow><boxGeometry args={[0.8, 1, 0.8]} /><meshStandardMaterial color="#1e293b" /></mesh>
					<mesh position={[0, 0, -1.2]} castShadow><boxGeometry args={[0.6, 0.1, 1.2]} /><meshStandardMaterial color="#475569" /></mesh>
				</group>
			)}
			{tag.name === 'Employee 1' && (
				<group scale={0.7} position={[0, 0.1, 0]}>
					<mesh position={[0, -0.2, 0]} castShadow><cylinderGeometry args={[0.3, 0.4, 1.2]} /><meshStandardMaterial color="#3b82f6" /></mesh>
					<mesh position={[0, 0.6, 0]} castShadow><sphereGeometry args={[0.3]} /><meshStandardMaterial color="#fcd34d" /></mesh>
				</group>
			)}
			{tag.name === 'Pallet Jack' && (
				<group scale={0.9} position={[0, -0.4, 0]}>
					<mesh position={[0, 0.1, 0.5]} castShadow><boxGeometry args={[0.6, 0.4, 0.4]} /><meshStandardMaterial color="#ef4444" /></mesh>
					<mesh position={[0.2, 0.05, -0.2]} castShadow><boxGeometry args={[0.15, 0.1, 1.2]} /><meshStandardMaterial color="#1e293b" /></mesh>
					<mesh position={[-0.2, 0.05, -0.2]} castShadow><boxGeometry args={[0.15, 0.1, 1.2]} /><meshStandardMaterial color="#1e293b" /></mesh>
					<mesh position={[0, 0.6, 0.6]} rotation={[0.2, 0, 0]} castShadow><cylinderGeometry args={[0.05, 0.05, 1]} /><meshStandardMaterial color="#94a3b8" /></mesh>
				</group>
			)}
			{tag.name === 'Drone Transport' && (
				<group scale={0.8}>
					<mesh castShadow><sphereGeometry args={[0.4]} /><meshStandardMaterial color="#1e293b" /></mesh>
					<mesh position={[0.6, 0, 0.6]} castShadow><boxGeometry args={[0.8, 0.05, 0.1]} rotation={[0, Math.PI/4, 0]}/><meshStandardMaterial color="#94a3b8" /></mesh>
					<mesh position={[-0.6, 0, -0.6]} castShadow><boxGeometry args={[0.8, 0.05, 0.1]} rotation={[0, Math.PI/4, 0]}/><meshStandardMaterial color="#94a3b8" /></mesh>
					<mesh position={[0.6, 0, -0.6]} castShadow><boxGeometry args={[0.8, 0.05, 0.1]} rotation={[0, -Math.PI/4, 0]}/><meshStandardMaterial color="#94a3b8" /></mesh>
					<mesh position={[-0.6, 0, 0.6]} castShadow><boxGeometry args={[0.8, 0.05, 0.1]} rotation={[0, -Math.PI/4, 0]}/><meshStandardMaterial color="#94a3b8" /></mesh>
				</group>
			)}
			{(tag.name?.includes('Raspberry') || tag.tagId === 'Tag_Pi' || tag.isPi || tag.wifi) && (
				<group scale={1.0} position={[0, -0.15, 0]}>
					{/* Raspberry Pi Green PCB Board */}
					<mesh position={[0, 0, 0]} castShadow receiveShadow>
						<boxGeometry args={[1.2, 0.1, 0.85]} />
						<meshStandardMaterial color="#15803d" roughness={0.3} metalness={0.2} />
					</mesh>
					{/* SoC Chip */}
					<mesh position={[-0.1, 0.08, 0]} castShadow>
						<boxGeometry args={[0.35, 0.06, 0.35]} />
						<meshStandardMaterial color="#94a3b8" metalness={0.9} roughness={0.2} />
					</mesh>
					{/* USB Ports */}
					<mesh position={[0.5, 0.12, 0.2]} castShadow>
						<boxGeometry args={[0.28, 0.18, 0.22]} />
						<meshStandardMaterial color="#cbd5e1" metalness={0.8} roughness={0.3} />
					</mesh>
					<mesh position={[0.5, 0.12, -0.2]} castShadow>
						<boxGeometry args={[0.28, 0.18, 0.22]} />
						<meshStandardMaterial color="#cbd5e1" metalness={0.8} roughness={0.3} />
					</mesh>
					{/* GPIO Header */}
					<mesh position={[-0.1, 0.08, -0.32]} castShadow>
						<boxGeometry args={[0.8, 0.08, 0.1]} />
						<meshStandardMaterial color="#1e293b" />
					</mesh>
					{/* Pulsing Wi-Fi Ring */}
					<mesh position={[0, 0.08, 0]} rotation={[-Math.PI/2, 0, 0]}>
						<ringGeometry args={[0.6, 0.75, 24]} />
						<meshBasicMaterial color="#c026d3" transparent opacity={0.65} side={THREE.DoubleSide} />
					</mesh>
				</group>
			)}
			<Html distanceFactor={18} center position={[0, 1.6, 0]} className="r3f-html-label" zIndexRange={[100, 0]}>
				<div style={{ 
					background: tag.wifi ? 'rgba(88, 28, 135, 0.92)' : 'rgba(15, 23, 42, 0.85)', 
					border: tag.wifi ? '1px solid #c026d3' : '1px solid rgba(56, 189, 248, 0.5)', 
					padding: '4px 10px', 
					borderRadius: '6px', 
					textAlign: 'center', 
					whiteSpace: 'nowrap', 
					color: 'white', 
					fontSize: '13px', 
					backdropFilter: 'blur(4px)',
					boxShadow: tag.wifi ? '0 0 12px rgba(192, 38, 211, 0.5)' : 'none'
				}}>
					<strong>{tag.wifi ? '🍓 ' + tag.name : tag.name}</strong>
					<br/>
					{tag.wifi ? (
						<span style={{ color: '#f0abfc', fontSize: '11px', fontWeight: 'bold' }}>
							📶 {tag.wifi.rssi || tag.wifi.rssi_dbm} dBm | 📏 {tag.wifi.distance_meters}m
						</span>
					) : (
						<span style={{ color: tag.battery < 20 ? '#ef4444' : '#10b981'}}>⚡ {tag.battery}%</span>
					)}
				</div>
			</Html>
		</group>
	);
};
const ReceiverPi = ({ label, lat, lon, elev }) => {
	const pos = gpsToLocal(lat, lon, elev);
	return (
		<mesh position={pos} castShadow>
			<boxGeometry args={[0.6, 0.6, 0.6]} />
			<meshStandardMaterial color="#f97316" emissive="#f97316" emissiveIntensity={0.2} metalness={0.4} roughness={0.2} />
			<Html distanceFactor={20} center position={[0, 1.2, 0]} zIndexRange={[100, 0]}>
				<div style={{ background: 'rgba(249, 115, 22, 0.9)', padding: '2px 8px', borderRadius: '4px', fontWeight: 'bold', color: 'white', border: '1px solid white', textShadow: '0 1px 2px rgba(0,0,0,0.5)' }}>
					📍 {label}
				</div>
			</Html>
		</mesh>
	)
}
const IndustrialShelving = ({ position, width, height, depth, levels }) => {
	const boxes = useMemo(() => {
		const generated = [];
		for (let l = 1; l < levels; l++) { 
			const yOffset = (height / levels) * l + 0.1; 
			const numBoxes = Math.floor(depth * 1.5); 
			for (let i = 0; i < numBoxes; i++) {
				const boxW = 0.6 + Math.random() * 0.8;
				const boxH = 0.4 + Math.random() * 0.7;
				const boxD = 0.6 + Math.random() * 0.8;
				const px = (Math.random() - 0.5) * (width - 1.5);
				const pz = (Math.random() - 0.5) * (depth - 1.5);
				generated.push({ px, pz, py: yOffset + (boxH / 2.0), boxW, boxH, boxD });
			}
		}
		return generated;
	}, [width, height, depth, levels]);
	return (
		<group position={position}>
			<mesh position={[-width/2 + 0.1, 0, -depth/2 + 0.1]} castShadow><boxGeometry args={[0.3, height, 0.3]} /><meshStandardMaterial color="#0ea5e9"/></mesh>
			<mesh position={[width/2 - 0.1, 0, -depth/2 + 0.1]} castShadow><boxGeometry args={[0.3, height, 0.3]} /><meshStandardMaterial color="#0ea5e9"/></mesh>
			<mesh position={[-width/2 + 0.1, 0, depth/2 - 0.1]} castShadow><boxGeometry args={[0.3, height, 0.3]} /><meshStandardMaterial color="#0ea5e9"/></mesh>
			<mesh position={[width/2 - 0.1, 0, depth/2 - 0.1]} castShadow><boxGeometry args={[0.3, height, 0.3]} /><meshStandardMaterial color="#0ea5e9"/></mesh>
			<mesh position={[-width/2 + 0.1, 0, 0]} castShadow><boxGeometry args={[0.3, height, 0.3]} /><meshStandardMaterial color="#0ea5e9"/></mesh>
			<mesh position={[width/2 - 0.1, 0, 0]} castShadow><boxGeometry args={[0.3, height, 0.3]} /><meshStandardMaterial color="#0ea5e9"/></mesh>
			{Array.from({ length: levels }).map((_, l) => {
				const yOff = (height / levels) * l - (height/2);
				return (
					<mesh key={l} position={[0, yOff, 0]} castShadow receiveShadow>
						<boxGeometry args={[width, 0.15, depth]} />
						<meshStandardMaterial color="#0ea5e9" metalness={0.4} roughness={0.6} />
					</mesh>
				)
			})}
			{boxes.map((b, i) => (
				<mesh key={i} position={[b.px, b.py - (height/2.0), b.pz]} castShadow receiveShadow>
					<boxGeometry args={[b.boxW, b.boxH, b.boxD]} />
					<meshStandardMaterial color="#d68d59" roughness={0.9} /> 
				</mesh>
			))}
		</group>
	);
};
const WarehouseInterior = () => {
	return (
		<group>
			<Box args={[30, 8, 1]} position={[0, 4, -15]} castShadow receiveShadow><meshStandardMaterial color="#e2e8f0" metalness={0.1} roughness={0.9} /></Box>
			<Box args={[30, 8, 1]} position={[0, 4, 15]} castShadow receiveShadow><meshStandardMaterial color="#e2e8f0" metalness={0.1} roughness={0.9} /></Box>
			<Box args={[1, 8, 30]} position={[-15, 4, 0]} castShadow receiveShadow><meshStandardMaterial color="#e2e8f0" metalness={0.1} roughness={0.9} /></Box>
			<Box args={[1, 8, 30]} position={[15, 4, 0]} castShadow receiveShadow><meshStandardMaterial color="#e2e8f0" metalness={0.1} roughness={0.9} /></Box>
			<IndustrialShelving position={[-5, 1.75, 0]} width={6} height={3.5} depth={20} levels={3} />
			<IndustrialShelving position={[5, 1.75, 0]} width={6} height={3.5} depth={20} levels={3} />
			<Box args={[1.5, 0.3, 1.5]} position={[-12, 0.15, -8]} castShadow><meshStandardMaterial color="#fbbf24" roughness={0.8} /></Box>
			<Box args={[1.5, 0.3, 1.5]} position={[0, 0.15, 10]} castShadow><meshStandardMaterial color="#fbbf24" roughness={0.8} /></Box>
			<Box args={[30, 0.4, 15]} position={[0, 3.8, -7.5]} castShadow receiveShadow>
				<meshStandardMaterial color="#475569" roughness={0.8} metalness={0.6} />
			</Box>
			<IndustrialShelving position={[-5, 4.0 + 1.25, -5]} width={6} height={2.5} depth={10} levels={2} />
			<IndustrialShelving position={[5, 4.0 + 1.25, -5]} width={6} height={2.5} depth={10} levels={2} />
			<mesh position={[12, 2.0, 4]} rotation={[Math.atan(4/8), 0, 0]} castShadow receiveShadow>
				<boxGeometry args={[4, 0.4, 8.94]} />
				<meshStandardMaterial color="#f59e0b" roughness={0.9} /> 
			</mesh>
			<mesh position={[-14, 1.9, -0.5]} castShadow><boxGeometry args={[0.5, 3.8, 0.5]} /><meshStandardMaterial color="#1e293b" /></mesh>
			<mesh position={[-5, 1.9, -0.5]} castShadow><boxGeometry args={[0.5, 3.8, 0.5]} /><meshStandardMaterial color="#1e293b" /></mesh>
			<mesh position={[5, 1.9, -0.5]} castShadow><boxGeometry args={[0.5, 3.8, 0.5]} /><meshStandardMaterial color="#1e293b" /></mesh>
			<mesh position={[14, 1.9, -0.5]} castShadow><boxGeometry args={[0.5, 3.8, 0.5]} /><meshStandardMaterial color="#1e293b" /></mesh>
			<Box args={[30, 0.1, 0.1]} position={[0, 4.4, -0.2]} castShadow><meshStandardMaterial color="#facc15" /></Box>
			<Box args={[0.1, 0.6, 0.1]} position={[-14.5, 4.1, -0.2]} castShadow><meshStandardMaterial color="#facc15" /></Box>
			<Box args={[0.1, 0.6, 0.1]} position={[-10, 4.1, -0.2]} castShadow><meshStandardMaterial color="#facc15" /></Box>
			<Box args={[0.1, 0.6, 0.1]} position={[-5, 4.1, -0.2]} castShadow><meshStandardMaterial color="#facc15" /></Box>
			<Box args={[0.1, 0.6, 0.1]} position={[0, 4.1, -0.2]} castShadow><meshStandardMaterial color="#facc15" /></Box>
			<Box args={[0.1, 0.6, 0.1]} position={[5, 4.1, -0.2]} castShadow><meshStandardMaterial color="#facc15" /></Box>
			<Box args={[0.1, 0.6, 0.1]} position={[9, 4.1, -0.2]} castShadow><meshStandardMaterial color="#facc15" /></Box>
		</group>
	)
}
function App() {
  const [isConnected, setIsConnected] = useState(false);
  const [tagCount, setTagCount] = useState(0);
  const [globalTags, setGlobalTags] = useState({});
  const [navTarget, setNavTarget] = useState("");
  const [dbStats, setDbStats] = useState({ total_history_records: 0, db_status: 'INITIALIZING' });
  const [recentAlert, setRecentAlert] = useState(null);
  const socketRef = useRef(null);

  useEffect(() => {
	socketRef.current = io(SOCKET_URL);
	socketRef.current.on('connect', () => setIsConnected(true));
	socketRef.current.on('disconnect', () => setIsConnected(false));
	socketRef.current.on('initial_state', (allTags) => {
	  setGlobalTags(allTags);
	  setTagCount(Object.keys(allTags).length);
	});
	socketRef.current.on('location_update', (tagData) => {
	  setGlobalTags(prev => ({
		...prev,
		[tagData.tagId]: tagData
	  }));
	});
	socketRef.current.on('system_alert', (alert) => {
	  setRecentAlert(alert);
	  setTimeout(() => setRecentAlert(null), 6000);
	});

	// Poll database analytics every 4 seconds
	const fetchAnalytics = async () => {
	  try {
		const res = await fetch(`${SOCKET_URL}/api/analytics`);
		if (res.ok) {
		  const data = await res.json();
		  setDbStats(data);
		}
	  } catch (e) {
		// Server might not have responded yet
	  }
	};
	fetchAnalytics();
	const interval = setInterval(fetchAnalytics, 4000);

	return () => {
	  clearInterval(interval);
	  if (socketRef.current) socketRef.current.disconnect();
	};
  }, []);

  return (
	<>
	  <div className="hud-overlay" style={{ zIndex: 10 }}>
		<div className="hud-header">
		  <h1>Three.js Warehouse VR</h1>
		  <div className={`status-badge ${isConnected ? 'connected' : 'disconnected'}`}>
			<div className="status-dot"></div>
			{isConnected ? 'LIVE' : 'OFFLINE'}
		  </div>
		</div>
		<div className="info-row">
		  <span className="info-label">Active UWB Tags</span>
		  <span className="info-value">{tagCount}</span>
		</div>
		<div className="info-row" style={{ marginTop: '6px' }}>
		  <span className="info-label">SQLite Database</span>
		  <span className="info-value" style={{ color: '#38bdf8', fontSize: '0.85rem' }}>
			{dbStats.total_history_records ? `💾 ${dbStats.total_history_records} logs` : '💾 WAL Ready'}
		  </span>
		</div>
		<div className="info-row" style={{ marginTop: '10px' }}>
		  <span className="info-label">Navigator Target</span>
		  <select 
			value={navTarget}
			style={{background: 'rgba(15, 23, 42, 0.8)', color: 'white', border: '1px solid rgba(74, 222, 128, 0.7)', borderRadius: '4px', padding: '4px 6px'}}
			onChange={(e) => setNavTarget(e.target.value)}
		  >
			<option value="">-- No Target (Free Roam) --</option>
			{Object.values(globalTags).map(t => <option key={t.tagId} value={t.tagId}>{t.name}</option>)}
		  </select>
		</div>
		{recentAlert && (
		  <div style={{ marginTop: '10px', background: 'rgba(239, 68, 68, 0.9)', color: 'white', padding: '6px 10px', borderRadius: '6px', fontSize: '0.8rem', fontWeight: 'bold', border: '1px solid #f87171', animation: 'pulse 1.5s infinite' }}>
			⚠️ ALERT: [{recentAlert.tagId}] {recentAlert.message}
		  </div>
		)}
		<p style={{fontSize: '0.82rem', color: 'var(--text-muted)', marginTop: '15px'}}>
		  <strong>CONTROLS:</strong> Click the screen to interact. Use <kbd style={{background: '#334155', padding: '2px 4px', borderRadius: '4px'}}>W</kbd> <kbd style={{background: '#334155', padding: '2px 4px', borderRadius: '4px'}}>A</kbd> <kbd style={{background: '#334155', padding: '2px 4px', borderRadius: '4px'}}>S</kbd> <kbd style={{background: '#334155', padding: '2px 4px', borderRadius: '4px'}}>D</kbd> to drive the Mover Entity.
		</p>
	  </div>
	  <div className="telemetry-panel" style={{ zIndex: 10 }}>
		<h3>Real-time Arrays</h3>
		<div className="telemetry-tag-card" style={{ borderColor: 'rgba(74, 222, 128, 0.5)', borderWidth: '2px', borderStyle: 'solid', background: 'rgba(20, 83, 45, 0.3)' }}>
		  <div className="telemetry-tag-header">
			<span style={{ color: '#4ade80' }}>👤 Local Mover Nav</span>
			<span style={{fontSize: '0.75rem', background: '#22c55e', color: 'white', padding: '2px 6px', borderRadius: '4px'}}>PHYSICS ENABLED</span>
		  </div>
		  <div className="telemetry-tag-dist"><span style={{color: '#94a3b8'}}>Navigator Target:</span> <span style={{color: 'white', fontWeight: 'bold'}}>{navTarget ? globalTags[navTarget]?.name || "Searching..." : "None"}</span></div>
		  <div className="telemetry-tag-dist" style={{marginTop: '4px'}}><span style={{color: '#94a3b8'}}>Distance to Target:</span> <span id="mover-target-dist" style={{color: '#4ade80', fontWeight: 'bold', fontSize: '1.2rem'}}>--</span></div>
		</div>
		{Object.values(globalTags).map((tag) => (
		  <div key={tag.tagId} className="telemetry-tag-card" style={{ 
			border: navTarget === tag.tagId ? '2px solid #38bdf8' : (tag.wifi ? '1px solid #c026d3' : 'none'),
			background: tag.wifi ? 'rgba(88, 28, 135, 0.25)' : undefined
		  }}>
			<div className="telemetry-tag-header">
			  <span>{tag.wifi ? '🍓 ' + tag.name : tag.name}</span>
			  {tag.wifi ? (
				<span style={{fontSize: '0.75rem', background: '#9333ea', color: 'white', padding: '2px 6px', borderRadius: '4px', fontWeight: 'bold'}}>WI-FI RTLS</span>
			  ) : (
				<span style={{fontSize: '0.8rem', color: tag.battery < 20 ? '#ef4444' : '#10b981'}}>⚡ {tag.battery}%</span>
			  )}
			</div>
			<div style={{ fontSize: '0.75rem', color: '#38bdf8', marginBottom: '4px', display: 'flex', alignItems: 'center', gap: '4px' }}>
			  <span>📍 Zone:</span>
			  <span style={{ fontWeight: 'bold', color: '#7dd3fc' }}>{tag.zone || 'General Floor'}</span>
			</div>
			{tag.wifi && (
			  <div style={{ margin: '6px 0', padding: '6px 8px', background: 'rgba(15, 23, 42, 0.6)', borderRadius: '6px', borderLeft: '3px solid #c026d3' }}>
				<div className="telemetry-tag-dist" style={{ color: '#e9d5ff' }}><span>Live RSSI:</span><span style={{ fontWeight: 'bold', color: '#f0abfc' }}>{tag.wifi.rssi || tag.wifi.rssi_dbm} dBm</span></div>
				<div className="telemetry-tag-dist" style={{ color: '#4ade80' }}><span>Calculated Distance:</span><span style={{ fontWeight: 'bold', fontSize: '1.1rem', color: '#4ade80' }}>{tag.wifi.distance_meters} m</span></div>
				{tag.wifi.ssid && <div className="telemetry-tag-dist" style={{ fontSize: '0.75rem', color: '#94a3b8' }}><span>Wi-Fi SSID:</span><span>{tag.wifi.ssid}</span></div>}
			  </div>
			)}
			{tag.distances ? (
			  <>
				<div className="telemetry-tag-dist"><span>Distance to R1:</span><span>{tag.distances.R1}m</span></div>
				<div className="telemetry-tag-dist"><span>Distance to R2:</span><span>{tag.distances.R2}m</span></div>
				<div className="telemetry-tag-dist"><span>Distance to R3:</span><span>{tag.distances.R3}m</span></div>
				<div className="telemetry-tag-dist"><span>Distance to R4:</span><span>{tag.distances.R4}m</span></div>
			  </>
			) : (
				<div className="telemetry-tag-dist">Calculating...</div>
			)}
		  </div>
		))}
	  </div>
	  <div className="map-container" style={{ position: 'absolute', top: 0, left: 0, width: '100%', height: '100%', pointerEvents: 'auto' }}>
		<Canvas shadows camera={{ position: [15, 12, 18], fov: 50 }}>
			<color attach="background" args={['#f8fafc']} />
			<fog attach="fog" args={['#f8fafc', 25, 80]} />
			<ambientLight intensity={0.7} />
			<spotLight position={[10, 25, 10]} angle={0.8} penumbra={1} castShadow intensity={2.0} shadow-mapSize={1024} />
			<directionalLight position={[-15, 20, -15]} intensity={1.0} />
			<Grid infiniteGrid fadeDistance={50} cellColor={'#cbd5e1'} sectionColor={'#94a3b8'} />
			<mesh rotation={[-Math.PI/2, 0, 0]} position={[0, -0.01, 0]} receiveShadow>
				<planeGeometry args={[100, 100]} />
				<meshStandardMaterial color="#64748b" roughness={0.4} metalness={0.1} />
			</mesh>
			<WarehouseInterior />
			<ReceiverPi label="Pi-1 (G-NW)" lat={43.861635} lon={-78.947087} elev={0} />
			<ReceiverPi label="Pi-2 (G-NE)" lat={43.861635} lon={-78.946712} elev={0} />
			<ReceiverPi label="Pi-3 (L2-SW)" lat={43.861365} lon={-78.947087} elev={4.0} />
			<ReceiverPi label="Pi-4 (L2-SE)" lat={43.861365} lon={-78.946712} elev={4.0} />
			<PlayerMover targetId={navTarget} allTags={globalTags} />
			{Object.values(globalTags).map(tag => <UwbTag key={tag.tagId} tag={tag} />)}
			<OrbitControls makeDefault maxPolarAngle={Math.PI / 2 - 0.05} minDistance={2} maxDistance={40} />
		</Canvas>
	  </div>
	</>
  );
}
export default App;