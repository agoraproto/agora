// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

import {Script, console2} from "forge-std/Script.sol";
import {AgoraEscrowV2} from "../src/AgoraEscrowV2.sol";

/// @notice Deploy AgoraEscrowV2 (hardened escrow that addresses the V1
/// security findings — see contracts/SECURITY_REVIEW.md).
///
/// Required env vars:
///   PRIVATE_KEY        - deployer (also becomes initial Ownable2Step owner)
///   USDC_ADDRESS       - ERC20 used for settlement
///   USDC_DECIMALS      - decimals of the settlement token (e.g. 6 for USDC)
///   FEE_RECIPIENT      - platform-fee wallet (Agora)
///   INSURANCE_POOL     - insurance/reserve wallet (Agora)
///
/// Optional env vars:
///   BASESCAN_API_KEY   - required if you pass --verify
///
/// Settlement token addresses:
///   Base Sepolia USDC:  0x036CbD53842c5426634e7929541eC2318f3dCF7e (6 decimals)
///   Base Mainnet USDC:  0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913 (6 decimals)
///
/// Sepolia deploy command (current target):
///   forge script script/DeployV2.s.sol:DeployV2 \
///     --rpc-url base_sepolia \
///     --broadcast --verify --etherscan-api-key $BASESCAN_API_KEY
///
/// Mainnet deploy command (post-audit, post-Safe-multisig handoff):
///   forge script script/DeployV2.s.sol:DeployV2 \
///     --rpc-url base_mainnet \
///     --broadcast --verify --etherscan-api-key $BASESCAN_API_KEY
///
/// Post-deploy:
///   - The deployer address is the Ownable2Step owner. Hand off to the
///     Safe multisig with `transferOwnership(safeAddress)` followed by
///     the Safe accepting via `acceptOwnership()`.
///   - Update apps/backend/src/agora_api/config.py:
///       escrow_contract_address = "<new V2 address>"
///       escrow_abi_version = "v2"  (planned config field — see escrow.py)
///   - Add the new address to apps/website/llms.txt and to
///     /.well-known/ai-services.json.
contract DeployV2 is Script {
    function run() external returns (AgoraEscrowV2 escrow) {
        uint256 pk = vm.envUint("PRIVATE_KEY");
        address token = vm.envAddress("USDC_ADDRESS");
        uint8 tokenDecimals = uint8(vm.envUint("USDC_DECIMALS"));
        address feeRecipient = vm.envAddress("FEE_RECIPIENT");
        address insurancePool = vm.envAddress("INSURANCE_POOL");

        require(tokenDecimals > 0 && tokenDecimals <= 36, "implausible decimals");

        console2.log("--- AgoraEscrowV2 deploy ---");
        console2.log("Chain id:       ", block.chainid);
        console2.log("Deployer:       ", vm.addr(pk));
        console2.log("USDC token:     ", token);
        console2.log("USDC decimals:  ", tokenDecimals);
        console2.log("Fee recipient:  ", feeRecipient);
        console2.log("Insurance pool: ", insurancePool);

        vm.startBroadcast(pk);
        escrow = new AgoraEscrowV2(token, tokenDecimals, feeRecipient, insurancePool);
        vm.stopBroadcast();

        console2.log("");
        console2.log("AgoraEscrowV2 deployed at:", address(escrow));
        console2.log("");
        console2.log("Next steps:");
        console2.log("  1. Update apps/backend config:");
        console2.log("     escrow_contract_address = <above>");
        console2.log("     escrow_abi_version      = v2");
        console2.log("  2. Update apps/website/llms.txt + ai-services.json");
        console2.log("  3. Hand off ownership to Safe multisig via");
        console2.log("     transferOwnership(safeAddress) -> acceptOwnership()");
    }
}
