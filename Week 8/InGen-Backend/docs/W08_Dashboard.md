# W08 operator dashboard

After migrating and starting the backend, open
[the local dashboard](http://localhost:8000/dashboard). The service serves
HTML, CSS and vanilla JavaScript directly; there is no front-end build.

The dashboard polls every three seconds. Recent detections show capture time,
robot, class and confidence. The robot panel shows platform, version and
current entity counts. The alerts panel shows unacknowledged rule events
with a text severity and a matching color. Filter by robot and optional local
date/time bounds. The browser converts local timestamps to UTC, then passes
the same range to the detection and event query APIs. Robot state remains current.

To acknowledge an alert, enter the operator's name and configured token,
then select **Acknowledge**. The page removes the alert after the server saves
the acknowledgement. The token is kept in the form for the current page and
is not saved to browser storage. The panel shows the 25 newest matching
unacknowledged alerts; use the event query API for older pages.

[Demo recording](W08_Demo_Recording.mp4) shows real requests to a disposable
SQLite-backed instance using synthetic JPEGs and the deterministic stub
detector. A separate loopback HTTP receiver verifies the body signature.
The recording shows detections and robot state, a rule firing after its
third matching frame, cooldown suppression and an operator acknowledgement.
