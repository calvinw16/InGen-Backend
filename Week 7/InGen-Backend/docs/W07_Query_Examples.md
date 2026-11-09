# W07 worked telemetry queries

These calls were run against the migrated SQLite seed database with 4,320 frames and 8,167 detections. Example IDs come from the captured run; replace the seed prefix and times when reproducing. The API shape is unchanged by the choice of database.

Plans are from the corresponding production SQL statements using SQLite `EXPLAIN QUERY PLAN` after `ANALYZE`. A `SCAN ... USING INDEX` for an unconstrained query is an ordered index walk that can stop at the limit. It is not a table scan. Minimum confidence is evaluated as a residual predicate. The full [plan capture](W07_Query_Plans.jsonl) includes both sort directions, all 32 filter subsets and their keyset continuations.

Each example uses limit 20 (the default). The sample JSON shows the page envelope and its first item; remaining items and long cursor values are abbreviated in this document. UTC range is inclusive at the start and exclusive at the end.

## Latest detections

```sh
curl -sG 'http://localhost:8000/v1/detections'
```

```json
{
  "items": [
    {
      "id": "fac05608-012b-4b37-820c-854b37eb5443",
      "frame_id": "0b6bba33-2b1b-486b-bdd5-a275db014237",
      "class_label": "obstacle",
      "confidence": 0.767,
      "bbox": {
        "x": 0.7413698311487575,
        "y": 0.21677532357141782,
        "w": 0.15291438727526985,
        "h": 0.19354998679803287
      },
      "tracker_id": null,
      "captured_at": "2026-11-08T23:54:00Z",
      "robot_id": "seed-b94b8b1a-03"
    }
  ],
  "count": 20,
  "next_cursor": "<opaque cursor from this page>"
}
```

```text
SCAN detections USING INDEX ix_detection_capture
```

## Robot only

```sh
curl -sG 'http://localhost:8000/v1/detections' --data-urlencode 'robot_id=seed-b94b8b1a-00'
```

```json
{
  "items": [
    {
      "id": "f77c2af2-ae74-4b65-a11a-fa754474d945",
      "frame_id": "74cb10e0-f3f6-4e21-a77e-f45b859492a0",
      "class_label": "obstacle",
      "confidence": 0.648,
      "bbox": {
        "x": 0.7036759269426516,
        "y": 0.7430905673676147,
        "w": 0.18930136096118294,
        "h": 0.16889359425864764
      },
      "tracker_id": null,
      "captured_at": "2026-11-08T23:48:00Z",
      "robot_id": "seed-b94b8b1a-00"
    }
  ],
  "count": 20,
  "next_cursor": "<opaque cursor from this page>"
}
```

```text
SEARCH detections USING INDEX ix_detection_robot_capture (robot_id=?)
```

## Class only

```sh
curl -sG 'http://localhost:8000/v1/detections' --data-urlencode 'class_label=person'
```

```json
{
  "items": [
    {
      "id": "b696ad96-b859-4184-ac7c-f033cf255adf",
      "frame_id": "0b6bba33-2b1b-486b-bdd5-a275db014237",
      "class_label": "person",
      "confidence": 0.744,
      "bbox": {
        "x": 0.7446060438286908,
        "y": 0.2737625161527264,
        "w": 0.11751794164051726,
        "h": 0.18666436752336757
      },
      "tracker_id": null,
      "captured_at": "2026-11-08T23:54:00Z",
      "robot_id": "seed-b94b8b1a-03"
    }
  ],
  "count": 20,
  "next_cursor": "<opaque cursor from this page>"
}
```

```text
SEARCH detections USING INDEX ix_detection_class_capture (class_label=?)
```

## Confidence floor

```sh
curl -sG 'http://localhost:8000/v1/detections' --data-urlencode 'min_confidence=0.7'
```

