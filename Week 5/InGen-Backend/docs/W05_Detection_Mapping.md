# Model output to Detection

`YoloDetector` delegates decoded, post-NMS Ultralytics Results to
`app/services/detection_mapping.py`. This adapter targets COCO YOLO detection
models, with `yolo11n.pt` as the default. Raw neural-network tensors are decoded
by Ultralytics, not by this adapter.

## Coordinates and validity

Week-2 `BoundingBox` uses normalized **top-left x/y and width/height**, with
origin at the top-left, x increasing rightward and y increasing downward.
Ultralytics `xyxy` is already restored to original image pixels (including
letterbox reversal). Divide horizontal values by `orig_shape[1]` and vertical
values by `orig_shape[0]`; do not divide by the network input size.

Clip endpoints to the original image before converting. Drop boxes that have
non-finite coordinates, zero/negative area after clipping, or non-finite or
out-of-range confidence. Invalid original image dimensions raise RuntimeError.
Absent results, absent boxes, empty boxes, or all-filtered rows return `[]`.
Each retained box gets a fresh UUID and `tracker_id=None`. The detector uses
`frame_id="pending"`; the worker attaches the real ID before invoking the completion callback.

## Confidence and NMS

Environment settings (validated at startup):

| Setting | Default | Allowed |
| --- | --- | --- |
| `YOLO_CONFIDENCE_THRESHOLD` | 0.25 | finite, 0–1 |
| `YOLO_NMS_IOU_THRESHOLD` | 0.7 | finite, 0–1 |
| `YOLO_MAX_DETECTIONS` | 300 | positive integer |

Both warm-up and normal inference pass these settings explicitly to
Ultralytics. Confidence must be **strictly greater** than the threshold,
matching the installed Ultralytics NMS behavior; the mapping layer rechecks
this boundary. NMS is class-aware (`agnostic_nms=False`), performed once by
Ultralytics in the original model class space, before label grouping. Boxes
of different COCO classes can survive even if both become `vehicle` or
`obstacle`. There is no second suppression pass after mapping. Max detections
is enforced by Ultralytics before mapping. NMS-free/end-to-end model variants
are outside this adapter's supported COCO YOLO contract.

## Class policy

Indices are contiguous **0–79 Ultralytics COCO indices**, not sparse COCO
annotation category IDs. The result's class name must also match the expected
COCO name at that index; mismatched custom-model labels become `unknown`.

| InGen label | COCO indices and names |
| --- | --- |
| person | 0 person |
| bicycle | 1 bicycle |
| vehicle | 2 car, 3 motorcycle, 4 airplane, 5 bus, 6 train, 7 truck, 8 boat |
| animal | 14 bird, 15 cat, 16 dog, 17 horse, 18 sheep, 19 cow, 20 elephant, 21 bear, 22 zebra, 23 giraffe |
| obstacle | 9 traffic light, 10 fire hydrant, 11 stop sign, 12 parking meter, 13 bench; every index 24–79 listed below |
| unknown | Out-of-range, fractional/non-finite class IDs, or IDs whose model name does not match COCO |

Obstacle indices 24–79, in order: backpack, umbrella, handbag, tie, suitcase,
frisbee, skis, snowboard, sports ball, kite, baseball bat, baseball glove,
skateboard, surfboard, tennis racket, bottle, wine glass, cup, fork, knife,
spoon, bowl, banana, apple, sandwich, orange, broccoli, carrot, hot dog, pizza,
donut, cake, chair, couch, potted plant, bed, dining table, toilet, tv, laptop,
mouse, remote, keyboard, cell phone, microwave, oven, toaster, sink,
refrigerator, book, clock, vase, scissors, teddy bear, hair drier, toothbrush.

No COCO class is dropped by label. This deliberately preserves visible physical
objects as possible obstacles, including small objects and elevated signs.
`obstacle` is a semantic grouping, not proof that an object blocks the robot's
path; downstream navigation needs geometry/depth to decide that. The policy
trades extra candidates for avoiding silent loss of potential hazards. A teddy
bear is an obstacle, not an animal; a motorcycle is a vehicle, not a bicycle.
Unknown labels are retained rather than guessed or silently dropped.

## Tests

`tests/fixtures/detection_mapping/wide.png` and `empty.png` are fixed synthetic
landscape/portrait images. `wide.json` contains fixed model-output rows and
expected normalized detections. Tests construct real Ultralytics Results for
these images, without downloading weights. They validate the adapter rather
than detector accuracy: all 80 class indices, unknown labels, threshold equality,
clipping, malformed boxes, empty outputs, portrait dimensions, and explicit
prediction/warm-up settings. Model prediction is mocked only at the detector
boundary; these tests do not independently evaluate Ultralytics NMS or accuracy.
