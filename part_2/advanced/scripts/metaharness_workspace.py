"""A small project for the meta-harness lesson: a booking ledger with one planted defect.

The notebook writes this project into a scratch folder, so no harness ever
edits the course itself. The defect: a booking that was cancelled is replayed
as if it were still confirmed.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

LEDGER_SOURCE = '''"""A booking ledger with idempotency keys."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field


@dataclass
class Booking:
    booking_id: str
    component: str
    offer_id: str
    status: str
    confirmation: str
    reason: str = ""


@dataclass
class Ledger:
    bookings: dict[str, Booking] = field(default_factory=dict)      # idempotency key -> booking

    @staticmethod
    def key(trip_id: str, component: str, offer_id: str, attempt: int = 0) -> str:
        return f"{trip_id}:{component}:{offer_id}:{attempt}"

    def book(self, trip_id: str, component: str, offer_id: str, attempt: int = 0) -> Booking:
        """The same request twice returns the first confirmation."""
        key = self.key(trip_id, component, offer_id, attempt)
        if key in self.bookings:
            return self.bookings[key]
        confirmation = "CONF-" + hashlib.sha256(key.encode()).hexdigest()[:8].upper()
        booking = Booking(f"BK-{len(self.bookings) + 1:04d}", component, offer_id, "CONFIRMED", confirmation)
        self.bookings[key] = booking
        return booking

    def cancel(self, booking_id: str, reason: str) -> None:
        for booking in self.bookings.values():
            if booking.booking_id == booking_id and booking.status == "CONFIRMED":
                booking.status = "CANCELLED"
                booking.reason = reason

    def confirmed(self) -> list[Booking]:
        return [b for b in self.bookings.values() if b.status == "CONFIRMED"]
'''

TEST_SOURCE = '''from tripbook.ledger import Ledger


def test_the_same_request_is_one_booking():
    ledger = Ledger()
    first = ledger.book("T1", "flight", "OF-1")
    again = ledger.book("T1", "flight", "OF-1")
    assert first.confirmation == again.confirmation
    assert len(ledger.confirmed()) == 1


def test_cancel_marks_the_booking():
    ledger = Ledger()
    booking = ledger.book("T1", "hotel", "OF-2")
    ledger.cancel(booking.booking_id, "sold out elsewhere")
    assert ledger.confirmed() == []
'''

FILES = {
    "README.md": """# tripbook

A booking ledger for a trip-booking workflow. `book()` must be idempotent: the same
request twice returns the first confirmation. `cancel()` marks a booking cancelled.

Run the tests with `python -m pytest -q`.
""",
    "tripbook/__init__.py": "",
    "tripbook/ledger.py": LEDGER_SOURCE,
    "tests/test_ledger.py": TEST_SOURCE,
    "pyproject.toml": '[tool.pytest.ini_options]\npythonpath = ["."]\n',
}


def write_workspace(folder: Path, git: bool = True) -> Path:
    """A fresh copy of the project, as a git repository so a harness's edits can be diffed."""
    if folder.exists():
        shutil.rmtree(folder)
    for name, text in FILES.items():
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    if git:
        subprocess.run(["git", "init", "-q"], cwd=folder, check=True)
        subprocess.run(["git", "add", "-A"], cwd=folder, check=True)
        subprocess.run(["git", "-c", "user.name=workshop", "-c", "user.email=workshop@example.com", "commit", "-q",
                        "-m", "tripbook: a booking ledger"], cwd=folder, check=True)
    return folder


if __name__ == "__main__":
    import sys
    print(write_workspace(Path(sys.argv[1] if len(sys.argv) > 1 else "~/.ppa_workshop/metaharness-workspace").expanduser()))
