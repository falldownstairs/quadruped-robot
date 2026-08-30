import inspect
import io
import json
import queue
import threading
from contextlib import asynccontextmanager
from typing import Iterator

import adafruit_ssd1306
import board
import busio
import servo as robot
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from libcamera import Transform
from picamera2 import Picamera2
from picamera2.encoders import MJPEGEncoder
from picamera2.outputs import FileOutput
from PIL import Image

from faces import FACE_NAMES, HEIGHT, WIDTH, frames_for


I2C_ADDRESS = 0x3C
FACE_ROTATION = 0
FACE_FRAME_DELAY = 0.20
HOST = "0.0.0.0"
PORT = 8000

MOVEMENT_ALIASES = {
    "forward": ("walk_forward", "forward", "walk"),
    "backward": ("walk_backward", "backward", "reverse"),
    "left": ("turn_left", "left"),
    "right": ("turn_right", "right"),
}

HIDDEN_ACTIONS = {
    "main",
    "cleanup",
    "close",
    "deinit",
    "init",
    "initialize",
    "convert_angle",
    "move_servos",
    "set_angle",
    "set_servo",
    "set_servo_angle",
}


class StreamingOutput(io.BufferedIOBase):
    def __init__(self):
        super().__init__()
        self.frame = None
        self.sequence = 0
        self.condition = threading.Condition()

    def write(self, buffer):
        with self.condition:
            self.frame = bytes(buffer)
            self.sequence += 1
            self.condition.notify_all()

        return len(buffer)

    def wait_for_frame(self, timeout=5.0):
        with self.condition:
            previous_sequence = self.sequence

            self.condition.wait_for(
                lambda: self.sequence != previous_sequence,
                timeout=timeout,
            )

            return self.frame


class RobotController:
    def __init__(self):
        self.functions = self._find_functions()
        self.commands = queue.Queue()
        self.lock = threading.Lock()
        self.pending = None
        self.active = None
        self.held_movement = None
        self.last_error = None
        self.running = True

        self.thread = threading.Thread(
            target=self._worker,
            daemon=True,
        )

    def _find_functions(self):
        functions = {}

        movement_names = {
            name
            for aliases in MOVEMENT_ALIASES.values()
            for name in aliases
        }

        for action, aliases in MOVEMENT_ALIASES.items():
            for name in aliases:
                function = getattr(robot, name, None)

                if callable(function):
                    functions[action] = function
                    break

        for name, function in inspect.getmembers(
            robot,
            inspect.isfunction,
        ):
            if function.__module__ != robot.__name__:
                continue

            if (
                name.startswith("_")
                or name in HIDDEN_ACTIONS
                or name in movement_names
            ):
                continue

            parameters = inspect.signature(
                function
            ).parameters.values()

            required = [
                parameter
                for parameter in parameters
                if (
                    parameter.default
                    is inspect.Parameter.empty
                    and parameter.kind
                    not in (
                        inspect.Parameter.VAR_POSITIONAL,
                        inspect.Parameter.VAR_KEYWORD,
                    )
                )
            ]

            if not required:
                functions[name] = function

        return functions

    def start(self):
        self.thread.start()

    def stop(self):
        self.running = False

        with self.lock:
            self.held_movement = None

        self.commands.put(None)
        self.thread.join(timeout=2)

    def submit(self, action):
        if action not in self.functions:
            raise KeyError(action)

        with self.lock:
            if (
                self.pending is not None
                or self.active is not None
            ):
                return False

            self.pending = action
            self.last_error = None

        self.commands.put(("action", action))

        return True

    def start_movement(self, action):
        if (
            action not in MOVEMENT_ALIASES
            or action not in self.functions
        ):
            raise KeyError(action)

        with self.lock:
            if (
                self.pending is not None
                or self.active is not None
                or self.held_movement is not None
            ):
                return False

            self.pending = action
            self.held_movement = action
            self.last_error = None

        self.commands.put(("movement", action))

        return True

    def stop_movement(self, action):
        if (
            action not in MOVEMENT_ALIASES
            or action not in self.functions
        ):
            raise KeyError(action)

        with self.lock:
            if self.held_movement == action:
                self.held_movement = None

    def status(self):
        with self.lock:
            return {
                "available_actions": list(self.functions),
                "pending": self.pending,
                "active": self.active,
                "held_movement": self.held_movement,
                "last_error": self.last_error,
            }

    def _run_movement_cycle(self, action):
        function = self.functions[action]

        if "cycles" in inspect.signature(
            function
        ).parameters:
            function(cycles=1)
        else:
            function()

    def _stand(self):
        stand = getattr(robot, "stand", None)

        if callable(stand):
            stand()

    def _worker(self):
        while self.running:
            command = self.commands.get()

            if command is None:
                break

            command_type, action = command

            with self.lock:
                self.pending = None
                self.active = action

            try:
                if command_type == "movement":
                    while self.running:
                        self._run_movement_cycle(action)

                        with self.lock:
                            if (
                                self.held_movement
                                != action
                            ):
                                break
                else:
                    self.functions[action]()

            except Exception as error:
                with self.lock:
                    self.last_error = str(error)

            finally:
                if command_type == "movement":
                    try:
                        self._stand()
                    except Exception as error:
                        with self.lock:
                            self.last_error = str(error)

                with self.lock:
                    if self.held_movement == action:
                        self.held_movement = None

                    self.active = None