```json
{
  "items": [
    {
      "id": "fac05608-012b-4b37-820c-854b37eb5443",
      "frame_id": "0b6bba33-2b1b-486b-bdd5-a275db014237",
      "class_label": "obstacle",
      "confidence": 0.767,
      "bbox": {
        "x": 0.7413698311487575,
        "y": 0.21677532357141782,
        "w": 0.15291438727526985,
        "h": 0.19354998679803287
      },
      "tracker_id": null,
      "captured_at": "2026-11-08T23:54:00Z",
      "robot_id": "seed-b94b8b1a-03"
    }
  ],
  "count": 20,
  "next_cursor": "<opaque cursor from this page>"
}
```

```text
SCAN detections USING INDEX ix_detection_capture
```

## UTC capture range ascending

```sh
curl -sG 'http://localhost:8000/v1/detections' --data-urlencode 'start=2026-11-07T00:00:00Z' --data-urlencode 'end=2026-11-08T23:00:00Z' --data-urlencode 'sort=asc'
```

```json
{
  "items": [
    {
      "id": "0dc69aa7-d8be-4a12-a61a-e5e03bab84d1",
      "frame_id": "97366291-4081-4bb7-a308-c5dc0ae3d785",
      "class_label": "vehicle",
      "confidence": 0.405,
      "bbox": {
        "x": 0.6369190643621403,
        "y": 0.6131243901144612,
        "w": 0.1666470079273312,
        "h": 0.06373230981128493
      },
      "tracker_id": null,
      "captured_at": "2026-11-07T00:00:00Z",
      "robot_id": "seed-b94b8b1a-01"
    }
  ],
  "count": 20,
  "next_cursor": "<opaque cursor from this page>"
}
```

```text
SEARCH detections USING INDEX ix_detection_capture (captured_at>? AND captured_at<?)
```

## Robot and class

```sh
curl -sG 'http://localhost:8000/v1/detections' --data-urlencode 'robot_id=seed-b94b8b1a-00' --data-urlencode 'class_label=person'
```

```json
{
  "items": [
    {
      "id": "9e712e16-28b1-401f-b608-7f9b92bf75e3",
      "frame_id": "11208b15-e43e-4d90-9bf0-12e82fed7bed",
      "class_label": "person",
      "confidence": 0.521,
      "bbox": {
        "x": 0.2649392702268953,
        "y": 0.22015518148050767,
        "w": 0.07337991150910343,
        "h": 0.06476086805809135
      },
      "tracker_id": null,
      "captured_at": "2026-11-08T23:42:00Z",
      "robot_id": "seed-b94b8b1a-00"
    }
  ],
  "count": 20,
  "next_cursor": "<opaque cursor from this page>"
}
```

```text
SEARCH detections USING INDEX ix_detection_robot_class_capture (robot_id=? AND class_label=?)
```

## Robot, confidence and lower time bound

```sh
curl -sG 'http://localhost:8000/v1/detections' --data-urlencode 'robot_id=seed-b94b8b1a-00' --data-urlencode 'min_confidence=0.7' --data-urlencode 'start=2026-11-07T00:00:00Z'
```

```json
{
  "items": [
    {
      "id": "30d21bda-9b61-4f6b-a657-a7b0a358d045",
      "frame_id": "9f6636ab-080e-4a52-b1df-138a425bb22e",
      "class_label": "obstacle",
      "confidence": 0.897,
      "bbox": {
        "x": 0.5217294226997783,
        "y": 0.35020350188754795,
        "w": 0.05955249224569755,
        "h": 0.061279603809148306
      },
      "tracker_id": null,
      "captured_at": "2026-11-08T23:36:00Z",
      "robot_id": "seed-b94b8b1a-00"
    }
  ],
  "count": 20,
  "next_cursor": "<opaque cursor from this page>"
}
```

```text
SEARCH detections USING INDEX ix_detection_robot_capture (robot_id=? AND captured_at>?)
```

## All filters, latest first

