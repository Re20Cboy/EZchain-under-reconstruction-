# EZ_App API Error Codes (MVP)

## Auth
- `unauthorized`: Missing or invalid `X-EZ-Token`
- `password_required`: Missing wallet password (header or body depending route)

## Request Validation
- `invalid_request`: malformed JSON, wrong type, or business validation failure
- `invalid_content_length`: invalid `Content-Length`
- `payload_too_large`: request body exceeds `security.max_payload_bytes`
- `nonce_required`: missing anti-replay header `X-EZ-Nonce` on `/tx/send`

## Wallet
- `wallet_not_found`: wallet has not been created/imported
- `mnemonic_and_password_required`: import request missing required fields

## Transaction
- `duplicate_transaction`: repeated `client_tx_id` for same sender
- `replay_detected`: repeated `X-EZ-Nonce` within nonce TTL
- `tx_action_unsupported`: action is explicitly unsupported on the current profile
- `tx_path_not_ready`: action belongs to a remote path that is not yet available in the current state
- `remote_account_not_running`: remote `tx send` requires a running `v2-account`
- `recipient_endpoint_required`: remote `tx send` requires `recipient_endpoint` or a saved contact endpoint
- `consensus_endpoint_missing`: remote `v2-account` state is missing its consensus endpoint
- `wallet_address_mismatch_with_account_node`: local wallet identity does not match the running remote `v2-account`
- `send_failed`: tx creation/submit pipeline failed

## Generic
- `not_found`: route not found
- `internal_error`: unexpected server error
- `balance_failed`: balance query failure

## Response Shape
Success:

```json
{"ok": true, "data": {...}}
```

Error:

```json
{"ok": false, "error": {"code": "...", "message": "..."}}
```
