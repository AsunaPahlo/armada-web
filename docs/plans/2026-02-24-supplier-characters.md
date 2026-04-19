# Supplier Characters Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Allow users to mark characters as "suppliers" in the Dalamud plugin, track their ceruleum and repair kit inventory via AllaganTools, and display supplier reserves with days-of-supply on the web stats page.

**Architecture:** Plugin-side supplier designation with data flowing through the existing fleet_data WebSocket payload. The web server stores supplier data alongside plugin data (in-memory + plugin_data.json persistence). Stats page shows a new "Supplier Reserves" card with totals and per-supplier breakdown.

**Tech Stack:** C# / ImGui (Dalamud plugin), Python / Flask / Jinja2 (web), AllaganTools IPC, Socket.IO

**Item IDs:** Ceruleum Tank = 10155, Magitek Repair Materials = 10373

---

### Task 1: Add SupplierCharacter model to plugin Configuration

**Files:**
- Modify: `C:\Users\Asuna\RiderProjects\Armada\Armada\Configuration.cs`

**Step 1: Add SupplierCharacter class and Suppliers dictionary**

Add after the `Nickname` property (line 27), before the closing brace:

```csharp
    /// <summary>
    /// Characters designated as suppliers (inventory mules for ceruleum/repair materials).
    /// Key is character Content ID (CID).
    /// </summary>
    public Dictionary<ulong, SupplierCharacter> Suppliers { get; set; } = new();
}

/// <summary>
/// A character designated as a supplier of ceruleum and repair materials.
/// </summary>
public class SupplierCharacter
{
    public string Name { get; set; } = "";
    public string World { get; set; } = "";
    public uint Ceruleum { get; set; }
    public uint RepairKits { get; set; }
    public DateTime LastUpdated { get; set; } = DateTime.MinValue;
}
```

**Step 2: Verify build**

Run: `dotnet build` in the Armada solution directory.
Expected: Build succeeds with no errors.

**Step 3: Commit**

```bash
git add Armada/Configuration.cs
git commit -m "feat: add SupplierCharacter model to plugin configuration"
```

---

### Task 2: Add supplier inventory query methods to FleetDataProvider

**Files:**
- Modify: `C:\Users\Asuna\RiderProjects\Armada\Armada\FleetDataProvider.cs`

**Step 1: Add item ID constants**

Near the top of the class (after the existing `DiveCreditItemId` constant around line 12), add:

```csharp
    private const uint CeruleumTankItemId = 10155;
    private const uint RepairMaterialsItemId = 10373;
```

**Step 2: Add method to get current character info**

Add a new public method after `GetCharacterDiveCredits` (after line 780):

```csharp
    /// <summary>
    /// Get the currently logged-in character's Content ID, name, and world.
    /// Returns null if not logged in.
    /// </summary>
    public (ulong cid, string name, string world)? GetCurrentCharacterInfo()
    {
        try
        {
            return Svc.Framework.RunOnFrameworkThread(() =>
            {
                if (!Svc.ClientState.IsLoggedIn || Svc.Objects.LocalPlayer == null)
                    return ((ulong, string, string)?)null;

                var player = Svc.Objects.LocalPlayer;
                var cid = Svc.PlayerState.ContentId;
                var name = player.Name.ToString();
                var world = player.HomeWorld.Value.Name.ToString();
                return (cid, name, world);
            }).Result;
        }
        catch (Exception ex)
        {
            PluginLog.Debug($"Armada: Failed to get current character info - {ex.Message}");
            return null;
        }
    }

    /// <summary>
    /// Query the current character's ceruleum and repair materials via AllaganTools.
    /// </summary>
    public (uint ceruleum, uint repairKits) GetSupplierInventory(ulong characterId)
    {
        if (_inventoryApi == null || !_inventoryApi.IsAvailable)
            return (0, 0);

        try
        {
            var ceruleum = _inventoryApi.GetItemCount(CeruleumTankItemId, characterId);
            var repairKits = _inventoryApi.GetItemCount(RepairMaterialsItemId, characterId);
            return (ceruleum, repairKits);
        }
        catch (Exception ex)
        {
            PluginLog.Debug($"Armada: Failed to get supplier inventory for {characterId} - {ex.Message}");
            return (0, 0);
        }
    }
```

**Step 3: Add suppliers to GetFleetData payload**

