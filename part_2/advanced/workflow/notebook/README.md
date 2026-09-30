# Book a trip: a durable, branching workflow harness

`advanced_trip_booking_workflow.ipynb` builds a workflow harness that takes one sentence
from a traveller, searches the real web for flights, hotels and cars, composes an
itinerary, pauses for approval, books the three parts as a saga with compensation, and
survives being cut off between two bookings.

Needs Docker (Oracle AI Database Free), `ANTHROPIC_API_KEY` and `TAVILY_API_KEY`; `TYPESAFE_API_KEY` switches System One on. About
three minutes to run; the outputs of the last execution are saved in the notebook.

| Part | What it builds | Live |
|---|---|---|
| 1 | Environment: schema through the container, embedding model in the database | |
| 2 | The system of record and the ledger | |
| 3 | Traveller memory on Oracle Agent Memory | ⭐ |
| 4 | Typed answers from the model | |
| 5 | A model that decides: Jev on four closed questions | ⭐ |
| 6 | Real search evidence with a confidence on every offer | ⭐ |
| 7 | Understanding and planning | |
| 8 | The booking system of record: idempotency, faults, cancellation | |
| 9 | The durable graph | ⭐ |
| 10 | A trip, up to the approval gate | ⭐ |
| 11 | Change, failure, compensation | ⭐ |
| 12 | Crash and resume | ⭐ |
| 13 | What the database holds | |

The diagrams' sources are in `diagrams/`. The notebook is generated from the appbook's
harness modules by `../../scripts/build_workflow_notebook.py`.
