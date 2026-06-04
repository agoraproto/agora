// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;

// AgoraEscrowV2 — hardened escrow with capped fee model (ADR 004),
// dispute resolution with payee/payer split, deadline enforcement,
// fee snapshotting, and safer admin surface.
//
// NOT YET AUDITED. The findings in `contracts/SECURITY_REVIEW.md` (against
// v1) are addressed here at the protocol-design level; an external audit
// is still required before mainnet.
//
// Compared to v1 this contract:
//   - Adds `resolveDispute(jobId, payeeAmount, payerAmount)` so a Disputed
//     job is no longer a one-way trap to refund-only (fixes H-01, H-02).
//   - Restricts `dispute()` to Submitted-state jobs only (fixes H-02).
//   - Enforces `block.timestamp <= deadline` in `submitResult` (fixes H-03);
//     `approveAndPay` accepts late approval as a deliberate UX choice --
//     see SECURITY_REVIEW_V2.md M-V2-01 for the trade-off.
//   - Splits the v1 `refund()` into permissionless `refundExpired()` for
//     deadline-elapsed Funded jobs and owner-only `resolveDispute()` for
//     Disputed jobs (fixes C-01, M-06).
//   - Snapshots fee parameters into the Job struct at create-time so
//     later parameter changes don't affect in-flight jobs (fixes M-03).
//   - Uses OZ `SafeERC20` (fixes L-04), `Ownable2Step` (fixes M-01),
//     `Pausable` (L-01), `ReentrancyGuard` (H-04).
//   - Detects fee-on-transfer tokens by checking `balanceOf` delta
//     instead of trusting `transferFrom`'s return (fixes H-05).
//   - Tracks `totalEscrowed` explicitly for invariant testing (fixes H-06).
//   - Zero-address checks in constructor and every setter (fixes M-02).
//   - Emits events on every owner-facing state change (fixes M-04).
//   - Starts `nextJobId` at 1 to avoid collision with the `None` sentinel
//     (fixes M-05).
//   - Requires `resultHash != 0` (fixes L-05) and bans `payee == payer`
//     (L-06).

import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import "@openzeppelin/contracts/access/Ownable2Step.sol";
import "@openzeppelin/contracts/utils/Pausable.sol";
import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