In `GetFleetData()` (line 327-333), add the suppliers key to the returned dictionary. Change the return block to:

```csharp
            // Refresh supplier inventory for the currently logged-in character
            var suppliersList = GetSupplierData();

            return new Dictionary<string, object>
            {
                ["nickname"] = C.Nickname,
                ["characters"] = characters,
                ["fc_data"] = fcData,
                ["route_plans"] = routePlans,
                ["suppliers"] = suppliersList
            };
```

**Step 4: Add GetSupplierData helper**

Add after the `GetSupplierInventory` method:

```csharp
    /// <summary>
    /// Get all supplier data for transmission. Refreshes inventory for the currently logged-in
    /// character if they are a registered supplier.
    /// </summary>
    private List<Dictionary<string, object>> GetSupplierData()
    {
        var result = new List<Dictionary<string, object>>();

        // Refresh the current character's supplier data if they're registered
        var charInfo = GetCurrentCharacterInfo();
        if (charInfo.HasValue && C.Suppliers.ContainsKey(charInfo.Value.cid))
        {
            var (ceruleum, repairKits) = GetSupplierInventory(charInfo.Value.cid);
            var supplier = C.Suppliers[charInfo.Value.cid];
            supplier.Name = charInfo.Value.name;
            supplier.World = charInfo.Value.world;
            supplier.Ceruleum = ceruleum;
            supplier.RepairKits = repairKits;
            supplier.LastUpdated = DateTime.UtcNow;
            Svc.PluginInterface.SavePluginConfig(C);
        }

        // Build list of all suppliers
        foreach (var (cid, supplier) in C.Suppliers)
        {
            result.Add(new Dictionary<string, object>
            {
                ["cid"] = cid.ToString(),
                ["name"] = supplier.Name,
                ["world"] = supplier.World,
                ["ceruleum"] = supplier.Ceruleum,
                ["repair_kits"] = supplier.RepairKits,
                ["last_updated"] = supplier.LastUpdated.ToString("o")
            });
        }

        return result;
    }
```

**Step 5: Verify build**

Run: `dotnet build`
Expected: Build succeeds.

**Step 6: Commit**

```bash
git add Armada/FleetDataProvider.cs
git commit -m "feat: add supplier inventory query and fleet data inclusion"
```

---

### Task 3: Add Supplier UI section to ConfigWindow

**Files:**
- Modify: `C:\Users\Asuna\RiderProjects\Armada\Armada\Windows\ConfigWindow.cs`

**Step 1: Add DrawSupplierSection call to Draw()**

In the `Draw()` method (line 29-64), add the supplier section after the AutoRetainer status block (after line 50). Insert between the cache status block and the setup instructions:

```csharp
        // Supplier Characters Section
        ImGui.Spacing();
        DrawSectionHeader("Supplier Characters");
        DrawSupplierSection();
```

**Step 2: Implement DrawSupplierSection()**

Add after `DrawCacheStatus()` (after line 380):

