# Surface defect inspection demo

## The job

The console submits a production-line camera job with an image, camera source, priority, image-detail setting, and sensitivity. The gateway chooses the edge worker or cloud worker using its current policy, estimated image-processing work, cloud probe measurements, local queue, and transfer size. The selected worker returns a `PASS` or `REVIEW` verdict, suspected anomaly boxes, and an annotated copy of the image.

## What the processor does

Both containers call the same `offloader.inspection.inspect_surface` implementation. It decodes the uploaded JPEG, PNG, or WebP, converts it to grayscale, compares each pixel with a local median neighborhood, groups high-contrast pixels into connected regions, and draws boxes around the largest regions. Sensitivity selects the contrast threshold. Image detail controls the maximum image dimension sent to the worker, which also changes the amount of processing work.

The built-in sample is generated in the browser and contains several dark scratches and pits on a light surface. It gives a repeatable input without an external image download. Users can also select their own image.

## Why offload

Local contrast checks are inexpensive on a small image, so edge can be the right choice when the network is slow. Larger, higher-detail jobs can benefit from more available cloud compute when the edge queue is busy and the network can carry the image quickly. The `cloud_only`, `edge_only`, `threshold`, and `adaptive` policies let the demo show those tradeoffs; poor-network and timeout scenarios show why moving every image to cloud is not always best. The router updates its service-rate estimates from completed jobs. Adaptive choosing edge is a real estimate outcome, not evidence that the Azure worker is fake. Choose Cloud only to force a remote run, or use the same-image comparison to run both workers concurrently.

## Limits

This is an explainable image-processing heuristic, not a trained vision model. It flags local contrast changes, so text, edges, texture, lighting, and surface finish can cause false positives or missed defects. A production inspection line needs a camera-specific dataset, validated model or calibrated rules, acceptance criteria, traceable model versions, and human review before safety or quality decisions. The demo does not claim certified inspection accuracy.

## API shape

The UI posts a JSON job to `POST /tasks`. Its job envelope includes `task_id`, `task_type: surface_defect_inspection`, `source`, `priority`, `workload_profile`, `image_width`, `image_height`, `sensitivity`, and a base64 encoded JPEG in `image_base64`. Image data is resized in the browser before upload. The API limits encoded images to 3 MB and decoded dimensions to 2.4 million pixels. The Compare edge + cloud control sends that same validated envelope to `POST /compare`, which runs both workers independently and returns a result or error for each side.

The returned JSON includes the job ID, selected destination and policy reason, verdict, defect count and boxes, pixel count, worker compute time, end-to-end completion time, worker/replica metadata, and an annotated image. Recent-event telemetry stores the verdict and count, not the image contents.
