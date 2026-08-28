import io
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse
from libcamera import Transform
from picamera2 import Picamera2
from picamera2.encoders import MJPEGEncoder
from picamera2.outputs import FileOutput


class StreamingOutput(io.BufferedIOBase):
    def __init__(self):
        self.frame = None
        self.condition = threading.Condition()

    def write(self, buffer):
        with self.condition:
            self.frame = bytes(buffer)
            self.condition.notify_all()
        return len(buffer)

    def wait_for_frame(self):
        with self.condition:
            self.condition.wait()
            return self.frame


output = StreamingOutput()
camera = None


@asynccontextmanager
async def lifespan(app):
    global camera

    camera = Picamera2()
    camera.configure(
        camera.create_video_configuration(
            main={"size": (1280, 720)},
            controls={"FrameRate": 30},
            transform=Transform(hflip=1, vflip=1),
        )
    )
    camera.start_recording(MJPEGEncoder(), FileOutput(output))

    yield

    camera.stop_recording()
    camera.close()


app = FastAPI(lifespan=lifespan)


PAGE = """
<!doctype html>
<html>
<head>
    <style>
        html, body {
            margin: 0;
            width: 100%;
            height: 100%;
        }

        body {
            display: flex;
            align-items: center;
            justify-content: center;
        }

        img {
            max-width: 100%;
            max-height: 100%;
        }
    </style>
</head>
<body>
    <img src="/stream.mjpg">
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def index():
    return PAGE


def generate_mjpeg():
    while True:
        frame = output.wait_for_frame()

        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n"
            + frame
            + b"\r\n"
        )


@app.get("/stream.mjpg")
def stream():
    return StreamingResponse(
        generate_mjpeg(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)