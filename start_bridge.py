import asyncio
import websockets
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional
from urllib.parse import urlparse
import aiohttp
from aiohttp import web
import socketio
import socket
import sys
import os
import re
import time

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Funscript conversion constants
FAKTOR_CONV = 6.25

def load_config(config_file: str = "config.json") -> dict:
    """Load configuration from JSON file"""
    try:
        if os.path.exists(config_file):
            with open(config_file, 'r') as f:
                return json.load(f)
        else:
            logger.warning(f"Config file {config_file} not found, using defaults")
            return {}
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        return {}

def check_port_available(host: str, port: int) -> bool:
    """Check if a port is available for binding"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((host, port))
            return True
    except OSError:
        return False

def find_available_port(host: str, start_port: int, max_attempts: int = 10) -> int:
    """Find an available port starting from start_port"""
    for port in range(start_port, start_port + max_attempts):
        if check_port_available(host, port):
            return port
    raise RuntimeError(f"Could not find available port starting from {start_port}")

class ButtplugConnector:
    """Handles connection to Intiface Central via WebSocket"""

    def __init__(self, buttplug_url: str = "ws://localhost:6969"):
        self.buttplug_url = buttplug_url
        self.websocket = None
        self.devices = {}
        self.connected = False
        self.message_id = 10  # Start message IDs from 10

    async def connect(self):
        """Connect to Buttplug server"""
        try:
            # Set a timeout for the connection attempt
            self.websocket = await asyncio.wait_for(
                websockets.connect(self.buttplug_url), 
                timeout=5.0
            )

            # Send handshake with proper Buttplug protocol format
            handshake = {
                "RequestServerInfo": {
                    "Id": 1,
                    "ClientName": "AdultTime Bridge",
                    "MessageVersion": 3
                }
            }
            message_json = json.dumps([handshake], ensure_ascii=False, separators=(',', ':'))
            logger.debug(f"Sending handshake: {message_json}")
            await self.websocket.send(message_json)

            # Receive handshake response with timeout
            response = json.loads(await asyncio.wait_for(
                self.websocket.recv(), 
                timeout=5.0
            ))
            logger.info(f"Handshake response: {response}")

            # Request device list
            device_list_msg = {"RequestDeviceList": {"Id": 2}}
            message_json = json.dumps([device_list_msg], ensure_ascii=False, separators=(',', ':'))
            logger.debug(f"Sending device list request: {message_json}")
            await self.websocket.send(message_json)

            self.connected = True
            logger.info("Connected to Buttplug server")
            
            # Start listening for messages in background
            asyncio.create_task(self._listen_for_messages())
            
            # Start heartbeat to keep connection alive
            asyncio.create_task(self._heartbeat())

        except asyncio.TimeoutError:
            logger.warning("Timeout connecting to Buttplug server - make sure Intiface Central is running")
            self.connected = False
        except Exception as e:
            logger.error(f"Failed to connect to Buttplug: {e}")
            self.connected = False

    async def scan_devices(self):
        """Start scanning for devices"""
        if not self.connected:
            return

        try:
            scan_msg = {"StartScanning": {"Id": 3}}
            message_json = json.dumps([scan_msg], ensure_ascii=False, separators=(',', ':'))
            logger.debug(f"Sending scan request: {message_json}")
            await self.websocket.send(message_json)
            logger.info("Started device scanning")
        except Exception as e:
            logger.error(f"Failed to start scanning: {e}")

    async def _heartbeat(self):
        """Send periodic ping to keep connection alive"""
        while self.connected and self.websocket:
            try:
                await asyncio.sleep(30)  # Send ping every 30 seconds
                if self.websocket and self.connected:
                    await self.websocket.ping()
                    logger.debug("Sent heartbeat ping")
            except Exception as e:
                logger.warning(f"Heartbeat failed: {e}")
                self.connected = False
                self.websocket = None
                break

    async def _listen_for_messages(self):
        """Listen for incoming messages from Buttplug server"""
        try:
            while self.connected and self.websocket:
                try:
                    message = await asyncio.wait_for(self.websocket.recv(), timeout=1.0)
                    await self._process_message(message)
                except asyncio.TimeoutError:
                    # Normal timeout, continue listening
                    continue
                except websockets.exceptions.ConnectionClosed:
                    logger.warning("Buttplug connection closed, attempting to reconnect...")
                    self.connected = False
                    self.websocket = None
                    # Try to reconnect
                    await asyncio.sleep(2)  # Wait before reconnecting
                    await self.connect()
                    break
        except Exception as e:
            logger.error(f"Error in message listener: {e}")
            self.connected = False
            self.websocket = None

    async def _process_message(self, message: str):
        """Process incoming message from Buttplug server"""
        try:
            data = json.loads(message)
            logger.debug(f"Received message: {data}")
            
            for msg in data:
                if "DeviceAdded" in msg:
                    device_info = msg["DeviceAdded"]
                    device_id = device_info["DeviceIndex"]
                    device_name = device_info["DeviceName"]
                    self.devices[device_id] = device_info
                    logger.info(f"Device added: {device_name} (ID: {device_id})")
                    
                elif "DeviceRemoved" in msg:
                    device_info = msg["DeviceRemoved"]
                    device_id = device_info["DeviceIndex"]
                    if device_id in self.devices:
                        device_name = self.devices[device_id].get("DeviceName", "Unknown")
                        del self.devices[device_id]
                        logger.info(f"Device removed: {device_name} (ID: {device_id})")
                        
                elif "DeviceList" in msg:
                    device_list = msg["DeviceList"]["Devices"]
                    for device_info in device_list:
                        device_id = device_info["DeviceIndex"]
                        device_name = device_info["DeviceName"]
                        self.devices[device_id] = device_info
                        logger.info(f"Found existing device: {device_name} (ID: {device_id})")
                        
        except Exception as e:
            logger.error(f"Error processing message: {e}")

    async def vibrate_device(self, device_id: int, strength: float):
        """Send vibration command to device"""
        if not self.websocket or device_id not in self.devices:
            logger.warning(f"Cannot vibrate device {device_id}: websocket_exists={bool(self.websocket)}, device_exists={device_id in self.devices}")
            # Try to reconnect if websocket is missing
            if not self.websocket:
                logger.info("Attempting to reconnect to Buttplug...")
                await self.connect()
                if not self.websocket or device_id not in self.devices:
                    return
            else:
                return

        # Mark as connected if we have websocket and devices
        if self.websocket and self.devices:
            self.connected = True

        try:
            self.message_id += 1
            vibrate_msg = {
                "VibrateCmd": {
                    "Id": self.message_id,
                    "DeviceIndex": device_id,
                    "Speeds": [{"Index": 0, "Speed": strength}]
                }
            }
            message_json = json.dumps([vibrate_msg], ensure_ascii=False, separators=(',', ':'))
            await self.websocket.send(message_json)
            logger.info(f"Sent vibration command: device={device_id}, strength={strength}, msg_id={self.message_id}")
        except Exception as e:
            logger.error(f"Failed to send vibration: {e}")
            self.connected = False
            self.websocket = None
            # Try to reconnect on next command
            logger.info("WebSocket connection lost, will attempt to reconnect on next command")

    async def stroke_device(self, device_id: int, position: float, duration: int):
        """Send stroke command to stroker device"""
        if not self.connected or device_id not in self.devices:
            return

        try:
            stroke_msg = {
                "LinearCmd": {
                    "Id": 0,  # System messages use Id 0
                    "DeviceIndex": device_id,
                    "Vectors": [{"Index": 0, "Duration": duration, "Position": position}]
                }
            }
            message_json = json.dumps([stroke_msg], ensure_ascii=False, separators=(',', ':'))
            await self.websocket.send(message_json)
            logger.debug(f"Sent stroke command: device={device_id}, position={position}")
        except Exception as e:
            logger.error(f"Failed to send stroke: {e}")

class VideoEventProcessor:
    """Processes video events and translates them to device commands"""

    def __init__(self, buttplug_connector: ButtplugConnector):
        self.buttplug = buttplug_connector
        self.intensity_scale = 1.0

    @property
    def active_devices(self):
        """Get list of active device IDs"""
        return list(self.buttplug.devices.keys())

    async def process_play_event(self):
        """Handle video play event"""
        logger.info("Video started playing")
        # Start gentle vibration to indicate connection
        for device_id in self.active_devices:
            await self.buttplug.vibrate_device(device_id, 0.2 * self.intensity_scale)

    async def process_pause_event(self):
        """Handle video pause event"""
        logger.info("Video paused")
        # Stop all vibrations
        for device_id in self.active_devices:
            await self.buttplug.vibrate_device(device_id, 0.0)

    async def process_scene_change(self, scene_intensity: str):
        """Handle scene change events"""
        intensity_map = {
            "low": 0.3,
            "medium": 0.6,
            "high": 0.9,
            "climax": 1.0
        }

        strength = intensity_map.get(scene_intensity, 0.5) * self.intensity_scale
        logger.info(f"Scene change: {scene_intensity} -> strength {strength}")

        for device_id in self.active_devices:
            await self.buttplug.vibrate_device(device_id, strength)

    async def process_audio_level(self, audio_level: float):
        """Process audio level for dynamic response"""
        # Scale audio level to vibration strength
        strength = min(audio_level * 0.8 * self.intensity_scale, 1.0)

        for device_id in self.active_devices:
            await self.buttplug.vibrate_device(device_id, strength)

class FunscriptDownloader:
    """Handles downloading and converting Lovense patterns to funscripts"""
    
    def __init__(self, cache_dir: str = "cache"):
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)
        logger.info(f"Funscript cache directory: {cache_dir}")
    
    def extract_adulttime_id(self, url: str) -> Optional[str]:
        """Extract video ID from Adult Time URL"""
        patterns = [
            r'adulttime\.com/.*?/([0-9]+)',
            r'members\.adulttime\.com/.*?/([0-9]+)',
            r'switch\.com/.*?/([0-9]+)',
            r'howwomenorgasm\.com/.*?/([0-9]+)',
            r'getupclose\.com/.*?/([0-9]+)',
            r'milfoverload\.net/.*?/([0-9]+)',
            r'dareweshare\.net/.*?/([0-9]+)',
            r'jerkbuddies\.com/.*?/([0-9]+)',
            r'adulttime\.studio/.*?/([0-9]+)',
            r'oopsie\.tube/.*?/([0-9]+)',
            r'adulttimepilots\.com/.*?/([0-9]+)',
            r'kissmefuckme\.net/.*?/([0-9]+)',
            r'youngerloverofmine\.com/.*?/([0-9]+)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None
    
    async def download_funscript(self, video_id: str, title: str = "", duration: int = 0) -> Optional[dict]:
        """Download and convert funscript for given video ID"""
        cache_file = os.path.join(self.cache_dir, f"{video_id}.funscript")
        pattern_cache = os.path.join(self.cache_dir, f"{video_id}.pat")
        info_cache = os.path.join(self.cache_dir, f"{video_id}.json")
        
        # Check if funscript already exists in cache
        if os.path.exists(cache_file):
            logger.info(f"Loading cached funscript for video ID {video_id}")
            try:
                with open(cache_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading cached funscript: {e}")
        
        try:
            # Download pattern info from Lovense API
            if not os.path.exists(info_cache):
                lovense_url = f"https://coll.lovense.com/coll-log/video-websites/get/pattern?videoId={video_id}&pf=Adulttime"
                
                async with aiohttp.ClientSession() as session:
                    async with session.get(lovense_url) as response:
                        if response.status == 200:
                            content = await response.text()
                            with open(info_cache, 'w') as f:
                                f.write(content)
                        else:
                            logger.error(f"Failed to download pattern info: HTTP {response.status}")
                            return None
            
            # Load pattern info
            with open(info_cache, 'r') as f:
                pattern_info = json.load(f)
            
            if pattern_info.get('code') != 0:
                logger.info(f"No interactive content available for video ID {video_id}")
                return None
            
            # Download pattern data
            if not os.path.exists(pattern_cache):
                pattern_url = pattern_info['data']['pattern']
                
                async with aiohttp.ClientSession() as session:
                    async with session.get(pattern_url) as response:
                        if response.status == 200:
                            content = await response.text()
                            with open(pattern_cache, 'w') as f:
                                f.write(content)
                        else:
                            logger.error(f"Failed to download pattern data: HTTP {response.status}")
                            return None
            
            # Convert to funscript
            funscript = await self.convert_lovense_to_funscript(pattern_cache, title, duration)
            
            # Cache the funscript
            with open(cache_file, 'w') as f:
                json.dump(funscript, f)
            
            logger.info(f"Successfully downloaded and converted funscript for video ID {video_id}")
            return funscript
            
        except Exception as e:
            logger.error(f"Error downloading funscript for video ID {video_id}: {e}")
            # Clean up potentially corrupted cache files
            for cache_path in [info_cache, pattern_cache, cache_file]:
                if os.path.exists(cache_path):
                    try:
                        os.remove(cache_path)
                    except:
                        pass
            return None
    
    async def convert_lovense_to_funscript(self, pattern_file: str, title: str = "", duration: int = 0) -> dict:
        """Convert Lovense pattern file to funscript format"""
        
        # Load Lovense actions
        with open(pattern_file, 'r') as f:
            lovense_actions = json.load(f)
        
        # Create funscript structure
        funscript = {
            "version": "1.0",
            "range": 100,
            "inverted": False,
            "metadata": {
                "bookmarks": {},
                "chapters": {},
                "performers": {},
                "tags": {},
                "title": title,
                "creator": "Adult Time Buttplug Bridge",
                "description": "Auto-downloaded from Lovense",
                "duration": duration,
                "license": "Open",
                "script_url": "",
                "type": "basic",
                "video_url": "",
                "notes": "Converted from Lovense to Funscript"
            },
            "actions": []
        }
        
        # Convert actions
        for action in lovense_actions:
            if action.get('t', 0) == 0:
                continue  # Skip invalid timestamps
            
            # Convert values
            marker_at = 0 if action.get('v', 0) == 0 else action['v'] * FAKTOR_CONV
            marker_pos = action['t']  # Timestamp in milliseconds
            
            funscript["actions"].append({
                "pos": int(marker_at + 0.5),
                "at": int(marker_pos + 0.5)
            })
        
        # Sort actions by timestamp
        funscript["actions"].sort(key=lambda x: x["at"])
        
        logger.info(f"Converted {len(funscript['actions'])} actions to funscript")
        return funscript

class AdultTimeBridge:
    """Main bridge application"""

    def __init__(self, config: dict = None):
        # Load configuration
        default_config = {
            'host': 'localhost',
            'port': 8080,
            'buttplug_url': 'ws://localhost:6969',
            'cache_dir': 'cache'
        }
        
        if config:
            default_config.update(config)
        
        self.config = default_config
        self.host = default_config['host']
        self.port = default_config['port']
        self.buttplug_url = default_config['buttplug_url']
        
        # Initialize components
        self.buttplug = ButtplugConnector(self.buttplug_url)
        self.processor = VideoEventProcessor(self.buttplug)
        self.funscript_downloader = FunscriptDownloader(default_config['cache_dir'])
        
        # Setup web components
        self.app = web.Application(middlewares=[self.cors_middleware])
        self.sio = socketio.AsyncServer(cors_allowed_origins="*")
        self.sio.attach(self.app)
        
        self.setup_routes()
        self.setup_socketio_handlers()
        
        self.server_url = None

    @web.middleware
    async def cors_middleware(self, request, handler):
        """Add CORS headers to all responses"""
        if request.method == "OPTIONS":
            # Handle preflight requests
            response = web.Response()
        else:
            response = await handler(request)
        
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        return response

    def setup_routes(self):
        """Setup HTTP routes"""
        self.app.router.add_get('/', self.index_handler)
        self.app.router.add_get('/status', self.status_handler)
        self.app.router.add_post('/api/video-event', self.video_event_handler)
        self.app.router.add_post('/api/connect-buttplug', self.connect_buttplug_handler)
        self.app.router.add_get('/tampermonkey.js', self.tampermonkey_script_handler)
        self.app.router.add_get('/api/proxy-image', self.image_proxy_handler)
        
        # Funscript endpoints
        self.app.router.add_post('/api/download-funscript', self.download_funscript_handler)
        self.app.router.add_get('/api/funscript/{video_id}', self.get_funscript_handler)
        self.app.router.add_post('/api/auto-funscript', self.auto_funscript_handler)

        # Serve static files for browser extension
        self.app.router.add_static('/static/', path='static/', name='static')

    def setup_socketio_handlers(self):
        """Setup Socket.IO event handlers"""

        @self.sio.event
        async def connect(sid, environ):
            logger.info(f"Client connected: {sid}")
            await self.sio.emit('status', {'connected': self.buttplug.connected}, room=sid)

        @self.sio.event
        async def video_play(sid, data):
            await self.processor.process_play_event()

        @self.sio.event
        async def video_pause(sid, data):
            await self.processor.process_pause_event()

        @self.sio.event
        async def scene_change(sid, data):
            await self.processor.process_scene_change(data.get('intensity', 'medium'))

        @self.sio.event
        async def audio_level(sid, data):
            await self.processor.process_audio_level(data.get('level', 0.0))

    async def index_handler(self, request):
        """Serve main page"""
        html_content = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Adult Time Buttplug Bridge</title>
            <script src="https://cdn.socket.io/4.7.4/socket.io.min.js"></script>
            <style>
                body { font-family: Arial, sans-serif; margin: 40px; background: #f5f5f5; }
                .container { background: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
                h1 { color: #333; margin-bottom: 20px; }
                .status { padding: 15px; margin: 20px 0; border-radius: 5px; font-weight: bold; }
                .connected { background: #d4edda; color: #155724; border: 1px solid #c3e6cb; }
                .disconnected { background: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }
                button { padding: 12px 20px; margin: 10px 5px; border: none; border-radius: 5px; cursor: pointer; font-size: 16px; }
                .connect-btn { background: #007bff; color: white; }
                .connect-btn:hover { background: #0056b3; }
                .tampermonkey-btn { background: #28a745; color: white; }
                .tampermonkey-btn:hover { background: #1e7e34; }
                .info { background: #e7f3ff; padding: 15px; border-left: 4px solid #007bff; margin: 20px 0; }
                .logs { background: #f8f9fa; padding: 15px; border-radius: 5px; margin: 20px 0; max-height: 200px; overflow-y: auto; font-family: monospace; }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>🔌 Adult Time Buttplug Bridge</h1>
                <div id="status" class="status disconnected">⏸️ Disconnected from Buttplug</div>
                
                <button class="connect-btn" onclick="connectButtplug()">🔗 Connect to Buttplug</button>
                <button class="tampermonkey-btn" onclick="installTampermonkey()">📥 Get Tampermonkey Script</button>
                
                <div class="info">
                    <h3>📋 Setup Instructions:</h3>
                    <ol>
                        <li>Start <strong>Intiface Central</strong> application</li>
                        <li>Click "Connect to Buttplug" above</li>
                        <li>Install the Tampermonkey script</li>
                        <li>Visit AdultTime and enjoy synchronized content!</li>
                    </ol>
                </div>

                <div class="logs" id="logs">
                    <div>Bridge server ready. Waiting for connections...</div>
                </div>
            </div>

            <script>
                const socket = io();
                let buttplugConnected = false;

                function addLog(message) {
                    const logs = document.getElementById('logs');
                    const time = new Date().toLocaleTimeString();
                    logs.innerHTML += `<div>[${time}] ${message}</div>`;
                    logs.scrollTop = logs.scrollHeight;
                }

                socket.on('connect', function() {
                    addLog('Connected to bridge server');
                });

                socket.on('status', function(data) {
                    buttplugConnected = data.connected;
                    updateStatus();
                });

                function updateStatus() {
                    const statusEl = document.getElementById('status');
                    if (buttplugConnected) {
                        statusEl.textContent = '✅ Connected to Buttplug';
                        statusEl.className = 'status connected';
                        addLog('Buttplug connection established');
                    } else {
                        statusEl.textContent = '⏸️ Disconnected from Buttplug';
                        statusEl.className = 'status disconnected';
                    }
                }

                async function connectButtplug() {
                    addLog('Attempting to connect to Buttplug...');
                    try {
                        const response = await fetch('/api/connect-buttplug', {method: 'POST'});
                        const result = await response.json();
                        if (result.status === 'connected') {
                            addLog('Successfully connected to Buttplug!');
                            buttplugConnected = true;
                            updateStatus();
                        } else {
                            addLog('Failed to connect: ' + (result.error || 'Unknown error'));
                        }
                    } catch (e) {
                        addLog('Connection error: ' + e.message);
                    }
                }

                function installTampermonkey() {
                    window.open('/tampermonkey.js', '_blank');
                }

                // Check initial status
                fetch('/status')
                    .then(r => r.json())
                    .then(data => {
                        buttplugConnected = data.buttplug_connected;
                        updateStatus();
                        addLog(`Bridge loaded. Buttplug: ${buttplugConnected ? 'Connected' : 'Disconnected'}`);
                    });
            </script>
        </body>
        </html>
        """
        return web.Response(text=html_content, content_type='text/html')

    async def status_handler(self, request):
        """API status endpoint"""
        # Simple check - if we have devices, consider connected
        websocket_connected = bool(self.buttplug.devices)
        
        return web.json_response({
            'buttplug_connected': websocket_connected,
            'active_devices': len(self.buttplug.devices),
            'devices': {str(device_id): info.get('DeviceName', 'Unknown') for device_id, info in self.buttplug.devices.items()}
        })

    async def video_event_handler(self, request):
        """Handle video events from browser extension"""
        data = await request.json()
        event_type = data.get('type')

        if event_type == 'play':
            await self.processor.process_play_event()
        elif event_type == 'pause':
            await self.processor.process_pause_event()
        elif event_type == 'scene_change':
            await self.processor.process_scene_change(data.get('intensity', 'medium'))
        elif event_type == 'audio_level':
            await self.processor.process_audio_level(data.get('level', 0.0))
        elif event_type == 'test':
            await self.processor.process_scene_change(data.get('intensity', 'medium'))
            logger.info(f"Test command sent with intensity: {data.get('intensity', 'medium')}")

        return web.json_response({'status': 'ok'})

    async def connect_buttplug_handler(self, request):
        """Handle manual Buttplug connection request"""
        # Check if already connected
        if self.buttplug.connected:
            logger.info("Already connected to Buttplug server")
            await self.sio.emit('status', {'connected': True})
            return web.json_response({'status': 'connected'})
        
        # If not connected, attempt to connect
        await self.buttplug.connect()
        if self.buttplug.connected:
            await self.buttplug.scan_devices()
            await self.sio.emit('status', {'connected': True})
            return web.json_response({'status': 'connected'})
        else:
            return web.json_response({'status': 'failed', 'error': 'Could not connect to Buttplug server'})

    async def image_proxy_handler(self, request):
        """Proxy images to bypass CORS restrictions"""
        try:
            # Get the image URL from query parameters
            image_url = request.query.get('url')
            if not image_url:
                return web.Response(text='Missing url parameter', status=400)
            
            # Validate the URL is from allowed domains
            allowed_domains = ['transform.gammacdn.com', 'cdn.adulttime.com']
            parsed_url = urlparse(image_url)
            if not any(domain in parsed_url.netloc for domain in allowed_domains):
                return web.Response(text='Domain not allowed', status=403)
            
            # Fetch the image
            connector = aiohttp.TCPConnector(ssl=False)  # Disable SSL verification for proxy
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.get(image_url) as response:
                    if response.status != 200:
                        return web.Response(text='Failed to fetch image', status=response.status)
                    
                    # Get content type
                    content_type = response.headers.get('content-type', 'image/jpeg')
                    image_data = await response.read()
                    
                    # Return the image with CORS headers
                    return web.Response(
                        body=image_data,
                        content_type=content_type,
                        headers={
                            'Access-Control-Allow-Origin': '*',
                            'Access-Control-Allow-Methods': 'GET',
                            'Access-Control-Allow-Headers': 'Content-Type',
                            'Cache-Control': 'public, max-age=3600'
                        }
                    )
        except Exception as e:
            logger.error(f"Error proxying image: {e}")
            return web.Response(text='Internal server error', status=500)

    async def download_funscript_handler(self, request):
        """Download funscript for a specific video ID"""
        try:
            data = await request.json()
            video_id = data.get('video_id')
            title = data.get('title', '')
            duration = data.get('duration', 0)
            
            if not video_id:
                return web.json_response({'error': 'Missing video_id'}, status=400)
            
            funscript = await self.funscript_downloader.download_funscript(video_id, title, duration)
            
            if funscript:
                return web.json_response({
                    'success': True,
                    'funscript': funscript,
                    'actions': len(funscript.get('actions', [])),
                    'cached': True
                })
            else:
                return web.json_response({
                    'success': False,
                    'error': 'No interactive content available for this video'
                }, status=404)
                
        except Exception as e:
            logger.error(f"Error downloading funscript: {e}")
            return web.json_response({'error': str(e)}, status=500)

    async def get_funscript_handler(self, request):
        """Get cached funscript for a video ID"""
        try:
            video_id = request.match_info['video_id']
            cache_file = os.path.join(self.funscript_downloader.cache_dir, f"{video_id}.funscript")
            
            if os.path.exists(cache_file):
                with open(cache_file, 'r') as f:
                    funscript = json.load(f)
                return web.json_response({
                    'success': True,
                    'funscript': funscript,
                    'cached': True
                })
            else:
                return web.json_response({
                    'success': False,
                    'error': 'Funscript not found in cache'
                }, status=404)
                
        except Exception as e:
            logger.error(f"Error getting funscript: {e}")
            return web.json_response({'error': str(e)}, status=500)

    async def auto_funscript_handler(self, request):
        """Auto-detect and download funscript from Adult Time URL"""
        try:
            data = await request.json()
            url = data.get('url')
            title = data.get('title', '')
            duration = data.get('duration', 0)
            
            if not url:
                return web.json_response({'error': 'Missing URL'}, status=400)
            
            # Extract video ID from URL
            video_id = self.funscript_downloader.extract_adulttime_id(url)
            
            if not video_id:
                return web.json_response({
                    'success': False,
                    'error': 'Could not extract video ID from URL'
                }, status=400)
            
            # Try to download funscript
            funscript = await self.funscript_downloader.download_funscript(video_id, title, duration)
            
            if funscript:
                return web.json_response({
                    'success': True,
                    'video_id': video_id,
                    'funscript': funscript,
                    'actions': len(funscript.get('actions', [])),
                    'message': f'Successfully downloaded funscript with {len(funscript.get("actions", []))} actions'
                })
            else:
                return web.json_response({
                    'success': False,
                    'video_id': video_id,
                    'error': 'No interactive content available for this video'
                }, status=404)
                
        except Exception as e:
            logger.error(f"Error in auto funscript download: {e}")
            return web.json_response({'error': str(e)}, status=500)

    async def tampermonkey_script_handler(self, request):
        """Serve Tampermonkey script for Adult Time integration"""
        # Use dynamic server URL
        bridge_url = self.server_url or 'http://localhost:8080'
        
        script_content = '''// ==UserScript==
// @name         Adult Time Buttplug Bridge
// @namespace    {bridge_url}/
// @version      2.0
// @description  Connects Adult Time videos to Buttplug devices via bridge server
// @author       You
// @match        https://*.adulttime.com/*
// @match        https://www.adulttime.com/*
// @grant        none
// ==/UserScript==

(function() {
    'use strict';
    
    console.log('🔌 Adult Time Buttplug Bridge v2.0 loaded');
    
    let bridgeConnected = false;
    let video = null;
    let lastIntensity = 0;
    let intensityUpdateInterval = null;
    
    // Bridge URL configuration
    const BRIDGE_URL = '{bridge_url}';
    
    // Check bridge connection status
    async function checkBridgeStatus() {
        try {
            const response = await fetch(`${{BRIDGE_URL}}/status`);
            const data = await response.json();
            bridgeConnected = data.buttplug_connected;
            console.log('🔌 Bridge status:', bridgeConnected ? 'Connected' : 'Disconnected');
            console.log('📊 Devices found:', data.active_devices);
            
            if (bridgeConnected) {
                showNotification(`✅ Connected to Buttplug Bridge! Found ${{data.active_devices}} device(s).`, 'success');
            } else {
                showNotification('⚠️ Bridge found but Buttplug not connected. Make sure Intiface Central is running.', 'warning');
            }
        } catch (e) {
            console.log('❌ Could not connect to bridge:', e.message);
            showNotification(`❌ Bridge not found. Make sure it's running on ${{BRIDGE_URL}}`, 'error');
            bridgeConnected = false;
        }
    }
    
    // Send events to bridge
    async function sendEvent(eventType, data = {}) {
        if (!bridgeConnected) return;
        
        try {
            await fetch(`${{BRIDGE_URL}}/api/video-event`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ type: eventType, ...data })
            });
            console.log('📡 Sent event:', eventType, data);
        } catch (e) {
            console.error('❌ Failed to send event:', e);
        }
    }
    
    // Calculate intensity based on video analysis
    function calculateIntensity() {
        if (!video || video.paused) return 0;
        
        // Simple audio-based intensity calculation
        // You can enhance this with more sophisticated analysis
        const currentTime = video.currentTime;
        const duration = video.duration;
        const progress = currentTime / duration;
        
        // Create varying intensity patterns
        const baseIntensity = 0.3;
        const variation = Math.sin(currentTime * 0.5) * 0.3;
        const progressBoost = progress > 0.8 ? 0.4 : 0; // Climax near end
        
        return Math.max(0, Math.min(1, baseIntensity + variation + progressBoost));
    }
    
    // Update device intensity
    function updateIntensity() {
        const intensity = calculateIntensity();
        if (Math.abs(intensity - lastIntensity) > 0.1) { // Only update if significant change
            sendEvent('audio_level', { level: intensity });
            lastIntensity = intensity;
        }
    }
    
    // Show notification
    function showNotification(message, type = 'info') {
        const notification = document.createElement('div');
        notification.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            z-index: 999999;
            padding: 15px 20px;
            border-radius: 8px;
            color: white;
            font-weight: bold;
            font-size: 14px;
            max-width: 300px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.3);
            background: ${type === 'success' ? '#28a745' : type === 'warning' ? '#ffc107' : type === 'error' ? '#dc3545' : '#007bff'};
        `;
        notification.textContent = message;
        document.body.appendChild(notification);
        
        setTimeout(() => {
            if (notification.parentNode) {
                notification.parentNode.removeChild(notification);
            }
        }, 5000);
    }
    
    // Find video element
    function findVideo() {
        return document.querySelector('video') || document.querySelector('iframe video');
    }
    
    // Setup video monitoring
    function setupVideoMonitoring() {
        video = findVideo();
        if (!video) {
            setTimeout(setupVideoMonitoring, 1000);
            return;
        }
        
        console.log('🎥 Video found:', video);
        showNotification('🎥 Video detected! Monitoring for events...', 'info');
        
        // Video event listeners
        video.addEventListener('play', () => {
            console.log('▶️ Video playing');
            sendEvent('video_play');
            
            // Start intensity monitoring
            if (intensityUpdateInterval) clearInterval(intensityUpdateInterval);
            intensityUpdateInterval = setInterval(updateIntensity, 500);
        });
        
        video.addEventListener('pause', () => {
            console.log('⏸️ Video paused');
            sendEvent('video_pause');
            
            // Stop intensity monitoring
            if (intensityUpdateInterval) {
                clearInterval(intensityUpdateInterval);
                intensityUpdateInterval = null;
            }
        });
        
        video.addEventListener('ended', () => {
            console.log('🏁 Video ended');
            sendEvent('video_pause');
            if (intensityUpdateInterval) {
                clearInterval(intensityUpdateInterval);
                intensityUpdateInterval = null;
            }
        });
        
        // Scene change detection (example based on time)
        video.addEventListener('timeupdate', () => {
            const currentTime = video.currentTime;
            const duration = video.duration;
            
            if (duration) {
                const progress = currentTime / duration;
                let intensity = 'medium';
                
                if (progress < 0.2) intensity = 'low';
                else if (progress > 0.8) intensity = 'high';
                else if (progress > 0.9) intensity = 'climax';
                
                // Send scene change every 30 seconds
                if (Math.floor(currentTime) % 30 === 0 && Math.floor(currentTime) !== lastIntensity) {
                    sendEvent('scene_change', { intensity });
                }
            }
        });
    }
    
    // Initialize
    async function init() {
        await checkBridgeStatus();
        setupVideoMonitoring();
        
        // Check status periodically
        setInterval(async () => {
            await checkBridgeStatus();
        }, 10000);
    }
    
    // Start when page loads
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
    
})();'''
        
        # Replace placeholder with actual URL
        script_content = script_content.replace('{bridge_url}', bridge_url)
        return web.Response(text=script_content, content_type='application/javascript')

    async def start_server(self, host=None, port=None):
        """Start the bridge server with config support and error handling"""
        # Use config values if not specified
        host = host or self.config.get('bridge', {}).get('host', 'localhost')
        port = port or self.config.get('bridge', {}).get('port', 8080)
        
        # Check if port is available
        if not check_port_available(host, port):
            logger.warning(f"Port {port} is already in use")
            try:
                port = find_available_port(host, port + 1)
                logger.info(f"Using alternative port: {port}")
            except RuntimeError as e:
                logger.error(f"Could not find available port: {e}")
                raise
        
        logger.info(f"Starting server on {host}:{port}")

        # Try to connect to Buttplug (non-blocking)
        await self.buttplug.connect()
        if self.buttplug.connected:
            await self.buttplug.scan_devices()
        else:
            logger.info("Starting server without Buttplug connection - you can connect later")

        # Start web server with error handling
        try:
            runner = web.AppRunner(self.app)
            await runner.setup()
            site = web.TCPSite(runner, host, port)
            await site.start()

            # Store the server URL for script generation
            self.server_url = f"http://{host}:{port}"
            
            logger.info(f"🚀 Bridge server running on {self.server_url}")
            if not self.buttplug.connected:
                logger.info("To connect to Buttplug devices:")
                logger.info("1. Start Intiface Central")
                logger.info(f"2. Visit {self.server_url} and click 'Connect to Buttplug'")
            return runner
            
        except OSError as e:
            if e.errno == 48:  # Address already in use
                logger.error(f"Port {port} is still in use. Please check if another instance is running.")
            raise

async def main():
    """Main entry point with improved error handling"""
    try:
        # Load config first for better error reporting
        config = load_config()
        logger.info("Configuration loaded successfully")
        
        bridge = AdultTimeBridge(config)
        runner = await bridge.start_server()

        try:
            logger.info("Bridge is running. Press Ctrl+C to stop.")
            # Keep the server running
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            logger.info("Received shutdown signal...")
        finally:
            logger.info("Cleaning up...")
            await runner.cleanup()
            logger.info("Bridge stopped.")
            
    except Exception as e:
        logger.error(f"Failed to start bridge: {e}")
        logger.error("Make sure:")
        logger.error("1. No other instance is already running")
        logger.error("2. The configuration file is valid")
        logger.error("3. Required dependencies are installed")
        sys.exit(1)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        sys.exit(1)