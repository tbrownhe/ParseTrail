# Standalone Qt focus/lifetime reproducer preparation

Status: **reduction incomplete; no validated standalone reproducer is published here yet**.

This directory is reserved for a small example that runs without ParseTrail,
profiles or pytest. `requirements.txt` pins the isolated reduction environment;
it does not establish a reproducible framework defect.

Experiments and their generated outputs remain under ignored
`scratch/qt-focus-reduction-20261110/`. The frozen Python sources and fixture in
the [`qt_heap_crash` archive](../qt_heap_crash/README.md) remain unchanged.

One earlier standalone worker-GC trial exited with `0xc0000374`, but controls
and later revisions did not establish a reliable case. The original application's
native traces also show GUI destruction on worker threads, which must be accounted
for before attributing the fault to PySide. Further crash runs were stopped after
repeated automated security-classifier interruptions reported during diagnosis.

See the [single work record](../../docs/work/2026-11-07-v2-core-desktop-journey.md#standalone-reproducer-reduction-and-thread-lifetime-finding)
for evidence, limitations and remaining work. Nothing has been submitted upstream.
