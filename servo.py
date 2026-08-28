import time
import board
import busio
from adafruit_motor import servo
from adafruit_pca9685 import PCA9685


FRAME_DELAY = 0.15

FRONT_LEFT_JOINT = 0
FRONT_LEFT_LEG = 1
FRONT_RIGHT_JOINT = 2
FRONT_RIGHT_LEG = 3
BACK_RIGHT_JOINT = 4
BACK_RIGHT_LEG = 5
BACK_LEFT_JOINT = 6
BACK_LEFT_LEG = 7

SERVO_LIMITS = {
    FRONT_LEFT_JOINT: {"min": 52, "max": 152},
    FRONT_LEFT_LEG: {"min": 12, "max": 108},
    FRONT_RIGHT_JOINT: {"min": 154, "max": 52},
    FRONT_RIGHT_LEG: {"min": 180, "max": 78},
    BACK_RIGHT_JOINT: {"min": 0, "max": 94},
    BACK_RIGHT_LEG: {"min": 24, "max": 122},
    BACK_LEFT_JOINT: {"min": 178, "max": 80},
    BACK_LEFT_LEG: {"min": 172, "max": 70},
}


i2c = busio.I2C(board.SCL, board.SDA)
pca = PCA9685(i2c, address=0x40)
pca.frequency = 50

servos = [
    servo.Servo(
        pca.channels[channel],
        min_pulse=500,
        max_pulse=2400,
        actuation_range=180,
    )
    for channel in range(8)
]


def convert_position(channel, position):
    if not 0.0 <= position <= 1.0:
        raise ValueError(
            f"Channel {channel}: position {position} is outside 0.0–1.0"
        )

    limits = SERVO_LIMITS[channel]

    physical_angle = (
        limits["min"]
        + position * (limits["max"] - limits["min"])
    )

    even_angle = int(round(physical_angle / 2.0)) * 2

    return max(0, min(180, even_angle))


def move_servos(targets, delay=FRAME_DELAY):
    converted_targets = {
        channel: convert_position(channel, position)
        for channel, position in targets.items()
    }

    for channel, physical_angle in converted_targets.items():
        servos[channel].angle = physical_angle

    time.sleep(delay)


def stand():
    move_servos({
        FRONT_LEFT_JOINT: 0.50,
        FRONT_LEFT_LEG: 0.00,
        FRONT_RIGHT_JOINT: 0.50,
        FRONT_RIGHT_LEG: 0.00,
        BACK_RIGHT_JOINT: 0.50,
        BACK_RIGHT_LEG: 0.00,
        BACK_LEFT_JOINT: 0.50,
        BACK_LEFT_LEG: 0.00,
    })


def walk(cycles=5):
    move_servos({
        FRONT_RIGHT_LEG: 0.50,
        FRONT_LEFT_LEG: 0.50,
        BACK_RIGHT_JOINT: 1.00,
        FRONT_LEFT_JOINT: 0.28,
    })

    for _ in range(cycles):
        move_servos({
            FRONT_RIGHT_LEG: 0.50,
            FRONT_LEFT_LEG: 0.00,
        })

        move_servos({
            BACK_LEFT_LEG: 0.50,
            BACK_LEFT_JOINT: 1.00,
            BACK_RIGHT_LEG: 0.00,
            FRONT_RIGHT_JOINT: 0.00,
        })

        move_servos({
            BACK_RIGHT_JOINT: 0.50,
            FRONT_LEFT_JOINT: 1.00,
        })

        move_servos({
            BACK_RIGHT_LEG: 0.50,
            BACK_LEFT_LEG: 0.00,
        })

        move_servos({
            FRONT_RIGHT_LEG: 0.00,
            FRONT_LEFT_LEG: 0.50,
            BACK_RIGHT_JOINT: 1.00,
            FRONT_LEFT_JOINT: 0.00,
        })

        move_servos({
            BACK_LEFT_JOINT: 0.50,
            FRONT_RIGHT_JOINT: 1.00,
        })

    stand()


def walk_backward(cycles=5):
    time.sleep(FRAME_DELAY)

    for _ in range(cycles):
        move_servos({
            FRONT_RIGHT_LEG: 0.50,
            FRONT_LEFT_LEG: 0.00,
        })

        move_servos({
            BACK_LEFT_LEG: 0.50,
            BACK_LEFT_JOINT: 0.50,
            BACK_RIGHT_LEG: 0.00,
            FRONT_RIGHT_JOINT: 1.00,
        })

        move_servos({
            BACK_RIGHT_JOINT: 1.00,
            FRONT_LEFT_JOINT: 0.00,
        })

        move_servos({
            BACK_RIGHT_LEG: 0.50,
            BACK_LEFT_LEG: 0.00,
        })

        move_servos({
            FRONT_RIGHT_LEG: 0.00,
            FRONT_LEFT_LEG: 0.50,
            BACK_RIGHT_JOINT: 0.50,
            FRONT_LEFT_JOINT: 1.00,
        })

        move_servos({
            BACK_LEFT_JOINT: 1.00,
            FRONT_RIGHT_JOINT: 0.00,
        })

    stand()


def turn_left(cycles=5):
    for _ in range(cycles):
        move_servos({
            FRONT_RIGHT_LEG: 0.50,
            BACK_LEFT_LEG: 0.50,
        })

        move_servos({
            FRONT_RIGHT_JOINT: 0.00,
            BACK_LEFT_JOINT: 0.00,
        })

        move_servos({
            FRONT_RIGHT_LEG: 0.00,
            BACK_LEFT_LEG: 0.00,
        })

        move_servos({
            FRONT_RIGHT_JOINT: 0.50,
            BACK_LEFT_JOINT: 0.50,
        })

        move_servos({
            BACK_RIGHT_LEG: 0.50,
            FRONT_LEFT_LEG: 0.50,
        })

        move_servos({
            BACK_RIGHT_JOINT: 1.00,
            FRONT_LEFT_JOINT: 1.00,
        })

        move_servos({
            BACK_RIGHT_LEG: 0.00,
            FRONT_LEFT_LEG: 0.00,
        })

        move_servos({
            BACK_RIGHT_JOINT: 0.50,
            FRONT_LEFT_JOINT: 0.50,
        })

    stand()


