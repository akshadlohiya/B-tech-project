# 🚀 3D RTLS Warehouse Dashboard - Startup Guide

Since this project operates using a modern **Microservice Architecture**, there are three distinct engines running simultaneously that communicate with each other. If you shut your computer down, you will need to start all three services in separate terminal windows.

Here is exactly how to bring the entire simulation back online from scratch:

---

## Step 1: Start the WebSocket Relay Server (Backend)
This is the central nervous system. It receives the positional math from Python and broadcasts it to the React website instantly.
1. Open a terminal.
2. Navigate to the backend folder:
   ```bash
   cd backend
   ```
3. Start the Node.js server:
   ```bash
   npm start
   ```
   *(You should see a message saying "Socket.io Server listening on port 3001")*

---

## Step 2: Start the Trilateration Emulator (Python)
This script simulates the hardware UWB tags. It calculates the live X/Y/Z Euclidean distances and transmits the moving coordinates to the backend server.
1. Open a **second** new terminal window.
2. Navigate to the emulator folder:
   ```bash
   cd emulator
   ```
3. Run the python script:
   ```bash
   python pi_emulator.py
   ```
   *(You should see numbers rapidly printing out as the Drone and Forklift begin moving)*

---

## Step 3: Start the 3D Game Engine (Frontend)
This is the Three.js visualizer where you drive the Mover and interact with the data.
1. Open a **third** new terminal window.
2. Navigate to the frontend folder:
   ```bash
   cd frontend
   ```
3. Boot up the Vite development server:
   ```bash
   npm run dev
   ```
4. Look at the terminal output. It will give you a local URL (usually `http://localhost:5173`). Open that link in your browser!

---

### 🛑 Troubleshooting Connection Drops
If the 3D website stops updating or the tags freeze:
1. Check your **Backend** terminal. If the node server crashed, restart it, and refresh your browser.
2. The **Python** terminal might have been paused. If you click inside the windows command prompt, it pauses execution. Simply press `ESC` or `ENTER` on your keyboard inside the python terminal to unpause it!