contract AgoraEscrowV2 is Ownable2Step, Pausable, ReentrancyGuard {
    using SafeERC20 for IERC20;

    enum JobStatus {
        None,
        Funded,
        Submitted,
        Approved,
        Disputed,
        Refunded,
        Resolved // new terminal state for owner-resolved disputes
    }

    struct Job {
        address payer;
        address payee;
        uint256 amount;
        bytes32 taskHash;
        bytes32 resultHash;
        uint64 deadline;
        JobStatus status;
        // Snapshot of the fee parameters in effect at creation time,
        // so later setFees() calls don't sneak-update in-flight jobs.
        uint16 snapshotFeeBps;
        uint256 snapshotMinFee;
        uint256 snapshotMaxFee;
        uint16 snapshotInsuranceShareBps;
    }

    IERC20 public immutable token;
    uint8 public immutable tokenDecimals;

    // 6 decimals (USDC). All caps are checked in setFees().
    uint16 public feeBps = 100;           // 1.00 %
    uint256 public minFee = 500_000;      // 0.50 USDC
    uint256 public maxFee = 25_000_000;   // 25.00 USDC
    uint16 public insuranceShareBps = 1_000; // 10 % of fee

    // Absolute parameter caps a setFees() call must respect.
    uint16 public constant MAX_FEE_BPS = 500;             // 5 %
    uint16 public constant MAX_INSURANCE_SHARE_BPS = 5_000; // 50 % of fee

    address public feeRecipient;
    address public insurancePool;

    mapping(uint256 => Job) public jobs;
    uint256 public nextJobId = 1; // start at 1 so 0 is never a valid id

    // Sum of `amount` across all jobs whose status is non-terminal
    // (Funded, Submitted, Disputed). Used as an invariant: this must
    // always equal `token.balanceOf(this)` for a well-behaved token.
    uint256 public totalEscrowed;

    // ─── Events ───────────────────────────────────────────────
    event JobCreated(
        uint256 indexed jobId,
        address indexed payer,
        address indexed payee,
        uint256 amount,
        bytes32 taskHash,
        uint64 deadline
    );
    event ResultSubmitted(uint256 indexed jobId, bytes32 resultHash);
    event JobApproved(uint256 indexed jobId, uint256 fee, uint256 insuranceCut);
    event JobDisputed(uint256 indexed jobId, address indexed raisedBy, string reason);
    event JobRefunded(uint256 indexed jobId, address indexed to, uint256 amount);
    event JobResolved(
        uint256 indexed jobId,
        uint256 payeeAmount,
        uint256 payerAmount,
        uint256 fee,
        uint256 insuranceCut
    );

    event FeesUpdated(
        uint16 oldFeeBps,
        uint256 oldMinFee,
        uint256 oldMaxFee,
        uint16 oldInsuranceShareBps,
        uint16 newFeeBps,
        uint256 newMinFee,
        uint256 newMaxFee,
        uint16 newInsuranceShareBps
    );
    event FeeRecipientUpdated(address indexed oldRecipient, address indexed newRecipient);
    event InsurancePoolUpdated(address indexed oldPool, address indexed newPool);

    // ─── Errors ───────────────────────────────────────────────
    error NotPayer();
    error NotPayee();
    error NotParty();
    error InvalidStatus();
    error TransferFailed();
    error AmountTooSmall();
    error AmountMismatch(); // balanceOf delta != amount (fee-on-transfer or rebasing token)
    error DeadlineExpired();
    error DeadlineNotElapsed();
    error InvalidAddress();
    error InvalidResultHash();
    error InvalidTaskHash();
    error SelfJob();
    error InvalidSplit();
    error FeeTooHigh();
    error InsuranceShareTooHigh();
    error MinExceedsMax();
    error ReasonTooLong();

    // ─── Constructor ──────────────────────────────────────────
    constructor(
        address _token,
        uint8 _tokenDecimals,
        address _feeRecipient,
        address _insurancePool
    ) Ownable(msg.sender) {
        if (_token == address(0)) revert InvalidAddress();
        if (_feeRecipient == address(0)) revert InvalidAddress();
        if (_insurancePool == address(0)) revert InvalidAddress();
        token = IERC20(_token);
        tokenDecimals = _tokenDecimals;
        feeRecipient = _feeRecipient;
        insurancePool = _insurancePool;
        emit FeeRecipientUpdated(address(0), _feeRecipient);
        emit InsurancePoolUpdated(address(0), _insurancePool);
    }

    // ─── Fee math ─────────────────────────────────────────────

    /// Pure fee computation using snapshot parameters of a specific job.
    /// `approveAndPay` and `resolveDispute` MUST use this on the job's
    /// snapshot, not the contract's mutable state, so M-03 stays fixed.
    function _computeFeeFor(Job storage j, uint256 amount) internal view returns (uint256) {
        uint256 calc = (amount * j.snapshotFeeBps) / 10_000;
        if (calc < j.snapshotMinFee) return j.snapshotMinFee;
        if (calc > j.snapshotMaxFee) return j.snapshotMaxFee;
        return calc;
    }

    /// Public, current-parameter fee preview. Off-chain clients use this
    /// to show users the fee they would pay *if they created the job now*.
    function previewFee(uint256 amount) external view returns (uint256) {
        uint256 calc = (amount * feeBps) / 10_000;
        if (calc < minFee) return minFee;
        if (calc > maxFee) return maxFee;
        return calc;
    }

    // ─── createJob ────────────────────────────────────────────
    function createJob(
        address payee,
        uint256 amount,
        bytes32 taskHash,
        uint64 deadline
    ) external whenNotPaused nonReentrant returns (uint256 jobId) {
        if (payee == address(0)) revert InvalidAddress();
        if (payee == msg.sender) revert SelfJob();
        if (amount <= minFee) revert AmountTooSmall();
        if (taskHash == bytes32(0)) revert InvalidTaskHash();
        if (deadline <= block.timestamp) revert DeadlineExpired();

        // H-05 fix: measure actual delta rather than trust transferFrom.
        uint256 balBefore = token.balanceOf(address(this));
        token.safeTransferFrom(msg.sender, address(this), amount);
        uint256 received = token.balanceOf(address(this)) - balBefore;
        if (received != amount) revert AmountMismatch();

        jobId = nextJobId++;
        jobs[jobId] = Job({
            payer: msg.sender,
            payee: payee,
            amount: amount,
            taskHash: taskHash,
            resultHash: bytes32(0),
            deadline: deadline,
            status: JobStatus.Funded,
            snapshotFeeBps: feeBps,
            snapshotMinFee: minFee,
            snapshotMaxFee: maxFee,
            snapshotInsuranceShareBps: insuranceShareBps
        });
        totalEscrowed += amount;
        emit JobCreated(jobId, msg.sender, payee, amount, taskHash, deadline);
    }

    // ─── submitResult ─────────────────────────────────────────
    function submitResult(uint256 jobId, bytes32 resultHash)
        external
        whenNotPaused
        nonReentrant
    {
        Job storage j = jobs[jobId];
        if (j.status != JobStatus.Funded) revert InvalidStatus();
        if (msg.sender != j.payee) revert NotPayee();
        if (block.timestamp > j.deadline) revert DeadlineExpired();
        if (resultHash == bytes32(0)) revert InvalidResultHash();

        j.resultHash = resultHash;
        j.status = JobStatus.Submitted;
        emit ResultSubmitted(jobId, resultHash);
    }

    // ─── approveAndPay ────────────────────────────────────────
    function approveAndPay(uint256 jobId) external nonReentrant {
        Job storage j = jobs[jobId];
        if (j.status != JobStatus.Submitted) revert InvalidStatus();
        if (msg.sender != j.payer) revert NotPayer();
        // H-03: late approval still allowed (grace) for buyer convenience,
        // but make the semantics explicit. If we ever want strict
        // enforcement, uncomment:
        // if (block.timestamp > j.deadline) revert DeadlineExpired();

        j.status = JobStatus.Approved;

        uint256 fee = _computeFeeFor(j, j.amount);
        uint256 insuranceCut = (fee * j.snapshotInsuranceShareBps) / 10_000;
        uint256 platformCut = fee - insuranceCut;
        uint256 payout = j.amount - fee;

        totalEscrowed -= j.amount;

        if (insuranceCut > 0) token.safeTransfer(insurancePool, insuranceCut);
        if (platformCut > 0) token.safeTransfer(feeRecipient, platformCut);
        token.safeTransfer(j.payee, payout);

        emit JobApproved(jobId, fee, insuranceCut);
    }

    // ─── dispute ──────────────────────────────────────────────
    function dispute(uint256 jobId, string calldata reason) external nonReentrant {
        Job storage j = jobs[jobId];
        // H-02 fix: dispute is only valid AFTER a result was submitted.
        // A payer who wants out before submission uses refundExpired()
        // once the deadline elapses, or cancels off-chain with the payee.
        if (j.status != JobStatus.Submitted) revert InvalidStatus();
        if (msg.sender != j.payer && msg.sender != j.payee) revert NotParty();
        // Cap the reason length to keep event logs sane.
        if (bytes(reason).length > 256) revert ReasonTooLong();

        j.status = JobStatus.Disputed;
        emit JobDisputed(jobId, msg.sender, reason);
    }

    // ─── resolveDispute (NEW) ─────────────────────────────────
    // Owner-only resolution of a Disputed job. Sums must equal the
    // original amount; protocol fee is taken from the payee's share
    // proportionally (or zero if payeeAmount == 0).
    function resolveDispute(
        uint256 jobId,
        uint256 payeeAmount,
        uint256 payerAmount
    ) external onlyOwner nonReentrant {
        Job storage j = jobs[jobId];
        if (j.status != JobStatus.Disputed) revert InvalidStatus();
        if (payeeAmount + payerAmount != j.amount) revert InvalidSplit();

        j.status = JobStatus.Resolved;
        totalEscrowed -= j.amount;

        uint256 fee = 0;
        uint256 insuranceCut = 0;
        if (payeeAmount > 0) {
            // Fee is taken from the payee's share, proportional to a
            // "what if approved" fee against the full amount.
            uint256 fullFee = _computeFeeFor(j, j.amount);
            fee = (fullFee * payeeAmount) / j.amount;
            if (fee > payeeAmount) fee = payeeAmount;
            insuranceCut = (fee * j.snapshotInsuranceShareBps) / 10_000;
            uint256 platformCut = fee - insuranceCut;
            uint256 net = payeeAmount - fee;
            if (insuranceCut > 0) token.safeTransfer(insurancePool, insuranceCut);
            if (platformCut > 0) token.safeTransfer(feeRecipient, platformCut);
            if (net > 0) token.safeTransfer(j.payee, net);
        }
        if (payerAmount > 0) {
            token.safeTransfer(j.payer, payerAmount);
        }
        emit JobResolved(jobId, payeeAmount, payerAmount, fee, insuranceCut);
    }

    // ─── refundExpired (permissionless, replaces v1 owner-refund) ──
    function refundExpired(uint256 jobId) external nonReentrant {
        Job storage j = jobs[jobId];
        if (j.status != JobStatus.Funded) revert InvalidStatus();
        if (block.timestamp <= j.deadline) revert DeadlineNotElapsed();

        j.status = JobStatus.Refunded;
        totalEscrowed -= j.amount;
        token.safeTransfer(j.payer, j.amount);
        emit JobRefunded(jobId, j.payer, j.amount);
    }

    // ─── Owner-only setters (now event-emitting) ─────────────
    function setFees(
        uint16 _feeBps,
        uint256 _minFee,
        uint256 _maxFee,
        uint16 _insuranceShareBps
    ) external onlyOwner {
        if (_feeBps > MAX_FEE_BPS) revert FeeTooHigh();
        if (_insuranceShareBps > MAX_INSURANCE_SHARE_BPS) revert InsuranceShareTooHigh();
        if (_minFee > _maxFee) revert MinExceedsMax();
        emit FeesUpdated(
            feeBps, minFee, maxFee, insuranceShareBps,
            _feeBps, _minFee, _maxFee, _insuranceShareBps
        );
        feeBps = _feeBps;
        minFee = _minFee;
        maxFee = _maxFee;
        insuranceShareBps = _insuranceShareBps;
    }

    function setFeeRecipient(address _r) external onlyOwner {
        if (_r == address(0)) revert InvalidAddress();
        emit FeeRecipientUpdated(feeRecipient, _r);
        feeRecipient = _r;
    }

    function setInsurancePool(address _p) external onlyOwner {
        if (_p == address(0)) revert InvalidAddress();
        emit InsurancePoolUpdated(insurancePool, _p);
        insurancePool = _p;
    }

    function pause() external onlyOwner {
        _pause();
    }

    function unpause() external onlyOwner {
        _unpause();
    }

    // ─── Convenience read ─────────────────────────────────────
    function getJob(uint256 jobId) external view returns (Job memory) {
        return jobs[jobId];
    }
}
