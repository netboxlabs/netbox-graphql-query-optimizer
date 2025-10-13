# NetBox GraphQL Query Optimizer

Find and fix slow GraphQL queries in your NetBox instance **before** they cause performance problems.

This tool analyzes your GraphQL queries and tells you:
- 🚨 Which queries will be expensive to run
- ⚠️ Common anti-patterns that cause slowdowns
- 💡 Specific recommendations to make queries faster

**No NetBox changes required** - this is a standalone analysis tool.

---

## Quick Start

### 1. Install

```bash
git clone https://github.com/netboxlabs/netbox-graphql-query-optimizer.git
cd netbox-graphql-query-optimizer
uv venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
uv pip install -e .
```

### 2. Calibrate with Your NetBox Data

Run calibration to get accurate complexity scores based on your actual data:

```bash
netbox-gqo calibrate --url https://your-netbox.com/ --token YOUR_API_TOKEN
```

This reads actual counts from your NetBox (devices, interfaces, IPs, etc.) and caches them for accurate analysis.

### 3. Analyze Your First Query

Save your GraphQL query to a file (e.g., `my-query.graphql`):

```graphql
query GetDevices {
  device_list {
    id
    name
    interfaces {
      name
      ip_addresses {
        address
      }
    }
  }
}
```

Run the analyzer:

```bash
netbox-gqo analyze my-query.graphql --url https://your-netbox.com/
```

You'll get instant feedback:

```
Query Analysis Summary

 Depth       3
 Complexity  20500  ⚠️ HIGH!
 Est. Rows   10000

Recommendations:

  ⚠ pagination: List field 'device_list' has no pagination args
  ⚠ pagination: List field 'interfaces' has no pagination args
  ⚠ pagination: List field 'ip_addresses' has no pagination args
  ⚠ fanout: 3 list→list nests without pagination
```

---

## Understanding the Output

### Complexity Score

The complexity score estimates how expensive your query is to run:

| Score | Severity | What It Means |
|-------|----------|---------------|
| **< 50** | ✅ Good | Fast query, safe for production |
| **50-200** | ⚠️ Moderate | May be slow, consider optimizing |
| **200-500** | 🔥 High | Will be slow, should optimize |
| **> 500** | 🚨 Critical | Very expensive, must optimize |

**How it's calculated:**

```
Complexity = Σ (Type Weight × Estimated Rows)
```

- **Type Weight:** How expensive each object type is to fetch
  - Device: 3 (heaviest - lots of relationships)
  - Interface: 2 (medium)
  - IPAddress: 1 (lightweight)
  - VirtualMachine: 3
  - Cable: 2
  - Circuit: 2
  - Rack: 2
  - Site: 2
  - VLAN: 1
  - Other types: 1 (default)

- **Estimated Rows:** Number of items the query will fetch
  - If you use `limit`: that number
  - Otherwise: actual count from your NetBox (if calibrated) or 100 (default)

**Example:**

```graphql
device_list(pagination: {limit: 10}) {
  interfaces(pagination: {limit: 5}) {
    ip_addresses(pagination: {limit: 2})
  }
}
```

Score = `(10 devices × 3) + (50 interfaces × 2) + (100 IPs × 1) = 230`

### Common Warnings

#### ⚠️ Missing Pagination

```
⚠ pagination: List field 'device_list' has no pagination args
```

**Problem:** Without pagination, the query fetches ALL items (could be thousands).

**Fix:** Add pagination:

```graphql
# ❌ Bad - fetches all devices
device_list {
  id
  name
}

# ✅ Good - fetches only 20 devices
device_list(pagination: {offset: 0, limit: 20}) {
  id
  name
}
```

#### ⚠️ Fan-out Pattern

```
⚠ fanout: 2 list→list nests without pagination
```

**Problem:** Nested lists multiply! 100 devices × 10 interfaces = 1,000 database queries.

**Fix:** Add pagination at each level:

```graphql
# ❌ Bad - 100 × 50 × 10 = 50,000 items!
device_list {
  interfaces {
    ip_addresses {
      address
    }
  }
}

# ✅ Good - 20 × 5 × 2 = 200 items
device_list(pagination: {limit: 20}) {
  interfaces(pagination: {limit: 5}) {
    ip_addresses(pagination: {limit: 2}) {
      address
    }
  }
}
```

#### ⚠️ Excessive Depth

```
⚠ depth: Depth 7 > 5
```

**Problem:** Deeply nested queries are hard to optimize and can cause timeouts.

**Fix:** Simplify your query or make separate queries.

#### ℹ️ Filter Suggestions

