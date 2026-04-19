# Supplier Characters Feature Design

## Problem

Users keep extra ceruleum and repair materials on dedicated "supplier" characters that restock FC workshops. There's no way to track these reserves or know how many days of supplies are stored across supplier characters.

## Solution

Add a supplier designation system: the Dalamud plugin lets users mark any logged-in character as a supplier, queries their inventory via AllaganTools, and sends supplier data to the web server as part of the existing fleet_data payload. The web stats page displays total supplier reserves and days-of-supply calculations.

## Tracked Items

- **Ceruleum Tank**: Item ID 10155
- **Magitek Repair Materials**: Item ID 10373

## Plugin Changes (C# / Dalamud)

### Configuration

New fields in `Configuration.cs`:

```csharp
public Dictionary<ulong, SupplierCharacter> Suppliers { get; set; } = new();
```

`SupplierCharacter` stores: Name, World, CID, Ceruleum count, RepairKits count, LastUpdated timestamp.

### Config UI

New "Supplier" section in `ConfigWindow.cs`:

- Shows current character name/world
- "Mark as Supplier" / "Remove as Supplier" toggle
- Requires AllaganTools to be installed (show warning if not)
- Lists all registered suppliers with counts and "Remove" buttons

### Data Collection

In `FleetDataProvider.cs`:

- If the currently logged-in character is a registered supplier, refresh their ceruleum/repair counts via AllaganTools IPC before sending fleet data
- Add `"suppliers"` key to the fleet data payload containing all supplier entries

### Payload Addition

```json
{
  "suppliers": [
    {
      "name": "Character Name",
      "world": "Server",
      "cid": "content_id",
      "ceruleum": 5000,
      "repair_kits": 3000,
      "last_updated": "ISO8601"
    }
  ]
}
```

## Web Server Changes (Python / Flask)

### WebSocket Handler

`websocket.py`: Extract `suppliers` from decompressed fleet data and pass to FleetManager.

### FleetManager

`fleet_manager.py`:

- Store supplier data in plugin data structure (persisted to `plugin_data.json`)
- New method `get_supplier_summary()` returning:
  - List of supplier characters with inventory counts
  - Total ceruleum / repair kits across all suppliers
  - Days of ceruleum supply = total supplier ceruleum / global ceruleum_per_day
  - Days of repair kit supply = total supplier repair kits / global kits_per_day

### No New Database Models

Supplier data is transient and stored in-memory with plugin data, persisted via `plugin_data.json`.

### Stats Route

`stats.py`: Call `get_supplier_summary()` and pass to template.

## Stats Page UI

New "Supplier Reserves" card on the stats page:

- **Summary**: Total ceruleum | Total repair kits across all suppliers
- **Days of supply**: Ceruleum days | Repair kit days (based on global FC consumption rates)
- **Per-supplier table**: Character | World | Ceruleum | Repair Kits | Last Updated

### Color Thresholds (for days-of-supply)

- Green: 30+ days
- Yellow: 14-30 days
- Red: < 14 days

## Constraints

- AllaganTools must be installed in the game for supplier inventory queries
- Supplier data only refreshes when the user is logged into that character and the plugin is running
- Characters may or may not also have submarines (both cases supported)
- Supply calculation uses global FC consumption (all non-excluded FCs combined)
