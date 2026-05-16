// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

import {Test} from "forge-std/Test.sol";
import {AgoraEscrow} from "../src/AgoraEscrow.sol";

contract MockERC20 {
    string public name = "MockUSDC";
    string public symbol = "mUSDC";
    uint8 public decimals = 6;
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    function mint(address to, uint256 amount) external { balanceOf[to] += amount; }
    function approve(address spender, uint256 amount) external returns (bool) {
        allowance[msg.sender][spender] = amount; return true;
    }
    function transfer(address to, uint256 amount) external returns (bool) {
        require(balanceOf[msg.sender] >= amount, "bal");
        balanceOf[msg.sender] -= amount; balanceOf[to] += amount; return true;
    }
    function transferFrom(address from, address to, uint256 amount) external returns (bool) {
        require(balanceOf[from] >= amount, "bal");
        require(allowance[from][msg.sender] >= amount, "allow");
        allowance[from][msg.sender] -= amount;
        balanceOf[from] -= amount; balanceOf[to] += amount; return true;
    }
}

contract AgoraEscrowTest is Test {
    AgoraEscrow escrow;
    MockERC20 token;
    address feeRecipient = address(0xFEE);
    address insurancePool = address(0xCAFE);
    address payer = address(0xAA);
    address payee = address(0xBB);

    uint256 constant USDC_10    = 10_000_000;
    uint256 constant USDC_100   = 100_000_000;
    uint256 constant USDC_1000  = 1_000_000_000;
    uint256 constant USDC_10000 = 10_000_000_000;

    function setUp() public {
        token = new MockERC20();
        escrow = new AgoraEscrow(address(token), feeRecipient, insurancePool);
    }

    function _fund(uint256 amount) internal returns (uint256 jobId) {
        token.mint(payer, amount);
        vm.prank(payer); token.approve(address(escrow), amount);
        vm.prank(payer);
        jobId = escrow.createJob(payee, amount, keccak256("task"), uint64(block.timestamp + 1 days));
    }

    function test_ComputeFee_MinApplies_For10USDC() public view {
        assertEq(escrow.computeFee(USDC_10), 500_000);
    }
    function test_ComputeFee_OnePercent_For100USDC() public view {
        assertEq(escrow.computeFee(USDC_100), 1_000_000);
    }
    function test_ComputeFee_OnePercent_For1000USDC() public view {
        assertEq(escrow.computeFee(USDC_1000), 10_000_000);
    }
    function test_ComputeFee_MaxApplies_For10000USDC() public view {
        assertEq(escrow.computeFee(USDC_10000), 25_000_000);
    }

    function test_HappyPath_100USDC() public {
        uint256 jobId = _fund(USDC_100);
        vm.prank(payee); escrow.submitResult(jobId, keccak256("r"));
        vm.prank(payer); escrow.approveAndPay(jobId);
        assertEq(token.balanceOf(insurancePool), 100_000);
        assertEq(token.balanceOf(feeRecipient), 900_000);
        assertEq(token.balanceOf(payee), 99_000_000);
    }

    function test_HappyPath_10000USDC_Capped() public {
        uint256 jobId = _fund(USDC_10000);
        vm.prank(payee); escrow.submitResult(jobId, keccak256("r"));
        vm.prank(payer); escrow.approveAndPay(jobId);
        assertEq(token.balanceOf(insurancePool), 2_500_000);
        assertEq(token.balanceOf(feeRecipient), 22_500_000);
        assertEq(token.balanceOf(payee), 9_975_000_000);
    }

    function test_RefundAfterDeadline() public {
        uint256 jobId = _fund(USDC_10);
        vm.warp(block.timestamp + 2 days);
        escrow.refund(jobId);
        assertEq(token.balanceOf(payer), USDC_10);
    }

    function test_DisputeBlocksApproval() public {
        uint256 jobId = _fund(USDC_100);
        vm.prank(payee); escrow.submitResult(jobId, keccak256("r"));
        vm.prank(payer); escrow.dispute(jobId, "bad");
        vm.expectRevert(AgoraEscrow.InvalidStatus.selector);
        vm.prank(payer); escrow.approveAndPay(jobId);
    }
}
