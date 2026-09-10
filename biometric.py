# SPDX-FileCopyrightText: 2021 ladyada for Adafruit Industries
# SPDX-License-Identifier: MIT

import os
import shutil
import requests
from io import BytesIO
import zipfile

import threading

import time
import adafruit_fingerprint


def set_sensor_led(color, cycles):
    try:
        result = finger.set_led(color=color, mode=2, speed=100, cycles=cycles)
        if result != adafruit_fingerprint.OK:
            print(f'Fingerprint sensor LED command failed with code {result}')
            return False
        return True
    except (AttributeError, RuntimeError) as error:
        print(f'Fingerprint sensor LED command is unsupported: {error}')
        return False


def blink_success():
    set_sensor_led(color=2, cycles=2)


def blink_failure():
    set_sensor_led(color=1, cycles=3)

# If using with Linux/Raspberry Pi and hardware UART:
import serial
uart = serial.Serial("/dev/ttyS0", baudrate=57600, timeout=1)

finger = adafruit_fingerprint.Adafruit_Fingerprint(uart)

from config import API_URL


def getserial():
        # Extract serial from cpuinfo file
        cpuserial = "0000000000000000"
        try:
            f = open('/proc/cpuinfo','r')
            for line in f:
                if line[0:6]=='Serial':
                    cpuserial = line[10:26]
            f.close()
        except:
            cpuserial = "ERROR000000000"
        return cpuserial


def delete_directory(directory):
    try:
        # Delete the entire directory and its contents
        shutil.rmtree(directory)
    except Exception as e:
        pass


def fetch_fingerprints():
    try:
        folder = "templates"
        delete_directory(folder)
        # Replace with the URL of your Flask endpoint
        url = f'{API_URL}/biometric/fetch/staff'

        # Make a GET request to the Flask endpoint
        response = requests.get(url, headers={'Authorization':getserial()})

        # Check if the request was successful (status code 200)
        if response.status_code == 200:
            # Create a BytesIO object from the response content
            zip_buffer = BytesIO(response.content)

            # Create a ZipFile object
            with zipfile.ZipFile(zip_buffer, 'r') as zip_file:
                # Specify the directory where you want to extract the files
                os.makedirs(folder, exist_ok=True)

                # Extract all files to the specified directory
                zip_file.extractall(folder)

        else:
            print(f"Error: {response.status_code}")
    except Exception as e:
        print(e)
        fetch_fingerprints()


def find_fingerprint_match():
    """Compares a new fingerprint template to an existing template stored in a file
    This is useful when templates are stored centrally (i.e. in a database)"""
    print("Waiting for finger print...")
    while finger.get_image() != adafruit_fingerprint.OK:
        pass
    print("Templating...")
    if finger.image_2_tz(1) != adafruit_fingerprint.OK:
        return False

    print("Loading files...")
    folder = "templates"
    files = os.listdir(os.path.join(folder))
    for f in files:
        with open(os.path.join(folder, f), "rb") as file:
            data = file.read()
        finger.send_fpdata(list(data), "char", 2)

        i = finger.compare_templates()
        if i == adafruit_fingerprint.OK:
            print("Fingerprint found")
            blink_success()
            threading.Thread(target=submit_attendance, args=(f, )).start()
            return True
        if i == adafruit_fingerprint.NOMATCH:
            pass
    blink_failure()
    return False

def submit_attendance(fingerprint):
    try:
        url = f'{API_URL}/attendance/staff'
        payload = {
            'staffid': fingerprint.split('.')[0]
        }
        headers = {
            'Content-Type': 'application/json',
            'Authorization': getserial()
        }
        # Make a GET request to the Flask endpoint
        response = requests.post(url, json=payload, headers=headers)
        if response.json().get('success'):
            print('success')
        else:
            print('failed')
    except Exception as e:
        print(e)

fetch_fingerprints()
while True:
    find_fingerprint_match()