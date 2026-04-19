# Armada Project Overview

This document provides context for Claude Code when working on the Armada ecosystem.

## Related Projects

| Project | Location | Type |
|---------|----------|------|
| Armada-web | `C:\Users\Asuna\PycharmProjects\Armada-web` | Flask web dashboard |
| Armada Plugin | `C:\Users\Asuna\RiderProjects\Armada` | Dalamud game plugin (C#) |

## What is Armada?

Armada is a **real-time submarine and airship fleet monitoring system** for Final Fantasy XIV. It tracks submarine voyages across multiple player accounts and Free Companies (guilds).

---

## Armada-web (This Project)

### Tech Stack
- **Backend**: Flask 3.1.2 (Python)
- **Real-time**: Flask-SocketIO with WebSocket
- **Database**: SQLite at `data/armada.db`
- **ORM**: Flask-SQLAlchemy
- **Auth**: Flask-Login
- **Scheduler**: APScheduler
- **Server**: Gunicorn with Gevent

### Key Features
- Real-time submarine status tracking
- Multi-account and multi-FC support
- Voyage history and loot tracking
- Supply forecasting (ceruleum, repair kits)
- Statistics and profit analysis
- Alert system (Email, Discord, Pushover)
- REST API v1 for external access
- Mobile/PWA support

### Project Structure
```
app/
├── models/          # SQLAlchemy models (user, voyage, api_key, etc.)
├── routes/          # Flask blueprints
│   ├── websocket.py # Plugin WebSocket interface (/plugin namespace)
│   ├── api_v1.py    # External REST API
│   ├── dashboard.py # Main web views
│   └── ...
├── services/        # Business logic
│   ├── fleet_manager.py    # Main orchestrator
│   ├── config_parser.py    # Parses submarine data
│   ├── stats_tracker.py    # Statistics
│   ├── alert_service.py    # Notifications
│   └── ...
├── static/          # Frontend assets
├── templates/       # Jinja2 templates
└── utils/           # Utilities (crypto, logging)
```

### Entry Points
- **Development**: `run.py`
- **Production**: `wsgi.py` (via gunicorn)

### Key Configuration
- `.env` file for environment variables
- `app/config.py` for Flask configuration
- Database at `data/armada.db`

---

## Armada Plugin (C# Dalamud)

### Tech Stack
- **Language**: C# (.NET 10.0-windows7.0)
- **Framework**: Dalamud (FFXIV plugin framework)
- **Communication**: SocketIOClient 3.1.1
- **Dependencies**: ECommons, FFXIVClientStructs, Lumina

### Key Components
- `Plugin.cs` - Plugin lifecycle and initialization
- `ArmadaClient.cs` - WebSocket client for server communication
- `FleetDataProvider.cs` - Data collection from AutoRetainer
- `VoyageLootHook.cs` - Game packet hooking for loot capture
- `DataCache.cs` - Offline data caching
- `Configuration.cs` - Plugin settings
- `ConfigWindow.cs` - ImGui settings UI

### Required Plugins
- **AutoRetainer** - Provides submarine data via IPC (mandatory)
- **AllaganTools** - Optional inventory tracking

---

## Plugin ↔ Web Communication

### Protocol
- **Transport**: Socket.IO WebSocket
- **Namespace**: `/plugin`
- **Authentication**: API key (64-char hex)
- **Compression**: GZIP + Base64 for fleet data

### Message Flow
```
Plugin                          Server
   │                              │
   ├─── authenticate ───────────→│  (API key, nickname, version)
   │←── auth_response ───────────┤  (success/failure)
   │                              │
   ├─── fleet_data ─────────────→│  (compressed submarine data)
   │←── data_response ───────────┤  (acknowledgment)
   │                              │
   ├─── voyage_loot ────────────→│  (completed voyage loot)
   │←── loot_response ───────────┤  (acknowledgment)
   │                              │
   ├─── ping ───────────────────→│
   │←── pong ────────────────────┤
```

### Fleet Data Structure
```json
{
  "api_key": "64-char-hex",
  "timestamp": "ISO8601",
  "compressed": true,
  "data": "base64-gzip-encoded-accounts-array"
}
```

### Account Data (after decompression)
```json
{
  "character": "Character Name",
  "cid": "character_id",
  "world": "Server Name",
  "fc_id": "free_company_id",
  "Gil": 10000000,
  "CurrentCeruleum": 1000,
  "CurrentRepairKits": 500,
  "Submarines": [{
    "Name": "Submarine Name",
    "Level": 90,
    "CurrentExp": 12345,
    "ReturnTime": "ISO8601",
    "Route": ["A", "B", "C", "D"],
    "Parts": [21792, 21793, 21794, 21795]
  }]
}
```

---

## REST API v1

**Base**: `/api/v1/*`
**Auth**: `Authorization: Bearer <api_key>`

| Endpoint | Description |
|----------|-------------|
| `GET /dashboard` | Full dashboard data |
| `GET /submarines` | All submarines list |
| `GET /submarines/ready` | Ready submarines |
| `GET /submarines/voyaging` | Active voyages |
| `GET /status` | Fleet summary |
| `GET /fc` | List all FCs |
| `GET /fc/<id>` | Specific FC data |
| `GET /supply` | Supply forecast |

---

## Data Flow

```
FFXIV Game Client
       ↓
  AutoRetainer Plugin (reads submarine data)
       ↓
  Armada Dalamud Plugin
       ↓ (Socket.IO WebSocket)
  Armada Web Server
       ├── FleetManager (orchestrates)
       ├── SQLite Database
       ├── Alert Service
       └── REST/WebSocket APIs
              ↓
  Web Browser Dashboard
```

---

## Development Notes

### Running Armada-web
```bash
# Development
python run.py

# Production (Docker)
docker-compose up -d
```

### Key Environment Variables
- `ARMADA_HOST` - Server bind address
- `ARMADA_PORT` - Server port (default: 5000)
- `SECRET_KEY` - Session/encryption key (required for production)
- `ARMADA_USERNAME` / `ARMADA_PASSWORD` - Initial admin credentials

### Database Models
- `User` - User accounts with roles (admin/read-only)
- `ApiKey` - Plugin authentication keys
- `Voyage` / `VoyageStats` - Voyage tracking
- `VoyageLoot` - Loot records
- `AlertSettings` / `AlertHistory` - Alert configuration
- `Tag` - FC organization tags
- `DailyStats` - Aggregated daily statistics
- `ActivityLog` - Event logging

### Security
- Session cookies: HTTPOnly, SameSite=Lax
- API keys: 64-char hex generated with secrets module
- Sensitive data encrypted with SECRET_KEY
- Account lockout after 5 failed logins (30 min)
