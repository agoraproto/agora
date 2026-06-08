// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

import {Test} from "forge-std/Test.sol";
import {TimelockController} from "@openzeppelin/contracts/governance/TimelockController.sol";
import {AgoraEscrowV21} from "../src/AgoraEscrowV21.sol";

/// Inline mock USDC -- same one used in AgoraEscrowV21.t.sol.
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

/// Sprint 47d -- end-to-end test of V2.1 deployed under a TimelockController owner,
/// with the Safe holding pauser + disputeResolver roles directly.
///
/// Proves that V2.1 actually solves the two Sprint-45 Option-B regressions:
///   * T-V2.1-01: pause() must be instant via Safe, not 24h-delayed
///   * T-V2.1-02: resolveDispute() must be instant via Safe, not 24h-delayed
///
/// And that the remaining admin path (setFees / setFeeRecipient / etc) still
/// goes through the 24h Timelock as designed in TIMELOCK_DESIGN.md.
contract AgoraEscrowV21TimelockTest is Test {
    TimelockController public timelock;
    AgoraEscrowV21 public escrow;
    MockUSDC public usdc;

    address constant SAFE = address(0xCAFE);      // stand-in for the 2-of-2 Safe
    address constant DEPLOYER = address(0xBEEF);
    address constant ATTACKER = address(0xBAD);
    address constant FEE_RECIPIENT = address(0xFEE);
    address constant INSURANCE = address(0x1A5);
    address constant PAYER = address(0xA1);
    address constant PAYEE = address(0xA2);

    uint256 constant AMOUNT = 1_000_000;       // 1 USDC at 6 decimals
    uint256 constant MIN_DELAY = 86400;        // 24h
    bytes32 constant TASK_HASH = keccak256("task");
    bytes32 constant RESULT_HASH = keccak256("result");

    function setUp() public {
        // 1) Deploy V2.1 escrow as the deployer
        usdc = new MockUSDC();
        vm.prank(DEPLOYER);
        escrow = new AgoraEscrowV21(address(usdc), 6, FEE_RECIPIENT, INSURANCE);

        // 2) Deploy Timelock with Safe as proposer + executor (no extra admin)
        address[] memory proposers = new address[](1);
        proposers[0] = SAFE;
        address[] memory executors = new address[](1);
        executors[0] = SAFE;
        timelock = new TimelockController(MIN_DELAY, proposers, executors, address(0));

        // 3) Owner sets the V2.1 roles to point at the Safe directly
        vm.startPrank(DEPLOYER);
        escrow.setPauser(SAFE);
        escrow.setDisputeResolver(SAFE);
        // 4) Then transfer V2.1 ownership to the Timelock via Ownable2Step
        escrow.transferOwnership(address(timelock));
        vm.stopPrank();
        vm.prank(address(timelock));
        escrow.acceptOwnership();

        // Top up the payer with USDC + allowance
        usdc.mint(PAYER, AMOUNT * 10);
        vm.prank(PAYER);
        usdc.approve(address(escrow), type(uint256).max);
    }

    function _createJob(uint64 deadline) internal returns (uint256 jobId) {
        vm.prank(PAYER);
        jobId = escrow.createJob(PAYEE, AMOUNT, TASK_HASH, deadline);
    }

    // ───────────────────────────────────────────────────────────
    //  Sanity: post-setUp invariants
    // ───────────────────────────────────────────────────────────

    function test_v21_is_owned_by_timelock() public view {
        assertEq(escrow.owner(), address(timelock));
    }

    function test_safe_is_pauser_and_resolver() public view {
        assertEq(escrow.pauser(), SAFE);
        assertEq(escrow.disputeResolver(), SAFE);
    }

    function test_timelock_is_self_administered() public view {
        assertTrue(timelock.hasRole(timelock.DEFAULT_ADMIN_ROLE(), address(timelock)));
        assertFalse(timelock.hasRole(timelock.DEFAULT_ADMIN_ROLE(), SAFE));
    }

    // ───────────────────────────────────────────────────────────
    //  T-V2.1-01: pause() must be instant via Safe (not 24h-delayed)
    // ───────────────────────────────────────────────────────────

    function test_safe_can_pause_instantly() public {
        // The whole point of T-V2.1-01: Safe pauses without scheduling on the Timelock.
        uint256 t0 = block.timestamp;
        vm.prank(SAFE);
        escrow.pause();
        assertTrue(escrow.paused());
        // Wall time elapsed: 0 seconds, not 86400.
        assertEq(block.timestamp, t0);
    }

    function test_safe_pause_blocks_new_jobs_immediately() public {
        vm.prank(SAFE);
        escrow.pause();

        // createJob is whenNotPaused; should revert
        vm.prank(PAYER);
        vm.expectRevert();
        escrow.createJob(PAYEE, AMOUNT, TASK_HASH, uint64(block.timestamp + 1 days));
    }

    function test_unpause_still_requires_timelock_24h() public {
        // unpause() stayed onlyOwner -- intentional asymmetry from ADR.
        vm.prank(SAFE);
        escrow.pause();
        assertTrue(escrow.paused());

        // Safe cannot unpause directly
        vm.prank(SAFE);
        vm.expectRevert();
        escrow.unpause();

        // Schedule + 24h + execute via Timelock
        bytes memory unpauseCall = abi.encodeWithSelector(AgoraEscrowV21.unpause.selector);
        bytes32 salt = keccak256("e2e-unpause");
        vm.prank(SAFE);
        timelock.schedule(address(escrow), 0, unpauseCall, bytes32(0), salt, MIN_DELAY);

        vm.warp(block.timestamp + MIN_DELAY + 1);
        vm.prank(SAFE);
        timelock.execute(address(escrow), 0, unpauseCall, bytes32(0), salt);

        assertFalse(escrow.paused());
    }

    // ───────────────────────────────────────────────────────────
    //  T-V2.1-02: resolveDispute() must be instant via Safe (not 24h-delayed)
    // ───────────────────────────────────────────────────────────

    function test_safe_can_resolve_dispute_instantly() public {
        // Set up a disputed job
        uint256 jobId = _createJob(uint64(block.timestamp + 1 days));
        vm.prank(PAYEE);
        escrow.submitResult(jobId, RESULT_HASH);
        vm.prank(PAYER);
        escrow.dispute(jobId, "result quality dispute");

        uint256 t0 = block.timestamp;
        // Safe resolves directly -- no Timelock scheduling involved
        vm.prank(SAFE);
        escrow.resolveDispute(jobId, AMOUNT / 2, AMOUNT / 2);
        assertEq(block.timestamp, t0);

        // Payee got half (minus fee from their half), payer got half back
        assertGt(usdc.balanceOf(PAYEE), 0);
        // payer's USDC is mint + refund - escrowed amount + payer half from resolve.
        // Just verify payer got a payout from the resolve.
        assertEq(usdc.balanceOf(PAYER), AMOUNT * 10 - AMOUNT + (AMOUNT / 2));
    }

    function test_attacker_cannot_resolve_dispute() public {
        uint256 jobId = _createJob(uint64(block.timestamp + 1 days));
        vm.prank(PAYEE);
        escrow.submitResult(jobId, RESULT_HASH);
        vm.prank(PAYER);
        escrow.dispute(jobId, "bad");

        vm.prank(ATTACKER);
        vm.expectRevert();
        escrow.resolveDispute(jobId, AMOUNT, 0);
    }

    // ───────────────────────────────────────────────────────────
    //  Remaining admin: setFees must still go through the 24h Timelock
    // ───────────────────────────────────────────────────────────

    function test_safe_cannot_setfees_directly() public {
        // The Safe is NOT the owner of V2.1 anymore -- the Timelock is.
        // setFees(onlyOwner) must therefore revert when called by the Safe directly.
        vm.prank(SAFE);
        vm.expectRevert();
        escrow.setFees(15, 0, 25_000_000, 1000);
    }

    function test_setfees_via_timelock_takes_24h() public {
        bytes memory callData = abi.encodeWithSelector(
            AgoraEscrowV21.setFees.selector,
            uint16(15),
            uint256(0),
            uint256(25_000_000),
            uint16(1000)
        );
        bytes32 salt = keccak256("e2e-setfees");

        vm.prank(SAFE);
        timelock.schedule(address(escrow), 0, callData, bytes32(0), salt, MIN_DELAY);

        // Pre-delay: not executable yet
        vm.prank(SAFE);
        vm.expectRevert();
        timelock.execute(address(escrow), 0, callData, bytes32(0), salt);

        // Wait the full 24h
        vm.warp(block.timestamp + MIN_DELAY + 1);
        vm.prank(SAFE);
        timelock.execute(address(escrow), 0, callData, bytes32(0), salt);

        // Fee actually changed
        assertEq(escrow.feeBps(), 15);
    }

    function test_setpauser_via_timelock_takes_24h() public {
        // Rotating the pauser role must also go through the Timelock (= slow).
        // This is the asymmetry the ADR describes: roles act fast, role-changes
        // happen slowly.
        address newPauser = address(0x99);
        bytes memory callData = abi.encodeWithSelector(AgoraEscrowV21.setPauser.selector, newPauser);
        bytes32 salt = keccak256("e2e-setpauser");

        vm.prank(SAFE);
        timelock.schedule(address(escrow), 0, callData, bytes32(0), salt, MIN_DELAY);

        // The Safe cannot setPauser directly -- it's owner-only
        vm.prank(SAFE);
        vm.expectRevert();
        escrow.setPauser(newPauser);

        // After 24h, execute
        vm.warp(block.timestamp + MIN_DELAY + 1);
        vm.prank(SAFE);
        timelock.execute(address(escrow), 0, callData, bytes32(0), salt);

        assertEq(escrow.pauser(), newPauser);
    }

    // ───────────────────────────────────────────────────────────
    //  M-V2-01: payeeForceApprove works unchanged under Timelock ownership
    // ───────────────────────────────────────────────────────────

    function test_payee_force_approve_works_under_timelock_owner() public {
        // The M-V2-01 escape valve is permissionless (modulo payee == msg.sender),
        // so Timelock ownership of the contract is irrelevant -- payee can still
        // force-approve after deadline + 7d.
        uint64 deadline = uint64(block.timestamp + 1 days);
        uint256 jobId = _createJob(deadline);
        vm.prank(PAYEE);
        escrow.submitResult(jobId, RESULT_HASH);

        vm.warp(deadline + 7 days + 1);
        vm.prank(PAYEE);
        escrow.payeeForceApprove(jobId);

        // Payee got paid -- no owner / Timelock involvement
        assertGt(usdc.balanceOf(PAYEE), 0);
    }

    // ───────────────────────────────────────────────────────────
    //  M-V2-02: refundExpired on Submitted works unchanged
    // ───────────────────────────────────────────────────────────

    function test_payer_force_refund_works_under_timelock_owner() public {
        uint64 deadline = uint64(block.timestamp + 1 days);
        uint256 jobId = _createJob(deadline);
        vm.prank(PAYEE);
        escrow.submitResult(jobId, RESULT_HASH);

        vm.warp(deadline + 3 days + 1);
        uint256 payerBalBefore = usdc.balanceOf(PAYER);
        vm.prank(PAYER);
        escrow.refundExpired(jobId);

        assertEq(usdc.balanceOf(PAYER), payerBalBefore + AMOUNT);
    }

    // ───────────────────────────────────────────────────────────
    //  Combined: an attacker who somehow gets PROPOSER_ROLE can't bypass anything
    //  (this is a soft regression check -- the deploy script grants PROPOSER
    //  only to the Safe, so a 'rogue proposer' scenario requires the Timelock
    //  itself to grant via a previous Timelock-scheduled grantRole. We just
    //  verify the contract correctly rejects a non-Safe scheduler today.)
    // ───────────────────────────────────────────────────────────

    function test_attacker_cannot_schedule_through_timelock() public {
        bytes memory callData = abi.encodeWithSelector(AgoraEscrowV21.setFeeRecipient.selector, ATTACKER);
        vm.prank(ATTACKER);
        vm.expectRevert();
        timelock.schedule(address(escrow), 0, callData, bytes32(0), bytes32(0), MIN_DELAY);
    }
}
