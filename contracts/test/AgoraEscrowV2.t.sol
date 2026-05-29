// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

import {Test} from "forge-std/Test.sol";
import {AgoraEscrowV2} from "../src/AgoraEscrowV2.sol";

/// Minimal ERC20 mock matching v1's. V2 also accepts this through the
/// SafeERC20 wrapper because the mock implements IERC20's return-bool
/// convention.
contract MockERC20 {
    string public name = "MockUSDC";
    string public symbol = "mUSDC";
    uint8 public decimals = 6;
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;
    uint256 public totalSupply;

    function mint(address to, uint256 amount) external {
        balanceOf[to] += amount;
        totalSupply += amount;
    }

    function approve(address spender, uint256 amount) external returns (bool) {
        allowance[msg.sender][spender] = amount;
        return true;
    }

    function transfer(address to, uint256 amount) external returns (bool) {
        require(balanceOf[msg.sender] >= amount, "bal");
        balanceOf[msg.sender] -= amount;
        balanceOf[to] += amount;
        return true;
    }

    function transferFrom(address from, address to, uint256 amount) external virtual returns (bool) {
        require(balanceOf[from] >= amount, "bal");
        require(allowance[from][msg.sender] >= amount, "allow");
        allowance[from][msg.sender] -= amount;
        balanceOf[from] -= amount;
        balanceOf[to] += amount;
        return true;
    }
}

/// A token that silently keeps 1% on every transfer — used to verify
/// that V2's `balanceOf` delta check (H-05 fix) actually rejects this.
contract FeeOnTransferToken is MockERC20 {
    function transferFrom(address from, address to, uint256 amount) external override returns (bool) {
        require(balanceOf[from] >= amount, "bal");
        require(allowance[from][msg.sender] >= amount, "allow");
        allowance[from][msg.sender] -= amount;
        balanceOf[from] -= amount;
        uint256 fee = amount / 100;
        balanceOf[to] += (amount - fee);
        balanceOf[address(0xDEAD)] += fee;
        return true;
    }
}