```
• filter-pushdown: Consider applying filters at 'device_list' using: filters
```

**Recommendation:** Use filters to reduce the number of items:

```graphql
# ✅ Better - filter before fetching
device_list(
  pagination: {limit: 50}
  filters: {site: "DC1", status: "active"}
) {
  id
  name
}
```

#### ⚠️ Overfetching Fields

```
⚠ overfetch: Query requests 87 total fields (consider requesting only necessary fields)
```

**Problem:** Requesting too many fields increases payload size, database load, and response time. Every field requires database access and serialization.

**Fix:** Only request fields you actually need:

```graphql
# ❌ Bad - requesting 87 fields including many unused ones
device_list(pagination: {limit: 100}) {
  id
  name
  serial
  status
  asset_tag
  comments
  created
  last_updated
  # ... 79 more fields including deep nesting
  interfaces {
    # many fields...
    ip_addresses {
      # many fields...
    }
  }
}

# ✅ Good - only request what you need (15 fields)
device_list(pagination: {limit: 100}) {
  id
  name
  serial
  status
  site {
    name
  }
  primary_ip4 {
    address
  }
}
```

**Thresholds:**
- > 50 fields: INFO warning (consider trimming)
- > 75 fields: WARN warning (definitely trim unused fields)
- Per-object > 15 fields: Breadth warning (may be requesting too much from one object)

---

## Real-World Example

### Before Optimization

```graphql
query BadQuery {
  device_list {
    name
    interfaces {
      name
      ip_addresses {
        address
      }
    }
  }
}
```

**Analysis:**
```
Complexity: 20,500  🚨 CRITICAL
Est. Rows: 10,000
Warnings: 3 pagination issues, fan-out detected
```

### After Optimization

```graphql
query GoodQuery {
  device_list(
    pagination: {limit: 20}
    filters: {status: "active"}
  ) {
    name
    interfaces(pagination: {limit: 5}) {
      name
      ip_addresses(pagination: {limit: 2}) {
        address
      }
    }
  }
}
```

**Analysis:**
```
Complexity: 17  ✅ GOOD
Est. Rows: 20
Warnings: None
```

**Result:** **1,200× faster!** (20,500 → 17)

---

## Advanced Usage

### Calibration for Accurate Complexity Scoring

Calibration is essential for getting accurate complexity scores. Without calibration, the tool uses default estimates (100 items per list). With calibration, it uses your actual NetBox data counts.

**How it works:**

1. **Probes your NetBox REST API** - Reads actual counts for each object type (devices, interfaces, IPs, etc.)
2. **Caches the results** - Stores counts in `~/.netbox-gqo/calibration/<host>.json`
3. **Uses real data in analysis** - When analyzing queries, multiplies type weights by your actual counts instead of defaults

**Example impact:**

| Without Calibration | With Calibration (Your Data) |
|---------------------|------------------------------|
| Assumes 100 devices | Uses your actual count (e.g., 2,500 devices) |
| Assumes 100 interfaces per device | Uses your actual count (e.g., 15 interfaces avg) |
| **Score: 300** | **Score: 7,800** (reflects reality) |

**Running calibration:**

```bash
# Basic calibration (requires API token)
netbox-gqo calibrate --url https://your-netbox.com/ --token YOUR_API_TOKEN

# Query-specific calibration (only probes types used in your query)
netbox-gqo calibrate --url https://your-netbox.com/ --token YOUR_API_TOKEN --query my-query.graphql
```

**What gets calibrated:**

The tool probes these NetBox REST endpoints:
- `/api/dcim/devices/` → Device count
- `/api/dcim/interfaces/` → Interface count
- `/api/ipam/ip-addresses/` → IP address count
- `/api/virtualization/virtual-machines/` → VM count
- `/api/dcim/cables/` → Cable count
- `/api/circuits/circuits/` → Circuit count
- `/api/dcim/racks/` → Rack count
- `/api/dcim/sites/` → Site count
- `/api/ipam/vlans/` → VLAN count

You can customize the type mappings in your config file to add more types or adjust endpoints.

**When to recalibrate:**

- After significant data changes (added/removed many devices)
- Periodically (monthly/quarterly) for production systems
- Before analyzing queries for capacity planning

### CI/CD Integration

Fail builds if queries are too complex:

```bash
# In your CI pipeline
netbox-gqo analyze query.graphql \
  --url https://netbox.com/ \
  --fail-on-score 200 \
  --output json
```

Exit codes:
- `0` = Query is okay
- `2` = Query exceeds complexity threshold

### JSON Output

For automation and tooling:

```bash
netbox-gqo analyze query.graphql --url https://netbox.com/ --output json
```

