# Decisions

Every interpretation the planner made where the specification is silent or ambiguous, with the
reason. Contract ids refer to `CONTRACT.md`. A decision may be revised only by a new, dated entry
that names the one it replaces.

## M1 — Stage 1

**D1. Check order for every authenticated write.** (S1-ERR-*, S1-IDEM-9)
Order: 401 `unauthenticated` → (settlements only: 403 `forbidden` for non-operators) → 400
`missing_idempotency_key` → 422 key longer than 255 → 400 `malformed_request` if the body does not
parse or is not a JSON object → idempotency lookup (200 replay / 409 `idempotency_key_reuse`) →
400 wrong JSON type of a non-special field / 422 field rules in the order the fields are listed in
the endpoint's table → 404 unknown handle or resource → 403 not the permitted party →
422 `self_payment` / `self_request` → 409 state (`request_not_pending`, then `insufficient_funds`).
Reason: §7 fixes "authenticated, body parsed as an object, then key resolved, then field
validation and resource checks"; the rest follows the order of the specification's tables.
Only one error applies to a request, so the order matters only when several rules are broken.

**D2. The idempotency record is keyed by (user, method, path, key).** (S1-IDEM-3, S1-IDEM-4)
Reason: §7 says the same key with the same body on a different path "is a different request, not a
replay, and must succeed normally". So `POST /requests/rq_1/pay` and `POST /requests/rq_2/pay`
with one key are independent. Within one (user, method, path, key), a different body is 409.
Only a 2xx outcome claims the key; any 4xx leaves it unclaimed.

**D3. "Same JSON value" compares numbers by exact numeric value.** (S1-IDEM-6, S1-MOD-2)
`1000`, `1000.0` and `1e3` are one value, since §4 says they "represent the same valid
minor-unit amount". Objects compare by key set and values regardless of order; arrays in order;
`true` is not `1`. Reason: consistency with §4.

**D4. Amounts are judged exactly, never through binary floating point.** (S1-MOD-2, S1-INV-6)
A number is a valid amount when its exact decimal value is an integer in range (e.g. parse JSON
numbers as `Decimal`). `1000.5`, `1e-3`, `null`, `true`, `"1000"`, arrays and objects are 422
`validation_failed`. Reason: §5 makes every invalid `amount` 422 and §4 forbids rounding error;
a float parse would accept `1000000000.0000001` as `1e9`.

**D5. Wrong JSON types of other fields are 400 `malformed_request`.** (S1-ERR-2, S1-ERR-10)
`to_handle`, `payer_handle`, `participant_handles` (and its elements), `email`, `password`,
`display_name` of the wrong JSON type (including `null`) are 400. A missing required field is 422.
Exceptions stated by the spec: `amount`, `note`, `visibility` (always 422), and settlement batch
shape (D17).

**D6. A handle that no user has is 404 even when it could never be valid.** (S1-PAY-9, S1-REQ-3)
`"ADA"` or `"@ada"` for `to_handle`/`payer_handle`/`participant_handles` is 404 `not_found`.
Matching is exact and case-sensitive. Reason: the tables say "No user has that handle → 404".

**D7. Character counts are Unicode code points.** (S1-PAY-7, S1-AUTH-4, S1-ERR-13)
`note` ≤ 200, password ≥ 8, `Idempotency-Key` 1..255 are counted in code points. Reason: the spec
says "characters"; code points are the unambiguous reading.

**D8. Emails.** (S1-AUTH-3, S1-AUTH-5)
Valid form: exactly one `@`, non-empty local part and non-empty domain, no whitespace. Uniqueness
and login lookup are case-insensitive; the email is stored as given. Handle derivation uses the
local part as given, lowercased (S1-MOD-4). Signup error order: 400 types → 422 (email form,
password length, missing fields) → 409 `email_taken` → 409 `handle_taken`. Reason: the form rule is
the plain reading of "`local@domain`"; mail addresses are conventionally case-insensitive.

**D9. `display_name` is a required string on signup.** Missing is 422; wrong type is 400. Any
string is accepted. Reason: the response returns it and §6 lists no rule for it.

**D10. Timestamps.** (S1-RT-5)
All timestamps are UTC formatted `YYYY-MM-DDTHH:MM:SS+00:00` (second precision). Seeded payments
and requests take the reset time; a fixture item that carries a valid RFC 3339 `created_at` keeps
it. Lists sort newest first by `created_at`, ties broken by creation order (later first), which
makes `GET /requests` pagination deterministic. Reason: examples use this format; fixtures carry no
times.

**D11. Seeded records.** (S1-FIX-*)
Seeded payments have `request_id: null` and `settlement_id: null`. Seeded requests with status
`paid` have `payment_id: null` unless the fixture supplies one. Seeded ids are used as given; the
service's own ids must never collide with seeded or imported ids (e.g. random suffixes).

