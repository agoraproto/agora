// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

import {Script, console2} from "forge-std/Script.sol";
import {AgoraEscrow} from "../src/AgoraEscrow.sol";

/// @notice Deploy AgoraEscrow.
///
/// Required env vars:
///   PRIVATE_KEY        - deployer (also becomes contract owner)
///   USDC_ADDRESS       - ERC20 used for settlement
///   FEE_RECIPIENT      - platform-fee wallet (Agora)
///   INSURANCE_POOL     - insurance/reserve wallet (Agora)
///
/// USDC addresses (set USDC_ADDRESS):
///   Base Sepolia:  0x036CbD53842c5426634e7929541eC2318f3dCF7e
///   Base Mainnet:  0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913
///
/// Usage:
///   forge script script/Deploy.s.sol:Deploy \
///     --rpc-url base_sepolia \
///     --broadcast --verify --etherscan-api-key $BASESCAN_API_KEY
contract Deploy is Script {
    function run() external returns (AgoraEscrow escrow) {
        uint256 pk = vm.envUint("PRIVATE_KEY");
        address token = vm.envAddress("USDC_ADDRESS");
        address feeRecipient = vm.envAddress("FEE_RECIPIENT");
        address insurancePool = vm.envAddress("INSURANCE_POOL");

        console2.log("Deployer:       ", vm.addr(pk));
        console2.log("USDC token:     ", token);
        console2.log("Fee recipient:  ", feeRecipient);
        console2.log("Insurance pool: ", insurancePool);

        vm.startBroadcast(pk);
        escrow = new AgoraEscrow(token, feeRecipient, insurancePool);
        vm.stopBroadcast();

        console2.log("AgoraEscrow deployed at:", address(escrow));
    }
}
