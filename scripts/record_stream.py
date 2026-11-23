"""CLI para grabación continua con ffmpeg y registro automático de segmentos."""

import argparse
import json

from app.services.recording_pipeline import ContinuousRecordingPipeline, RecordingUploader


def main() -> None:
    parser = argparse.ArgumentParser(description="Grabación continua segmentada con ffmpeg")
    parser.add_argument("--source", default="http://127.0.0.1:8000/api/v1/video/live")
    parser.add_argument("--backend-url", default="http://127.0.0.1:8000")
    parser.add_argument("--output-dir", default="storage/segments")
    parser.add_argument("--segment-seconds", type=int, default=10)
    parser.add_argument("--vuelo-id", type=int, default=None)
    parser.add_argument("--duration-limit", type=int, default=None)
    args = parser.parse_args()

    uploader = RecordingUploader(base_url=args.backend_url)
    pipeline = ContinuousRecordingPipeline(
        output_dir=args.output_dir,
        uploader=uploader,
        segment_seconds=args.segment_seconds,
        vuelo_id=args.vuelo_id,
    )
    summary = pipeline.run(args.source, duration_limit=args.duration_limit)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
