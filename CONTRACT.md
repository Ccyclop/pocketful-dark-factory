# Contract

Every externally visible element of the specification, copied verbatim with an id and its
specification reference. Interpretations of silent or ambiguous points are in `DECISIONS.md`
and are referenced here as `Dn`. The specification wins over this file if they ever differ.

Source: `pocketful/spec/stage-N.md` in the event kit. Ids: `S<stage>-<area>-<n>`.

---

## Milestone M1 — Stage 1: payments and settlements (delivery folder `stage-1/`)

### Global invariants (stage-1 §1, §4)

| Id | Verbatim | Ref |
|---|---|---|
| S1-INV-1 | "The sum of wallet balances always equals the total seeded by the last `POST /_test/reset`." | §1 |
| S1-INV-2 | "No wallet balance may be negative, including transiently." | §1 |
| S1-INV-3 | "A payment request may move money at most once." | §1 |
| S1-INV-4 | "The following apply to all operations, including concurrent requests and retries" (applies to S1-INV-1..3) | §1 |
| S1-INV-5 | "All amounts are exact integer counts of minor units. Deposits, top-ups, withdrawals, cards and bank integrations are out of scope. Money moves only between existing wallets." | §1 |
| S1-INV-6 | "`amount` is at most `1000000000` on any single request, and no operation produces a balance outside ±2⁵³. Monetary arithmetic must preserve exact minor-unit values without rounding error." | §4 |
| S1-INV-7 | "Requests must not produce 5xx responses, including under concurrent load." | §5 |
| S1-INV-8 | "Only the HTTP API is required." | §1 |
| S1-INV-9 | "Build from the supplied requirements. Source code, API documentation and schemas from existing products in this domain must not be used." | preamble |

### Delivery and runtime (stage-1 §2, §3; dispatch)

| Id | Verbatim | Ref |
|---|---|---|
| S1-DEL-1 | "Deliver an HTTP service, a `Dockerfile` and a `RUN.md` with a command that builds and starts the service without manual setup." | §2 |
| S1-DEL-2 | "The image must run on its own with `-e PORT=<port>` and a port mapping. Runtime networking has no outbound access. All runtime dependencies, initialization and seed data must work within that single container. Compose configuration is not used to start the service." | §2 |
| S1-DEL-3 | Resource limits: "CPU 2 vCPU; Memory 2 GiB; Start to first healthy response 60 s; Concurrent requests up to 50 in flight; Per-request timeout 5 s (10 s for `POST /_test/reset`); Outbound network available during `docker build`, **none at run time**; Disk ephemeral; state need not survive a container restart" | §2 table |
| S1-DEL-4 | "Runtime assets and dependencies must be included in the image. This includes fonts, scripts and stylesheets; external services are unavailable at runtime." | §2 |
| S1-DEL-5 | Dispatch stack: "Python 3.12, FastAPI and uvicorn, SQLite from the standard library with every write in a transaction." | dispatch |
| S1-DEL-6 | Dispatch folders: "stage-N/ is both the working folder and the delivery folder, and it is frozen once released." "Every stage folder is a complete service on its own, with a Dockerfile and a RUN.md whose command builds and starts it with no manual steps." "A stage folder solves its own stage and not a later one: do not build later-stage behaviour early." "Acceptance tests go in acceptance/ and attack scripts in adversary/, both outside the stage folders." | dispatch |
| S1-RT-1 | "Listen on `0.0.0.0` using the `PORT` environment variable, default `8080`." | §3.1 |
| S1-RT-2 | "`GET /health  ->  200  {"status": "ok"}`" "Return 200 once the service and its data store can serve requests, within 60 seconds of container start. Non-200 responses are permitted before the service is ready." | §3.2 |
| S1-RT-3 | "`POST /_test/reset` … `{ ...fixture... }` -> `204 No Content`" "Replace all service state with the fixture in the request body (§4). When reset returns 204, subsequent requests must see only that fixture. Repeated resets are supported. This test endpoint must be enabled in the delivered image and requires no authentication." | §3.3 |
| S1-RT-4 | "Requests and responses are `application/json; charset=utf-8`." | §3.4 |
| S1-RT-5 | "Timestamps in responses are RFC 3339 with an explicit offset, e.g. `2026-09-24T19:00:00+02:00`." | §3.4 |
| S1-RT-6 | "Unknown fields in a request body are ignored, never an error." | §3.4 |
| S1-RT-7 | "Unknown query parameters are ignored." | §3.4 |
| S1-RT-8 | "IDs are opaque strings of at most 64 characters. Their format is yours." | §3.4 |