class FaceController:
    def __init__(self):
        self.i2c = busio.I2C(
            board.SCL,
            board.SDA,
        )

        self.display = (
            adafruit_ssd1306.SSD1306_I2C(
                WIDTH,
                HEIGHT,
                self.i2c,
                addr=I2C_ADDRESS,
            )
        )

        self.lock = threading.Lock()
        self.changed = threading.Event()
        self.running = True

        self.name = (
            "idle"
            if "idle" in FACE_NAMES
            else FACE_NAMES[0]
        )

        self.version = 0

        first_frame = frames_for(
            self.name
        )[0]

        self.preview = self._png(first_frame)

        self.thread = threading.Thread(
            target=self._worker,
            daemon=True,
        )

    def _image(self, bitmap):
        image = Image.frombytes(
            "1",
            (WIDTH, HEIGHT),
            bitmap,
        )

        if FACE_ROTATION:
            image = image.rotate(
                FACE_ROTATION
            )

        return image

    def _png(self, bitmap):
        buffer = io.BytesIO()

        self._image(bitmap).save(
            buffer,
            format="PNG",
        )

        return buffer.getvalue()

    def start(self):
        self.display.fill(0)
        self.display.show()
        self.thread.start()

    def stop(self):
        self.running = False
        self.changed.set()
        self.thread.join(timeout=2)

    def set_face(self, name):
        if (
            name not in FACE_NAMES
            or not frames_for(name)
        ):
            raise KeyError(name)

        with self.lock:
            self.name = name
            self.version += 1

        self.changed.set()

    def status(self):
        with self.lock:
            return {
                "face": self.name,
            }

    def preview_png(self):
        with self.lock:
            return self.preview

    def _worker(self):
        while self.running:
            with self.lock:
                name = self.name
                version = self.version

            face_frames = frames_for(name)

            for bitmap in face_frames:
                if not self.running:
                    return

                with self.lock:
                    if self.version != version:
                        break

                image = self._image(bitmap)

                self.display.image(image)
                self.display.show()

                with self.lock:
                    self.preview = self._png(
                        bitmap
                    )

                delay = (
                    FACE_FRAME_DELAY
                    if len(face_frames) > 1
                    else 3600
                )

                if self.changed.wait(delay):
                    self.changed.clear()
                    break


camera_output = StreamingOutput()
camera = None
robot_controller = None
face_controller = None


@asynccontextmanager
async def lifespan(_):
    global camera
    global robot_controller
    global face_controller

    robot_controller = RobotController()
    face_controller = FaceController()
    camera = Picamera2()

    configuration = (
        camera.create_video_configuration(
            main={
                "size": (1280, 720),
            },
            controls={
                "FrameRate": 30,
            },
            buffer_count=4,
            transform=Transform(
                hflip=1,
                vflip=1,
            ),
        )
    )

    camera.configure(configuration)

    robot_controller.start()
    face_controller.start()

    camera.start_recording(
        MJPEGEncoder(),
        FileOutput(camera_output),
    )

    try:
        yield

    finally:
        camera.stop_recording()
        camera.close()

        face_controller.stop()
        robot_controller.stop()

        camera = None
        face_controller = None
        robot_controller = None