```csharp
    private void DrawSupplierSection()
    {
        ImGui.Indent(4);

        // Check AllaganTools availability
        if (!P.FleetDataProvider.IsAllaganToolsAvailable)
        {
            ImGui.TextColored(SubtleTextColor, "Requires AllaganTools to track supplier inventory.");
            ImGui.Unindent(4);
            return;
        }

        // Current character info
        var charInfo = P.FleetDataProvider.GetCurrentCharacterInfo();
        if (charInfo.HasValue)
        {
            var (cid, name, world) = charInfo.Value;
            var isSupplier = C.Suppliers.ContainsKey(cid);

            ImGui.TextUnformatted($"Current: {name} @ {world}");
            ImGui.SameLine();

            if (isSupplier)
            {
                if (ImGui.SmallButton("Remove as Supplier"))
                {
                    C.Suppliers.Remove(cid);
                    Svc.PluginInterface.SavePluginConfig(C);
                }
            }
            else
            {
                if (ImGui.SmallButton("Mark as Supplier"))
                {
                    var (ceruleum, repairKits) = P.FleetDataProvider.GetSupplierInventory(cid);
                    C.Suppliers[cid] = new SupplierCharacter
                    {
                        Name = name,
                        World = world,
                        Ceruleum = ceruleum,
                        RepairKits = repairKits,
                        LastUpdated = DateTime.UtcNow
                    };
                    Svc.PluginInterface.SavePluginConfig(C);
                }
            }
        }
        else
        {
            ImGui.TextColored(SubtleTextColor, "Log in to a character to manage suppliers.");
        }

        // List registered suppliers
        if (C.Suppliers.Count > 0)
        {
            ImGui.Spacing();
            ImGui.TextColored(SubtleTextColor, $"Registered Suppliers ({C.Suppliers.Count}):");
            ImGui.Spacing();

            ulong? removeKey = null;
            foreach (var (cid, supplier) in C.Suppliers)
            {
                var isCurrentChar = charInfo.HasValue && charInfo.Value.cid == cid;
                var nameDisplay = isCurrentChar ? $"{supplier.Name}*" : supplier.Name;

                ImGui.TextUnformatted($"  {nameDisplay} @ {supplier.World}");
                ImGui.SameLine();
                ImGui.TextColored(SubtleTextColor, $"- Ceruleum: {supplier.Ceruleum:N0}  Repair: {supplier.RepairKits:N0}");

                ImGui.SameLine();
                ImGui.PushID($"remove_{cid}");
                if (ImGui.SmallButton("X"))
                {
                    removeKey = cid;
                }
                ImGui.PopID();

                // Show last updated time
                if (supplier.LastUpdated > DateTime.MinValue)
                {
                    var ago = DateTime.UtcNow - supplier.LastUpdated;
                    var agoStr = ago.TotalHours < 1 ? $"{ago.Minutes}m ago" :
                                 ago.TotalDays < 1 ? $"{ago.Hours}h ago" :
                                 $"{ago.Days}d ago";
                    ImGui.TextColored(SubtleTextColor, $"    Last updated: {agoStr}");
                }
            }

            if (removeKey.HasValue)
            {
                C.Suppliers.Remove(removeKey.Value);
                Svc.PluginInterface.SavePluginConfig(C);
            }
        }

        ImGui.Unindent(4);
    }
```

**Step 3: Verify build**

Run: `dotnet build`
Expected: Build succeeds.

**Step 4: Commit**

```bash
git add Armada/Windows/ConfigWindow.cs
git commit -m "feat: add supplier management UI to plugin config window"
```

---

### Task 4: Handle supplier data on the web server (WebSocket + FleetManager)

**Files:**
- Modify: `C:\Users\Asuna\PycharmProjects\Armada-web\app\routes\websocket.py`
- Modify: `C:\Users\Asuna\PycharmProjects\Armada-web\app\services\fleet_manager.py`

**Step 1: Extract supplier data in websocket handler**

In `websocket.py`, the `on_fleet_data` method decompresses the payload into `accounts` (line 203/213). The decompressed data is the full plugin payload dict containing `characters`, `fc_data`, `route_plans`, and now `suppliers`. However, looking at the code, `accounts` is extracted from the top-level decompressed data.

We need to understand the data flow: the plugin sends `fleet_data` with a `data` field that is gzip+base64 encoded. When decompressed, it's the full dict from `GetFleetData()` — containing `nickname`, `characters`, `fc_data`, `route_plans`, and now `suppliers`.

Check how `decompress_data` works and what `accounts` actually contains. The decompressed data is the full dict, and `accounts` is extracted later. Look at how the websocket currently processes it.

Reading the code more carefully: `accounts = decompress_data(compressed_data)` returns the decompressed JSON. Then `_plugin_data[plugin_id]['accounts'] = accounts` stores it. Then `fleet.set_plugin_data(plugin_id, accounts, ...)` is called.

The key question: does `decompress_data` return the full dict or just the accounts list? Let's check.

In the websocket handler (line 213): `accounts = data.get('accounts', [])` for uncompressed. For compressed (line 203): `accounts = decompress_data(compressed_data)`.

Looking at the ArmadaClient.cs, the plugin serializes `accountsData` (which is the full dict from `GetFleetData()`) and compresses it. So `decompress_data` returns the full dict `{"nickname": ..., "characters": [...], "fc_data": {...}, "route_plans": {...}, "suppliers": [...]}`.

But the variable is named `accounts` and is passed directly to `fleet.set_plugin_data(plugin_id, accounts, ...)`. Let's check what `set_plugin_data` expects — it takes `accounts_data: list[dict]` which is iterated as a list of account dicts.

This means the decompressed data must be a list of account dicts (the `characters` array), not the full dict. Let me re-read the plugin's send code.

