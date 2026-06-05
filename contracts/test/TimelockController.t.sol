// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

import {Test} from "forge-std/Test.sol";
import {TimelockController} from "@openzeppelin/contracts/governance/TimelockController.sol";
import {AgoraEscrowV2} from "../src/AgoraEscrowV2.sol";

// Reuse the MockERC20 idiom from AgoraEscrowV2.t.sol -- kept inline so
// the test file is self-contained.
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

/// Sprint 45 -- verify the TimelockController configuration we will
/// deploy on Sepolia behaves as the design doc says it does.
///
/// What this proves:
///   * minDelay is 24h
///   * Safe has PROPOSER + CANCELLER + EXECUTOR role
///   * Nobody has the optional admin (admin=address(0) at constructor)
///   * schedule -> wait -> execute end-to-end works against a V2 admin call
///   * Premature execute reverts
///   * cancel() removes a pending proposal
///   * Random EOA cannot propose or execute
///   * pause() also goes through the 24h delay (Option B documented cost)
contract TimelockControllerTest is Test {
    TimelockController public timelock;
    AgoraEscrowV2 public escrow;
    MockUSDC public usdc;

    address constant SAFE = address(0xCAFE);
    address constant DEPLOYER = address(0xBEEF);
    address constant ATTACKER = address(0xBAD);
    address constant FEE_RECIPIENT = address(0xFEE);
    address constant INSURANCE = address(0x1A5);

    uint256 constant MIN_DELAY = 86400; // 24h

    function setUp() public {
        usdc = new MockUSDC();
        vm.prank(DEPLOYER);
        escrow = new AgoraEscrowV2(address(usdc), 6, FEE_RECIPIENT, INSURANCE);

        address[] memory proposers = new address[](1);
        proposers[0] = SAFE;
        address[] memory executors = new address[](1);
        executors[0] = SAFE;
        timelock = new TimelockController(MIN_DELAY, proposers, executors, address(0));

        // Transfer V2 ownership to the timelock. In production this goes
        // through Ownable2Step's two-step path executed by the Safe and
        // then the Timelock itself; here we simulate the post-flip state.
        vm.startPrank(DEPLOYER);
        escrow.transferOwnership(address(timelock));
        vm.stopPrank();
        vm.prank(address(timelock));
        escrow.acceptOwnership();
    }

    function test_safe_has_proposer_role() public view {
        assertTrue(timelock.hasRole(timelock.PROPOSER_ROLE(), SAFE));
    }

    function test_safe_has_canceller_role() public view {
        assertTrue(timelock.hasRole(timelock.CANCELLER_ROLE(), SAFE));
    }

    function test_safe_has_executor_role() public view {
        assertTrue(timelock.hasRole(timelock.EXECUTOR_ROLE(), SAFE));
    }

    function test_no_external_admin() public view {
        assertTrue(timelock.hasRole(timelock.DEFAULT_ADMIN_ROLE(), address(timelock)));
        assertFalse(timelock.hasRole(timelock.DEFAULT_ADMIN_ROLE(), SAFE));
        assertFalse(timelock.hasRole(timelock.DEFAULT_ADMIN_ROLE(), DEPLOYER));
        assertFalse(timelock.hasRole(timelock.DEFAULT_ADMIN_ROLE(), ATTACKER));
    }

    function test_min_delay_is_24h() public view {
        assertEq(timelock.getMinDelay(), MIN_DELAY);
    }

    function test_v2_is_owned_by_timelock() public view {
        assertEq(escrow.owner(), address(timelock));
    }

    function test_schedule_wait_execute_setFees() public {
        bytes memory callData = abi.encodeWithSelector(
            AgoraEscrowV2.setFees.selector,
            uint16(15),
            uint256(0),
            uint256(25_000_000),
            uint16(1000)
        );
        bytes32 salt = keccak256("test-setfees");
        bytes32 id = timelock.hashOperation(address(escrow), 0, callData, bytes32(0), salt);

        vm.prank(SAFE);
        timelock.schedule(address(escrow), 0, callData, bytes32(0), salt, MIN_DELAY);
        assertTrue(timelock.isOperationPending(id));
        assertFalse(timelock.isOperationReady(id));

        vm.warp(block.timestamp + MIN_DELAY - 1);
        vm.prank(SAFE);
        vm.expectRevert();
        timelock.execute(address(escrow), 0, callData, bytes32(0), salt);

        vm.warp(block.timestamp + 2);
        assertTrue(timelock.isOperationReady(id));

        vm.prank(SAFE);
        timelock.execute(address(escrow), 0, callData, bytes32(0), salt);

        uint16 feeBps = escrow.feeBps();
        assertEq(feeBps, 15);
        assertTrue(timelock.isOperationDone(id));
    }

    function test_cancel_removes_pending_proposal() public {
        bytes memory callData = abi.encodeWithSelector(AgoraEscrowV2.setFeeRecipient.selector, ATTACKER);
        bytes32 salt = keccak256("test-cancel");
        bytes32 id = timelock.hashOperation(address(escrow), 0, callData, bytes32(0), salt);

        vm.prank(SAFE);
        timelock.schedule(address(escrow), 0, callData, bytes32(0), salt, MIN_DELAY);
        assertTrue(timelock.isOperationPending(id));

        vm.prank(SAFE);
        timelock.cancel(id);
        assertFalse(timelock.isOperationPending(id));

        vm.warp(block.timestamp + MIN_DELAY + 1);
        vm.prank(SAFE);
        vm.expectRevert();
        timelock.execute(address(escrow), 0, callData, bytes32(0), salt);

        assertEq(escrow.feeRecipient(), FEE_RECIPIENT);
    }

    function test_attacker_cannot_schedule() public {
        bytes memory callData = abi.encodeWithSelector(AgoraEscrowV2.setFeeRecipient.selector, ATTACKER);
        vm.prank(ATTACKER);
        vm.expectRevert();
        timelock.schedule(address(escrow), 0, callData, bytes32(0), bytes32(0), MIN_DELAY);
    }

    function test_attacker_cannot_execute_after_safe_scheduled() public {
        bytes memory callData = abi.encodeWithSelector(
            AgoraEscrowV2.setFees.selector,
            uint16(12),
            uint256(0),
            uint256(25_000_000),
            uint16(1000)
        );
        bytes32 salt = keccak256("test-atk-exec");
        vm.prank(SAFE);
        timelock.schedule(address(escrow), 0, callData, bytes32(0), salt, MIN_DELAY);

        vm.warp(block.timestamp + MIN_DELAY + 1);

        vm.prank(ATTACKER);
        vm.expectRevert();
        timelock.execute(address(escrow), 0, callData, bytes32(0), salt);

        uint16 feeBps = escrow.feeBps();
        assertEq(feeBps, 100);
    }

    function test_pause_requires_24h_delay_via_timelock() public {
        bytes memory callData = abi.encodeWithSelector(AgoraEscrowV2.pause.selector);
        bytes32 salt = keccak256("emergency-pause");
        bytes32 id = timelock.hashOperation(address(escrow), 0, callData, bytes32(0), salt);

        vm.prank(SAFE);
        timelock.schedule(address(escrow), 0, callData, bytes32(0), salt, MIN_DELAY);
        assertTrue(timelock.isOperationPending(id));

        vm.prank(SAFE);
        vm.expectRevert();
        escrow.pause();

        vm.warp(block.timestamp + MIN_DELAY + 1);
        vm.prank(SAFE);
        timelock.execute(address(escrow), 0, callData, bytes32(0), salt);
        assertTrue(escrow.paused());
    }
}
