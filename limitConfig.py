import time
import board
import busio
from adafruit_motor import servo
from adafruit_pca9685 import PCA9685


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

limits = {}


def choose_angle(channel, bound_name):
    last_angle = None

    print(f"\nSet the {bound_name} angle for servo {channel}.")
    print("Enter an angle from 0–180, or type 'n' when satisfied.")

    while True:
        value = input("> ").strip()

        if value == "n":
            if last_angle is not None:
                return last_angle

            print("Enter at least one angle first.")
            continue

        try:
            angle = int(value)

            if not 0 <= angle <= 180:
                print("Angle must be between 0 and 180.")
                continue

            servos[channel].angle = angle
            last_angle = angle
            time.sleep(0.2)

        except ValueError:
            print("Enter a number or 'n'.")


try:
    for channel in range(8):
        print(f"\n--- Servo {channel} ---")

        minimum = choose_angle(channel, "minimum")
        maximum = choose_angle(channel, "maximum")

        limits[channel] = {
            "min": minimum,
            "max": maximum,
        }

    print("\nSERVO_LIMITS = {")
    for channel, values in limits.items():
        print(
            f'    {channel}: '
            f'{{"min": {values["min"]}, "max": {values["max"]}}},'
        )
    print("}")

except KeyboardInterrupt:
    print("\nStopped.")

finally:
    for channel in range(8):
        pca.channels[channel].duty_cycle = 0

    pca.deinit()
    i2c.deinit()