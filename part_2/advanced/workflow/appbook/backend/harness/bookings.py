"""The booking system of record.

Real providers are not called: a booking here is a row that stands for the
provider's confirmation. What matters for the lesson is real: an idempotency
key makes the same booking request return the same confirmation, so a process
that dies after the provider answered but before the harness saved its
progress cannot book twice; a provider can fail; and a failed component makes
the harness cancel what it already booked before it plans again.
"""
from __future__ import annotations

import hashlib

from shared.oracle import execute, rows

from .tables import new_id


class ProviderError(Exception):
    """The provider refused: sold out, price gone, or the provider is down."""


def add_fault(component: str, match: str, fault: str = "sold_out", times: int = 1) -> str:
    """Make the next ``times`` bookings of offers whose provider or summary contains ``match`` fail."""
    fault_id = new_id("FT")
    execute("INSERT INTO trip_provider_faults (fault_id, component, match, fault, remaining) "
            "VALUES (:1, :2, :3, :4, :5)", [fault_id, component, match, fault, times])
    return fault_id


def take_fault(component: str, offer: dict) -> str | None:
    text = f"{offer.get('provider', '')} {offer.get('summary', '')} {offer.get('offer_id', '')}".lower()
    for fault in rows("SELECT fault_id, match, fault FROM trip_provider_faults "
                      "WHERE component = :c AND remaining > 0", {"c": component}):
        if fault["match"].lower() in text:
            execute("UPDATE trip_provider_faults SET remaining = remaining - 1 WHERE fault_id = :f",
                    {"f": fault["fault_id"]})
            return fault["fault"]
    return None


def idempotency_key(trip_id: str, component: str, offer_id: str, attempt: int) -> str:
    """The same offer, for the same trip, in the same booking attempt, is one booking.

    A crash and a resume keep the attempt number, so they replay the confirmation.
    A compensation raises it, so booking the same offer again is a new booking.
    """
    return f"{trip_id}:{component}:{offer_id}:{attempt}"


def book(trip_id: str, component: str, offer: dict, attempt: int = 0) -> dict:
    """Book one offer. The same request twice returns the first confirmation."""
    key = idempotency_key(trip_id, component, offer["offer_id"], attempt)
    found = rows("SELECT booking_id, status, confirmation, price_gbp FROM trip_bookings "
                 "WHERE idempotency_key = :k", {"k": key})
    if found and found[0]["status"] == "CONFIRMED":
        return {**found[0], "component": component, "offer_id": offer["offer_id"], "replayed": True}
    fault = take_fault(component, offer)
    if fault:
        execute("INSERT INTO trip_bookings (booking_id, trip_id, component, offer_id, provider, idempotency_key, "
                "status, price_gbp, reason) VALUES (:1, :2, :3, :4, :5, :6, 'FAILED', :7, :8)",
                [new_id("BK"), trip_id, component, offer["offer_id"], offer.get("provider", "")[:200],
                 f"{key}:failed:{new_id('x')}", offer.get("total_gbp"), fault])
        raise ProviderError(f"{component}: {offer.get('provider')} answered {fault}")
    booking_id = new_id("BK")
    confirmation = "CONF-" + hashlib.sha256(key.encode()).hexdigest()[:8].upper()
    execute("INSERT INTO trip_bookings (booking_id, trip_id, component, offer_id, provider, idempotency_key, "
            "status, confirmation, price_gbp) VALUES (:1, :2, :3, :4, :5, :6, 'CONFIRMED', :7, :8)",
            [booking_id, trip_id, component, offer["offer_id"], offer.get("provider", "")[:200], key,
             confirmation, offer.get("total_gbp")])
    return {"booking_id": booking_id, "status": "CONFIRMED", "confirmation": confirmation,
            "price_gbp": offer.get("total_gbp"), "component": component, "offer_id": offer["offer_id"],
            "replayed": False}


def cancel(booking_id: str, reason: str) -> None:
    execute("UPDATE trip_bookings SET status = 'CANCELLED', cancelled_at = SYSTIMESTAMP, reason = :r "
            "WHERE booking_id = :b AND status = 'CONFIRMED'", {"r": reason[:1000], "b": booking_id})


def confirmed_bookings(trip_id: str) -> list[dict]:
    return rows("SELECT booking_id, component, offer_id, provider, confirmation, price_gbp FROM trip_bookings "
                "WHERE trip_id = :t AND status = 'CONFIRMED' ORDER BY created_at", {"t": trip_id})


def all_bookings(trip_id: str) -> list[dict]:
    return rows("SELECT booking_id, component, offer_id, provider, status, confirmation, price_gbp, reason, "
                "created_at, cancelled_at FROM trip_bookings WHERE trip_id = :t ORDER BY created_at", {"t": trip_id})
