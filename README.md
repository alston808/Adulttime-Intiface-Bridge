# AdultTime-Intiface Bridge

A Python bridge that connects Adult Time video content to Buttplug.io/Intiface devices for interactive experiences. This project automatically downloads and synchronizes funscripts with Adult Time videos, providing real-time haptic feedback through connected toys.

## Features

- 🎯 **Auto-Funscript Detection**: Automatically finds and downloads interactive content for Adult Time videos
- 🔗 **Intiface Integration**: Direct connection to Intiface Central for device control
- 🌐 **Web Interface**: Clean web UI for device management and status monitoring
- 📱 **Real-time Sync**: Synchronized haptic feedback with video playback
- 🎮 **Multi-Device Support**: Works with various Buttplug.io compatible devices
- 🔄 **WebSocket API**: Real-time communication between browser and devices
- 📁 **Funscript Caching**: Intelligent caching system for downloaded scripts
- 🎚️ **Intensity Control**: Adjustable intensity settings for personalized experience

## Prerequisites

- Python 3.8 or higher
- [Intiface Central](https://intiface.com/central/) installed and running
- Compatible adult toy devices (Lovense, Kiiroo, etc.)
- Modern web browser with Tampermonkey extension

## Installation

### 1. Clone the Repository
```bash
git clone https://github.com/yourusername/Adulttime-Intiface-Bridge.git
cd Adulttime-Intiface-Bridge
```

### 2. Install Python Dependencies
```bash
pip install -r requirements.txt
```

### 3. Install Tampermonkey Script
1. Install the [Tampermonkey browser extension](https://www.tampermonkey.net/)
2. Open Tampermonkey dashboard
3. Click "Create a new script"
4. Copy the contents of `tampermonkey.js` into the editor
5. Save the script (Ctrl+S)

### 4. Setup Intiface Central
1. Download and install [Intiface Central](https://intiface.com/central/)
2. Start Intiface Central
3. Enable WebSocket server (default port 6969)
4. Connect your devices

## Usage

### Starting the Bridge
```bash
python start_bridge.py
```

The bridge will start on `http://localhost:8080` by default.

### Configuration
Create a `config.json` file to customize settings:

```json
{
  "bridge_host": "localhost",
  "bridge_port": 8080,
  "buttplug_url": "ws://localhost:6969",
  "cache_dir": "cache",
  "auto_funscript": true,
  "debug": false
}
```

### Using with Adult Time
1. Ensure the bridge is running
2. Navigate to any Adult Time video
3. The Tampermonkey script will automatically:
   - Connect to the bridge
   - Download available funscripts
   - Sync haptic feedback with video playback

### Web Interface
Visit `http://localhost:8080` to access the control panel:
- View connected devices
- Monitor bridge status
- Manually download funscripts
- Adjust intensity settings

## API Endpoints

### Bridge Status
- `GET /api/status` - Get bridge and device status
- `GET /api/devices` - List connected devices

### Funscript Management
- `POST /api/auto-funscript` - Auto-download funscript for a video
- `GET /api/funscript/{video_id}` - Get cached funscript data
- `POST /api/download-funscript` - Manually download funscript

### Device Control
- `POST /api/connect-buttplug` - Connect to Intiface Central
- `POST /api/video-event` - Send video events (play/pause/seek)

## Technical Details

### Architecture
```
Browser (Tampermonkey) ←→ Bridge Server ←→ Intiface Central ←→ Devices
```

The bridge acts as a middleware layer that:
1. Receives video events from the browser
2. Downloads and processes funscripts
3. Converts timing data to device commands
4. Communicates with Intiface Central via WebSocket

### Supported Formats
- **Funscript (.funscript)**: Industry standard interactive script format
- **Lovense Patterns**: Auto-converted to funscript format
- **Real-time Audio**: Audio level-based intensity (fallback mode)

### Device Compatibility
Works with any Buttplug.io compatible device:
- Lovense toys (Max, Nora, Lush, etc.)
- Kiiroo devices
- We-Vibe products
- Many other manufacturers

## Troubleshooting

### Common Issues

**Bridge won't connect to Intiface Central**
- Ensure Intiface Central is running
- Check that WebSocket server is enabled (port 6969)
- Verify no firewall is blocking the connection

**No funscripts found**
- Not all videos have interactive content
- Try manually searching funscript databases
- Check the video URL format is supported

**Device not responding**
- Ensure device is paired with Intiface Central
- Check device battery level
- Verify device compatibility with Buttplug.io

**Browser script not loading**
- Disable other userscripts that might conflict
- Check browser console for JavaScript errors
- Ensure Tampermonkey is properly installed

### Debug Mode
Enable debug logging by setting `debug: true` in your config file or running:
```bash
python start_bridge.py --debug
```

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## Security & Privacy

- All communication happens locally on your machine
- No data is sent to external servers except for funscript downloads
- Adult Time credentials are never accessed or stored
- Device control remains within your local network

## Legal Notice

This software is for educational and personal use only. Users are responsible for complying with all applicable laws and terms of service of the platforms they use. The developers are not affiliated with Adult Time, Intiface, or any device manufacturers.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Support

- Open an issue for bug reports or feature requests
- Check existing issues before creating new ones
- Include debug logs when reporting problems

## Acknowledgments

- [Buttplug.io](https://buttplug.io/) team for the amazing haptics framework
- [Intiface](https://intiface.com/) for the user-friendly device management
- The funscript community for content and standards
- Adult Time for providing a platform (unofficial integration) 