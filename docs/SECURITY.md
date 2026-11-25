# Security overview, verification status and what an external tester should cover

## Controls in place (all covered by automated tests unless noted)
* **Tenant isolation:** every tenant record has a mandatory restaurant; the tenant is taken only from the validated host; cross-tenant and cross-branch ids return 404. A route sweep proves every non-public endpoint refuses anonymous callers and never returns a 5xx for garbage input.
* **Authentication:** JWT with a per-user token version (password change, deactivation and MFA reset revoke every session at once); login lockout; throttles; generic failure messages.
* **Two-factor authentication (TOTP, RFC 6238):** mandatory for platform administrators and restaurant administrators (`MFA_REQUIRED_ROLES` extends it). Secrets are encrypted at rest; a code works once; ten single-use recovery codes (HMAC only is stored); failed attempts lock the account for 15 minutes; enrolment needs the password; an unenrolled privileged account can reach nothing but the enrolment screens; Google sign-in cannot bypass it; a platform administrator can reset a staff member's factor and an operator can reset any (`manage.py mfa_reset <email>`); every step is audited. Production refuses to start with `MFA_ENFORCEMENT` off. Verified against the RFC test vectors and in a real browser (enrol, QR, recovery codes, two-step sign-in).
* **Uploads:** real image decoding, size and format limits, random storage names, built-in rejection of the EICAR signature and embedded script/PHP markers, and every accepted image is also **re-encoded from its pixels** (hidden payloads, polyglot tails and EXIF/GPS data do not survive), and **ClamAV scanning over the clamd protocol** is available (`UPLOAD_SCANNER=clamav`). Production requires `clamav`, or `builtin` where no ClamAV daemon can run (for example Render without Docker); it fails closed when ClamAV is configured but unreachable. The protocol client is tested against a stand-in clamd; it has **not** been run against a real ClamAV daemon.
* **Money and records:** server-side pricing, Decimal only, immutable receipts/payments/audit/stock movements, idempotent sensitive operations, separation of duties in payroll, voiding instead of deleting.
* **Secrets and configuration:** environment only; `preflight` verifies production configuration without printing secrets.
* **Backups:** encrypted (Fernet), checksummed, verified, restore from the System page needs the password, an authenticator code and a typed confirmation, takes a verified safety snapshot first and runs in maintenance mode (also available to an operator by command into an empty database); uploaded media is backed up as a second encrypted archive when stored locally (Cloudinary keeps its own copies).
* **Dependencies:** `pip-audit` and `npm audit` reported no known vulnerabilities on 2026-11-25. Re-run both before every release (`pip install pip-audit; python -m pip_audit` in `backend`, `npm audit` in `frontend`) and in CI; both need internet access.

## Not verified / not done: be honest with auditors and customers
* **No external penetration test has been performed.** It cannot be done by the developers of the system. Commission one before taking real customer money. Suggested scope below.
* ClamAV, Redis, PostgreSQL, Cloudflare R2, Brevo and Monime have not been exercised against real services in this environment.
* MFA: the JWT carries the "privileged" and "enrolled" flags from sign-in time; a role granted later takes effect at the next sign-in or refresh of the account's tokens. SMS/email codes and WebAuthn/passkeys are not offered (authenticator apps only).
* The token/CSRF model assumes the API is called with a bearer token (no cookies). Content-Security-Policy headers must be set at the web server for the static frontend.
* Payroll statutory rules are configured by the restaurant: the system does not know any country's tax law. A wrong rate produces wrong pay slips.

## Suggested penetration-test scope
1. Tenant isolation: IDOR across restaurants and branches on every `/api/v1` endpoint, host-header and custom-domain spoofing, WebSocket authentication and origin checks.
2. Authentication: lockout and throttle bypass, token tampering/replay, MFA brute force and replay, recovery-code handling, password reset and invitation links, Google sign-in linking.
3. Payments: webhook signature handling and replay, amount/currency mismatch handling, idempotency abuse, refund and discount abuse by staff roles.
4. Uploads and file serving: polyglot files, content sniffing, path traversal, scanner bypass and fail-closed behaviour.
5. Business logic: payroll approval separation, reservation double-booking races, stock oversell races (run `concurrency_check` on staging PostgreSQL first), invoice and expense voiding rules.
6. Infrastructure: TLS, proxy header trust, rate limiting behind the load balancer, secrets handling, backup bucket permissions, restore procedure.
