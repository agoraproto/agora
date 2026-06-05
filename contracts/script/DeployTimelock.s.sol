// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

import {Script, console2} from "forge-std/Script.sol";
import {TimelockController} from "@openzeppelin/contracts/governance/TimelockController.sol";

/// @notice Deploy an OpenZeppelin TimelockController that will become the
/// new Ownable2Step owner of AgoraEscrowV2 (Sprint 45, Option B of
/// `contracts/TIMELOCK_DESIGN.md`).
///
/// Architecture:
///
///   [ Safe 2-of-2 ]                      << on-chain admin identity
///         |  proposer + canceller + executor
///         v
///   [ TimelockController, minDelay=24h ] << this contract
///         |  owner
///         v
///   [ AgoraEscrowV2 ]
///
/// After this script deploys the Timelock, ownership of V2 must be
/// transferred via `experiments/timelock/RUNBOOK_OWNERSHIP_FLIP.md`.
///
/// Required env vars:
///   PRIVATE_KEY     - deployer (pays gas, gets no Timelock role)
///   SAFE_ADDRESS    - the 2-of-2 Safe that gets PROPOSER + EXECUTOR + CANCELLER
///
/// Optional env vars:
///   MIN_DELAY_SECONDS  - default 86400 (24h)
///   BASESCAN_API_KEY   - required if you pass --verify
///
/// Sepolia deploy command:
///   forge script script/DeployTimelock.s.sol:DeployTimelock \
///     --rpc-url base_sepolia \
///     --broadcast --verify --etherscan-api-key $BASESCAN_API_KEY
contract DeployTimelock is Script {
    function run() external returns (TimelockController timelock) {
        uint256 pk = vm.envUint("PRIVATE_KEY");
        address safe = vm.envAddress("SAFE_ADDRESS");
        uint256 minDelay = vm.envOr("MIN_DELAY_SECONDS", uint256(86400));

        require(safe != address(0), "SAFE_ADDRESS=0");
        require(minDelay >= 3600, "minDelay<1h refusing");
        require(minDelay <= 30 days, "minDelay>30d refusing");

        address[] memory proposers = new address[](1);
        proposers[0] = safe;
        address[] memory executors = new address[](1);
        executors[0] = safe;

        console2.log("--- TimelockController deploy ---");
        console2.log("Chain id:       ", block.chainid);
        console2.log("Deployer:       ", vm.addr(pk));
        console2.log("Safe (admin):   ", safe);
        console2.log("minDelay (s):   ", minDelay);

        vm.startBroadcast(pk);
        // admin=address(0): renounces the OPTIONAL admin slot at deploy.
        // The Timelock retains DEFAULT_ADMIN_ROLE only as `address(this)`,
        // meaning role changes can only happen by routing through the
        // Timelock itself (which means: a 24h delay).
        timelock = new TimelockController(minDelay, proposers, executors, address(0));
        vm.stopBroadcast();

        console2.log("");
        console2.log("TimelockController deployed at:", address(timelock));
        console2.log("");
        console2.log("Roles assigned:");
        console2.log("  PROPOSER_ROLE   -> Safe");
        console2.log("  CANCELLER_ROLE  -> Safe");
        console2.log("  EXECUTOR_ROLE   -> Safe");
        console2.log("  DEFAULT_ADMIN_ROLE -> Timelock itself");
        console2.log("");
        console2.log("Next steps:");
        console2.log("  1. Update apps/website/llms.txt + ai-services.json");
        console2.log("  2. RUNBOOK_OWNERSHIP_FLIP.md: Safe.transferOwnership(timelock)");
        console2.log("     then schedule+execute(acceptOwnership) via Timelock");
        console2.log("  3. RUNBOOK_PERMANENT_PAUSE_QUEUE.md: queue emergency pause");
    }
}