app = FastAPI(
    title="Robot Manual Control",
    lifespan=lifespan,
)


PAGE = """
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">

    <meta
        name="viewport"
        content="width=device-width, initial-scale=1"
    >

    <title>Robot Manual Control</title>

    <style>
        * {
            box-sizing: border-box;
        }

        body {
            margin: 0;
            height: 100vh;
            overflow: hidden;
            background: white;
            color: black;
            font-family: Arial, sans-serif;
        }

        main {
            display: grid;
            grid-template-columns: 38% 62%;
            grid-template-rows: 50% 50%;
            height: 100%;
        }

        section {
            min-width: 0;
            min-height: 0;
            padding: 16px;
            overflow: hidden;
            border: 1px solid black;
        }

        h2 {
            margin: 0 0 12px;
            font-size: 18px;
            text-transform: uppercase;
        }

        button {
            min-height: 44px;
            padding: 10px 14px;
            border: 2px solid black;
            border-radius: 0;
            background: white;
            color: black;
            font: inherit;
            font-weight: 700;
            cursor: pointer;
        }

        button:hover,
        button.active {
            background: black;
            color: white;
        }

        button:disabled {
            color: #999;
            border-color: #999;
            cursor: not-allowed;
        }

        #commands {
            display: flex;
            flex-direction: column;
        }

        #command-buttons {
            display: grid;
            grid-template-columns:
                repeat(3, minmax(0, 1fr));
            gap: 8px;
            overflow-y: auto;
        }

        #robot-status {
            margin-top: auto;
            padding-top: 12px;
            font-family: monospace;
        }

        #movement {
            display: grid;
            grid-template-rows: auto 1fr;
        }

        #dpad {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            grid-template-rows: repeat(2, 1fr);
            gap: 8px;
            width: min(100%, 330px);
            height: min(100%, 260px);
            margin: auto;
        }

        .arrow {
            padding: 0;
            font-size: clamp(28px, 5vw, 52px);
            touch-action: none;
            user-select: none;
        }

        #forward {
            grid-column: 2;
            grid-row: 1;
        }

        #left {
            grid-column: 1;
            grid-row: 2;
        }

        #backward {
            grid-column: 2;
            grid-row: 2;
        }

        #right {
            grid-column: 3;
            grid-row: 2;
        }

        #camera-panel {
            display: grid;
            grid-template-rows: auto 1fr;
        }

        #camera {
            width: 100%;
            height: 100%;
            min-height: 0;
            object-fit: contain;
            background: black;
        }

        #faces {
            display: grid;
            grid-template-columns:
                minmax(220px, 42%) 1fr;
            gap: 16px;
        }

        #face-display {
            display: flex;
            min-width: 0;
            flex-direction: column;
        }

        #face-preview {
            width: 100%;
            max-height: calc(100% - 64px);
            flex: 1;
            object-fit: contain;
            border: 2px solid black;
            background: black;
            image-rendering: pixelated;
        }

        #current-face {
            margin: 10px 0 0;
            overflow-wrap: anywhere;
            font-family: monospace;
        }

        #face-options {
            display: grid;
            grid-template-columns:
                repeat(3, minmax(0, 1fr));
            min-width: 0;
            overflow-y: auto;
            align-content: start;
            gap: 8px;
        }

        #face-options button {
            overflow-wrap: anywhere;
        }

        @media (max-width: 800px) {
            body {
                height: auto;
                overflow: auto;
            }

            main {
                display: block;
            }

            section {
                min-height: 420px;
            }

            #faces {
                grid-template-columns: 1fr;
            }

            #face-preview {
                height: 180px;
            }
        }
    </style>
</head>

<body>
    <main>
        <section id="commands">
            <h2>
                Commands
            </h2>

            <div id="command-buttons"></div>

            <div id="robot-status">
                Ready
            </div>
        </section>

        <section id="camera-panel">
            <h2>
                Camera
            </h2>

            <img
                id="camera"
                src="/stream.mjpg"
                alt="Live robot camera"
            >
        </section>

        <section id="movement">
            <h2>
                Movement
            </h2>

            <div id="dpad">
                <button
                    id="forward"
                    class="arrow"
                    data-action="forward"
                    aria-label="Walk forward"
                >
                    ↑
                </button>

                <button
                    id="left"
                    class="arrow"
                    data-action="left"
                    aria-label="Turn left"
                >
                    ←
                </button>

                <button
                    id="backward"
                    class="arrow"
                    data-action="backward"
                    aria-label="Walk backward"
                >
                    ↓
                </button>

                <button
                    id="right"
                    class="arrow"
                    data-action="right"
                    aria-label="Turn right"
                >
                    →
                </button>
            </div>
        </section>

        <section id="faces">
            <div id="face-display">
                <h2>
                    Current Face
                </h2>

                <img
                    id="face-preview"
                    src="/face-preview.png"
                    alt="Current LCD face"
                >

                <p id="current-face">
                    Loading
                </p>
            </div>

            <div id="face-options"></div>
        </section>
    </main>

    <script>
        const faceNames = __FACE_NAMES__;

        const movementActions = [
            "forward",
            "backward",
            "left",
            "right"
        ];

        const commandButtons =
            document.getElementById(
                "command-buttons"
            );

        const faceOptions =
            document.getElementById(
                "face-options"
            );

        const robotStatus =
            document.getElementById(
                "robot-status"
            );

        const currentFace =
            document.getElementById(
                "current-face"
            );

        const facePreview =
            document.getElementById(
                "face-preview"
            );

        let availableActions = [];

        const movementControl = {
            action: null,
            pressed: false,
            stopping: false,
            startPromise: null
        };

        function label(name) {
            return name
                .replaceAll("_", " ")
                .toUpperCase();
        }

        async function sendAction(action) {
            robotStatus.textContent =
                `Sending: ${label(action)}`;

            try {
                const response = await fetch(
                    `/api/action/${
                        encodeURIComponent(action)
                    }`,
                    {
                        method: "POST"
                    }
                );

                const data =
                    await response.json();

                if (!response.ok) {
                    throw new Error(
                        data.detail
                        || "Command failed"
                    );
                }

                robotStatus.textContent =
                    `Queued: ${label(action)}`;

            } catch (error) {
                robotStatus.textContent =
                    error.message;
            }
        }

        async function movementRequest(
            action,
            operation
        ) {
            const response = await fetch(
                `/api/movement/${
                    encodeURIComponent(action)
                }/${operation}`,
                {
                    method: "POST"
                }
            );

            const data =
                await response.json();

            if (!response.ok) {
                throw new Error(
                    data.detail
                    || "Movement failed"
                );
            }

            return data;
        }

        function movementButton(action) {
            return document.querySelector(
                `[data-action="${action}"]`
            );
        }

        function resetMovement(action) {
            if (
                movementControl.action
                !== action
            ) {
                return;
            }

            movementButton(
                action
            ).classList.remove(
                "active"
            );

            movementControl.action = null;
            movementControl.pressed = false;
            movementControl.stopping = false;
            movementControl.startPromise = null;
        }

        async function pressMovement(action) {
            if (
                movementControl.action
                !== null
            ) {
                return;
            }

            movementControl.action = action;
            movementControl.pressed = true;
            movementControl.stopping = false;

            movementButton(
                action
            ).classList.add(
                "active"
            );

            robotStatus.textContent =
                `Starting: ${label(action)}`;

            movementControl.startPromise =
                movementRequest(
                    action,
                    "start"
                );

            try {
                await movementControl.startPromise;

                if (
                    movementControl.action
                    === action
                    && !movementControl.pressed
                ) {
                    stopMovement(action);
                }

            } catch (error) {
                robotStatus.textContent =
                    error.message;

                resetMovement(action);
            }
        }

        async function stopMovement(action) {
            if (
                movementControl.action
                !== action
            ) {
                return;
            }

            movementControl.pressed = false;

            movementButton(
                action
            ).classList.remove(
                "active"
            );

            if (movementControl.stopping) {
                return;
            }

            movementControl.stopping = true;

            try {
                await movementControl.startPromise;

                await movementRequest(
                    action,
                    "stop"
                );

                robotStatus.textContent =
                    "Finishing current cycle, then standing";

            } catch (error) {
                robotStatus.textContent =
                    error.message;

            } finally {
                resetMovement(action);
            }
        }

        async function setFace(name) {
            try {
                const response = await fetch(
                    `/api/face/${
                        encodeURIComponent(name)
                    }`,
                    {
                        method: "POST"
                    }
                );

                const data =
                    await response.json();

                if (!response.ok) {
                    throw new Error(
                        data.detail
                        || "Face change failed"
                    );
                }

                currentFace.textContent =
                    label(name);

            } catch (error) {
                robotStatus.textContent =
                    error.message;
            }
        }

        function buildControls() {
            for (
                const action
                of availableActions
            ) {
                if (
                    movementActions.includes(
                        action
                    )
                ) {
                    continue;
                }

                const button =
                    document.createElement(
                        "button"
                    );

                button.textContent =
                    label(action);

                button.addEventListener(
                    "click",
                    () => sendAction(action)
                );

                commandButtons.appendChild(
                    button
                );
            }

            for (
                const action
                of movementActions
            ) {
                const button =
                    movementButton(action);

                button.disabled =
                    !availableActions.includes(
                        action
                    );

                button.addEventListener(
                    "pointerdown",
                    event => {
                        if (
                            event.pointerType
                            === "mouse"
                            && event.button !== 0
                        ) {
                            return;
                        }

                        event.preventDefault();

                        button.setPointerCapture(
                            event.pointerId
                        );

                        pressMovement(action);
                    }
                );

                button.addEventListener(
                    "pointerup",
                    event => {
                        event.preventDefault();
                        stopMovement(action);
                    }
                );

                button.addEventListener(
                    "pointercancel",
                    () => stopMovement(action)
                );

                button.addEventListener(
                    "lostpointercapture",
                    () => stopMovement(action)
                );

                button.addEventListener(
                    "contextmenu",
                    event => {
                        event.preventDefault();
                    }
                );
            }

            for (
                const name
                of faceNames
            ) {
                const button =
                    document.createElement(
                        "button"
                    );

                button.textContent =
                    label(name);

                button.dataset.face =
                    name;

                button.addEventListener(
                    "click",
                    () => setFace(name)
                );

                faceOptions.appendChild(
                    button
                );
            }
        }

        function updateFaceButtons(name) {
            document
                .querySelectorAll(
                    "[data-face]"
                )
                .forEach(button => {
                    button.classList.toggle(
                        "active",
                        button.dataset.face
                        === name
                    );
                });
        }

        async function refreshStatus() {
            try {
                const response =
                    await fetch(
                        "/api/status",
                        {
                            cache: "no-store"
                        }
                    );

                const data =
                    await response.json();

                const action =
                    data.robot.active
                    || data.robot.pending;

                robotStatus.textContent =
                    data.robot.last_error
                    ? `Error: ${
                        data.robot.last_error
                    }`
                    : action
                        ? `Running: ${
                            label(action)
                        }`
                        : "Ready";

                currentFace.textContent =
                    label(
                        data.face.face
                    );

                updateFaceButtons(
                    data.face.face
                );

            } catch (error) {
                robotStatus.textContent =
                    "Disconnected";
            }
        }

        const keyboardMovement = {
            ArrowUp: "forward",
            ArrowDown: "backward",
            ArrowLeft: "left",
            ArrowRight: "right"
        };

        document.addEventListener(
            "keydown",
            event => {
                if (event.repeat) {
                    return;
                }

                const action =
                    keyboardMovement[
                        event.key
                    ];

                if (
                    action
                    && availableActions.includes(
                        action
                    )
                ) {
                    event.preventDefault();
                    pressMovement(action);
                }
            }
        );

        document.addEventListener(
            "keyup",
            event => {
                const action =
                    keyboardMovement[
                        event.key
                    ];

                if (action) {
                    event.preventDefault();
                    stopMovement(action);
                }
            }
        );

        window.addEventListener(
            "blur",
            () => {
                if (
                    movementControl.action
                ) {
                    stopMovement(
                        movementControl.action
                    );
                }
            }
        );

        document.addEventListener(
            "visibilitychange",
            () => {
                if (
                    document.hidden
                    && movementControl.action
                ) {
                    stopMovement(
                        movementControl.action
                    );
                }
            }
        );

        async function start() {
            const response = await fetch(
                "/api/status",
                {
                    cache: "no-store"
                }
            );

            const data =
                await response.json();

            availableActions =
                data.robot.available_actions;

            buildControls();
            refreshStatus();

            setInterval(
                refreshStatus,
                500
            );

            setInterval(
                () => {
                    facePreview.src =
                        `/face-preview.png?t=${
                            Date.now()
                        }`;
                },
                200
            );
        }

        start();
    </script>
</body>
</html>
"""


