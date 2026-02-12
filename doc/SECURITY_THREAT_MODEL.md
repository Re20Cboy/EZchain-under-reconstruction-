# EZchain MVP Threat Model (Internal Gate)

## Scope
- Local loopback API service (`EZ_App/service.py`)
- Local wallet state and transaction submission path
- P2P envelope verification for handshake and key transaction messages

## Threats and Mitigations
1. Replay attack on transaction submit
- Threat: reuse prior valid request to trigger duplicate state transitions.
- Mitigation: `X-EZ-Nonce` required; nonce cache with TTL; replay returns `replay_detected`.

2. Duplicate transaction submission
- Threat: repeated client request with same semantic transaction.
- Mitigation: `client_tx_id` idempotency check; duplicates return `duplicate_transaction`.

3. Malformed payload and oversized body
- Threat: crash/resource abuse with invalid JSON or huge body.
- Mitigation: request size cap (`max_payload_bytes`), strict JSON object parsing, explicit error codes.

4. Weak input validation
- Threat: invalid identifiers or unexpected characters reach business layer.
- Mitigation: server-side format checks for nonce, recipient, and `client_tx_id`.

5. Key and secret exposure via logs
- Threat: wallet secrets/passwords leaked in audit log.
- Mitigation: audit logger redaction for sensitive fields and token/password headers.

## Residual Risk
- No external audit completed in MVP stage.
- DoS resistance is limited to local service constraints and basic rate surfaces.
- Public testnet posture is lower than mainnet security assumptions.