contract AgoraEscrowV2Test is Test {
    AgoraEscrowV2 escrow;
    MockERC20 token;
    address feeRecipient = address(0xFEE);
    address insurancePool = address(0xCAFE);
    address payer = address(0xAA);
    address payee = address(0xBB);
    address other = address(0xCC);

    uint256 constant USDC_10 = 10_000_000;
    uint256 constant USDC_100 = 100_000_000;

    function setUp() public {
        token = new MockERC20();
        escrow = new AgoraEscrowV2(address(token), 6, feeRecipient, insurancePool);
    }

    // ── helpers ─────────────────────────────────────────────────

    function _fund(uint256 amount, uint64 deadline) internal returns (uint256 jobId) {
        token.mint(payer, amount);
        vm.prank(payer);
        token.approve(address(escrow), amount);
        vm.prank(payer);
        jobId = escrow.createJob(payee, amount, keccak256("task"), deadline);
    }

    // ── happy path ──────────────────────────────────────────────

    function test_happy_path_hire_submit_approve() public {
        uint256 jobId = _fund(USDC_100, uint64(block.timestamp + 1 days));
        assertEq(jobId, 1, "nextJobId starts at 1");
        assertEq(escrow.totalEscrowed(), USDC_100);

        vm.prank(payee);
        escrow.submitResult(jobId, keccak256("result"));

        vm.prank(payer);
        escrow.approveAndPay(jobId);

        // Fee math: 1% of 100 USDC = 1 USDC, insurance 10% of fee = 0.10
        // platform = 0.90, payee = 99.00.
        assertEq(token.balanceOf(payee), USDC_100 - 1_000_000);
        assertEq(token.balanceOf(insurancePool), 100_000);
        assertEq(token.balanceOf(feeRecipient), 900_000);
        assertEq(escrow.totalEscrowed(), 0);
    }

    // ── M-05: nextJobId starts at 1, not 0 ────────────────────

    function test_first_job_id_is_one() public {
        uint256 id = _fund(USDC_100, uint64(block.timestamp + 1 days));
        assertEq(id, 1);
    }

    // ── L-06: self-job rejected ────────────────────────────────

    function test_cannot_create_self_job() public {
        token.mint(payer, USDC_100);
        vm.prank(payer);
        token.approve(address(escrow), USDC_100);
        vm.prank(payer);
        vm.expectRevert(AgoraEscrowV2.SelfJob.selector);
        escrow.createJob(payer, USDC_100, keccak256("t"), uint64(block.timestamp + 1 days));
    }

    // ── H-03: submitResult enforces deadline ───────────────────

    function test_submit_after_deadline_reverts() public {
        uint64 dl = uint64(block.timestamp + 1 hours);
        uint256 jobId = _fund(USDC_100, dl);
        vm.warp(uint256(dl) + 1);
        vm.prank(payee);
        vm.expectRevert(AgoraEscrowV2.DeadlineExpired.selector);
        escrow.submitResult(jobId, keccak256("late"));
    }

    // ── H-02: dispute is rejected in Funded state ──────────────

    function test_cannot_dispute_funded() public {
        uint256 jobId = _fund(USDC_100, uint64(block.timestamp + 1 days));
        vm.prank(payer);
        vm.expectRevert(AgoraEscrowV2.InvalidStatus.selector);
        escrow.dispute(jobId, "I changed my mind");
    }

    // ── H-01: resolveDispute splits funds correctly ────────────

    function test_resolve_dispute_split_50_50() public {
        uint256 jobId = _fund(USDC_100, uint64(block.timestamp + 1 days));
        vm.prank(payee);
        escrow.submitResult(jobId, keccak256("partial"));
        vm.prank(payer);
        escrow.dispute(jobId, "result is half-correct");

        // Owner (this test contract) resolves 50/50.
        uint256 payeeShare = USDC_100 / 2; // 50 USDC
        uint256 payerShare = USDC_100 - payeeShare;
        escrow.resolveDispute(jobId, payeeShare, payerShare);

        // Fee taken proportional to payee's share against full-amount fee.
        // fullFee = max(0.50, min(25, 1%*100)) = 1.00 USDC.
        // proportionalFee = 1.00 * 50 / 100 = 0.50 USDC.
        // insurance 10% of 0.50 = 0.05; platform = 0.45.
        // payee net = 50 - 0.50 = 49.50.
        assertEq(token.balanceOf(payee), 49_500_000);
        assertEq(token.balanceOf(payer), payerShare); // 50.00 back
        assertEq(token.balanceOf(insurancePool), 50_000);  // 0.05
        assertEq(token.balanceOf(feeRecipient), 450_000);  // 0.45
        assertEq(escrow.totalEscrowed(), 0);
    }

    function test_resolve_dispute_full_to_payer() public {
        // 100% to payer = same effect as refund, but only owner can do it.
        uint256 jobId = _fund(USDC_100, uint64(block.timestamp + 1 days));
        vm.prank(payee);
        escrow.submitResult(jobId, keccak256("bad"));
        vm.prank(payer);
        escrow.dispute(jobId, "rejected");
        escrow.resolveDispute(jobId, 0, USDC_100);

        assertEq(token.balanceOf(payer), USDC_100);
        assertEq(token.balanceOf(payee), 0);
        assertEq(escrow.totalEscrowed(), 0);
    }

    function test_resolve_dispute_rejects_bad_split() public {
        uint256 jobId = _fund(USDC_100, uint64(block.timestamp + 1 days));
        vm.prank(payee);
        escrow.submitResult(jobId, keccak256("r"));
        vm.prank(payer);
        escrow.dispute(jobId, "x");
        vm.expectRevert(AgoraEscrowV2.InvalidSplit.selector);
        escrow.resolveDispute(jobId, 1, 1); // sum != amount
    }

    function test_only_owner_can_resolve() public {
        uint256 jobId = _fund(USDC_100, uint64(block.timestamp + 1 days));
        vm.prank(payee);
        escrow.submitResult(jobId, keccak256("r"));
        vm.prank(payer);
        escrow.dispute(jobId, "x");
        vm.prank(payer);
        // Ownable's OwnableUnauthorizedAccount in OZ v5; selector matches.
        vm.expectRevert();
        escrow.resolveDispute(jobId, USDC_100, 0);
    }

    // ── C-01 / M-06: refundExpired is permissionless after deadline ──

    function test_refund_expired_anyone_can_call() public {
        uint64 dl = uint64(block.timestamp + 1 hours);
        uint256 jobId = _fund(USDC_100, dl);
        vm.warp(uint256(dl) + 1);
        // Not the payer, not the owner — anyone.
        vm.prank(other);
        escrow.refundExpired(jobId);
        assertEq(token.balanceOf(payer), USDC_100);
        assertEq(escrow.totalEscrowed(), 0);
    }

    function test_refund_expired_blocked_before_deadline() public {
        uint256 jobId = _fund(USDC_100, uint64(block.timestamp + 1 days));
        vm.expectRevert(AgoraEscrowV2.DeadlineNotElapsed.selector);
        escrow.refundExpired(jobId);
    }

    function test_refund_expired_blocked_on_submitted() public {
        uint64 dl = uint64(block.timestamp + 1 hours);
        uint256 jobId = _fund(USDC_100, dl);
        vm.prank(payee);
        escrow.submitResult(jobId, keccak256("r"));
        vm.warp(uint256(dl) + 1);
        // Submitted job past deadline — can NOT be unilaterally refunded.
        // Either party must dispute, then owner resolves.
        vm.expectRevert(AgoraEscrowV2.InvalidStatus.selector);
        escrow.refundExpired(jobId);
    }

    // ── M-03: fee snapshot survives owner's setFees ───────────

    function test_fee_snapshot_not_affected_by_setFees() public {
        uint256 jobId = _fund(USDC_100, uint64(block.timestamp + 1 days));

        // Owner doubles the fee mid-flight.
        escrow.setFees(200, 500_000, 25_000_000, 1_000);

        vm.prank(payee);
        escrow.submitResult(jobId, keccak256("r"));
        vm.prank(payer);
        escrow.approveAndPay(jobId);

        // Should still pay the SNAPSHOT fee (1% of 100 = 1 USDC), not 2%.
        assertEq(token.balanceOf(payee), USDC_100 - 1_000_000);
    }

    // ── L-01: Pausable blocks createJob ───────────────────────

    function test_paused_blocks_createJob() public {
        escrow.pause();
        token.mint(payer, USDC_100);
        vm.prank(payer);
        token.approve(address(escrow), USDC_100);
        vm.prank(payer);
        vm.expectRevert(); // Pausable: paused
        escrow.createJob(payee, USDC_100, keccak256("t"), uint64(block.timestamp + 1 days));
    }

    // ── M-02: zero-address checks ─────────────────────────────

    function test_setFeeRecipient_rejects_zero() public {
        vm.expectRevert(AgoraEscrowV2.InvalidAddress.selector);
        escrow.setFeeRecipient(address(0));
    }

    function test_setInsurancePool_rejects_zero() public {
        vm.expectRevert(AgoraEscrowV2.InvalidAddress.selector);
        escrow.setInsurancePool(address(0));
    }

    function test_constructor_rejects_zero_token() public {
        vm.expectRevert(AgoraEscrowV2.InvalidAddress.selector);
        new AgoraEscrowV2(address(0), 6, feeRecipient, insurancePool);
    }

    // ── H-05: fee-on-transfer token rejected ──────────────────

    function test_fee_on_transfer_token_rejected() public {
        FeeOnTransferToken bad = new FeeOnTransferToken();
        AgoraEscrowV2 e = new AgoraEscrowV2(address(bad), 6, feeRecipient, insurancePool);
        bad.mint(payer, USDC_100);
        vm.prank(payer);
        bad.approve(address(e), USDC_100);
        vm.prank(payer);
        vm.expectRevert(AgoraEscrowV2.AmountMismatch.selector);
        e.createJob(payee, USDC_100, keccak256("t"), uint64(block.timestamp + 1 days));
    }

    // ── M-01: Ownable2Step (constructor sets owner; transfer is two-step) ──

    function test_ownership_is_two_step() public {
        address newOwner = address(0xD00D);
        // pendingOwner stage
        escrow.transferOwnership(newOwner);
        assertEq(escrow.owner(), address(this), "owner doesn't change until acceptance");
        assertEq(escrow.pendingOwner(), newOwner);
        // accept stage
        vm.prank(newOwner);
        escrow.acceptOwnership();
        assertEq(escrow.owner(), newOwner);
    }

    // ── L-05: empty resultHash rejected ───────────────────────

    function test_empty_result_hash_rejected() public {
        uint256 jobId = _fund(USDC_100, uint64(block.timestamp + 1 days));
        vm.prank(payee);
        vm.expectRevert(AgoraEscrowV2.InvalidResultHash.selector);
        escrow.submitResult(jobId, byte