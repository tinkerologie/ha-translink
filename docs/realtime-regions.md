# Regional live data

Translink publishes separate GTFS Realtime TripUpdates, VehiclePositions, and
Alerts feeds for South East Queensland (`SEQ`) and Cairns (`CNS`). Journeys
use the configured region for trip updates and, when enabled, vehicle fixes.
Journey disruption notices come from the planner. Departure and arrival boards
use the selected stop timetable and its embedded predictions and notices.
[Translink open data](https://translink.com.au/about-translink/open-data)

The Cairns planner signals observed for buses are region ID `C` and region name
`Cairns`. A Cairns trip update must match the planner trip's base ID, service
date from the planner trip ID, and route code after normalization. The boarding
stop must appear once and any explicit boarding prediction with both a time and
a delay must agree with the scheduled boarding time. A Cairns vehicle fix must
share the validated TripUpdate's full trip ID and any vehicle IDs present on
both records must agree.

Feed headers are required. A feed or trip observation may be at most five
minutes old or up to 60 seconds ahead of the clock. A matched stale trip can
report its stale timestamp. Vehicle fixes have a separate 90-second maximum
age and 30-second future tolerance based on the fix timestamp.

The Cairns planner and protobuf fixtures in
[`tests/test_realtime_regions.py`](../tests/test_realtime_regions.py) are
synthetic. They exercise the observed planner and feed ID formats, including
route `110` and feed route `C110-33`, a platform ID with the `SI:` prefix,
and a vehicle descriptor with the same trip ID as its TripUpdate. Fixture
identities, timing and coordinates are test data.