**D12. Reset validation.** (S1-FIX-4, S1-FIX-5, S1-RT-3)
`POST /_test/reset` returns 400 `malformed_request` for a body that does not parse or is not an
object, and 422 `validation_failed`, changing nothing, for: a negative or non-integer balance,
`minor_units` not in {0, 2, 3}, missing `currency`/`users`, a user missing `id`/`email`/`password`/
`handle`/`balance`, a handle not matching `^[a-z0-9_]{1,20}$`, duplicate user ids, handles or
emails, a total balance above 2⁵³, a payment or request naming an unknown user or with an invalid
amount/status/visibility. `payments`, `requests` and `settlement_operator_ids` default to `[]`;
operator ids that name no user are ignored. Reset must return within 10 s for a fixture of 200
users on 2 vCPU, so password hashing cost must be chosen (or parallelised) to fit.

**D13. Unrouted method or path is 404 `not_found`** with the error body. Reason: §5 requires the
error body on every 4xx; 404 is the listed code that fits.

**D14. Request bodies are parsed as JSON regardless of `Content-Type`.** Invalid UTF-8 is 400
`malformed_request`. For `POST /requests/{id}/pay` only, an empty body is treated as `{}`.
`decline` and `cancel` ignore their body. Reason: robustness; pay's body is entirely optional.

**D15. Requests by a third party.** (S1-RPAY-4, S1-RDEC-1, S1-RCAN-1)
For an existing request, any authenticated caller who is not the permitted party (including a user
who is neither requester nor payer) gets 403 `forbidden`; an id that does not exist is 404. Order:
404 → 403 → 409. Reason: the endpoint tables name 403 for "not the payer/requester" explicitly.

**D16. Zero-amount requests.** (S1-MON-3)
A split may create a request with `amount: 0`. Paying it succeeds and creates a payment of `0`.
`POST /requests` and `POST /payments` still require `amount ≥ 1`.

**D17. Settlement validation.** (S1-SET-2..5)
Order: 401 → 403 non-operator → 400/422 key → 400 unparseable body/not an object → key lookup →
batch shape (422 `validation_failed`: `transfers` missing, not an array, empty, more than 32
entries, or an entry that is not an object) → entries in input order; within an entry: `from_handle`
/`to_handle` missing or not a string (422), `amount`, `note`, `visibility` (422) → unknown handle
(404) → self-transfer (422 `self_payment`) → collective affordability (409 `insufficient_funds`).
The first failing entry decides the response. Reason: "malformed batch shape is 422" and "Entry
errors take precedence in input order, before insufficient funds".
Affordability is computed on net per-wallet deltas and all balances change in one transaction, so
no wallet is negative at any time. The operator need not be a party to any transfer.

**D18. `settlement_id` is part of every payment body in stage 1** (null for non-members), in
`POST /payments`, `POST /requests/{id}/pay`, `GET /activity` and settlement responses.
Reason: §11 "nonmembers expose null for that field".

**D19. Settlement ids and payments.** Settlement member payments are ordinary payments (appear in
`GET /activity` by the feed rule). `committed_at` and each member's `created_at` are the identical
string.

**D20. Import validation.** (S1-EXP-*)
Body must be an object with `track == "pocketful"`, `format_version == 1` (the integer) and a
`state` object this service can load; otherwise 422 `validation_failed` and no change. An
unparseable body is 400. Export and import each run in one transaction.

**D21. Passwords** are hashed with a salted memory-hard or iterated KDF from the standard library
(e.g. `hashlib.scrypt`), cost chosen to meet D12 and the 5 s request limit at 50 concurrent logins.

**D22. Stage-1 folder builds no stage-2 behaviour** (no HTML screens). The stage-2 suite line in
the check run is expected to fail.

**D23. The payment created by paying a request copies the request's `note`**, goes from the payer
to the requester for the request's `amount`, and has `settlement_id: null`. Reason: §8 says pay
returns a payment "exactly as `POST /payments` returns one", and the pay body carries only
`visibility`, so the note can only come from the request.

**D24. WI-1.1 criteria 2 and 6 (no outbound network) are verified on an isolated network.**
Docker does not publish `-p` ports for a `--network none` container, so the literal command in the
criterion cannot be reached from the host. Criteria 2 and 6 are satisfied by either (a) `--network
none` with the request made from inside the container, or (b) a `docker network create --internal`
network with the request made from another container on it. Host-reachable checks of criteria 2–5
use the default bridge. This changes how the criterion is observed, not what it requires.

**D25. Reset fixture field types** (extends D12). On `POST /_test/reset`, a fixture field of the
wrong JSON type (e.g. `"balance": "100"`, `"users": {}`) is 422 `validation_failed`, like any other
invalid fixture; 400 `malformed_request` is only for a body that does not parse or is not an
object. Seeded emails and passwords are not checked for form or length; a missing seeded
`display_name` defaults to the handle; seeded request amounts may be 0..1e9 (D16), seeded payment
amounts 1..1e9. Reason: §4 calls a bad fixture "a reset error: return 422"; the fixture is test
input and must load whatever valid-enough data the harness sends.