```sh
curl -sG 'http://localhost:8000/v1/detections' --data-urlencode 'robot_id=seed-b94b8b1a-00' --data-urlencode 'class_label=person' --data-urlencode 'min_confidence=0.7' --data-urlencode 'start=2026-11-07T00:00:00Z' --data-urlencode 'end=2026-11-08T23:00:00Z'
```

```json
{
  "items": [
    {
      "id": "2016e7af-4968-4952-9a11-a2dd7a5ee20e",
      "frame_id": "16667125-ba6a-4f1b-9c14-2c1ca5d4fc07",
      "class_label": "person",
      "confidence": 0.92,
      "bbox": {
        "x": 0.7063275559465597,
        "y": 0.5877003431930954,
        "w": 0.10717913167666222,
        "h": 0.10269578456024492
      },
      "tracker_id": null,
      "captured_at": "2026-11-08T22:54:00Z",
      "robot_id": "seed-b94b8b1a-00"
    }
  ],
  "count": 20,
  "next_cursor": "<opaque cursor from this page>"
}
```

```text
SEARCH detections USING INDEX ix_detection_robot_class_capture (robot_id=? AND class_label=? AND captured_at>? AND captured_at<?)
```

## Next page with the same filters

```sh
curl -sG 'http://localhost:8000/v1/detections' --data-urlencode 'robot_id=seed-b94b8b1a-00' --data-urlencode 'class_label=person' --data-urlencode 'min_confidence=0.7' --data-urlencode 'start=2026-11-07T00:00:00Z' --data-urlencode 'end=2026-11-08T23:00:00Z' --data-urlencode 'cursor=<paste next_cursor>'
```

```json
{
  "items": [
    {
      "id": "cc746019-3133-4759-a0ed-6538a6693dfe",
      "frame_id": "154e2420-c145-4307-b99b-fee3e7de43d1",
      "class_label": "person",
      "confidence": 0.743,
      "bbox": {
        "x": 0.45411629855882035,
        "y": 0.6246181108962925,
        "w": 0.10016086886458629,
        "h": 0.05539649693707297
      },
      "tracker_id": null,
      "captured_at": "2026-11-08T09:54:00Z",
      "robot_id": "seed-b94b8b1a-00"
    }
  ],
  "count": 20,
  "next_cursor": "<opaque cursor from this page>"
}
```

```text
SEARCH detections USING INDEX ix_detection_robot_class_capture (robot_id=? AND class_label=? AND captured_at>? AND captured_at<?)
```

## Hourly robot timeline

```sh
curl -sG 'http://localhost:8000/v1/robots/seed-b94b8b1a-00/timeline' --data-urlencode 'start=2026-11-07T00:00:00Z' --data-urlencode 'end=2026-11-08T23:00:00Z' --data-urlencode 'bucket_seconds=3600'
```

```json
{
  "robot_id": "seed-b94b8b1a-00",
  "bucket_seconds": 3600,
  "items": [
    {
      "start": "2026-11-07T00:00:00+00:00",
      "count": 17,
      "by_class": {
        "animal": 6,
        "bicycle": 2,
        "obstacle": 4,
        "person": 2,
        "vehicle": 3
      }
    }
  ]
}
```

```text
SEARCH detections USING INDEX ix_detection_robot_capture (robot_id=? AND captured_at>? AND captured_at<?)
USE TEMP B-TREE FOR GROUP BY
```

## Measured comparison

The all-filters descending query returned the same rows with and without indexes. Over 40 warmed SQLite executions, median database execution and fetch time was **0.036 ms** with the index versus **0.244 ms** with `NOT INDEXED`. The forced scan required a temporary sort. These local measurements exclude HTTP and do not establish production latency.

```text
SCAN detections
USE TEMP B-TREE FOR ORDER BY
```

The timeline uses the robot/time index for its input range; SQLite uses a temporary B-tree for the aggregation, which is expected. It returns occupied buckets only, aligned to UTC Unix epoch multiples of bucket_seconds.