@app.get(
    "/",
    response_class=HTMLResponse,
)
def index():
    return PAGE.replace(
        "__FACE_NAMES__",
        json.dumps(FACE_NAMES),
    )


def generate_mjpeg():
    while True:
        frame = (
            camera_output.wait_for_frame()
        )

        if frame is None:
            continue

        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n"
            b"Content-Length: "
            + str(len(frame)).encode()
            + b"\r\n\r\n"
            + frame
            + b"\r\n"
        )


@app.get("/stream.mjpg")
def stream():
    return StreamingResponse(
        generate_mjpeg(),
        media_type=(
            "multipart/x-mixed-replace; "
            "boundary=frame"
        ),
        headers={
            "Cache-Control": (
                "no-store, no-cache, "
                "must-revalidate, max-age=0"
            ),
            "Pragma": "no-cache",
        },
    )


@app.get("/face-preview.png")
def face_preview():
    if face_controller is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Face controller is not ready"
            ),
        )

    return Response(
        content=(
            face_controller.preview_png()
        ),
        media_type="image/png",
        headers={
            "Cache-Control": "no-store",
        },
    )


@app.post("/api/action/{action}")
def run_action(action):
    if robot_controller is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Robot controller is not ready"
            ),
        )

    try:
        if action in MOVEMENT_ALIASES:
            accepted = (
                robot_controller
                .start_movement(action)
            )

            if accepted:
                robot_controller.stop_movement(
                    action
                )
        else:
            accepted = (
                robot_controller.submit(
                    action
                )
            )

    except KeyError:
        raise HTTPException(
            status_code=404,
            detail=(
                "No compatible servo.py "
                f"function was found for "
                f"'{action}'"
            ),
        )

    if not accepted:
        raise HTTPException(
            status_code=409,
            detail=(
                "Robot is already running "
                "a command"
            ),
        )

    return {
        "ok": True,
        "action": action,
    }