### Model and fixture (stage-1 §4)

| Id | Verbatim | Ref |
|---|---|---|
| S1-MOD-1 | "The service has **one currency**, declared in the fixture. Every amount in the API is an integer count of its minor units: `1000` in a `minor_units: 2` service is €10.00, and `1000` in a `minor_units: 0` service is ¥1000." | §4 |
| S1-MOD-2 | "API amounts must have an integral numeric value: JSON `1000`, `1000.0` and `1e3` all represent the same valid minor-unit amount. Booleans and strings are not numbers here." | §4 |
| S1-MOD-3 | "Every user has a **handle**: unique across the service, matching `^[a-z0-9_]{1,20}$`, and never changing once set. Users identify recipients by handle. Directory and user-search endpoints are out of scope." | §4 |
| S1-MOD-4 | "Seeded users take their handle from the fixture. A user created through `POST /auth/signup` (§6 — there is no `handle` field in the signup body) has one **derived** from their email: take the local part, lowercase it, replace every character outside `[a-z0-9_]` with `_`, and truncate to 20 characters. If that handle is already taken the signup fails; see the signup table in §6." | §4 |
| S1-MOD-5 | "New users start with a balance of `0`. They can receive money and be asked for money immediately." | §4 |
| S1-MOD-6 | "A **payment** moves money from one wallet to another, immediately and atomically. It is either sent directly or created by paying a request." | §4 |
| S1-MOD-7 | "A **request** asks someone for money. The `requester` will receive; the `payer` is being asked. A request is `pending`, and then exactly one of `paid`, `declined` or `cancelled`. Only the payer may pay or decline it; only the requester may cancel it." | §4 |
| S1-MOD-8 | "**A request may exceed the payer's balance.** That is a legal state, not an error at creation time: the request stays `pending` until it is paid, declined or cancelled, and an attempt to pay it while short is `409 insufficient_funds` and changes nothing. Money can arrive later and the same request then becomes payable." | §4 |
| S1-MOD-9 | "**Visibility belongs to the payment, not the request.** The payer chooses it when the money moves. A request carries no visibility of its own and never appears in anyone else's feed." | §4 |
| S1-FEED-1 | "`GET /activity` returns payments only. A payment appears for a caller **if and only if** its `visibility` is `public`, **or** the caller is its sender or its receiver. There is no other rule, no follow graph and no mute list. Requests never appear in the activity feed; they are read through `GET /requests`, which returns only requests where the caller is the requester or the payer." | §4 |
| S1-FEED-2 | "A split is not a feed item. The requests it creates are visible to their own two parties, and the payments that eventually fulfil them follow the rule above." | §4 |
| S1-FEED-3 | "Visibility is **one value on the payment**, seen identically by both parties and by everyone else. A `private` payment is hidden from third parties, not from its own receiver." | §4 |
| S1-FIX-1 | Fixture format: `{"currency": "EUR", "minor_units": 2, "users": [{"id","email","password","display_name","handle","balance"}...], "payments": [{"id","from_user_id","to_user_id","amount","note","visibility"}...], "requests": [{"id","requester_id","payer_id","amount","note","status"}...]}` (exact example in §4) | §4 |
| S1-FIX-2 | "Seeded users must be able to log in with the given password immediately." | §4 |
| S1-FIX-3 | "`balance` is the wallet balance **after** every seeded payment has been applied. Seeded numbers are consistent; you do not replay seeded payments against balances." | §4 |
| S1-FIX-4 | "A `balance` below zero in a fixture is a reset error: return `422 validation_failed` from `POST /_test/reset` and change nothing." | §4 |
| S1-FIX-5 | "`minor_units` is `0`, `2` or `3`. Fixtures use `EUR` (2), `JPY` (0) and `BHD` (3)." | §4 |
| S1-FIX-6 | "An administrative balance endpoint is out of scope." | §4 |
| S1-FIX-7 | "The reset fixture may include `settlement_operator_ids`, an array of user ids, default []." | §11 |

### Errors (stage-1 §5)

