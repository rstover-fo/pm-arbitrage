#!/usr/bin/env python3
"""Test Polymarket API connection and diagnose 400 errors."""

import asyncio
import sys

# Add project to path
sys.path.insert(0, "src")


async def test_connection() -> None:
    """Test API connection step by step."""
    from pm_arb.core.auth import load_credentials
    from pm_arb.adapters.venues.polymarket import PolymarketAdapter, HAS_CLOB_CLIENT

    print("=" * 60)
    print("POLYMARKET API CONNECTION TEST")
    print("=" * 60)

    # Step 1: Check py-clob-client is installed
    print("\n[1] Checking py-clob-client installation...")
    if not HAS_CLOB_CLIENT:
        print("   ✗ FAIL: py-clob-client not installed")
        print("   Run: pip install py-clob-client")
        return
    print("   ✓ py-clob-client installed")

    # Step 2: Load credentials
    print("\n[2] Loading credentials...")
    try:
        creds = load_credentials("polymarket")
        print(f"   ✓ Credentials loaded: {creds}")
    except ValueError as e:
        print(f"   ✗ FAIL: {e}")
        return

    # Step 3: Test adapter connection
    print("\n[3] Connecting to Polymarket...")
    adapter = PolymarketAdapter(credentials=creds)
    try:
        await adapter.connect()
        print(f"   ✓ Connected (authenticated: {adapter.is_authenticated})")
    except Exception as e:
        print(f"   ✗ FAIL: Connection error: {e}")
        return

    if not adapter.is_authenticated:
        print("   ✗ FAIL: Not authenticated after connect()")
        print("   Check: API key, secret, passphrase, and private key")
        await adapter.disconnect()
        return

    # Step 4: Check wallet balance
    print("\n[4] Checking wallet balance...")
    try:
        balance = await adapter.get_balance()
        print(f"   ✓ Balance: ${balance:.2f} USDC")
        if balance < 1:
            print("   ⚠ WARNING: Balance < $1, cannot place test trade")
    except Exception as e:
        print(f"   ✗ FAIL: Balance check failed: {e}")
        print("   This is often the source of 400 errors!")

    # Step 5: Test fetching markets
    print("\n[5] Fetching active markets...")
    try:
        markets = await adapter.get_markets()
        print(f"   ✓ Fetched {len(markets)} active markets")

        # Find a crypto market with good liquidity for testing
        crypto_markets = [m for m in markets if any(k in m.title.lower() for k in ["btc", "bitcoin", "eth"])]
        if crypto_markets:
            test_market = crypto_markets[0]
            print(f"   Found test market: {test_market.title[:50]}...")
            print(f"   Market ID: {test_market.id}")
            print(f"   YES price: {test_market.yes_price}")
            print(f"   Token IDs: YES={test_market.yes_token_id[:20]}...")
        else:
            print("   ⚠ No crypto markets found for testing")
    except Exception as e:
        print(f"   ✗ FAIL: Market fetch failed: {e}")

    # Step 6: Test order book fetch (no trade placed)
    print("\n[6] Testing order book API...")
    if crypto_markets:
        try:
            book = await adapter.get_order_book(test_market.id, "YES")
            if book and book.asks:
                print(f"   ✓ Order book fetched: {len(book.bids)} bids, {len(book.asks)} asks")
                print(f"   Best ask: {book.asks[0].price} @ {book.asks[0].size} size")
            else:
                print("   ⚠ Order book empty or unavailable")
        except Exception as e:
            print(f"   ✗ FAIL: Order book fetch failed: {e}")

    # Step 7: Test py-clob-client directly
    print("\n[7] Testing py-clob-client directly...")
    try:
        from py_clob_client.client import ClobClient
        from py_clob_client.clob_types import ApiCreds

        clob_creds = ApiCreds(
            api_key=creds.api_key,
            api_secret=creds.secret,
            api_passphrase=creds.passphrase,
        )
        client = ClobClient(
            host="https://clob.polymarket.com",
            chain_id=137,
            key=creds.private_key,
            creds=clob_creds,
        )

        # Test get_orders (safe, read-only)
        orders = client.get_orders()
        print(f"   ✓ Open orders: {len(orders)}")

        # Test get_balance_allowance
        try:
            allowance = client.get_balance_allowance()
            print(f"   ✓ Allowance data: {allowance}")
        except Exception as e:
            print(f"   ⚠ Allowance check failed: {e}")
            print("   This might indicate you need to approve USDC spending")

    except Exception as e:
        print(f"   ✗ FAIL: py-clob-client error: {e}")
        import traceback
        traceback.print_exc()

    await adapter.disconnect()
    print("\n" + "=" * 60)
    print("TEST COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_connection())
