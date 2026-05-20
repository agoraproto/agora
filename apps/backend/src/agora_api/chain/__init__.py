"""On-chain settlement (Sprint 9 / ADR 004 + ADR 009).

This package wraps web3.py calls to AgoraEscrow.sol on Base. It is only
loaded when settings.enable_onchain_payments is True; off-chain ledger
mode keeps working without any of this.
"""

from .escrow import AgoraEscrowClient, OnchainJob, get_escrow_client
from .watcher import chain_watcher_loop

__all__ = ["AgoraEscrowClient", "OnchainJob", "chain_watcher_loop", "get_escrow_client"]
