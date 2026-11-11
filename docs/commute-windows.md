# Commute windows

Add a **Commute window** entry and choose the origin, destination, and transport
modes. A one-off entry runs on one date. A recurring entry runs on selected
weekdays. Setup resolves the endpoints and saves the schedule, then the first
planner request waits until the entry becomes active.

## Schedule and polling

Enter dates and times in Australia/Brisbane, to the minute. An end earlier than
the start falls on the following day. The occurrence belongs to the date it
starts, so Friday 23:00–01:00 runs through Saturday at 01:00. The end must differ
from the start and the window can last up to 12 hours.

Polling starts 15 minutes early by default and runs every 60 seconds. You can
set a lead of 0–120 minutes and a refresh interval of 30–600 seconds. Before the
window ends, each refresh makes one planner request for the later of the window
start and the current time. After the end, outstanding trips can receive
realtime updates for up to 60 minutes. Idle and expired entries make zero API
calls. A one-off entry remains visible as expired until you delete it.

## Tracked trips

An itinerary belongs to the occurrence when its first scheduled transit
departure falls on or after the start and before the end. Translink identifies
each itinerary by its ordered transit trip IDs, boarding and alighting stop IDs,
and scheduled departure instants. Alternatives with complete identities are
sorted by first transit departure. The entry retains up to six by default,
configurable from one to ten. The planner returns a subset of available trips.
An omitted trip has unknown realtime status.

Commute windows use the public Translink planner and the South East Queensland
GTFS Realtime TripUpdates feed. Legs identified as belonging to another region
retain unknown realtime status. Windows use the endpoints you enter and publish
trip changes through Home Assistant. Notification delivery is configured in
your own automations.

## Confirmed changes and restart behavior

The **Trip changes** entity exposes four event types:

| Event | When it fires |
| --- | --- |
| `trip_delayed` | A confirmed delay reaches the threshold, or increases by at least the configured step from the previous delay alert. |
| `trip_recovered` | The delay falls to two minutes below the threshold or earlier after a delay alert. |
| `trip_cancelled` | A fresh, uniquely matched update confirms that the trip or one of its required stops was cancelled. |
| `trip_disruption` | A tracked leg references a relevant notice and has a confirmed realtime observation. |

The delay threshold defaults to 3 minutes (1–60). The additional delay step
defaults to 5 minutes (1–30). A fresh matching observation must carry the
TripUpdate timestamp. Delay is the largest signed boarding delay among the
remaining transit legs, rounded to whole minutes. A confirmed cancellation
suppresses future delay and recovery events for that trip. A cancellation and
each distinct notice can alert once per trip and occurrence. Missing, stale,
ambiguous, and failed observations leave the alert ledger unchanged.

Home Assistant stores a per-entry alert ledger and the public transit identifiers
and schedule facts needed to resume outstanding trips during the grace period.
A restart resumes the current occurrence, suppresses recorded events, and can
emit a new confirmed change once. Missed occurrences are skipped. The ledger
and grace data are discarded when the occurrence finishes. Manually entered
endpoint names and addresses stay in the ordinary config entry.