In ArmadaClient.cs line 376: `JsonSerializer.Serialize(accountsData)` where `accountsData` is from `GetFleetData()`. But `GetFleetData()` returns a `Dictionary<string, object>` — so the serialized data IS the full dict.

On the web side, `decompress_data` returns this dict. But then it's used as `accounts` directly. This means the web side must be handling this differently, or the decompressed data IS a list.

Actually, re-reading more carefully: `SendFleetDataAsync` receives `accountsData` which is `GetFleetData()` result — a dict. When the web side gets it via `decompress_data`, it gets the dict. Then `accounts = decompress_data(...)`. Then `fleet.set_plugin_data(plugin_id, accounts, ...)` where `accounts` is the full dict. But `set_plugin_data` expects `list[dict]` and iterates it.

This inconsistency suggests the decompressed data is actually a list. Let me check `decompress_data`.

Actually — looking at it again, the dict keys are `nickname`, `characters`, `fc_data`, `route_plans`. The web side stores `_plugin_data[plugin_id]['accounts'] = accounts` (line 220). Then `fleet.set_plugin_data(plugin_id, accounts)` is called. In `set_plugin_data`, it iterates `accounts_data` and calls `self.parser.parse_plugin_data(account_data)` for each. `parse_plugin_data` expects a single account dict with keys like `character`, `submarines`, etc.

So `accounts` from decompression must be a LIST of account dicts (the `characters` list), not the full dict. This means the plugin is compressing just the `characters` list, not the full dict.

Wait, no. Let me re-read ArmadaClient.cs. Line 376: `var jsonData = JsonSerializer.Serialize(accountsData)` where `accountsData` is from `P.FleetDataProvider.GetFleetData()`. `GetFleetData()` returns a Dict with keys: `nickname`, `characters`, `fc_data`, `route_plans`.

So when decompressed on the web side, the result IS the full dict. But then how does `set_plugin_data` work with it? It calls `for account_data in accounts_data` — iterating a dict iterates its keys.

This needs more investigation. Let me check the actual websocket handler and decompress function.

In `websocket.py` line 200-213:
```python
if data.get('compressed', False):
    accounts = decompress_data(compressed_data)
else:
    accounts = data.get('accounts', [])
```

For the uncompressed case, it expects `data['accounts']` to be a list. For the compressed case, it just assigns the decompressed result. If the plugin sends the full dict as compressed, then `accounts` would be a dict, which would break the downstream code.

But the system works in production, so something must be right. Perhaps the plugin restructures the data before compression, or perhaps `set_plugin_data` handles both formats.

Let me check — maybe the full payload dict from the plugin has a different format. Looking at ArmadaClient lines 355-409 more carefully.

Actually, I think I need to just read the actual send code more carefully and the decompress utility.

Let me continue writing the plan with the assumption that the compressed payload IS the full dict from GetFleetData(), and that the websocket handler needs to be updated to extract `suppliers` from it before passing `characters` to set_plugin_data. This is likely already handling the dict format somehow (maybe parse_plugin_data handles it), or perhaps the accounts format in the compressed data IS just a list.

For the plan, I'll modify the websocket handler to extract suppliers from the decompressed data if present, alongside the existing accounts extraction.

**Detailed modification to websocket.py on_fleet_data (lines 200-229):**

After the decompression/extraction block (after line 213), add supplier extraction:

```python
        # Extract supplier data if present
        suppliers = []
        if isinstance(accounts, dict):
            # Compressed payload is the full plugin dict
            suppliers = accounts.get('suppliers', [])
            # accounts_data is what we pass to fleet manager
            # (the full dict is handled by set_plugin_data)
        elif isinstance(accounts, list):
            # Already a list of account dicts
            pass
```

Actually, this approach is fragile. A better approach: modify `set_plugin_data` to accept optional `suppliers` data. Update the websocket to extract suppliers from the decompressed payload if present.

After the decompression/extraction of `accounts` (line 213), and before storing in `_plugin_data` (line 217), add:

```python
        # Extract supplier data if present in the payload
        suppliers = None
        if isinstance(accounts, dict):
            suppliers = accounts.get('suppliers', [])
```

Then pass `suppliers` to `fleet.set_plugin_data`:
```python
            fleet.set_plugin_data(plugin_id, accounts, timestamp=timestamp, received_at=received_at, suppliers=suppliers)
```

**Step 2: Add supplier storage to FleetManager**

