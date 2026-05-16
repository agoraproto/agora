// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

// AgoraEscrow - minimal escrow with capped fee model (ADR 004).
// NOT audited. Do not deploy to mainnet without audit.
// Fee formula: max(minFee, min(maxFee, feeBps * amount)).

contract AgoraEscrow {
    enum JobStatus { None, Funded, Submitted, Approved, Disputed, Refunded }

    struct Job {
        address payer;
        address payee;
        uint256 amount;
        bytes32 taskHash;
        bytes32 resultHash;
        uint64 deadline;
        JobStatus status;
    }

    address public immutable token;

    // 6 decimals (USDC)
    uint16 public feeBps = 100;           // 1.00%
    uint256 public minFee = 500_000;      // 0.50 USDC
    uint256 public maxFee = 25_000_000;   // 25.00 USDC
    uint16 public insuranceShareBps = 1_000; // 10% of fee

    address public feeRecipient;
    address public insurancePool;
    address public owner;

    mapping(uint256 => Job) public jobs;
    uint256 public nextJobId;

    event JobCreated(uint256 indexed jobId, address indexed payer, address indexed payee, uint256 amount, bytes32 taskHash, uint64 deadline);
    event ResultSubmitted(uint256 indexed jobId, bytes32 resultHash);
    event JobApproved(uint256 indexed jobId, uint256 fee, uint256 insuranceCut);
    event JobDisputed(uint256 indexed jobId, string reason);
    event JobRefunded(uint256 indexed jobId);
    event FeesUpdated(uint16 feeBps, uint256 minFee, uint256 maxFee, uint16 insuranceShareBps);

    error NotPayer();
    error NotPayee();
    error InvalidStatus();
    error TransferFailed();
    error Unauthorized();
    error AmountTooSmall();

    modifier onlyOwner() { if (msg.sender != owner) revert Unauthorized(); _; }

    constructor(address _token, address _feeRecipient, address _insurancePool) {
        token = _token;
        feeRecipient = _feeRecipient;
        insurancePool = _insurancePool;
        owner = msg.sender;
    }

    function computeFee(uint256 amount) public view returns (uint256) {
        uint256 calc = (amount * feeBps) / 10_000;
        if (calc < minFee) return minFee;
        if (calc > maxFee) return maxFee;
        return calc;
    }

    function createJob(address payee, uint256 amount, bytes32 taskHash, uint64 deadline) external returns (uint256 jobId) {
        if (amount <= minFee) revert AmountTooSmall();
        require(deadline > block.timestamp, "deadline<=now");
        if (!_transferFrom(msg.sender, address(this), amount)) revert TransferFailed();
        jobId = nextJobId++;
        jobs[jobId] = Job({
            payer: msg.sender,
            payee: payee,
            amount: amount,
            taskHash: taskHash,
            resultHash: bytes32(0),
            deadline: deadline,
            status: JobStatus.Funded
        });
        emit JobCreated(jobId, msg.sender, payee, amount, taskHash, deadline);
    }

    function submitResult(uint256 jobId, bytes32 resultHash) external {
        Job storage j = jobs[jobId];
        if (j.status != JobStatus.Funded) revert InvalidStatus();
        if (msg.sender != j.payee) revert NotPayee();
        j.resultHash = resultHash;
        j.status = JobStatus.Submitted;
        emit ResultSubmitted(jobId, resultHash);
    }

    function approveAndPay(uint256 jobId) external {
        Job storage j = jobs[jobId];
        if (j.status != JobStatus.Submitted) revert InvalidStatus();
        if (msg.sender != j.payer) revert NotPayer();
        j.status = JobStatus.Approved;
        uint256 fee = computeFee(j.amount);
        uint256 insuranceCut = (fee * insuranceShareBps) / 10_000;
        uint256 platformCut = fee - insuranceCut;
        uint256 payout = j.amount - fee;
        if (insuranceCut > 0 && !_transfer(insurancePool, insuranceCut)) revert TransferFailed();
        if (platformCut > 0 && !_transfer(feeRecipient, platformCut)) revert TransferFailed();
        if (!_transfer(j.payee, payout)) revert TransferFailed();
        emit JobApproved(jobId, fee, insuranceCut);
    }

    function dispute(uint256 jobId, string calldata reason) external {
        Job storage j = jobs[jobId];
        if (j.status != JobStatus.Submitted && j.status != JobStatus.Funded) revert InvalidStatus();
        if (msg.sender != j.payer && msg.sender != j.payee) revert Unauthorized();
        j.status = JobStatus.Disputed;
        emit JobDisputed(jobId, reason);
    }

    function refund(uint256 jobId) external {
        Job storage j = jobs[jobId];
        if (j.status != JobStatus.Funded && j.status != JobStatus.Disputed) revert InvalidStatus();
        bool deadlineExpired = block.timestamp > j.deadline && j.status == JobStatus.Funded;
        if (!deadlineExpired && msg.sender != owner) revert Unauthorized();
        j.status = JobStatus.Refunded;
        if (!_transfer(j.payer, j.amount)) revert TransferFailed();
        emit JobRefunded(jobId);
    }

    function setFees(uint16 _feeBps, uint256 _minFee, uint256 _maxFee, uint16 _insuranceShareBps) external onlyOwner {
        require(_feeBps <= 200, "fee bps too high");
        require(_minFee <= _maxFee, "min>max");
        require(_insuranceShareBps <= 5_000, "insurance > 50%");
        feeBps = _feeBps;
        minFee = _minFee;
        maxFee = _maxFee;
        insuranceShareBps = _insuranceShareBps;
        emit FeesUpdated(_feeBps, _minFee, _maxFee, _insuranceShareBps);
    }

    function setFeeRecipient(address _r) external onlyOwner { feeRecipient = _r; }
    function setInsurancePool(address _p) external onlyOwner { insurancePool = _p; }
    function transferOwnership(address _n) external onlyOwner { owner = _n; }

    function _transfer(address to, uint256 amount) internal returns (bool) {
        (bool ok, bytes memory data) = token.call(abi.encodeWithSelector(0xa9059cbb, to, amount));
        return ok && (data.length == 0 || abi.decode(data, (bool)));
    }

    function _transferFrom(address from, address to, uint256 amount) internal returns (bool) {
        (bool ok, bytes memory data) = token.call(abi.encodeWithSelector(0x23b872dd, from, to, amount));
        return ok && (data.length == 0 || abi.decode(data, (bool)));
    }
}
