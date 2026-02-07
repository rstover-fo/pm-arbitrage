# Adapter Conventions

## Error Handling Pattern

All adapters follow a consistent error handling pattern: **log errors, return None (or rejected object for order operations)**.

### For methods returning `T | None`

```python
async def get_data(self, id: str) -> SomeData | None:
    try:
        response = await self._client.get(f"/api/{id}")
        response.raise_for_status()
        return self._parse_response(response.json())
    except httpx.HTTPError as e:
        logger.error("fetch_failed", id=id, error=str(e))
        return None
```

Callers must check for None:
```python
data = await adapter.get_data(id)
if data is None:
    # Handle missing data - skip, retry, or raise
    continue
```

### For methods that must return an object (e.g., `place_order`)

Return an object with error state:
```python
async def place_order(self, ...) -> Order:
    try:
        response = self._client.create_order(...)
        return Order(..., status=OrderStatus.OPEN)
    except Exception as e:
        logger.error("order_failed", error=str(e))
        return Order(..., status=OrderStatus.REJECTED, error_message=str(e))
```

Callers check the status:
```python
order = await adapter.place_order(...)
if order.status == OrderStatus.REJECTED:
    # Handle failure
    logger.warning("order_rejected", reason=order.error_message)
```

### Why this pattern?

1. **Explicit failure handling** - Callers must handle None, no silent failures
2. **Debugging** - All errors logged with context
3. **Resilience** - One adapter failure doesn't crash the system
4. **Consistency** - Same pattern everywhere, predictable behavior

### Adapters following this pattern

- `src/pm_arb/adapters/oracles/coingecko.py`
- `src/pm_arb/adapters/oracles/crypto.py` (Binance)
- `src/pm_arb/adapters/oracles/weather.py` (NWS)
- `src/pm_arb/adapters/venues/polymarket.py`
