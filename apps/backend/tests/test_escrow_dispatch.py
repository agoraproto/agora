"""Sprint 36c: regression tests for V1/V2 ABI dispatch in AgoraEscrowClient.

Mocks the web3 contract so we can assert which contract function name is
called for fee preview, refund, and dispute resolution under each ABI
version. No RPC is touched.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agora_api.chain.escrow import AgoraEscrowClient


def _build_client(abi_version: str) -> AgoraEscrowClient:
    """Construct a client without doing real RPC."""
    with patch("agora_api.chain.escrow.Web3") as w3_cls:
        # Web3.to_checksum_address is a classmethod-ish on the Web3 module;
        # the client calls it directly so it must be intact.
        w3_cls.to_checksum_address = lambda a: a
        w3_cls.HTTPProvider = MagicMock()
        w3_instance = MagicMock()
        w3_cls.return_value = w3_instance
        w3_instance.eth.contract = MagicMock(side_effect=lambda **kw: MagicMock())
        client = AgoraEscrowClient(
            rpc_url="http://localhost:8545",
            escrow_address="0x" + "1" * 40,
            usdc_address="0x" + "2" * 40,
            settler_pk="",
            abi_version=abi_version,
        )
    return client


def test_rejects_invalid_abi_version() -> None:
    with pytest.raises(ValueError, match="abi_version"):
        _build_client("v3")


def test_records_abi_version() -> None:
    assert _build_client("v1").abi_version == "v1"
    assert _build_client("v2").abi_version == "v2"
    assert _build_client("v2.1").abi_version == "v2.1"


@pytest.mark.asyncio
async def test_compute_fee_dispatches_v1_to_computeFee() -> None:
    client = _build_client("v1")
    fn = MagicMock()
    fn.call = MagicMock(return_value=42)
    client.escrow.functions.computeFee = MagicMock(return_value=fn)
    # previewFee MUST NOT be touched on V1.
    client.escrow.functions.previewFee = MagicMock(
        side_effect=AssertionError("V1 must not call previewFee")
    )

    result = await client.compute_fee(1_000_000)
    assert result == 42
    client.escrow.functions.computeFee.assert_called_once_with(1_000_000)


@pytest.mark.asyncio
async def test_compute_fee_dispatches_v2_to_previewFee() -> None:
    client = _build_client("v2")
    fn = MagicMock()
    fn.call = MagicMock(return_value=99)
    client.escrow.functions.previewFee = MagicMock(return_value=fn)
    # computeFee MUST NOT be touched on V2 (it doesn't exist in V2 ABI).
    client.escrow.functions.computeFee = MagicMock(
        side_effect=AssertionError("V2 must not call computeFee")
    )

    result = await client.compute_fee(1_000_000)
    assert result == 99
    client.escrow.functions.previewFee.assert_called_once_with(1_000_000)


@pytest.mark.asyncio
async def test_refund_dispatches_v1_to_refund() -> None:
    client = _build_client("v1")
    client.escrow.functions.refund = MagicMock(return_value=MagicMock())
    client.escrow.functions.refundExpired = MagicMock(
        side_effect=AssertionError("V1 must not call refundExpired")
    )
    # Avoid actually broadcasting.
    with patch.object(client, "_send_tx", return_value="0xabc") as send:
        tx = await client.refund(7)

    assert tx == "0xabc"
    client.escrow.functions.refund.assert_called_once_with(7)
    assert send.call_args.kwargs["tag"] == "refund"


@pytest.mark.asyncio
async def test_refund_dispatches_v2_to_refundExpired() -> None:
    client = _build_client("v2")
    client.escrow.functions.refundExpired = MagicMock(return_value=MagicMock())
    client.escrow.functions.refund = MagicMock(
        side_effect=AssertionError("V2 must not call refund (only refundExpired)")
    )
    with patch.object(client, "_send_tx", return_value="0xdef") as send:
        tx = await client.refund(7)

    assert tx == "0xdef"
    client.escrow.functions.refundExpired.assert_called_once_with(7)
    assert send.call_args.kwargs["tag"] == "refundExpired"


@pytest.mark.asyncio
async def test_resolve_dispute_rejects_v1() -> None:
    client = _build_client("v1")
    with pytest.raises(RuntimeError, match="requires V2"):
        await client.resolve_dispute(7, 100, 200)


@pytest.mark.asyncio
async def test_resolve_dispute_works_on_v2() -> None:
    client = _build_client("v2")
    client.escrow.functions.resolveDispute = MagicMock(return_value=MagicMock())
    with patch.object(client, "_send_tx", return_value="0xfed"):
        tx = await client.resolve_dispute(7, 100, 200)

    assert tx == "0xfed"
    client.escrow.functions.resolveDispute.assert_called_once_with(7, 100, 200)


@pytest.mark.asyncio
async def test_get_job_unpacks_v1_seven_tuple() -> None:
    client = _build_client("v1")
    payer = "0x" + "a" * 40
    payee = "0x" + "b" * 40
    fn = MagicMock()
    fn.call = MagicMock(
        return_value=(payer, payee, 1_000_000, b"\x01" * 32, b"\x02" * 32, 1700000000, 1)
    )
    client.escrow.functions.jobs = MagicMock(return_value=fn)

    job = await client.get_job(42)
    assert job.payer == payer
    assert job.payee == payee
    assert job.amount == 1_000_000
    assert job.deadline == 1700000000
    assert job.status == 1


@pytest.mark.asyncio
async def test_get_job_unpacks_v2_eleven_tuple_ignoring_snapshot() -> None:
    """V2 jobs() returns 4 extra snapshot-fee fields; get_job must ignore them."""
    client = _build_client("v2")
    payer = "0x" + "c" * 40
    payee = "0x" + "d" * 40
    v2_return = (
        payer, payee, 2_000_000, b"\x03" * 32, b"\x04" * 32, 1800000000, 2,
        # V2 snapshot fields (snapshotFeeBps, snapshotMinFee, snapshotMaxFee,
        # snapshotInsuranceShareBps) — unused by OnchainJob today.
        10, 0, 25_000_000, 1000,
    )
    fn = MagicMock()
    fn.call = MagicMock(return_value=v2_return)
    client.escrow.functions.jobs = MagicMock(return_value=fn)

    job = await client.get_job(42)
    assert job.payer == payer
    assert job.payee == payee
    assert job.amount == 2_000_000
    assert job.deadline == 1800000000
    assert job.status == 2


# ── Sprint 47 follow-up: v2.1 dispatch regression tests ─────────────────

def test_records_abi_version_v21() -> None:
    """V2.1 client is constructible and remembers its version."""
    client = _build_client("v2.1")
    assert client.abi_version == "v2.1"


@pytest.mark.asyncio
async def test_compute_fee_dispatches_v21_to_previewFee() -> None:
    """V2.1 inherits V2's previewFee selector (NOT V1's computeFee)."""
    client = _build_client("v2.1")
    fn = MagicMock()
    fn.call = MagicMock(return_value=12345)
    client.escrow.functions.previewFee = MagicMock(return_value=fn)
    result = await client.compute_fee(1_000_000)
    assert result == 12345
    client.escrow.functions.previewFee.assert_called_once_with(1_000_000)


@pytest.mark.asyncio
async def test_refund_dispatches_v21_to_refundExpired() -> None:
    """V2.1 inherits V2's refundExpired selector (NOT V1's refund)."""
    client = _build_client("v2.1")
    client.escrow.functions.refundExpired = MagicMock(return_value=MagicMock())
    with patch.object(client, "_send_tx", return_value="0xabc"):
        tx = await client.refund(42)
    assert tx == "0xabc"
    client.escrow.functions.refundExpired.assert_called_once_with(42)


@pytest.mark.asyncio
async def test_resolve_dispute_works_on_v21() -> None:
    """V2.1 resolveDispute selector matches V2's (still onlyResolverOrOwner on-chain)."""
    client = _build_client("v2.1")
    client.escrow.functions.resolveDispute = MagicMock(return_value=MagicMock())
    with patch.object(client, "_send_tx", return_value="0xdef"):
        tx = await client.resolve_dispute(7, 600, 400)
    assert tx == "0xdef"
    client.escrow.functions.resolveDispute.assert_called_once_with(7, 600, 400)


@pytest.mark.asyncio
async def test_payee_force_approve_works_on_v21() -> None:
    """V2.1 exposes payeeForceApprove — the M-V2-01 escape valve."""
    client = _build_client("v2.1")
    client.escrow.functions.payeeForceApprove = MagicMock(return_value=MagicMock())
    with patch.object(client, "_send_tx", return_value="0xfa"):
        tx = await client.payee_force_approve(99)
    assert tx == "0xfa"
    client.escrow.functions.payeeForceApprove.assert_called_once_with(99)


@pytest.mark.asyncio
async def test_payee_force_approve_rejects_v1() -> None:
    """Calling payee_force_approve on a V1 client must error before touching RPC."""
    client = _build_client("v1")
    with pytest.raises(RuntimeError, match=r"requires V2\.1"):
        await client.payee_force_approve(99)


@pytest.mark.asyncio
async def test_payee_force_approve_rejects_v2() -> None:
    """V2 also lacks payeeForceApprove — must error clearly, not opaque-revert."""
    client = _build_client("v2")
    with pytest.raises(RuntimeError, match=r"requires V2\.1"):
        await client.payee_force_approve(99)
