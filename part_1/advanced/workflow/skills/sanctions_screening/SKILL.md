---
name: sanctions-screening
description: Evaluate a supplier's supplied sanctions-screening record, preserve the screening reference, and fail closed when a possible match exists.
tools: [screen_supplier_sanctions]
---

# Sanctions screening

## When to use

Use this procedure for every supplier review, even when the evidence bundle already labels a sanctions control as passed.

## Steps

1. Send the supplier identity and authoritative screening record to `screen_supplier_sanctions`.
2. Preserve the screening reference and checked-at timestamp.
3. Return `clear` only when the supplied record explicitly has no possible match.
4. Return `blocked` when a possible match exists or the screening record is missing.
5. Keep this result separate from evidence freshness so one check cannot mask the other.

## Do not use

Do not perform open-web name matching or infer a result from supplier nationality alone.
