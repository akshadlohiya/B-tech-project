import React, { useEffect, useRef, useState, useMemo } from 'react';
import { io } from 'socket.io-client';
import { Canvas, useFrame } from '@react-three/fiber';
import { OrbitControls, Html, Box, Grid, Line, TransformControls } from '@react-three/drei';
import * as THREE from 'three';
import './index.css';
const SOCKET_URL = 'http://localhost:3000';

// ---- Unity-style scene editor: default positions/rotations of movable warehouse objects ----
const LAYOUT_STORAGE_KEY = 'warehouse-layout-v1';
const MAPS_STORAGE_KEY = 'warehouse-maps-v1';
const DEFAULT_LAYOUT = {
	shelfA:  { position: [-5, 1.75, 0],       rotation: [0, 0, 0], label: 'Shelf A (Ground)' },
	shelfB:  { position: [5, 1.75, 0],        rotation: [0, 0, 0], label: 'Shelf B (Ground)' },
	shelfA2: { position: [-5, 5.25, -5],      rotation: [0, 0, 0], label: 'Shelf A (Mezzanine)' },
	shelfB2: { position: [5, 5.25, -5],       rotation: [0, 0, 0], label: 'Shelf B (Mezzanine)' },
	dock1:   { position: [-12, 0.15, -8],     rotation: [0, 0, 0], label: 'Dock Marker 1' },
	dock2:   { position: [0, 0.15, 10],       rotation: [0, 0, 0], label: 'Dock Marker 2' },
	mezzanine: { position: [0, 3.8, -7.5],    rotation: [0, 0, 0], label: 'Mezzanine Floor' },
	ramp:    { position: [12, 2.0, 4],        rotation: [Math.atan(4 / 8), 0, 0], label: 'Ramp' },
};
const loadLayout = () => {
	try {
		const raw = localStorage.getItem(LAYOUT_STORAGE_KEY);
		if (!raw) return DEFAULT_LAYOUT;
		const parsed = JSON.parse(raw);
		// Keep built-in objects and any runtime-created objects from previous sessions.
		const merged = { ...parsed };
		Object.keys(DEFAULT_LAYOUT).forEach(id => {
			merged[id] = parsed[id] ? { ...DEFAULT_LAYOUT[id], ...parsed[id] } : DEFAULT_LAYOUT[id];
		});
		return merged;
	} catch {
		return DEFAULT_LAYOUT;
	}
};
const loadMaps = () => {
	try {
		const savedMaps = localStorage.getItem(MAPS_STORAGE_KEY);
		if (savedMaps) {
			const parsed = JSON.parse(savedMaps);
			if (parsed && typeof parsed === 'object' && Object.keys(parsed).length > 0) return parsed;
		}
		return {
			warehouse: { name: 'Warehouse Layout', layout: loadLayout(), updatedAt: Date.now() },
		};
	} catch {
		return { warehouse: { name: 'Warehouse Layout', layout: DEFAULT_LAYOUT, updatedAt: Date.now() } };
	}
};
const saveMaps = (maps) => {
	try { localStorage.setItem(MAPS_STORAGE_KEY, JSON.stringify(maps)); } catch {}
};
const INITIAL_MAPS = loadMaps();
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
const PlayerMover = ({ targetId, allTags, frozen, rampTransform }) => {
	const keys = useKeyboard();
	const posRef = useRef(new THREE.Vector3(0, 0.5, 0));
	const meshRef = useRef();
	const lineRef = useRef();
	useFrame((state, delta) => {
		if (frozen) return; // paused while the scene editor is active
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
		const hitWallX = hitOuterWall || hitLeft || hitRight;
		if (!hitWallX) posRef.current.x = nx;
		let hitGuardRail = false;
		if (posRef.current.z <= 0 && posRef.current.y > 2.0 && nz > 0) {
			if (posRef.current.x <= 10 || posRef.current.x >= 14) hitGuardRail = true;
		}
		const hitWallZ = hitOuterWall || hitLeft || hitRight || hitGuardRail;
		if (!hitWallZ) posRef.current.z = nz;

		// Sample the edited ramp surface in its local coordinates so its position
		// and rotation in the scene editor also control the mover's climbable area.
		const rampPosition = new THREE.Vector3(...rampTransform.position);
		const rampQuaternion = new THREE.Quaternion().setFromEuler(new THREE.Euler(...rampTransform.rotation));
		const inverseRampQuaternion = rampQuaternion.clone().invert();
		const rampLocalPoint = new THREE.Vector3(posRef.current.x, rampPosition.y, posRef.current.z)
			.sub(rampPosition)
			.applyQuaternion(inverseRampQuaternion);
		const rampHalfWidth = 2;
		const rampHalfLength = 8.94 / 2;
		if (Math.abs(rampLocalPoint.x) <= rampHalfWidth && Math.abs(rampLocalPoint.z) <= rampHalfLength) {
			const rampSurface = new THREE.Vector3(rampLocalPoint.x, 0, rampLocalPoint.z)
				.applyQuaternion(rampQuaternion)
				.add(rampPosition);
			posRef.current.y = rampSurface.y + 0.5;
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
const UwbTag = ({ tag, positionOverride }) => {
	const targetPos = positionOverride || gpsToLocal(tag.lat, tag.lon, tag.elev);
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
			<Html distanceFactor={18} center position={[0, 1.6, 0]} className="r3f-html-label" zIndexRange={[100, 0]}>
				<div style={{ background: 'rgba(15, 23, 42, 0.85)', border: '1px solid rgba(56, 189, 248, 0.5)', padding: '4px 10px', borderRadius: '6px', textAlign: 'center', whiteSpace: 'nowrap', color: 'white', fontSize: '13px', backdropFilter: 'blur(4px)' }}>
					<strong>{tag.name}</strong>
					<br/>
					<span style={{ color: tag.battery < 20 ? '#ef4444' : '#10b981'}}>⚡ {tag.battery}%</span>
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
// Wraps a movable warehouse object so it can be clicked, selected, and driven by TransformControls.
// Position/rotation are applied imperatively to the underlying Object3D (not via React props) so that
// dragging the gizmo doesn't fight with React's render cycle. `registerRef` hands the live Object3D
// back up to <App> so it can be passed into <TransformControls object={...}>.
const Selectable = ({ id, layout, editMode, selectedId, onSelect, registerRef, children }) => {
	const groupRef = useRef();
	useEffect(() => {
		if (groupRef.current) {
			registerRef(id, groupRef.current);
			const { position, rotation } = layout[id];
			groupRef.current.position.set(...position);
			groupRef.current.rotation.set(...(rotation || [0, 0, 0]));
		}
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, []);
	const isSelected = editMode && selectedId === id;
	return (
		<group
			ref={groupRef}
			onClick={(e) => { if (editMode) { e.stopPropagation(); onSelect(id); } }}
			onPointerOver={(e) => { if (editMode) { e.stopPropagation(); document.body.style.cursor = 'pointer'; } }}
			onPointerOut={() => { document.body.style.cursor = 'auto'; }}
		>
			{children}
			{isSelected && (
				<Html distanceFactor={20} center position={[0, 3, 0]} zIndexRange={[200, 0]}>
					<div style={{ background: '#22c55e', color: 'white', padding: '2px 8px', borderRadius: '4px', fontSize: '11px', fontWeight: 'bold', whiteSpace: 'nowrap', border: '1px solid white' }}>
						✥ {layout[id].label}
					</div>
				</Html>
			)}
		</group>
	);
};
const RuntimeObject = ({ id, object, layout, editMode, selectedId, onSelect, registerRef }) => (
	<Selectable id={id} layout={layout} editMode={editMode} selectedId={selectedId} onSelect={onSelect} registerRef={registerRef}>
		{object.type === 'anchor' ? (
			<group>
				<mesh position={[0, 0.3, 0]} castShadow>
					<cylinderGeometry args={[0.35, 0.35, 0.6, 20]} />
					<meshStandardMaterial color="#f97316" emissive="#7c2d12" emissiveIntensity={0.35} />
				</mesh>
				{selectedId === id && <mesh position={[0, 0.3, 0]}>
					<sphereGeometry args={[object.radius || 5, 32, 20]} />
					<meshBasicMaterial color="#fb923c" transparent opacity={0.16} wireframe depthWrite={false} />
				</mesh>}
			</group>
		) : object.type === 'shelf' ? (
			<IndustrialShelving
				position={[0, 0, 0]}
				width={object.width}
				height={object.height}
				depth={object.depth}
				levels={object.levels}
			/>
		) : (
			<Box args={[object.width, object.height, object.depth]} castShadow receiveShadow>
				<meshStandardMaterial color={object.type === 'floor' ? '#64748b' : '#c08457'} roughness={0.85} />
			</Box>
		)}
	</Selectable>
);
const RuntimeEntity = ({ id, object, layout, editMode, selectedId, onSelect, registerRef, targetId, allTags, rampTransform }) => {
	const entityNames = { mover: 'Mover', forklift: 'Forklift', employee: 'Employee 1', drone: 'Drone Transport', pallet: 'Pallet Jack' };
	const entityType = object.entityType || object.type;
	const entityName = object.entityName || entityNames[entityType] || object.label;
	const liveTag = Object.values(allTags).find(tag => tag.name === entityName);
	const livePosition = liveTag ? gpsToLocal(liveTag.lat, liveTag.lon, liveTag.elev) : object.position;
	const localLivePosition = livePosition.map((value, index) => value - object.position[index]);
	const displayTag = liveTag || { name: entityName, battery: 100 };
	return (
	<Selectable id={id} layout={layout} editMode={editMode} selectedId={selectedId} onSelect={onSelect} registerRef={registerRef}>
		{entityType === 'mover' && <PlayerMover targetId={targetId} allTags={allTags} frozen={editMode} rampTransform={rampTransform} />}
		{entityType !== 'mover' && <UwbTag tag={displayTag} positionOverride={localLivePosition} />}
	</Selectable>
)};
const WarehouseInterior = ({ layout, editMode, selectedId, onSelect, registerRef, targetId, allTags }) => {
	const hasObject = (id) => Boolean(layout[id]);
	const isEmptyMap = Object.keys(layout).length === 0;
	return (
		<group>
			{/* Outer walls are fixed — WASD collision logic in PlayerMover is hardcoded to these bounds */}
			<Box args={[30, 8, 1]} position={[0, 4, -15]} castShadow receiveShadow><meshStandardMaterial color="#e2e8f0" metalness={0.1} roughness={0.9} /></Box>
			<Box args={[30, 8, 1]} position={[0, 4, 15]} castShadow receiveShadow><meshStandardMaterial color="#e2e8f0" metalness={0.1} roughness={0.9} /></Box>
			<Box args={[1, 8, 30]} position={[-15, 4, 0]} castShadow receiveShadow><meshStandardMaterial color="#e2e8f0" metalness={0.1} roughness={0.9} /></Box>
			<Box args={[1, 8, 30]} position={[15, 4, 0]} castShadow receiveShadow><meshStandardMaterial color="#e2e8f0" metalness={0.1} roughness={0.9} /></Box>

			{/* Movable objects, each wrapped in <Selectable> */}
			{hasObject('shelfA') && <Selectable id="shelfA" layout={layout} editMode={editMode} selectedId={selectedId} onSelect={onSelect} registerRef={registerRef}>
				<IndustrialShelving position={[0, 0, 0]} width={6} height={3.5} depth={20} levels={3} />
			</Selectable>}
			{hasObject('shelfB') && <Selectable id="shelfB" layout={layout} editMode={editMode} selectedId={selectedId} onSelect={onSelect} registerRef={registerRef}>
				<IndustrialShelving position={[0, 0, 0]} width={6} height={3.5} depth={20} levels={3} />
			</Selectable>}
			{hasObject('dock1') && <Selectable id="dock1" layout={layout} editMode={editMode} selectedId={selectedId} onSelect={onSelect} registerRef={registerRef}>
				<Box args={[1.5, 0.3, 1.5]} castShadow><meshStandardMaterial color="#fbbf24" roughness={0.8} /></Box>
			</Selectable>}
			{hasObject('dock2') && <Selectable id="dock2" layout={layout} editMode={editMode} selectedId={selectedId} onSelect={onSelect} registerRef={registerRef}>
				<Box args={[1.5, 0.3, 1.5]} castShadow><meshStandardMaterial color="#fbbf24" roughness={0.8} /></Box>
			</Selectable>}
			{hasObject('mezzanine') && <Selectable id="mezzanine" layout={layout} editMode={editMode} selectedId={selectedId} onSelect={onSelect} registerRef={registerRef}>
				<Box args={[30, 0.4, 15]} castShadow receiveShadow>
					<meshStandardMaterial color="#475569" roughness={0.8} metalness={0.6} />
				</Box>
			</Selectable>}
			{hasObject('shelfA2') && <Selectable id="shelfA2" layout={layout} editMode={editMode} selectedId={selectedId} onSelect={onSelect} registerRef={registerRef}>
				<IndustrialShelving position={[0, 0, 0]} width={6} height={2.5} depth={10} levels={2} />
			</Selectable>}
			{hasObject('shelfB2') && <Selectable id="shelfB2" layout={layout} editMode={editMode} selectedId={selectedId} onSelect={onSelect} registerRef={registerRef}>
				<IndustrialShelving position={[0, 0, 0]} width={6} height={2.5} depth={10} levels={2} />
			</Selectable>}
			{hasObject('ramp') && <Selectable id="ramp" layout={layout} editMode={editMode} selectedId={selectedId} onSelect={onSelect} registerRef={registerRef}>
				<mesh castShadow receiveShadow>
					<boxGeometry args={[4, 0.4, 8.94]} />
					<meshStandardMaterial color="#f59e0b" roughness={0.9} />
				</mesh>
			</Selectable>}
			{Object.entries(layout)
				.filter(([id, object]) => !DEFAULT_LAYOUT[id] && ['shelf', 'floor', 'box', 'anchor'].includes(object.type))
				.map(([id, object]) => (
					<RuntimeObject key={id} id={id} object={object} layout={layout} editMode={editMode} selectedId={selectedId} onSelect={onSelect} registerRef={registerRef} />
				))}
			{Object.entries(layout)
				.filter(([id, object]) => !DEFAULT_LAYOUT[id] && (object.type === 'entity' || ['mover', 'forklift', 'employee', 'drone', 'pallet'].includes(object.entityType || object.type)))
				.map(([id, object]) => <RuntimeEntity key={id} id={id} object={object} layout={layout} editMode={editMode} selectedId={selectedId} onSelect={onSelect} registerRef={registerRef} targetId={targetId} allTags={allTags} rampTransform={layout.ramp || DEFAULT_LAYOUT.ramp} />)}

			{/* Fixed decoration belongs to populated warehouse maps, not empty room maps. */}
			{!isEmptyMap && <>
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
			</>}
		</group>
	)
}
function App() {
  const [isConnected, setIsConnected] = useState(false);
  const [tagCount, setTagCount] = useState(0);
  const [globalTags, setGlobalTags] = useState({});
  const [navTarget, setNavTarget] = useState("");
  const socketRef = useRef(null);

  // ---- Unity-style scene editor state ----
  const [editMode, setEditMode] = useState(false);
	const [maps, setMaps] = useState(INITIAL_MAPS);
	const [activeMapId, setActiveMapId] = useState(Object.keys(INITIAL_MAPS)[0]);
	const [layout, setLayout] = useState(INITIAL_MAPS[Object.keys(INITIAL_MAPS)[0]].layout);
  const [selectedId, setSelectedId] = useState(null);
	const [showAddMenu, setShowAddMenu] = useState(false);
  const [gizmoMode, setGizmoMode] = useState('translate'); // 'translate' | 'rotate'
  const [orbitEnabled, setOrbitEnabled] = useState(true);
  const objectRefs = useRef({});
	const mapFileInputRef = useRef(null);
  const registerRef = (id, obj) => { objectRefs.current[id] = obj; };

  const commitLayout = (nextLayout) => {
	  setLayout(nextLayout);
	  setMaps(prev => {
		const nextMaps = {
			...prev,
			[activeMapId]: { ...prev[activeMapId], layout: nextLayout, updatedAt: Date.now() },
		};
		saveMaps(nextMaps);
		return nextMaps;
	  });
  };

  const switchMap = (mapId) => {
	  if (!maps[mapId]) return;
	  setActiveMapId(mapId);
	  setLayout(maps[mapId].layout);
	  setSelectedId(null);
	  setShowAddMenu(false);
	  objectRefs.current = {};
  };

  const createMap = () => {
	  const mapId = `map-${Date.now()}`;
	  const nextMaps = {
		...maps,
			[mapId]: { name: `New Map ${Object.keys(maps).length}`, layout: {}, updatedAt: Date.now() },
	  };
	  setMaps(nextMaps);
	  saveMaps(nextMaps);
	  setActiveMapId(mapId);
	  setLayout(nextMaps[mapId].layout);
	  setSelectedId(null);
	  objectRefs.current = {};
  };

  const duplicateMap = () => {
	  const mapId = `map-${Date.now()}`;
	  const nextMaps = {
		...maps,
		[mapId]: { name: `${maps[activeMapId].name} Copy`, layout: structuredClone(layout), updatedAt: Date.now() },
	  };
	  setMaps(nextMaps);
	  saveMaps(nextMaps);
	  setActiveMapId(mapId);
  };

  const renameActiveMap = () => {
	  const name = window.prompt('Map name', maps[activeMapId].name);
	  if (!name?.trim()) return;
	  const nextMaps = { ...maps, [activeMapId]: { ...maps[activeMapId], name: name.trim(), updatedAt: Date.now() } };
	  setMaps(nextMaps);
	  saveMaps(nextMaps);
  };

  const deleteActiveMap = () => {
	  if (Object.keys(maps).length === 1) return;
	  const nextMaps = { ...maps };
	  delete nextMaps[activeMapId];
	  const nextMapId = Object.keys(nextMaps)[0];
	  setMaps(nextMaps);
	  saveMaps(nextMaps);
	  setActiveMapId(nextMapId);
	  setLayout(nextMaps[nextMapId].layout);
	  setSelectedId(null);
	  objectRefs.current = {};
  };

  const exportMaps = () => {
	  const file = new Blob([JSON.stringify({ version: 1, exportedAt: new Date().toISOString(), maps }, null, 2)], { type: 'application/json' });
	  const url = URL.createObjectURL(file);
	  const link = document.createElement('a');
	  link.href = url;
	  link.download = 'warehouse-maps.json';
	  link.click();
	  URL.revokeObjectURL(url);
  };

  const importMaps = (event) => {
	  const file = event.target.files?.[0];
	  if (!file) return;
	  const reader = new FileReader();
	  reader.onload = () => {
		try {
		  const parsed = JSON.parse(reader.result);
		  const importedMaps = parsed.maps || parsed;
		  if (!importedMaps || typeof importedMaps !== 'object' || Object.keys(importedMaps).length === 0) throw new Error('Invalid map file');
		  const nextMapId = Object.keys(importedMaps)[0];
		  setMaps(importedMaps);
		  saveMaps(importedMaps);
		  setActiveMapId(nextMapId);
		  setLayout(importedMaps[nextMapId].layout || {});
		  setSelectedId(null);
		  objectRefs.current = {};
		} catch {
		  window.alert('Could not import this map file. Please select a warehouse-maps.json file.');
		}
		if (mapFileInputRef.current) mapFileInputRef.current.value = '';
	  };
	  reader.readAsText(file);
  };

  const syncSelectedToState = () => {
    const obj = objectRefs.current[selectedId];
    if (!obj) return;
	const next = {
		...layout,
        [selectedId]: {
			...layout[selectedId],
          position: [obj.position.x, obj.position.y, obj.position.z],
          rotation: [obj.rotation.x, obj.rotation.y, obj.rotation.z],
        },
      };
	commitLayout(next);
  };

	const updateSelectedTransform = (property, axis, value) => {
		if (!selectedId || !Number.isFinite(value)) return;
		const obj = objectRefs.current[selectedId];
		if (!obj) return;
		const nextValue = property === 'rotation' ? THREE.MathUtils.degToRad(value) : value;
		obj[property][axis] = nextValue;
		const next = {
			...layout,
			[selectedId]: {
				...layout[selectedId],
				position: [obj.position.x, obj.position.y, obj.position.z],
				rotation: [obj.rotation.x, obj.rotation.y, obj.rotation.z],
			},
		};
		commitLayout(next);
	};

	const updateSelectedProperty = (property, value) => {
		if (!selectedId || !Number.isFinite(value) || value <= 0 || DEFAULT_LAYOUT[selectedId]) return;
		commitLayout({ ...layout, [selectedId]: { ...layout[selectedId], [property]: value } });
	};

	const renameSelectedObject = (name) => {
		if (!selectedId || !name.trim()) return;
		commitLayout({ ...layout, [selectedId]: { ...layout[selectedId], label: name } });
	};

	  const selectObject = (id) => setSelectedId(id);
	  const selectedLiveTag = selectedId && layout[selectedId]?.type === 'entity'
		? Object.values(globalTags).find(tag => tag.name === layout[selectedId].entityName)
		: null;

	const addRuntimeObject = (type) => {
		const id = `${type}-${Date.now()}`;
		const entityNames = { forklift: 'Forklift', employee: 'Employee 1', drone: 'Drone Transport', pallet: 'Pallet Jack' };
		const entityName = entityNames[type] || 'Mover';
		const liveTag = Object.values(globalTags).find(tag => tag.name === entityName);
		const entityPosition = liveTag ? gpsToLocal(liveTag.lat, liveTag.lon, liveTag.elev) : [0, 0.75, 0];
		const object = type === 'shelf'
			? { type, position: [0, 1.75, 0], rotation: [0, 0, 0], label: 'New Shelf', width: 6, height: 3.5, depth: 8, levels: 3 }
			: type === 'floor'
				? { type, position: [0, 0.1, 0], rotation: [0, 0, 0], label: 'New Floor', width: 8, height: 0.2, depth: 8 }
					: type === 'anchor'
						? { type, position: [0, 0.3, 0], rotation: [0, 0, 0], label: 'New Anchor', radius: 5 }
					: type === 'box'
					? { type, position: [0, 0.75, 0], rotation: [0, 0, 0], label: 'New Box', width: 2, height: 1.5, depth: 2 }
					: { type: 'entity', entityType: type, entityName, position: type === 'mover' ? [0, 0.5, 0] : entityPosition, rotation: [0, 0, 0], label: type === 'drone' ? 'Drone Transport' : type === 'pallet' ? 'Pallet Jack' : type[0].toUpperCase() + type.slice(1) };
		commitLayout({ ...layout, [id]: object });
		setSelectedId(id);
		setShowAddMenu(false);
	};

	const autoPlaceMinimumAnchors = () => {
		const anchorPositions = [
			[-12, 0.3, -12],
			[12, 0.3, -12],
			[0, 0.3, 12],
		];
		const next = Object.fromEntries(Object.entries(layout).filter(([, object]) => object.type !== 'anchor'));
		anchorPositions.forEach((position, index) => {
			next[`anchor-${index + 1}`] = {
				type: 'anchor',
				position,
				rotation: [0, 0, 0],
				label: `Anchor ${index + 1}`,
				radius: 24,
			};
		});
		commitLayout(next);
		setSelectedId(null);
		setShowAddMenu(false);
	};

	const deleteSelectedObject = () => {
		if (!selectedId || DEFAULT_LAYOUT[selectedId]) return;
		const next = { ...layout };
		delete next[selectedId];
		commitLayout(next);
		delete objectRefs.current[selectedId];
		setSelectedId(null);
	};

  const handleResetLayout = () => {
    Object.entries(DEFAULT_LAYOUT).forEach(([id, def]) => {
      const obj = objectRefs.current[id];
      if (obj) {
        obj.position.set(...def.position);
        obj.rotation.set(...(def.rotation || [0, 0, 0]));
      }
    });
		commitLayout(structuredClone(DEFAULT_LAYOUT));
  };

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
	return () => {
	  if (socketRef.current) socketRef.current.disconnect();
	};
  }, []);
  return (
	<>
	  {editMode && (
		<div className="unity-toolbar">
		  <div className="unity-toolbar-brand"><span className="unity-cube">◆</span> Scene Workspace</div>
		  <div className="unity-toolbar-group">
			<label htmlFor="map-selector">Map</label>
			<select id="map-selector" value={activeMapId} onChange={(e) => switchMap(e.target.value)}>
			  {Object.entries(maps).map(([id, map]) => <option key={id} value={id}>{map.name}</option>)}
			</select>
			<button onClick={createMap}>New</button>
			<button onClick={duplicateMap}>Duplicate</button>
			<button onClick={renameActiveMap}>Rename</button>
			<button className="unity-danger-button" onClick={deleteActiveMap} disabled={Object.keys(maps).length === 1}>Delete</button>
			<button onClick={exportMaps}>Export JSON</button>
			<button onClick={() => mapFileInputRef.current?.click()}>Import JSON</button>
			<input ref={mapFileInputRef} type="file" accept="application/json,.json" onChange={importMaps} hidden />
			<button onClick={() => { setEditMode(false); setSelectedId(null); }}>Exit Editor</button>
		  </div>
		  <div className="unity-toolbar-status">Saved locally</div>
		</div>
	  )}
	  <div className={`hud-overlay ${editMode ? 'editor-hud-hidden' : ''}`} style={{ zIndex: 10 }}>
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
		<p style={{fontSize: '0.82rem', color: 'var(--text-muted)', marginTop: '15px'}}>
		  <strong>CONTROLS:</strong> Click the screen to interact. Use <kbd style={{background: '#334155', padding: '2px 4px', borderRadius: '4px'}}>W</kbd> <kbd style={{background: '#334155', padding: '2px 4px', borderRadius: '4px'}}>A</kbd> <kbd style={{background: '#334155', padding: '2px 4px', borderRadius: '4px'}}>S</kbd> <kbd style={{background: '#334155', padding: '2px 4px', borderRadius: '4px'}}>D</kbd> to drive the Mover Entity.
		</p>
		<button
		  onClick={() => { setEditMode(e => !e); setSelectedId(null); }}
		  style={{ marginTop: '12px', width: '100%', padding: '8px', borderRadius: '6px', border: 'none', fontWeight: 'bold', cursor: 'pointer', background: editMode ? '#22c55e' : '#334155', color: 'white' }}
		>
		  {editMode ? '🛠 Editing Scene — click to exit' : '🛠 Enter Scene Editor'}
		</button>
	  </div>
	  {editMode && (
		<div className="telemetry-panel scene-hierarchy-panel" style={{ zIndex: 10, top: '62px', bottom: '20px', left: '20px', right: 'auto', width: '260px' }}>
		  <h3>Scene Hierarchy</h3>
		  <div className="scene-add-actions">
			<button className="scene-add-button" onClick={() => setShowAddMenu(menuOpen => !menuOpen)}>+ Add Item</button>
			{showAddMenu && (
			  <div className="scene-add-menu">
				<button onClick={() => addRuntimeObject('shelf')}>Shelf</button>
				<button onClick={() => addRuntimeObject('floor')}>Floor</button>
				<button onClick={() => addRuntimeObject('box')}>Box</button>
				<button onClick={() => addRuntimeObject('anchor')}>Anchor</button>
				<button className="scene-auto-anchor-button" onClick={autoPlaceMinimumAnchors}>Auto-place 3 Anchors</button>
				<button onClick={() => addRuntimeObject('mover')}>Mover</button>
				<button onClick={() => addRuntimeObject('forklift')}>Forklift</button>
				<button onClick={() => addRuntimeObject('employee')}>Employee</button>
				<button onClick={() => addRuntimeObject('drone')}>Drone Transport</button>
				<button onClick={() => addRuntimeObject('pallet')}>Pallet Jack</button>
			  </div>
			)}
		  </div>
		  {Object.entries(layout).map(([id, obj]) => (
			<div
			  key={id}
			  onClick={() => selectObject(id)}
			  style={{
				padding: '6px 10px', marginBottom: '4px', borderRadius: '4px', cursor: 'pointer',
				background: selectedId === id ? 'rgba(74, 222, 128, 0.25)' : 'rgba(255,255,255,0.05)',
				border: selectedId === id ? '1px solid #4ade80' : '1px solid transparent',
				color: 'white', fontSize: '0.85rem',
			  }}
			>
			  {selectedId === id ? '📦 ' : '▫️ '}{obj.label}
			</div>
		  ))}
		  {selectedId && (
			<div className="hierarchy-inspector-legacy" style={{ marginTop: '10px', paddingTop: '10px', borderTop: '1px solid rgba(255,255,255,0.15)' }}>
			  <div className="scene-inspector">
				<div className="scene-inspector-heading">
				  <span>Inspector</span>
				  <span className="scene-inspector-id">{selectedId}</span>
				</div>
				<div className="scene-property-group">
				  <div className="scene-property-title">Position</div>
				  <div className="scene-property-row">
					{['x', 'y', 'z'].map((axis, index) => (
					  <label key={axis} className="scene-property-field">
						<span>{axis.toUpperCase()}</span>
						<input
						  type="number"
						  step="0.1"
						  value={layout[selectedId].position[index].toFixed(2)}
						  onChange={(e) => updateSelectedTransform('position', index, Number(e.target.value))}
						/>
					  </label>
					))}
				  </div>
				</div>
				<div className="scene-property-group">
				  <div className="scene-property-title">Rotation <span>(degrees)</span></div>
				  <div className="scene-property-row">
					{['x', 'y', 'z'].map((axis, index) => (
					  <label key={axis} className="scene-property-field">
						<span>{axis.toUpperCase()}</span>
						<input
						  type="number"
						  step="1"
						  value={THREE.MathUtils.radToDeg(layout[selectedId].rotation[index]).toFixed(1)}
						  onChange={(e) => updateSelectedTransform('rotation', index, Number(e.target.value))}
						/>
					  </label>
					))}
				  </div>
				</div>
				{!DEFAULT_LAYOUT[selectedId] && ['shelf', 'floor', 'box'].includes(layout[selectedId].type) && (
				  <div className="scene-property-group">
					<div className="scene-property-title">Size</div>
					<div className="scene-property-row">
					  {['width', 'height', 'depth'].map((property) => (
						<label key={property} className="scene-property-field">
						  <span>{property[0].toUpperCase()}</span>
						  <input
							type="number"
							min="0.1"
							step="0.1"
							value={layout[selectedId][property].toFixed(2)}
							onChange={(e) => updateSelectedProperty(property, Number(e.target.value))}
						  />
						</label>
						))}
					</div>
					{layout[selectedId].type === 'shelf' && (
					  <label className="scene-level-field">
						<span>Shelf levels</span>
						<input
							type="number"
							min="1"
							step="1"
							value={layout[selectedId].levels}
							onChange={(e) => updateSelectedProperty('levels', Math.max(1, Math.floor(Number(e.target.value))))}
						/>
					  </label>
					)}
				  </div>
				)}
				{layout[selectedId].type === 'anchor' && <div className="scene-property-group">
					<div className="scene-property-title">Coverage <span>(sphere)</span></div>
					<label className="scene-level-field"><span>Radius</span><input type="number" min="0.5" step="0.5" value={(layout[selectedId].radius || 5).toFixed(1)} onChange={(e) => updateSelectedProperty('radius', Number(e.target.value))} /></label>
				</div>}
				{layout[selectedId].type === 'entity' && (
				  <div className="scene-entity-properties">
					<div className="scene-property-title">Live Properties</div>
					<div className="scene-entity-row"><span>Tracked as</span><strong>{layout[selectedId].entityName}</strong></div>
					<div className="scene-entity-row"><span>Battery</span><strong>{selectedLiveTag ? `${selectedLiveTag.battery}%` : 'Waiting for signal'}</strong></div>
					{selectedLiveTag?.distances && <div className="scene-entity-distances">
					  {Object.entries(selectedLiveTag.distances).map(([receiver, distance]) => <div key={receiver}><span>{receiver}</span><strong>{distance}m</strong></div>)}
					</div>}
				  </div>
				)}
				<div className="scene-property-meta">Changes save automatically to this browser.</div>
			  </div>
			  <div style={{ display: 'flex', gap: '6px', marginBottom: '10px' }}>
				<button
				  onClick={() => setGizmoMode('translate')}
				  style={{ flex: 1, padding: '6px', borderRadius: '4px', border: 'none', cursor: 'pointer', fontWeight: 'bold', background: gizmoMode === 'translate' ? '#38bdf8' : '#334155', color: 'white' }}
				>↔ Move</button>
				<button
				  onClick={() => setGizmoMode('rotate')}
				  style={{ flex: 1, padding: '6px', borderRadius: '4px', border: 'none', cursor: 'pointer', fontWeight: 'bold', background: gizmoMode === 'rotate' ? '#38bdf8' : '#334155', color: 'white' }}
				>⟳ Rotate</button>
			  </div>
			  <p style={{ fontSize: '0.75rem', color: '#94a3b8' }}>Drag the gizmo arrows/rings in the scene to reposition <strong style={{color:'white'}}>{layout[selectedId].label}</strong>. Changes auto-save.</p>
			  {!DEFAULT_LAYOUT[selectedId] && (
				<button className="scene-delete-button" onClick={deleteSelectedObject}>Delete {layout[selectedId].label}</button>
			  )}
			</div>
		  )}
		  <button
			onClick={handleResetLayout}
			style={{ marginTop: '10px', width: '100%', padding: '6px', borderRadius: '4px', border: '1px solid #ef4444', background: 'transparent', color: '#ef4444', cursor: 'pointer', fontWeight: 'bold' }}
		  >Reset Layout to Default</button>
		</div>
	  )}
	  <div className="telemetry-panel runtime-panel inspector-panel" style={{ zIndex: 10 }}>
		<h3>Inspector</h3>
		{selectedId ? (
		  <>
			<div className="scene-inspector">
			  <div className="scene-inspector-heading">
				<span>{layout[selectedId].label}</span>
				<span className="scene-inspector-id">{selectedId}</span>
			  </div>
			  <label className="scene-name-field">
				<span>Name</span>
				<input type="text" value={layout[selectedId].label} onChange={(e) => renameSelectedObject(e.target.value)} />
			  </label>
			  <div className="scene-property-group">
				<div className="scene-property-title">Position</div>
				<div className="scene-property-row">
				  {['x', 'y', 'z'].map((axis, index) => <label key={axis} className="scene-property-field"><span>{axis.toUpperCase()}</span><input type="number" step="0.1" value={layout[selectedId].position[index].toFixed(2)} onChange={(e) => updateSelectedTransform('position', index, Number(e.target.value))} /></label>)}
				</div>
			  </div>
			  <div className="scene-property-group">
				<div className="scene-property-title">Rotation <span>(degrees)</span></div>
				<div className="scene-property-row">
				  {['x', 'y', 'z'].map((axis, index) => <label key={axis} className="scene-property-field"><span>{axis.toUpperCase()}</span><input type="number" step="1" value={THREE.MathUtils.radToDeg(layout[selectedId].rotation[index]).toFixed(1)} onChange={(e) => updateSelectedTransform('rotation', index, Number(e.target.value))} /></label>)}
				</div>
			  </div>
			  {!DEFAULT_LAYOUT[selectedId] && ['shelf', 'floor', 'box'].includes(layout[selectedId].type) && <div className="scene-property-group">
				<div className="scene-property-title">Size</div>
				<div className="scene-property-row">
				  {['width', 'height', 'depth'].map((property) => <label key={property} className="scene-property-field"><span>{property[0].toUpperCase()}</span><input type="number" min="0.1" step="0.1" value={layout[selectedId][property].toFixed(2)} onChange={(e) => updateSelectedProperty(property, Number(e.target.value))} /></label>)}
				</div>
				{layout[selectedId].type === 'shelf' && <label className="scene-level-field"><span>Shelf levels</span><input type="number" min="1" step="1" value={layout[selectedId].levels} onChange={(e) => updateSelectedProperty('levels', Math.max(1, Math.floor(Number(e.target.value))))} /></label>}
			  </div>}
			  {layout[selectedId].type === 'anchor' && <div className="scene-property-group">
				<div className="scene-property-title">Coverage</div>
				<label className="scene-level-field"><span>Radius</span><input type="number" min="0.5" step="0.5" value={layout[selectedId].radius.toFixed(1)} onChange={(e) => updateSelectedProperty('radius', Number(e.target.value))} /></label>
			  </div>}
			  {layout[selectedId].type === 'entity' && <div className="scene-entity-properties">
				<div className="scene-property-title">Live Properties</div>
				<div className="scene-entity-row"><span>Tracked as</span><strong>{layout[selectedId].entityName}</strong></div>
				<div className="scene-entity-row"><span>Battery</span><strong>{selectedLiveTag ? `${selectedLiveTag.battery}%` : 'Waiting for signal'}</strong></div>
				{selectedLiveTag?.distances && <div className="scene-entity-distances">{Object.entries(selectedLiveTag.distances).map(([receiver, distance]) => <div key={receiver}><span>{receiver}</span><strong>{distance}m</strong></div>)}</div>}
			  </div>}
			  <div className="scene-property-meta">Changes save automatically to this browser.</div>
			</div>
			<div className="inspector-gizmo-actions"><button onClick={() => setGizmoMode('translate')}>↔ Move</button><button onClick={() => setGizmoMode('rotate')}>⟳ Rotate</button></div>
			<p className="inspector-help">Drag the gizmo in the scene to reposition <strong>{layout[selectedId].label}</strong>.</p>
			{!DEFAULT_LAYOUT[selectedId] && <button className="scene-delete-button" onClick={deleteSelectedObject}>Delete {layout[selectedId].label}</button>}
		  </>
		) : <div className="inspector-empty">Select an object from the hierarchy to edit its properties.</div>}
	  </div>
	  <div className={`map-container ${editMode ? 'unity-scene-window' : ''}`} style={{ position: 'absolute', top: editMode ? '42px' : 0, left: editMode ? '330px' : 0, width: editMode ? 'calc(100% - 738px)' : '100%', height: editMode ? 'calc(100% - 42px)' : '100%', pointerEvents: 'auto' }}>
		<Canvas shadows camera={{ position: [15, 12, 18], fov: 50 }} onPointerMissed={() => editMode && setSelectedId(null)}>
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
			<WarehouseInterior key={activeMapId} layout={layout} editMode={editMode} selectedId={selectedId} onSelect={selectObject} registerRef={registerRef} targetId={navTarget} allTags={globalTags} />
			{editMode && selectedId && objectRefs.current[selectedId] && (
				<TransformControls
					object={objectRefs.current[selectedId]}
					mode={gizmoMode}
					onMouseDown={() => setOrbitEnabled(false)}
					onMouseUp={() => { setOrbitEnabled(true); syncSelectedToState(); }}
				/>
			)}
			<OrbitControls makeDefault enabled={orbitEnabled} maxPolarAngle={Math.PI / 2 - 0.05} minDistance={2} maxDistance={40} />
		</Canvas>
	  </div>
	</>
  );
}
export default App;