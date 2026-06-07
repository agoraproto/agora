// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

import {Script, console2} from "forge-std/Script.sol";
import {AgoraEscrowV21} from "../src/AgoraEscrowV21.sol";

/// @notice Deploy AgoraEscrowV21 -- V2 + 4 patches from ADR_M-V2-DECISIONS.md
/// (Sprint 47 spike).
///
/// Required env vars:
///   PRIVATE_KEY        - deployer (becomes initial Ownable2Step owner)
///   USDC_ADDRESS       - ERC20 used for settlement
///   USDC_DECIMALS      - decimals of the settlement token (6 for USDC)
///   FEE_RECIPIENT      - platform-fee wallet (Agora)
///   INSURANCE_POOL     - insurance/reserve wallet (Agora)
///
/// Settlement token addresses:
///   Base Sepolia USDC:  0x036CbD53842c5426634e7929541eC2318f3dCF7e (6 decimals)
///   Base Mainnet USDC:  0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913 (6 decimals)
///
/// Sepolia deploy:
///   forge script script/DeployV21.s.sol:DeployV21 \
///     --rpc-url base_sepolia \
///     --broadcast --verify --etherscan-api-key $BASESCAN_API_KEY
///
/// Mainnet deploy (Phase C of MAINNET_MIGRATION_RUNBOOK.md):
///   forge script script/DeployV21.s.sol:DeployV21 \
///     --rpc-url base_mainnet \
///     --broadcast --verify --etherscan-api-key $BASESCAN_API_KEY
///
/// Post-deploy steps (per Phase A.2 / C.2 of MAINNET_MIGRATION_RUNBOOK.md):
///   1. setPauser(Safe)
///   2. setDisputeResolver(Safe)
///   3. transferOwnership(Timelock)
///   4. Schedule + execute acceptOwnership() via Timelock
contract DeployV21 is Script {
    function run() external returns (AgoraEscrowV21 escrow) {
        uint256 pk = vm.envUint("PRIVATE_KEY");
        address token = vm.envAddress("USDC_ADDRESS");
        uint8 tokenDecimals = uint8(vm.envUint("USDC_DECIMALS"));
        address feeRecipient = vm.envAddress("FEE_RECIPIENT");
        address insurancePool = vm.envAddress("INSURANCE_POOL");

        require(tokenDecimals > 0 && tokenDecimals <= 36, "implausible decimals");

        console2.log("--- AgoraEscrowV21 deploy ---");
        console2.log("Chain id:       ", block.chainid);
        console2.log("Deployer:       ", vm.addr(pk));
        console2.log("USDC token:     ", token);
        console2.log("USDC decimals:  ", tokenDecimals);
        console2.log("Fee recipient:  ", feeRecipient);
        console2.log("Insurance pool: ", insurancePool);

        vm.startBroadcast(pk);
        escrow = new AgoraEscrowV21(token, tokenDecimals, feeRecipient, insurancePool);
        vm.stopBroadcast();

        console2.log("");
        console2.log("AgoraEscrowV21 deployed at:", address(escrow));
        console2.log("");
        console2.log("Next steps (see contracts/runbooks/MAINNET_MIGRATION_RUNBOOK.md):");
        console2.log("  1. setPauser(<Safe>)");
        console2.log("  2. setDisputeResolver(<Safe>)");
        console2.log("  3. transferOwnership(<Timelock>)");
        console2.log("  4. Timelock.schedule + 24h + execute(acceptOwnership)");
    }
}
