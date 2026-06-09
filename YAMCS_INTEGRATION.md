# F Prime GDS - YAMCS Integration

This document describes how to use YAMCS as the transport layer for F Prime integration tests.

## Overview

The YAMCS integration allows F Prime integration tests to:
- Connect to YAMCS server instead of TCP middleware
- Stream telemetry and events from YAMCS into GDS RAM histories
- Use the existing IntegrationTestAPI without changes
- Run `test_basic.py` and other tests with YAMCS backend

## Architecture

```
YAMCS Server (WebSocket)
    ↓
YamcsTransportClient
  - Subscribes to parameter/event streams
  - Converts YAMCS objects → F Prime binary packets
    ↓
Distributor (unchanged)
    ↓
Decoders (unchanged)
    ↓
ChData/EventData (unchanged)
    ↓
RAM Histories (unchanged)
    ↓
IntegrationTestAPI (unchanged)
```

**Key Feature**: Existing tests work unchanged. YAMCS data is converted to F Prime binary format transparently.

## Requirements

1. **F Prime GDS** with YAMCS transport (this package)
2. **yamcs-client** Python library:
   ```bash
   pip install yamcs-client
   ```
3. **Running YAMCS server** with F Prime deployment configured

## Usage

### Running Tests with YAMCS

Add the `--use-yamcs` flag to your pytest command:

```bash
cd fprime-yamcs-reference/FprimeYamcsReference/YamcsDeployment

# Basic usage (assumes YAMCS at localhost:8090)
pytest test/int/test_basic.py \
    --use-yamcs \
    --dictionary build-artifacts/*/dict/*.json \
    --logs /tmp/test-logs

# Custom YAMCS server
pytest test/int/test_basic.py \
    --use-yamcs \
    --yamcs-url http://yamcs-server:8090 \
    --yamcs-instance my-fprime-instance \
    --yamcs-processor realtime \
    --dictionary build-artifacts/*/dict/*.json
```

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `--use-yamcs` | False | Enable YAMCS transport (required) |
| `--yamcs-url` | `http://localhost:8090` | YAMCS server URL |
| `--yamcs-instance` | `fprime-project` | YAMCS instance name |
| `--yamcs-processor` | `realtime` | YAMCS processor name |
| `--dictionary` | (required) | Path to F Prime JSON dictionary |

### Programmatic Usage

You can also use YAMCS transport directly in Python:

```python
from fprime_gds.common.pipeline.standard import StandardPipeline
from fprime_gds.common.transport_yamcs import YamcsTransportClient
from fprime_gds.common.testing_fw.api import IntegrationTestAPI

# Create pipeline with YAMCS transport
pipeline = StandardPipeline()
pipeline.transport_implementation = YamcsTransportClient

# Setup
pipeline.setup(
    config=None,
    dictionaries='/path/to/dict.json',
    file_store='/tmp/fprime-test'
)

# Connect to YAMCS
pipeline.connect_yamcs(
    yamcs_url='http://localhost:8090',
    instance='fprime-project',
    processor='realtime'
)

# Create test API (works just like TCP mode!)
api = IntegrationTestAPI(pipeline)
api.setup()

# Use API normally
api.send_command("CMD_NO_OP")
results = api.assert_telemetry_count(5, timeout=10)

# Cleanup
api.teardown()
pipeline.disconnect()
```

## How It Works

### 1. Parameter Stream (Telemetry)

YAMCS sends `ParameterValue` objects via WebSocket:

```python
# YAMCS ParameterValue
{
    'name': 'temperature.sensor_1',
    'eng_value': 42.5,
    'raw_value': 1523,
    'generation_time': '2024-06-09T10:30:00Z',
    'engineering_units': '°C',
    ...
}
```

YamcsTransportClient converts this to F Prime binary packet:

```
[4 bytes: length]
[4 bytes: descriptor = FW_PACKET_TELEM (2)]
[4 bytes: channel_id]
[4 bytes: time_seconds]
[4 bytes: time_microseconds]
[N bytes: serialized value]
```

This binary packet flows through the standard GDS pipeline:
- Distributor routes to ChannelDecoder
- ChannelDecoder creates ChData object
- ChData added to RAM history
- IntegrationTestAPI reads from history

### 2. Event Stream

Similar flow for YAMCS events:

```python
# YAMCS Event
{
    'type': 'CMD_NO_OP_OPCODE_COMPLETED',
    'message': 'Command completed',
    'severity': 'INFO',
    'generation_time': '2024-06-09T10:30:00Z',
    'extra': {'arg1': 'value'}
}
```

Converted to F Prime event binary packet and processed through EventDecoder → EventData → history.

## Limitations (MVP)

This is a **minimum viable product** to get basic tests working. Current limitations:

### ❌ Not Yet Implemented

