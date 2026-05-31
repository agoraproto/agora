#!/usr/bin/env bash
# Sprint 37c diagnose — figure out why V2.owner didn't flip even though Safe tx had status=1

V2=0x0e8E6A760c76cA92c5C5dA06d293E33f1B5fbAEc
SAFE=0x8ec63fe30dab84308b5009b8d91d9e4deb5a61fc
TX=0xee83c1db2c8e918ba48b7d3281264d8227ab5d13addfef39194970515f9d3dc1
RPC=https://sepolia.base.org
CAST=/root/.foundry/bin/cast

echo "=== 1) Re-read V2 + Safe state (was RPC just stale?) ==="
echo -n "  V2.owner():        "; $CAST call $V2 "owner()(address)" --rpc-url $RPC
echo -n "  V2.pendingOwner(): "; $CAST call $V2 "pendingOwner()(address)" --rpc-url $RPC
echo -n "  Safe.nonce():      "; $CAST call $SAFE "nonce()(uint256)" --rpc-url $RPC
echo -n "  Safe.getThreshold(): "; $CAST call $SAFE "getThreshold()(uint256)" --rpc-url $RPC

echo ""
echo "=== 2) Decode the receipt — what events did Safe emit? ==="
$CAST receipt $TX --rpc-url $RPC --json | python3 -c "
import json, sys
r = json.load(sys.stdin)
print(f'  status:     {r.get(\"status\")}')
print(f'  block:      {r.get(\"blockNumber\")}')
print(f'  gasUsed:    {r.get(\"gasUsed\")}')
print(f'  from:       {r.get(\"from\")}')
print(f'  to:         {r.get(\"to\")}')
print(f'  logs ({len(r.get(\"logs\", []))} entries):')

# Known Safe v1.4.1 event topic hashes
TOPICS = {
    '0x442e715f626346e8c54381002da614f62bee8d27386535b2521ec8540898556e': 'ExecutionSuccess(bytes32,uint256)',
    '0x23428b18acfb3ea64b08dc0c1d296ea9c09702c09083ca5272e64d115b687d23': 'ExecutionFailure(bytes32,uint256)',
    '0xc7f505b2f371ae2175ee4913f4499e1f2633a7b5936321eed1cdaeb6115181d2': 'SafeReceived(address,uint256)',
    # OZ Ownable2Step
    '0x38d16b8cac22d99fc7c124b9cd0de2d3fa1faef420bfe791d8c362d765e22700': 'OwnershipTransferred(address,address)',
    '0x5b6a64bd03d34d8a25fde0c8acaa86a6c7eba6e0b9bd49b35c69ee5c70b7afa3': 'OwnershipTransferStarted(address,address)',
    # Note: OwnershipTransferStarted hash above is wrong — let's compute
}

for i, log in enumerate(r.get('logs', [])):
    addr = log.get('address', '')
    topic0 = log.get('topics', [None])[0]
    name = TOPICS.get(topic0.lower() if topic0 else '', '?unknown?')
    print(f'    [{i}] addr={addr} topic0={topic0}')
    print(f'        decoded: {name}')
    if len(log.get('topics', [])) > 1:
        for j, t in enumerate(log['topics'][1:], 1):
            print(f'        topic{j}: {t}')
    if log.get('data') and log['data'] != '0x':
        d = log['data']
        print(f'        data: {d[:80]}{\"...\" if len(d) > 80 else \"\"}')
"

echo ""
echo "=== 3) Selector check — was 0x79ba5097 actually V2.acceptOwnership()? ==="
# selector for acceptOwnership() should be 0x79ba5097
python3 -c "
from eth_utils import keccak
sig = b'acceptOwnership()'
sel = keccak(sig)[:4].hex()
print(f'  keccak(\"{sig.decode()}\")[:4] = 0x{sel}')
print(f'  matches 0x79ba5097: {sel == \"79ba5097\"}')
"

echo ""
echo "=== 4) Try calling V2.acceptOwnership() statically as the Safe ==="
# eth_call from Safe's perspective — would it succeed without state change?
$CAST call $V2 "acceptOwnership()" --from $SAFE --rpc-url $RPC 2>&1 | head -5 || true
