import time

import adafruit_ssd1306
import board
import busio
from PIL import Image

from faces import FACE_NAMES, HEIGHT, WIDTH, frames_for


I2C_ADDRESS = 0x3C
FACE_DURATION = 1.5
FRAME_DELAY = 0.2


def bitmap_image(bitmap: bytes) -> Image.Image:
    image = Image.frombytes("1", (WIDTH, HEIGHT), bitmap)

    return image


def show_bitmap(
    display: adafruit_ssd1306.SSD1306_I2C,
    bitmap: bytes,
) -> None:
    display.image(bitmap_image(bitmap))
    display.show()


def show_face(
    display: adafruit_ssd1306.SSD1306_I2C,
    face_name: str,
) -> None:
    frames = frames_for(face_name)

    print(f"SHOW: {face_name} ({len(frames)} frame(s))")

    if len(frames) == 1:
        show_bitmap(display, frames[0])
        time.sleep(FACE_DURATION)
        return

    deadline = time.monotonic() + FACE_DURATION
    frame_index = 0

    while time.monotonic() < deadline:
        show_bitmap(display, frames[frame_index])

        frame_index += 1

        if frame_index == len(frames):
            frame_index = 0

        remaining = deadline - time.monotonic()
        time.sleep(min(FRAME_DELAY, max(0, remaining)))


def main() -> None:
    i2c = busio.I2C(board.SCL, board.SDA)

    display = adafruit_ssd1306.SSD1306_I2C(
        WIDTH,
        HEIGHT,
        i2c,
        addr=I2C_ADDRESS,
    )

    display.fill(0)
    display.show()

    try:
        for index, face_name in enumerate(FACE_NAMES, start=1):
            print(f"[{index}/{len(FACE_NAMES)}]", end=" ")
            show_face(display, face_name)

    except KeyboardInterrupt:
        print("\nFace test stopped.")

    finally:
        idle_frames = frames_for("idle")

        if idle_frames:
            show_bitmap(display, idle_frames[0])
        else:
            display.fill(0)
            display.show()


if __name__ == "__main__":
    main()