| Id | Verbatim | Ref |
|---|---|---|
| S1-ERR-1 | "Every 4xx and 5xx response carries this body: `{ "error": { "code": "insufficient_funds", "message": "human readable, any wording" } }`" "Use the specified HTTP status and `code`. The human-readable `message` may use any wording." | §5 |
| S1-ERR-2 | 400 `malformed_request` — "Unparseable body, or a field of the wrong JSON type" | §5 |
| S1-ERR-3 | 400 `missing_idempotency_key` — "Required `Idempotency-Key` header absent or empty" | §5 |
| S1-ERR-4 | 401 `unauthenticated` — "Missing, malformed or unknown bearer token" | §5 |
| S1-ERR-5 | 403 `forbidden` — "Authenticated, but not permitted to touch this resource" | §5 |
| S1-ERR-6 | 404 `not_found` — "No such resource, or not visible to this caller" | §5 |
| S1-ERR-7 | 409 `idempotency_key_reuse` — "Key already used by this caller with a different request body" | §5 |
| S1-ERR-8 | 422 `validation_failed` — "A required field or query parameter is missing, or a stated rule is violated with no more specific code" | §5 |
| S1-ERR-9 | "A field of the correct JSON type with an invalid format or out-of-range value gives 422 `validation_failed`, unless an endpoint specifies a different error. This includes invalid dates, negative counts and values exceeding a stated maximum or length." | §5 |
| S1-ERR-10 | "Endpoint-specific field rules take precedence: invalid `amount` values (including strings and booleans), non-string `note` values (including `null`), and any `visibility` other than `public` or `private` are 422 `validation_failed`. Omission alone selects the optional-field defaults. Other wrong JSON types follow the rule below." | §5 |
| S1-ERR-11 | "An integer-valued **query parameter** is written as plain decimal digits: `1e9`, `4.0` and `+4` are 422 `validation_failed` whatever their numeric value." | §5 |
| S1-ERR-12 | "Reserve 400 `malformed_request` for a body that does not parse or a field of the wrong type." | §5 |
| S1-ERR-13 | Shared ranges, "enforced on every endpoint that takes them": `Idempotency-Key` "1 to 255 characters" else 422 `validation_failed`; `limit` "integer 1 to 200" else 422 `validation_failed`; `offset` "integer 0 or more" else 422 `validation_failed` | §5 |

### Authentication (stage-1 §6)

| Id | Verbatim | Ref |
|---|---|---|
| S1-AUTH-1 | "`POST /auth/signup` `{ "email": "a@example.com", "password": "correct horse", "display_name": "Ada" }` -> `201 { "user_id": "u_1", "display_name": "Ada", "token": "..." }`" | §6 |
| S1-AUTH-2 | "`POST /auth/login` `{ "email": "a@example.com", "password": "correct horse" }` -> `200 { "user_id": "u_1", "display_name": "Ada", "token": "..." }`" | §6 |
| S1-AUTH-3 | Email already registered → 409 `email_taken` | §6 table |
| S1-AUTH-4 | Password shorter than 8 characters → 422 `validation_failed` | §6 table |
| S1-AUTH-5 | `email` not of the form `local@domain` → 422 `validation_failed` | §6 table |
| S1-AUTH-6 | Wrong password or unknown email on login → 401 `unauthenticated` | §6 table |
| S1-AUTH-7 | The handle derived from the email (§4) is already taken → 409 `handle_taken`, "and no account is created" | §6 table |
| S1-AUTH-8 | "Every other endpoint requires a bearer token, except `/health`, `/_test/reset` and the two above. Wallet API endpoints require authentication." `Authorization: Bearer <token>` | §6 |
| S1-AUTH-9 | "Tokens do not expire. An account may have multiple valid tokens and concurrent sessions." | §6 |
| S1-AUTH-10 | "Passwords must be stored using a password-hashing function such as bcrypt, scrypt or Argon2, or an equivalent. Plaintext password storage is not permitted." | §6 |
| S1-AUTH-11 | "Email verification, password reset, refresh tokens and role-management endpoints are out of scope. Permissions specified elsewhere in these requirements still apply." | §6 |

### Idempotency (stage-1 §7)

