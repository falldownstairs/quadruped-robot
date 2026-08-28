#!/usr/bin/python3
# coding=utf-8
# File name   : setup.py
# Author      : Adeept

import os
import time
import subprocess

def run_command(cmd=""):
    import subprocess
    p = subprocess.Popen(
        cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    result = p.stdout.read().decode('utf-8')
    status = p.poll()
    return status, result

def check_raspbain_version():
    _, result = run_command("cat /etc/debian_version|awk -F. '{print $1}'")
    return int(result.strip())

commands_apt = [
"sudo apt-get update",
"sudo apt-get install -y i2c-tools",
"sudo apt-get install -y python3-smbus",
"sudo apt-get install python3-gpiozero python3-pigpio",
]
mark_apt = 0
for x in range(3):
    for command in commands_apt:
        if os.system(command) != 0:
            print("Error running installation step apt")
            mark_apt = 1
    if mark_apt == 0:
        break

commands_pip_1 = [
"sudo pip3 install adafruit-circuitpython-motor",
"sudo pip3 install adafruit-circuitpython-pca9685",
"sudo -H pip3 install --upgrade luma.oled",
"sudo pip3 install mpu6050-raspberrypi",
"sudo pip3 install spidev",
"sudo pip3 install adafruit-circuitpython-busdevice adafruit-circuitpython-ssd1306",
"sudo pip3 install numpy",
"sudo pip3 install adafruit-circuitpython-ads7830"
]
commands_pip_2 = [
"sudo pip3 install adafruit-circuitpython-motor --break-system-packages",
"sudo pip3 install adafruit-circuitpython-pca9685 --break-system-packages",
"sudo -H pip3 install --upgrade luma.oled --break-system-packages",
"sudo pip3 install mpu6050-raspberrypi --break-system-packages",
"sudo pip3 install spidev --break-system-packages",
"sudo pip3 install adafruit-circuitpython-busdevice adafruit-circuitpython-ssd1306 --break-system-packages",
"sudo pip3 install numpy --break-system-packages",
"sudo pip3 install adafruit-circuitpython-ads7830 --break-system-packages"
]
mark_pip = 0
OS_version = check_raspbain_version()
if OS_version <= 11:
    for x in range(3):
        for command in commands_pip_1:
            if os.system(command) != 0:
                print("Error running installation step pip")
                mark_pip = 1
        if mark_pip == 0:
            break
else:
    for x in range(3):
        for command in commands_pip_2:
            if os.system(command) != 0:
                print("Error running installation step pip")
                mark_pip = 1
        if mark_pip == 0:
            break

print('All dependency libraries required for the project have been fully configured and completed.')