1. **YAMCS Metadata** - Rich YAMCS features discarded during conversion:
   - Engineering units
   - Alarm states
   - Data validity flags
   - Raw vs. calibrated values
   - Expiration times
   
3. **Historical Queries** - Can't query YAMCS archive from tests
   - Only real-time streaming supported
   
4. **Complex Types** - Basic type serialization only:
   - Primitives (U32, I32, F32, etc.) ✅
   - Strings ✅
   - Enums ⚠️ (treated as integers)
   - Arrays ❌
   - Structs ❌

### ✅ Works Today

- **Telemetry streaming** into histories
- **Event streaming** into histories
- **Command uplink** to YAMCS
- `send_command()` / `send_and_assert_command()`
- `assert_telemetry()` / `assert_telemetry_count()`
- `assert_event()` / `assert_event_count()`
- `await_telemetry()` / `await_event()`
- All IntegrationTestAPI search/assert methods

## Future Enhancements

The transport is designed to support future enhancements:

### Phase 2: Enhanced Data Types

Add optional YAMCS metadata to ChData/EventData:

```python
@dataclass
class YamcsMetadata:
    raw_value: Any
    eng_value: Any
    units: str
    validity: str
    alarm_state: str

class ChData(SysData):
    def __init__(self, val, temp, time, yamcs_meta=None):
        self.yamcs_meta = yamcs_meta  # Optional metadata
```

Tests can then access:
```python
result = api.await_telemetry("temperature.sensor_1")
print(f"Value: {result.val} {result.yamcs_meta.units}")
print(f"Valid: {result.yamcs_meta.validity}")
```

### Phase 4: Archive Queries

Add archive query support to IntegrationTestAPI:

```python
history = api.query_historical_parameter(
    "temperature.sensor_1",
    start=datetime(2024, 6, 9, 10, 0, 0),
    duration=timedelta(hours=1)
)
```

### Phase 5: Native YAMCS Decoders

Skip binary conversion - pass YAMCS objects directly to decoders:

```python
class YamcsChannelDecoder(ChDecoder):
    def decode_api(self, data):
        if isinstance(data, ParameterValue):  # Native YAMCS
            return self._decode_yamcs(data)
        else:  # Binary F Prime
            return super().decode_api(data)
```

## Troubleshooting

### "Unknown parameter in F Prime dictionary"

**Cause**: YAMCS parameter name doesn't match F Prime dictionary.

**Solution**: 
1. Check XTCE dictionary matches F Prime JSON dictionary
2. Verify parameter names use same format (e.g., `component.parameter`)
3. Try short name matching (transport strips component prefix)

### "YAMCS connection refused"

**Cause**: YAMCS server not running or wrong URL.

**Solution**:
```bash
# Check YAMCS is running
curl http://localhost:8090/api

# Check correct instance exists
curl http://localhost:8090/api/mdb/fprime-project
```

### "No telemetry received"

**Cause**: F Prime deployment not sending data to YAMCS.

**Solution**:
1. Check YAMCS link status in web UI
2. Verify UDP ports match between F Prime and YAMCS config
3. Check YAMCS MDB loaded correctly (`/api/mdb/<instance>`)

### Type serialization errors

**Cause**: Complex F Prime type not supported by basic serializer.

**Solution**: 
- File an issue with the specific type
- Workaround: Use simpler types in tests
- Future: Enhanced type serialization support

## Example Test

```python
def test_is_streaming(fprime_test_api: IntegrationTestAPI):
    """Test that flight software is streaming telemetry via YAMCS"""
    results = fprime_test_api.assert_telemetry_count(5, timeout=10)
    print(f"Received {len(results)} telemetry items from YAMCS")

def test_send_no_op(fprime_test_api: IntegrationTestAPI):
    """Test sending a simple NO-OP command via YAMCS"""
    fprime_test_api.send_command("CdhCore.cmdDisp.CMD_NO_OP")
    time.sleep(0.5)
    
    # Verify command was sent
    assert fprime_test_api.get_command_test_history().size() == 1
    
    # Verify event was generated
    events = fprime_test_api.get_event_test_history()
    assert events.size() > 0
```

Run with:
```bash
pytest test_basic.py --use-yamcs --dictionary dict.json
```

## Contributing

To extend YAMCS support:

1. **YamcsTransportClient** (`fprime-gds/src/fprime_gds/common/transport_yamcs.py`)
   - Add command uplink support
   - Enhance type serialization
   - Add archive query methods

2. **Data Types** (`fprime-gds/src/fprime_gds/common/data_types/`)
   - Add YamcsMetadata optional fields
   - Keep backward compatibility

3. **IntegrationTestAPI** (`fprime-gds/src/fprime_gds/common/testing_fw/api.py`)
   - Add YAMCS-specific assertion methods
   - Add historical query methods

See design docs in this repository for full architecture.