def turn_right(cycles=5):
    for _ in range(cycles):
        move_servos({
            BACK_RIGHT_LEG: 0.50,
            FRONT_LEFT_LEG: 0.50,
        })

        move_servos({
            BACK_RIGHT_JOINT: 0.00,
            FRONT_LEFT_JOINT: 0.00,
        })

        move_servos({
            BACK_RIGHT_LEG: 0.00,
            FRONT_LEFT_LEG: 0.00,
        })

        move_servos({
            BACK_RIGHT_JOINT: 0.50,
            FRONT_LEFT_JOINT: 0.50,
        })

        move_servos({
            FRONT_RIGHT_LEG: 0.50,
            BACK_LEFT_LEG: 0.50,
        })

        move_servos({
            FRONT_RIGHT_JOINT: 1.00,
            BACK_LEFT_JOINT: 1.00,
        })

        move_servos({
            FRONT_RIGHT_LEG: 0.00,
            BACK_LEFT_LEG: 0.00,
        })

        move_servos({
            FRONT_RIGHT_JOINT: 0.50,
            BACK_LEFT_JOINT: 0.50,
        })

    stand()


def bow():
    stand()
    time.sleep(0.2)

    move_servos({
        FRONT_LEFT_JOINT: 0.00,
        FRONT_RIGHT_JOINT: 0.00,
        FRONT_LEFT_LEG: 0.00,
        FRONT_RIGHT_LEG: 0.00,
        BACK_LEFT_JOINT: 0.00,
        BACK_RIGHT_JOINT: 0.00,
        BACK_RIGHT_LEG: 0.00,
        BACK_LEFT_LEG: 0.00,
    }, delay=0.6)

    move_servos({
        FRONT_LEFT_LEG: 1.00,
        FRONT_RIGHT_LEG: 1.00,
    }, delay=3.0)

    stand()


def worm(cycles=5):
    stand()
    time.sleep(0.2)

    move_servos({
        FRONT_RIGHT_JOINT: 0.00,
        BACK_RIGHT_JOINT: 0.00,
        FRONT_LEFT_JOINT: 0.00,
        BACK_LEFT_JOINT: 0.00,
        BACK_RIGHT_LEG: 1.00,
        FRONT_RIGHT_LEG: 1.00,
        FRONT_LEFT_LEG: 1.00,
        BACK_LEFT_LEG: 1.00,
    }, delay=0.2)

    for _ in range(cycles):
        move_servos({
            FRONT_RIGHT_LEG: 1.00,
            FRONT_LEFT_LEG: 1.00,
            BACK_RIGHT_LEG: 0.50,
            BACK_LEFT_LEG: 0.50,
        }, delay=0.3)

        move_servos({
            FRONT_RIGHT_LEG: 0.50,
            FRONT_LEFT_LEG: 0.50,
            BACK_RIGHT_LEG: 1.00,
            BACK_LEFT_LEG: 1.00,
        }, delay=0.3)

    stand()


def cute(cycles=5):
    stand()
    time.sleep(0.2)

    move_servos({
        BACK_LEFT_JOINT: 0.22,
        BACK_RIGHT_JOINT: 0.22,
        BACK_RIGHT_LEG: 0.00,
        BACK_LEFT_LEG: 0.00,
        FRONT_LEFT_JOINT: 0.00,
        FRONT_RIGHT_JOINT: 0.00,
        FRONT_LEFT_LEG: 0.00,
        FRONT_RIGHT_LEG: 0.00,
    }, delay=0.2)

    for _ in range(cycles):
        move_servos({
            BACK_RIGHT_LEG: 0.00,
            BACK_LEFT_LEG: 0.50,
        }, delay=0.3)

        move_servos({
            BACK_RIGHT_LEG: 0.50,
            BACK_LEFT_LEG: 0.00,
        }, delay=0.3)

    stand()


def dance(cycles=5):
    move_servos({
        FRONT_RIGHT_JOINT: 1.00,
        BACK_RIGHT_JOINT: 1.00,
        FRONT_LEFT_JOINT: 1.00,
        BACK_LEFT_JOINT: 1.00,
        BACK_RIGHT_LEG: 0.22,
        FRONT_RIGHT_LEG: 0.22,
        FRONT_LEFT_LEG: 0.11,
        BACK_LEFT_LEG: 0.11,
    }, delay=0.3)

    for _ in range(cycles):
        move_servos({
            BACK_RIGHT_LEG: 0.72,
            FRONT_RIGHT_LEG: 0.72,
            FRONT_LEFT_LEG: 0.11,
            BACK_LEFT_LEG: 0.11,
        }, delay=0.3)

        move_servos({
            BACK_RIGHT_LEG: 0.22,
            FRONT_RIGHT_LEG: 0.22,
            FRONT_LEFT_LEG: 0.72,
            BACK_LEFT_LEG: 0.72,
        }, delay=0.3)

    stand()


try:
    stand()
    time.sleep(1)

    bow()
    worm(cycles=5)
    cute(cycles=5)
    dance(cycles=5)

except KeyboardInterrupt:
    print("\nStopped.")

finally:
    stand()
    time.sleep(1)

    for channel in range(8):
        pca.channels[channel].duty_cycle = 0

    pca.deinit()
    i2c.deinit()