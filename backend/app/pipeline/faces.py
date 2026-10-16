"""Find a single steady face so a landscape clip can be cropped to 9:16 around the speaker."""

import asyncio
import logging
import statistics

log = logging.getLogger(__name__)


def face_center_sync(path: str, duration: float, samples: int = 8) -> float | None:
    try:
        import cv2
    except ImportError:
        return None
    try:
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        cascade = cv2.CascadeClassifier(cascade_path)
        if cascade.empty():
            return None
        cap = cv2.VideoCapture(path)
        xs: list[float] = []
        crowded = 0
        for i in range(samples):
            cap.set(cv2.CAP_PROP_POS_MSEC, duration * (i + 0.5) / samples * 1000)
            ok, frame = cap.read()
            if not ok:
                continue
            h, w = frame.shape[:2]
            scale = 480 / max(h, w)
            small = cv2.resize(frame, (int(w * scale), int(h * scale)))
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            min_side = int(min(small.shape[:2]) * 0.12)
            faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=6, minSize=(min_side, min_side))
            if len(faces) == 1:
                x, _, fw, _ = faces[0]
                xs.append((x + fw / 2) / small.shape[1])
            elif len(faces) > 1:
                crowded += 1
        cap.release()
    except Exception as exc:
        log.warning("face detection failed: %s", exc)
        return None
    if len(xs) < samples * 0.5 or crowded > 1:
        return None
    if len(xs) > 1 and statistics.pstdev(xs) > 0.08:
        return None
    return round(statistics.median(xs), 3)


async def face_center(path: str, duration: float) -> float | None:
    return await asyncio.to_thread(face_center_sync, path, duration)