```json
{
  "score": 410,
  "depth": 3,
  "fanout": 2,
  "rows": 400,
  "findings": [
    {
      "rule_id": "pagination",
      "message": "List field 'device_list' has no pagination args",
      "severity": "WARN"
    }
  ]
}
```

### Configuration File

Create `~/.netbox-gqo/config.yaml` for custom settings:

```yaml
# Your NetBox URL
default_url: https://netbox.example.com/

# Thresholds (defaults shown)
max_depth: 5            # Warn if query nests deeper than this
max_aliases: 10         # Warn if more than this many aliases
breadth_warn: 15        # Warn if single object requests > 15 fields
leaf_warn: 20           # Warn if single object has > 20 scalar fields
pagination_default: 100 # Default row estimate if not calibrated

# Type weights (how expensive each object type is to fetch)
type_weights:
  Device: 3        # Devices are expensive (lots of relationships)
  Interface: 2     # Medium cost
  IPAddress: 1     # Lightweight
  VirtualMachine: 3
  Cable: 2
  Circuit: 2
  Rack: 2
  Site: 2
  VLAN: 1

# Type mappings for calibration (GraphQL type → REST endpoint)
type_mappings:
  Device: dcim/devices
  Interface: dcim/interfaces
  IPAddress: ipam/ip-addresses
  VirtualMachine: virtualization/virtual-machines
  Cable: dcim/cables
  Circuit: circuits/circuits
  Rack: dcim/racks
  Site: dcim/sites
  VLAN: ipam/vlans
```

---

## Best Practices

### ✅ DO

1. **Always use pagination** on list fields
2. **Start with small limits** (10-20) while developing
3. **Use filters** to reduce data at the source
4. **Keep queries shallow** (depth ≤ 3 is ideal)
5. **Run the analyzer** before deploying new queries
6. **Calibrate for production** systems to get accurate scores

### ❌ DON'T

1. **Don't fetch all items** without pagination
2. **Don't nest lists** without limits at each level
3. **Don't request fields you don't need**
4. **Don't ignore high complexity scores**
5. **Don't skip calibration** for production systems

---

## Troubleshooting

### "No URL provided"

**Problem:** You haven't specified your NetBox URL.

**Fix:**
```bash
# Option 1: Pass URL on command line
netbox-gqo analyze query.graphql --url https://your-netbox.com/

# Option 2: Set in config file
echo "default_url: https://your-netbox.com/" > ~/.netbox-gqo/config.yaml
```

### "Introspection failed"

**Problem:** Can't reach your NetBox GraphQL endpoint.

**Fix:**
```bash
# If authentication is required, provide a token
netbox-gqo schema pull --url https://your-netbox.com/ --token YOUR_TOKEN

# Verify the GraphQL endpoint is accessible
curl https://your-netbox.com/graphql/
```

### High Complexity Score

**Problem:** Your query has a complexity score > 200.

**Fix:**
1. Add pagination to all list fields
2. Reduce `limit` values
3. Add filters to reduce result set
4. Split into multiple smaller queries

---

## How It Works

1. **Schema Loading:** Fetches your NetBox GraphQL schema (cached for speed)
2. **Query Parsing:** Validates your query against the schema
3. **AST Analysis:** Walks the query structure to find patterns
4. **Rule Checking:** Applies best-practice rules (8 rules total)
5. **Cost Calculation:** Estimates complexity based on types and counts
6. **Reporting:** Shows findings and recommendations

All analysis is **static** - no queries are actually run against your NetBox.

---

## FAQ

**Q: Will this slow down my NetBox?**
A: No! The tool only reads your schema (once, then cached). It never runs your actual queries.

**Q: Do I need to modify NetBox?**
A: No. This is a standalone CLI tool.

**Q: What version of NetBox is supported?**
A: Any version with GraphQL support (NetBox 3.3+).

**Q: How accurate are the complexity scores?**
A: Without calibration: Reasonable estimates. With calibration: Very accurate for your specific deployment.

**Q: Can I use this with other GraphQL APIs?**
A: It's optimized for NetBox, but the core analysis works with any GraphQL API. You may need to adjust type weights and mappings.

**Q: What if I don't have an API token?**
A: For public/unauthenticated NetBox instances, you can omit the `--token` parameter. For authenticated instances, you'll need a token for both schema pulling and calibration.

---

## Getting Help

- **Issues:** https://github.com/netboxlabs/netbox-graphql-query-optimizer/issues
- **Discussions:** https://github.com/netboxlabs/netbox-graphql-query-optimizer/discussions

---

## License

Apache License 2.0 - see LICENSE file for details.
