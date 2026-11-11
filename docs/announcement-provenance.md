# Announcement provenance and availability

These utilities validate locally captured announcement bytes and their supplied
metadata. They do not download announcements, authenticate source timestamps,
extract financial features or approve a model for training.

## Local normalization

```bash
python -m daily_data.nse_announcement_records \
  --file /path/to/response.json \
  --provenance /path/to/capture.json \
  --symbol SYMBOL \
  --isin EXPECTED_ISIN \
  --output local-output/announcements.json
```

The response must be a nonempty JSON array of records containing `symbol`,
`sm_isin`, `seq_id`, `an_dt`, `exchdisstime`, `difference`, and `attchmntFile`.
An optional `desc` supplies the subject. The capture metadata requires:

| Field | Meaning |
| --- | --- |
| `url` | HTTPS NSE corporate-announcements endpoint with exactly one equities index, requested symbol, `from_date` and `to_date` |
| `status` | Must be `captured` |
| `sha256` | SHA-256 of the original response bytes |
| `size_bytes` | Positive integer matching the original response length |
| `row_count` | Positive integer matching the response array length |
| `request_started_at` | Timezone-aware request-start timestamp |
| `capture_completed_at` | Timezone-aware completion timestamp, no earlier than request start |

Query dates use `DD-MM-YYYY`. Missing, repeated, malformed or reversed bounds
are rejected, and each record's receipt date must be within the requested range.
Record and expected symbol/ISIN must match; sequence IDs must be unique within
the response. ISIN matching does not certify a checksum or historical identity.
Attachment URLs must use an allowed NSE archive host; no attachment is fetched
or authenticated by this module.

## Three distinct clocks

The normalizer retains `an_dt` as receipt time and `exchdisstime` as dissemination
time; the source's stated delay must match their difference. Dissemination cannot
precede receipt or exceed collection completion. A near-midnight receipt can
legitimately disseminate on the next date.

**`Asia/Kolkata` is an explicit interpretation of the source's naive timestamp
strings, not a certified timezone.** The query interval is evaluated using that
interpretation. Normalized outputs keep `original_timezone_verified` false.

Availability to this pipeline is conservatively no earlier than capture
completion and dissemination. A document retrieved today is not evidence that
this pipeline possessed it years ago. `historical_feature_approved`,
`model_feature_approved`, and the output's `training_approved` remain false.

## As-of snapshot guard

`daily_data.announcement_snapshot.validate_snapshot(record, payload, decision_at,
symbol)` checks an individual local snapshot with `symbol`, `source_url`,
`version_id`, `broadcast_at`, `captured_at`, and `sha256` metadata. Every clock
must include its timezone. The decision must be strictly later than both
publication and collection; an equal or earlier time is rejected.

For an exchange announcement, a caller must explicitly map the vetted
dissemination instant to `broadcast_at`; receipt alone is insufficient. The
general snapshot guard does not establish that this mapping or timezone is
correct. Offset-equivalent clocks receive the same canonical snapshot identity;
changed bytes receive a different one. This stateless guard is not an immutable
archive or revision registry.

The normalizer separately retains a source-response hash, row hash and capture
ID. These identify content and capture provenance; they do not prove historical
authenticity. Multiple announcement records can refer to one document or
economic event. Do not count repeated dividend disclosures as additional
entitlements without content/event reconciliation.

## Evidence and test boundaries

The CLI requires explicit local paths and refuses to overwrite its source
response or metadata. It writes output only after validation succeeds. No
captured exchange records, issuer PDFs or website snapshots are distributed
here. The tests generate invented JSON records, metadata and temporary output
files, and run offline. Real usage still requires authorized inputs, source
availability and revision/coverage checks, plus a separately validated research
protocol. Passing these checks is not a forecasting or profitability result.
