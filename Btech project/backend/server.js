const express = require('express');
const http = require('http');
const { Server } = require('socket.io');
const cors = require('cors');
const app = express();
app.use(cors());
const server = http.createServer(app);
const io = new Server(server, {
  cors: {
	origin: '*',
	methods: ['GET', 'POST']
  }
});
let tagPositions = {};
io.on('connection', (socket) => {
  console.log(`Client connected: ${socket.id}`);
  socket.emit('initial_state', tagPositions);
  socket.on('update_location', (data) => {
	tagPositions[data.tagId] = data;
	socket.broadcast.emit('location_update', data);
  });
  socket.on('disconnect', () => {
	console.log(`Client disconnected: ${socket.id}`);
  });
});
const PORT = 3000;
server.listen(PORT, () => {
  console.log(`WebSocket Hub Server running on port ${PORT}`);
});