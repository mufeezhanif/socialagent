"""Local harness: python -m app.pipeline.cli samples/talk.mp4 --style hype --out out/talk"""

import argparse
import asyncio
import json
import time
from pathlib import Path

from app.pipeline.edit import EditInput, run_edit


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("src")
    parser.add_argument("--style", default=None)
    parser.add_argument("--out", default="out/cli")
    parser.add_argument("--context", default=None)
    parser.add_argument("--change", action="append", default=[])
    args = parser.parse_args()

    started = time.time()
    result = await run_edit(
        EditInput(
            src=Path(args.src),
            workdir=Path(args.out),
            style_request=args.style,
            user_context=args.context,
            change_requests=args.change,
        )
    )
    print(
        json.dumps(
            {
                "seconds": round(time.time() - started, 1),
                "duration_in": result.duration_in,
                "duration_out": result.duration_out,
                "from_ai": result.from_ai,
                "summary": result.summary,
                "question": result.question,
                "master": str(result.master),
                "preview": str(result.preview),
                "words": len(result.transcript.get("words", [])),
                "storyboard": result.storyboard,
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