In `fleet_manager.py`, add a `_supplier_data` dict to `__init__` (after line 44):

```python
        self._supplier_data: dict[str, list[dict]] = {}  # plugin_id -> list of supplier dicts
```

**Step 3: Update set_plugin_data to accept suppliers**

Add `suppliers: list[dict] = None` parameter to `set_plugin_data` (line 301). After the existing persistence block (line 362), add:

```python
            # Store supplier data if provided
            if suppliers is not None:
                self._supplier_data[plugin_id] = suppliers
                self._save_plugin_data()
```

**Step 4: Update _save_plugin_data to include suppliers**

In `_save_plugin_data` (lines 113-120), add supplier data to the save structure:

```python
                save_data[plugin_id] = {
                    'accounts': accounts_data,
                    'timestamp': metadata.get('timestamp'),
                    'received_at': metadata.get('received_at'),
                    'suppliers': self._supplier_data.get(plugin_id, [])
                }
```

**Step 5: Update _load_plugin_data to restore suppliers**

In `_load_plugin_data` (lines 67-78), after loading accounts and metadata, add:

```python
                    # Load supplier data
                    if isinstance(plugin_entry, dict):
                        suppliers = plugin_entry.get('suppliers', [])
                        if suppliers:
                            self._supplier_data[plugin_id] = suppliers
```

**Step 6: Add get_supplier_summary method**

Add a new method to FleetManager after `get_dashboard_data`:

```python
    def get_supplier_summary(self) -> dict:
        """
        Get aggregated supplier character data.

        Returns dict with:
            - suppliers: list of individual supplier entries
            - total_ceruleum: total across all suppliers
            - total_repair_kits: total across all suppliers
            - ceruleum_days: days of supply based on global consumption
            - repair_days: days of supply based on global consumption
        """
        all_suppliers = []
        total_ceruleum = 0
        total_repair_kits = 0

        for plugin_id, suppliers in self._supplier_data.items():
            for s in suppliers:
                ceruleum = s.get('ceruleum', 0)
                repair_kits = s.get('repair_kits', 0)
                total_ceruleum += ceruleum
                total_repair_kits += repair_kits
                all_suppliers.append({
                    'name': s.get('name', 'Unknown'),
                    'world': s.get('world', ''),
                    'ceruleum': ceruleum,
                    'repair_kits': repair_kits,
                    'last_updated': s.get('last_updated', '')
                })

        # Get consumption rates from dashboard data
        dashboard = self.get_dashboard_data()
        forecast = dashboard.get('supply_forecast', {})
        ceruleum_per_day = forecast.get('ceruleum_per_day', 0)
        kits_per_day = forecast.get('kits_per_day', 0)

        ceruleum_days = total_ceruleum / ceruleum_per_day if ceruleum_per_day > 0 else None
        repair_days = total_repair_kits / kits_per_day if kits_per_day > 0 else None

        return {
            'suppliers': all_suppliers,
            'total_ceruleum': total_ceruleum,
            'total_repair_kits': total_repair_kits,
            'ceruleum_days': round(ceruleum_days, 1) if ceruleum_days is not None else None,
            'repair_days': round(repair_days, 1) if repair_days is not None else None
        }
```

**Step 7: Commit**

```bash
git add app/routes/websocket.py app/services/fleet_manager.py
git commit -m "feat: handle supplier data in websocket handler and fleet manager"
```

---

### Task 5: Add supplier data to stats route and template

**Files:**
- Modify: `C:\Users\Asuna\PycharmProjects\Armada-web\app\routes\stats.py`
- Modify: `C:\Users\Asuna\PycharmProjects\Armada-web\app\templates\stats.html`

**Step 1: Pass supplier data from stats route**

In `stats.py` `index()` (around line 252), after getting supply_data, add:

```python
    # Get supplier reserve data
    supplier_data = fleet.get_supplier_summary()
```

Then add `supplier_data=supplier_data` to the `render_template` call (line 257-268):

```python
    return render_template('stats.html',
                           summary=summary,
                           daily_stats=daily,
                           region_counts=region_counts,
                           fleet_summary=filtered_summary,
                           supply_data=supply_data,
                           supplier_data=supplier_data,
                           fleet_chart_data=fleet_chart_data,
                           days=days,
                           all_tags=all_tags,
                           exclude_tag_ids=exclude_tag_ids,
                           active_regions=active_regions,
                           all_regions=ALL_REGIONS)
```