| Id | Verbatim | Ref |
|---|---|---|
| S1-IDEM-1 | "Five write paths require an idempotency key (§8 and §11): **`POST /payments`**, **`POST /requests`**, **`POST /requests/{id}/pay`**, **`POST /splits`** and **`POST /settlements`**. Everything below applies to each of them independently." | §7 |
| S1-IDEM-2 | "`Idempotency-Key: <client-chosen string, 1..255 characters>`" | §7 |
| S1-IDEM-3 | "The key is scoped to **the authenticated user**. Two different users may use the same key string with no interaction between them." | §7 |
| S1-IDEM-4 | "A replay means the same user sending the **same method, the same path and the same body**. The same key with the same body on a different path is a different request, not a replay, and must succeed normally." | §7 |
| S1-IDEM-5 | Header absent or empty → 400 `missing_idempotency_key`; First use of the key → "The normal response, **201**"; Replay: same key, same body → "**200**, body identical to the original response as a JSON value"; Same key, different body → 409 `idempotency_key_reuse`; Key reused after the original request failed with 4xx → "Treated as a first use" | §7 table |
| S1-IDEM-6 | "\"Same body\" means the same JSON value after parsing — key order and whitespace do not matter." | §7 |
| S1-IDEM-7 | "For concurrent identical requests with an unused key, exactly one returns 201. The others return 200 with the same body. The operation takes effect only once." | §7 |
| S1-IDEM-8 | "A successful replay returns the original response, even after the resource changes or is cancelled. It makes no further state changes." | §7 |
| S1-IDEM-9 | "After the body has parsed as a JSON object and the caller is authenticated, an already claimed key is resolved before endpoint field validation or current-resource checks. Thus changing a successful request to an invalid body with the same key still returns `409 idempotency_key_reuse`." | §7 |

### API (stage-1 §8)

