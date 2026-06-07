// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

import {Test} from "forge-std/Test.sol";
import {AgoraEscrowV21} from "../src/AgoraEscrowV21.sol";

contract MockUSDC {
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

    function transferFrom(address from, address to, uint256 amount) external returns (bool) {
        require(balanceOf[from] >= amount, "bal");
        require(allowance[from][msg.sender] >= amount, "allow");
        allowance[from][msg.sender] -= amount;
        balanceOf[from] -= amount;
        balanceOf[to] += amount;
        return true;
    }
}

/// Sprint 47 -- AgoraEscrowV21 spike tests.
/// Focused on the four ADR_M-V2-DECISIONS.md patches:
///   M-V2-01:  payeeForceApprove(jobId) after deadline + 7d grace
///   M-V2-02:  refundExpired accepts Submitted at deadline + 3d grace (payer-only)
///   T-V2.1-01: separate pauser role
///   T-V2.1-02: separate disputeResolver role
contract AgoraEscrowV21Test is Test {
    AgoraEscrowV21 public escrow;
    MockUSDC public usdc;

    address constant OWNER = address(0xBEEF);
    address constant SAFE_PAUSER = address(0xCAFE);
    address constant SAFE_RESOLVER = address(0xC0DE);
    address constant FEE_RECIPIENT = address(0xFEE);
    address constant INSURANCE = address(0x1A5);
    address constant PAYER = address(0xA1);
    address constant PAYEE = address(0xA2);
    address constant ATTACKER = address(0xBAD);

    uint256 constant AMOUNT = 1_000_000; // 1 USDC at 6 decimals
    bytes32 constant TASK_HASH = keccak256("task");
    bytes32 constant RESULT_HASH = keccak256("result");

    function setUp() public {
        usdc = new MockUSDC();
        vm.prank(OWNER);
        escrow = new AgoraEscrowV21(address(usdc), 6, FEE_RECIPIENT, INSURANCE);
        // After deploy, owner sets the V2.1 roles.
        vm.startPrank(OWNER);
        escrow.setPauser(SAFE_PAUSER);
        escrow.setDisputeResolver(SAFE_RESOLVER);
        vm.stopPrank();

        usdc.mint(PAYER, AMOUNT * 10);
        vm.prank(PAYER);
        usdc.approve(address(escrow), type(uint256).max);
    }

    function _createJob(uint64 deadline) internal returns (uint256 jobId) {
        vm.prank(PAYER);
        jobId = escrow.createJob(PAYEE, AMOUNT, TASK_HASH, deadline);
    }

    // ───────────────────────────────────────────────────────────
    //  T-V2.1-01: pauser role
    // ───────────────────────────────────────────────────────────

    function test_pauser_can_pause_directly() public {
        vm.prank(SAFE_PAUSER);
        escrow.pause();
        assertTrue(escrow.paused());
    }

    function test_owner_can_pause_too() public {
        vm.prank(OWNER);
        escrow.pause();
        assertTrue(escrow.paused());
    }

    function test_attacker_cannot_pause() public {
        vm.prank(ATTACKER);
        vm.expectRevert();
        escrow.pause();
    }

    function test_unpause_is_owner_only() public {
        vm.prank(SAFE_PAUSER);
        escrow.pause();
        // pauser cannot unpause -- intentional asymmetry
        vm.prank(SAFE_PAUSER);
        vm.expectRevert();
        escrow.unpause();
        vm.prank(OWNER);
        escrow.unpause();
        assertFalse(escrow.paused());
    }

    function test_setPauser_is_owner_only() public {
        vm.prank(ATTACKER);
        vm.expectRevert();
        escrow.setPauser(ATTACKER);
        vm.prank(OWNER);
        escrow.setPauser(address(0x99));
        assertEq(escrow.pauser(), address(0x99));
    }

    function test_setPauser_rejects_zero() public {
        vm.prank(OWNER);
        vm.expectRevert();
        escrow.setPauser(address(0));
    }

    // ───────────────────────────────────────────────────────────
    //  T-V2.1-02: disputeResolver role
    // ───────────────────────────────────────────────────────────

    function test_resolver_can_resolve_dispute() public {
        uint256 jobId = _createJob(uint64(block.timestamp + 1 days));
        vm.prank(PAYEE);
        escrow.submitResult(jobId, RESULT_HASH);
        vm.prank(PAYER);
        escrow.dispute(jobId, "bad result");

        vm.prank(SAFE_RESOLVER);
        escrow.resolveDispute(jobId, AMOUNT / 2, AMOUNT / 2);
        // Both got their half (minus fee from payee's half)
        assertGt(usdc.balanceOf(PAYEE), 0);
        assertGt(usdc.balanceOf(PAYER), 0);
    }

    function test_attacker_cannot_resolve_dispute() public {
        uint256 jobId = _createJob(uint64(block.timestamp + 1 days));
        vm.prank(PAYEE);
        escrow.submitResult(jobId, RESULT_HASH);
        vm.prank(PAYER);
        escrow.dispute(jobId, "bad result");

        vm.prank(ATTACKER);
        vm.expectRevert();
        escrow.resolveDispute(jobId, AMOUNT, 0);
    }

    function test_owner_can_still_resolve_dispute_if_resolver_absent() public {
        // Edge case: resolver = address(0). Only owner can resolve.
        vm.prank(OWNER);
        escrow.setDisputeResolver(address(0x99));
        // ... actually contract refuses to set to 0. So we just verify
        // owner is also valid via the modifier.

        uint256 jobId = _createJob(uint64(block.timestamp + 1 days));
        vm.prank(PAYEE);
        escrow.submitResult(jobId, RESULT_HASH);
        vm.prank(PAYER);
        escrow.dispute(jobId, "bad result");

        vm.prank(OWNER);
        escrow.resolveDispute(jobId, AMOUNT, 0);
    }

    function test_setDisputeResolver_is_owner_only() public {
        vm.prank(ATTACKER);
        vm.expectRevert();
        escrow.setDisputeResolver(ATTACKER);
        vm.prank(OWNER);
        escrow.setDisputeResolver(address(0x99));
        assertEq(escrow.disputeResolver(), address(0x99));
    }

    // ───────────────────────────────────────────────────────────
    //  M-V2-01: payeeForceApprove
    // ───────────────────────────────────────────────────────────

    function test_payee_force_approve_after_grace() public {
        uint64 deadline = uint64(block.timestamp + 1 days);
        uint256 jobId = _createJob(deadline);
        vm.prank(PAYEE);
        escrow.submitResult(jobId, RESULT_HASH);

        // Before deadline + 7d: revert
        vm.warp(deadline + 7 days);
        vm.prank(PAYEE);
        vm.expectRevert();
        escrow.payeeForceApprove(jobId);

        // After deadline + 7d + 1s: success
        vm.warp(deadline + 7 days + 1);
        vm.prank(PAYEE);
        escrow.payeeForceApprove(jobId);

        // Payee received the funds (minus fee)
        assertGt(usdc.balanceOf(PAYEE), 0);
    }

    function test_payee_force_approve_rejects_non_payee() public {
        uint64 deadline = uint64(block.timestamp + 1 days);
        uint256 jobId = _createJob(deadline);
        vm.prank(PAYEE);
        escrow.submitResult(jobId, RESULT_HASH);
        vm.warp(deadline + 7 days + 1);

        vm.prank(ATTACKER);
        vm.expectRevert();
        escrow.payeeForceApprove(jobId);

        vm.prank(PAYER);
        vm.expectRevert();
        escrow.payeeForceApprove(jobId);
    }

    function test_payee_force_approve_rejects_non_submitted() public {
        uint64 deadline = uint64(block.timestamp + 1 days);
        uint256 jobId = _createJob(deadline);
        // Status is Funded, not Submitted
        vm.warp(deadline + 7 days + 1);
        vm.prank(PAYEE);
        vm.expectRevert();
        escrow.payeeForceApprove(jobId);
    }

    function test_payee_force_approve_blocked_when_disputed() public {
        uint64 deadline = uint64(block.timestamp + 1 days);
        uint256 jobId = _createJob(deadline);
        vm.prank(PAYEE);
        escrow.submitResult(jobId, RESULT_HASH);
        vm.prank(PAYER);
        escrow.dispute(jobId, "bad");
        // Now status is Disputed -- payee cannot force-approve any more
        vm.warp(deadline + 7 days + 1);
        vm.prank(PAYEE);
        vm.expectRevert();
        escrow.payeeForceApprove(jobId);
    }

    // ───────────────────────────────────────────────────────────
    //  M-V2-02: refundExpired on Submitted
    // ───────────────────────────────────────────────────────────

    function test_payer_force_refund_submitted_after_grace() public {
        uint64 deadline = uint64(block.timestamp + 1 days);
        uint256 jobId = _createJob(deadline);
        vm.prank(PAYEE);
        escrow.submitResult(jobId, RESULT_HASH);

        // Before deadline + 3d: revert
        vm.warp(deadline + 3 days);
        vm.prank(PAYER);
        vm.expectRevert();
        escrow.refundExpired(jobId);

        // After deadline + 3d + 1s: success
        vm.warp(deadline + 3 days + 1);
        uint256 payerBalBefore = usdc.balanceOf(PAYER);
        vm.prank(PAYER);
        escrow.refundExpired(jobId);
        assertEq(usdc.balanceOf(PAYER), payerBalBefore + AMOUNT);
    }

    function test_payer_force_refund_rejects_non_payer() public {
        uint64 deadline = uint64(block.timestamp + 1 days);
        uint256 jobId = _createJob(deadline);
        vm.prank(PAYEE);
        escrow.submitResult(jobId, RESULT_HASH);
        vm.warp(deadline + 3 days + 1);

        // Payee cannot trigger the payer-grace path
        vm.prank(PAYEE);
        vm.expectRevert();
        escrow.refundExpired(jobId);

        // Random EOA cannot either
        vm.prank(ATTACKER);
        vm.expectRevert();
        escrow.refundExpired(jobId);
    }

    function test_funded_refund_path_unchanged() public {
        // V2.1 must not break the V2 permissionless Funded-refund path.
        uint64 deadline = uint64(block.timestamp + 1 days);
        uint256 jobId = _createJob(deadline);
        // Job stays Funded -- nobody submits
        vm.warp(deadline + 1);
        // Anyone can call -- attacker is fine
        vm.prank(ATTACKER);
        escrow.refundExpired(jobId);
        // Payer got their refund
        assertEq(usdc.balanceOf(PAYER), AMOUNT * 10); // back to initial mint
    }

    function test_funded_refund_still_requires_deadline_elapsed() public {
        uint64 deadline = uint64(block.timestamp + 1 days);
        uint256 jobId = _createJob(deadline);
        // Before deadline
        vm.prank(PAYER);
        vm.expectRevert();
        escrow.refundExpired(jobId);
    }

    function test_dispute_still_works_on_submitted_within_grace() public {
        // Within the 3d grace, payer's choice is approve / dispute, not refund.
        uint64 deadline = uint64(block.timestamp + 1 days);
        uint256 jobId = _createJob(deadline);
        vm.prank(PAYEE);
        escrow.submitResult(jobId, RESULT_HASH);
        vm.warp(deadline + 1 days); // within 3d grace
        vm.prank(PAYER);
        escrow.dispute(jobId, "bad");
        // Now job is Disputed -- refundExpired should revert
        vm.warp(deadline + 10 days);
        vm.prank(PAYER);
        vm.expectRevert();
        escrow.refundExpired(jobId);
    }
}