**Step 2: Add Supplier Reserves card to stats.html**

Insert a new row after the supply chart row (after line 228, after `</div>` closing the Charts Row 3). Add:

```html
<!-- Supplier Reserves -->
{% if supplier_data and supplier_data.suppliers %}
<div class="row mb-4">
    <div class="col-12">
        <div class="card">
            <div class="card-header">
                <h5 class="mb-0"><i class="bi bi-box-seam"></i> Supplier Reserves</h5>
            </div>
            <div class="card-body">
                <!-- Summary row -->
                <div class="row text-center mb-3">
                    <div class="col-md-3">
                        <h6 class="text-muted mb-1">Total Ceruleum</h6>
                        <h3 class="mb-0">{{ "{:,.0f}".format(supplier_data.total_ceruleum) }}</h3>
                    </div>
                    <div class="col-md-3">
                        <h6 class="text-muted mb-1">Total Repair Materials</h6>
                        <h3 class="mb-0">{{ "{:,.0f}".format(supplier_data.total_repair_kits) }}</h3>
                    </div>
                    <div class="col-md-3">
                        <h6 class="text-muted mb-1">Ceruleum Days</h6>
                        {% if supplier_data.ceruleum_days is not none %}
                        <h3 class="mb-0 {% if supplier_data.ceruleum_days >= 30 %}text-success{% elif supplier_data.ceruleum_days >= 14 %}text-warning{% else %}text-danger{% endif %}">
                            {{ supplier_data.ceruleum_days }}
                        </h3>
                        {% else %}
                        <h3 class="mb-0 text-muted">N/A</h3>
                        {% endif %}
                    </div>
                    <div class="col-md-3">
                        <h6 class="text-muted mb-1">Repair Days</h6>
                        {% if supplier_data.repair_days is not none %}
                        <h3 class="mb-0 {% if supplier_data.repair_days >= 30 %}text-success{% elif supplier_data.repair_days >= 14 %}text-warning{% else %}text-danger{% endif %}">
                            {{ supplier_data.repair_days }}
                        </h3>
                        {% else %}
                        <h3 class="mb-0 text-muted">N/A</h3>
                        {% endif %}
                    </div>
                </div>
                <!-- Per-supplier table -->
                <div class="table-responsive">
                    <table class="table table-sm table-hover mb-0">
                        <thead>
                            <tr>
                                <th>Character</th>
                                <th>World</th>
                                <th class="text-end">Ceruleum</th>
                                <th class="text-end">Repair Materials</th>
                                <th class="text-end">Last Updated</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for s in supplier_data.suppliers %}
                            <tr>
                                <td>{{ s.name }}</td>
                                <td>{{ s.world }}</td>
                                <td class="text-end">{{ "{:,.0f}".format(s.ceruleum) }}</td>
                                <td class="text-end">{{ "{:,.0f}".format(s.repair_kits) }}</td>
                                <td class="text-end text-muted">
                                    {% if s.last_updated %}
                                    {{ s.last_updated[:16].replace('T', ' ') }}
                                    {% else %}
                                    Never
                                    {% endif %}
                                </td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>
</div>
{% endif %}
```

**Step 3: Commit**

```bash
git add app/routes/stats.py app/templates/stats.html
git commit -m "feat: display supplier reserves on stats page"
```

---

### Task 6: Test end-to-end and verify

**Step 1: Start the web server**

Run: `python run.py` from the Armada-web directory.
Expected: Server starts without errors.

**Step 2: Verify stats page loads without supplier data**

Navigate to the stats page in browser. The supplier reserves card should NOT appear (no suppliers registered yet).

**Step 3: Verify plugin builds**

Run: `dotnet build` in the Armada solution directory.
Expected: Build succeeds.

**Step 4: Manual test with plugin (when available)**

1. Load the plugin in-game
2. Open config window — verify "Supplier Characters" section appears
3. If AllaganTools is not installed, verify it shows the "requires AllaganTools" message
4. If AllaganTools IS available, click "Mark as Supplier" for current character
5. Verify supplier appears in the list with ceruleum/repair counts
6. Click "Send Now" to push fleet data
7. Check stats page — supplier reserves card should appear with data
8. Remove supplier and verify it disappears

**Step 5: Final commit**

```bash
git add -A
git commit -m "feat: supplier characters feature - plugin marking + web stats display"
```