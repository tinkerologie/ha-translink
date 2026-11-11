# Journey progress evidence

A followed journey is a single in-memory copy of its schedule, routes and
public transit stops. Progress uses a new copy while the planner's first
itinerary is still upcoming, then follows the last copy after departure.
A journey identifier derived from its leg identities and scheduled times
scopes observations and deduplication. Reloading the integration discards them.

GTFS Realtime VehiclePosition describes which stop the vehicle is approaching,
at, or travelling towards using `current_status` and `current_stop_sequence`.
An absent status gives no confirmation, and status is unusable without a
sequence. The sequence and normalised stop ID must match a TripUpdate
alighting occurrence. A schedule baseline resolves repeated stop IDs when
exactly one candidate matches. Trip timetable display order is independent of
the GTFS sequence.

The vehicle must be matched to the same trip, route and service date when
available. Both observations must be fresh, and their timestamps must increase.
An earlier sequence followed by explicit `STOPPED_AT` at the alighting
occurrence confirms the vehicle's arrival. Skipped visits, cancelled trips,
ambiguous matches and sequence jumps give no confirmation. The event describes
vehicle behaviour independently of the rider. A missed stop observation can
result in no event.