| Id | Verbatim | Ref |
|---|---|---|
| S1-ME-1 | `GET /me` → `{ "user_id": "u_ada", "display_name": "Ada", "handle": "ada", "balance": 10000, "currency": "EUR", "minor_units": 2 }` | §8 |
| S1-PAY-1 | `POST /payments` — "**An idempotent write path.** `Idempotency-Key` is required; see §7." Body `{ "to_handle": "bob", "amount": 1500, "note": "dinner", "visibility": "public" }` | §8 |
| S1-PAY-2 | "`note` is optional and defaults to `""`. `visibility` is optional and defaults to `"public"`." | §8 |
| S1-PAY-3 | 201 payment body: `{ "payment_id": "p_7", "from_user_id": "u_ada", "from_handle": "ada", "to_user_id": "u_bob", "to_handle": "bob", "amount": 1500, "currency": "EUR", "note": "dinner", "visibility": "public", "request_id": null, "created_at": "2026-09-24T11:04:03+00:00" }` — plus `settlement_id` per S1-SET-8 | §8, §11 |
| S1-PAY-4 | The caller's balance is below `amount` → 409 `insufficient_funds` | §8 table |
| S1-PAY-5 | `amount` below 1, above 1000000000, or not an integer → 422 `validation_failed` | §8 table |
| S1-PAY-6 | `to_handle` is the caller's own handle → 422 `self_payment` | §8 table |
| S1-PAY-7 | `note` longer than 200 characters → 422 `validation_failed` | §8 table |
| S1-PAY-8 | `visibility` is neither `public` nor `private` → 422 `validation_failed` | §8 table |
| S1-PAY-9 | No user has that handle → 404 `not_found` | §8 table |
| S1-PAY-10 | "The debit and the credit are one atomic step. A payment is never visible in one wallet and not the other, and a failed payment leaves no trace in either." | §8 |
| S1-PAY-11 | "`note` is stored and returned verbatim: no trimming, no escaping, no normalisation. Unicode and emoji survive a round trip byte for byte." | §8 |
| S1-REQ-1 | `POST /requests` — "**An idempotent write path.**" Body `{ "payer_handle": "ada", "amount": 1200, "note": "taxi" }` "The caller is the requester." | §8 |
| S1-REQ-2 | 201 request body: `{ "request_id": "rq_4", "requester_id": "u_bob", "requester_handle": "bob", "payer_id": "u_ada", "payer_handle": "ada", "amount": 1200, "currency": "EUR", "note": "taxi", "status": "pending", "payment_id": null, "created_at": "2026-09-24T11:06:10+00:00" }` | §8 |
| S1-REQ-3 | `amount` below 1, above 1000000000, or not an integer → 422 `validation_failed`; `payer_handle` is the caller's own handle → 422 `self_request`; `note` longer than 200 characters → 422 `validation_failed`; No user has that handle → 404 `not_found` | §8 table |
| S1-REQ-4 | "**The payer's balance is not checked here.** A request for more than the payer holds is created normally and sits `pending`." | §8 |
| S1-RPAY-1 | `POST /requests/{id}/pay` — "**An idempotent write path.** Only the payer may call it." Body `{ "visibility": "private" }` | §8 |
| S1-RPAY-2 | "The body carries `visibility` only, optional, default `"public"`. It is the payer's choice, not the requester's. **A replay must send the identical body** — `{}` and `{"visibility": "public"}` are different JSON values, so reusing a key across the two is `409 idempotency_key_reuse`, per §7." | §8 |
| S1-RPAY-3 | "Returns `201` with the created **payment**, exactly as `POST /payments` returns one, with `request_id` set to this request. The request becomes `paid` and carries the new `payment_id`." | §8 |
| S1-RPAY-4 | The request is not `pending` → 409 `request_not_pending`; The payer's balance is below `amount` → 409 `insufficient_funds`; The caller is not the request's payer → 403 `forbidden`; Unknown request → 404 `not_found` | §8 table |
| S1-RPAY-5 | "Replaying a successful payment returns 200 with its original payment body, including when the request is already `paid`. It moves no additional money and must not return `409 request_not_pending`." | §8 |
| S1-RDEC-1 | `POST /requests/{id}/decline` — "Only the payer. No idempotency key. Returns `200` with the request, `status: "declined"`. Declining an already-declined request is `200` with the current state — declining twice is not an error. A `paid` or `cancelled` request is `409 request_not_pending`. Not the payer is `403 forbidden`." | §8 |
| S1-RCAN-1 | `POST /requests/{id}/cancel` — "Only the requester. No idempotency key. Returns `200` with the request, `status: "cancelled"`. Cancelling an already-cancelled request is `200`. A `paid` or `declined` request is `409 request_not_pending`. Not the requester is `403 forbidden`." | §8 |
| S1-RLIST-1 | `GET /requests?direction=incoming&status=pending&limit=50&offset=0` — "Requests where the caller is the requester or the payer, and no others. Newest first by `created_at`." | §8 |
| S1-RLIST-2 | "`direction` is `incoming` (the caller is the payer), `outgoing` (the caller is the requester) or absent for both." "`status` is one of the four statuses, or absent for all." | §8 |
| S1-RLIST-3 | "`limit` defaults to 50, range 1 to 200. `offset` defaults to 0 and must be 0 or more. Outside either range is 422 `validation_failed`. An unknown `direction` or `status` value is also 422." | §8 |
| S1-RLIST-4 | "`has_more` is true when items exist beyond the last one returned." Response `{ "requests": [ { ...request... } ], "has_more": false }` | §8 |
| S1-SPL-1 | `POST /splits` — "**An idempotent write path.** Splits an amount the caller already paid, and asks each of the other participants for their share by creating one `pending` request each." Body `{ "amount": 3000, "participant_handles": ["ada", "bob", "cy"], "note": "dinner" }` | §8 |
| S1-SPL-2 | "The caller may be included in `participant_handles` or omitted. Shares follow the equal-split rule in §9, in the order the handles are given. **A request is created for every participant except the caller**, each for that participant's share, with the caller as requester." | §8 |
| S1-SPL-3 | 201 body `{ "split_id": "sp_2", "amount": 3000, "currency": "EUR", "note": "dinner", "shares": [ { "handle": "ada", "amount": 1000 }, { "handle": "bob", "amount": 1000 }, { "handle": "cy", "amount": 1000 } ], "requests": [ { ...request for bob... }, { ...request for cy... } ], "created_at": "2026-09-24T11:11:00+00:00" }` | §8 |
| S1-SPL-4 | "`shares` covers every participant including the caller, in the order given, and always sums to `amount`. `requests` covers every participant except the caller, in the same order." | §8 |
| S1-SPL-5 | `amount` below 1, above 1000000000, or not an integer → 422 `validation_failed`; `participant_handles` empty, or containing a duplicate handle → 422 `validation_failed`; `note` longer than 200 characters → 422 `validation_failed`; Any handle is unknown → 404 `not_found` | §8 table |
| S1-SPL-6 | "A split whose only participant is the caller is **valid**: it computes one share, creates zero requests, and returns `"requests": []`. Nothing about a split checks anyone's balance." | §8 |
| S1-ACT-1 | `GET /activity?limit=50&offset=0` — "Payments visible to the caller by the feed contract in §4, newest first by `created_at`." Response `{ "payments": [ { ...payment... } ], "has_more": false }` | §8 |
| S1-ACT-2 | "The relative order of two payments created within the same second is unspecified. Stable pagination during concurrent writes is not required for this endpoint." "`limit` and `offset` behave exactly as in `GET /requests`." | §8 |

### Money and rounding (stage-1 §9)