@app.post(
    "/api/movement/{action}/start"
)
def start_movement(action):
    if robot_controller is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Robot controller is not ready"
            ),
        )

    try:
        accepted = (
            robot_controller
            .start_movement(action)
        )

    except KeyError:
        raise HTTPException(
            status_code=404,
            detail=(
                "No compatible servo.py "
                f"function was found for "
                f"'{action}'"
            ),
        )

    if not accepted:
        raise HTTPException(
            status_code=409,
            detail=(
                "Robot is already running "
                "a command"
            ),
        )

    return {
        "ok": True,
        "action": action,
    }


@app.post(
    "/api/movement/{action}/stop"
)
def stop_movement(action):
    if robot_controller is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Robot controller is not ready"
            ),
        )

    try:
        robot_controller.stop_movement(
            action
        )

    except KeyError:
        raise HTTPException(
            status_code=404,
            detail=(
                "No compatible servo.py "
                f"function was found for "
                f"'{action}'"
            ),
        )

    return {
        "ok": True,
        "action": action,
    }


@app.post("/api/face/{face_name}")
def set_face(face_name):
    if face_controller is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Face controller is not ready"
            ),
        )

    try:
        face_controller.set_face(
            face_name
        )

    except KeyError:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Unknown face '{face_name}'"
            ),
        )

    return {
        "ok": True,
        "face": face_name,
    }


@app.get("/api/status")
def get_status():
    if (
        robot_controller is None
        or face_controller is None
    ):
        raise HTTPException(
            status_code=503,
            detail=(
                "Controllers are not ready"
            ),
        )

    return {
        "robot": robot_controller.status(),
        "face": face_controller.status(),
        "camera": (
            camera is not None
            and camera_output.frame
            is not None
        ),
    }


if __name__ == "__main__":
    uvicorn.run(
        app,
        host=HOST,
        port=PORT,
    )