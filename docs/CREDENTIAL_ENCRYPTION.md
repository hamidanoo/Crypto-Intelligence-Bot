# Credential Encryption at Rest (Phase 8)

## Design

- Algorithm: AES-GCM (authenticated encryption) via the
  `cryptography` library, which was already pinned.
- Key: `CREDENTIAL_ENCRYPTION_KEY`, a base64-encoded
  32-byte key stored outside source control (deployment
  environment or secret manager). The key is never
  committed, never logged, and never returned by any
  API.
- Storage: `api_integrations.encrypted_secret` holds the
  ciphertext (base64), `encrypted_nonce` holds the
  fresh 12-byte nonce (base64), and `encryption_key_id`
  records which key encrypted the row (`current` or
  `previous`). A fresh nonce is generated for every
  encryption, so identical plaintexts never produce
  identical ciphertexts.
- Display: read APIs return only `api_key_masked`, at
  most the last four characters of the API key
  (`****ABCD`). Decrypted secrets are never returned.
- Decryption happens only in authorised internal
  service paths: the integration test-connection path.
  It is never performed for a list or detail response.

## Behaviour when the key is missing or invalid

- Production startup fails without
  `CREDENTIAL_ENCRYPTION_KEY` (settings validator).
- In non-production, credential writes fail with a
  clear 503 error and the application still starts, so
  the misconfiguration is visible instead of silently
  storing plaintext.
- An invalid (non-base64, or not 32 bytes) key fails
  the same way. A stored credential that cannot be
  decrypted (wrong key, tampered ciphertext) fails the
  test-connection with a clear error and no plaintext.

## Rotation procedure

1. Generate a new 32-byte key and set it as
   `CREDENTIAL_ENCRYPTION_KEY`, keeping the old key as
   `CREDENTIAL_ENCRYPTION_KEY_PREVIOUS`.
2. For each integration, run test-connection: rows
   encrypted under the old key still decrypt through
   the `previous` key id. Re-save the credential
   through the integration update endpoint, which
   re-encrypts it under the current key.
3. Once every row's `encryption_key_id` is `current`,
   remove `CREDENTIAL_ENCRYPTION_KEY_PREVIOUS` from the
   deployment environment.
4. Record the rotation in the audit log (credential
   updates are audited without secret values).

## What is not encrypted, and why

Bot tokens and API keys that arrive through
environment variables (for example
`TELEGRAM_BOT_TOKEN`) are deployment secrets managed
by the deployment environment, not by this service;
they are never returned by any API and never logged.
Only credentials entered through the admin API are
encrypted at rest by this design. Telegram group
configuration stored in the database contains no
token.