| Id | Verbatim | Ref |
|---|---|---|
| S1-MON-1 | "Shares must be whole minor units, sum exactly to `amount` and differ by at most one minor unit. When the amount does not divide evenly, the larger shares go to the first participants in `participant_handles` order." | §9 |
| S1-MON-2 | Examples: 1000/3 → 334, 333, 333; 1/3 → 1, 0, 0; 10/3 → 4, 3, 3; 999/3 → 333, 333, 333; 5/5 → 1, 1, 1, 1, 1 | §9 table |
| S1-MON-3 | "Splitting the same amount among the same people in a different `participant_handles` order gives the extra unit to a different person. A share of `0` is legal and still produces a request for that participant." | §9 |
| S1-MON-4 | "Each split's shares are independent of previous splits. After any number of splits have been paid in full, wallet balances must still sum exactly to the seeded total." | §9 |

### Export and import (stage-1 §10)

| Id | Verbatim | Ref |
|---|---|---|
| S1-EXP-1 | "The service must support `GET /_test/export` and `POST /_test/import`. Like reset, these are unauthenticated test endpoints. Exports may contain credentials and session tokens; handle them as private test artifacts." | §10 |
| S1-EXP-2 | "Return 200 from export with a JSON object containing `track: "pocketful"`, `format_version: 1` and `state` (an implementation-defined JSON object). The state format is opaque to the caller and must be accepted unchanged by import." | §10 |
| S1-EXP-3 | "Import takes that entire object and atomically replaces the service's state, returning 204. It must accept an unchanged export produced by this service. No dependency on the source process, files, volume, port or network address is allowed. Import is replacement, not merge; repeating it restores the exported state without duplicating anything." | §10 |
| S1-EXP-4 | "Invalid JSON follows §5; missing fields, wrong track/version or an invalid state give 422 `validation_failed` without changing the destination. Test control calls have a 10-second timeout. Export is an atomic, read-only snapshot; subsequent source writes do not change it." | §10 |
| S1-EXP-5 | "Preserve accounts and hashed-password login, existing bearer tokens, currency, balances, payments, requests, permissions, all completed idempotent request bodies and original responses. Identities, timestamps and monetary records must not be regenerated or replayed against an already-net balance. Failed request keys remain reusable. Existing receipts, tokens and retries must remain valid after import; replacing the state with a fresh fixture does not satisfy this requirement." | §10 |
| S1-EXP-6 | "Import removes all previous destination data and credentials. Reset clears all state, including imported state. State need not survive an abrupt container restart." | §10 |

### Atomic net settlements (stage-1 §11)

| Id | Verbatim | Ref |
|---|---|---|
| S1-SET-1 | "An operator may execute a settlement across any wallets. This permission does not grant access to another user's requests or private activity items." | §11 |
| S1-SET-2 | "`POST /settlements` requires an operator and an idempotency key. No token gives 401; authenticated non-operator gives 403 `forbidden`." Body `{"transfers": [{"from_handle": "ada", "to_handle": "bob", "amount": 100}, {"from_handle": "bob", "to_handle": "cy", "amount": 50}]}` | §11 |
| S1-SET-3 | "transfers contains 1..32 objects. Each uses ordinary payment amount, note and visibility rules (defaults: empty note, public). Unknown handle is 404; self-transfer is 422 `self_payment`; malformed batch shape is 422 `validation_failed`. Entry errors take precedence in input order, before insufficient funds. Unknown fields are ignored." | §11 |
| S1-SET-4 | "A settlement is affordable when every wallet's balance after all incoming and outgoing transfers is nonnegative. Insufficient collective funds gives 409 `insufficient_funds`." | §11 |
| S1-SET-5 | "Either all movements commit together or none do; failed validation claims no idempotency key and creates no payment or revision." | §11 |
| S1-SET-6 | "Return 201 with `settlement_id`, `committed_at` and `payments` in input order." | §11 |
| S1-SET-7 | "Every member is an ordinary payment with `settlement_id` linking the batch; nonmembers expose null for that field. Members have null request_id and the same server-assigned created_at, equal to committed_at." | §11 |
| S1-SET-8 | "Constituents follow ordinary activity-feed visibility. The settlement response contains every member's receipt. Replays return 200 with the original complete response. This is the fifth idempotent write path in stage 1." | §11 |
| S1-SET-9 | "A reset/import must preserve settlement operator permissions, original payments, requests, settlement membership and retry responses." | §11 |
