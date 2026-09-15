# SPDX-FileCopyrightText: 2021 ladyada for Adafruit Industries
# SPDX-License-Identifier: MIT

import os
import shutil
import requests
from io import BytesIO
import zipfile

import threading
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

import time
import adafruit_fingerprint


# If using with Linux/Raspberry Pi and hardware UART:
import serial
uart = serial.Serial("/dev/ttyS0", baudrate=57600, timeout=1)

finger = adafruit_fingerprint.Adafruit_Fingerprint(uart)

from config import API_URL

QUEUE_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'attendance_queue.db')
UTC_PLUS_ONE = timezone(timedelta(hours=1))
queue_lock = threading.Lock()


def initialize_queue():
    with sqlite3.connect(QUEUE_DB) as connection:
        connection.execute(
            '''CREATE TABLE IF NOT EXISTS pending_attendance (
                event_id TEXT PRIMARY KEY,
                staffid TEXT NOT NULL,
                captured_at TEXT NOT NULL
            )'''
        )
        connection.commit()


def current_local_time():
    return datetime.now(timezone.utc).astimezone(UTC_PLUS_ONE).replace(microsecond=0)


def purge_old_attendance():
    current_month = current_local_time().strftime('%Y-%m')
    with sqlite3.connect(QUEUE_DB) as connection:
        connection.execute(
            'DELETE FROM pending_attendance WHERE substr(captured_at, 1, 7) != ?',
            (current_month,),
        )
        connection.commit()


def queue_attendance(staffid, captured_at):
    with sqlite3.connect(QUEUE_DB) as connection:
        connection.execute(
            'INSERT INTO pending_attendance (event_id, staffid, captured_at) VALUES (?, ?, ?)',
            (str(uuid.uuid4()), staffid, captured_at),
        )
        connection.commit()


def sync_pending_attendance():
    purge_old_attendance()
    with queue_lock:
        with sqlite3.connect(QUEUE_DB) as connection:
            pending = connection.execute(
                'SELECT event_id, staffid, captured_at FROM pending_attendance ORDER BY captured_at'
            ).fetchall()

        for event_id, staffid, captured_at in pending:
            try:
                response = requests.post(
                    f'{API_URL}/attendance/staff',
                    json={'staffid': staffid, 'captured_at': captured_at},
                    headers={
                        'Content-Type': 'application/json',
                        'Authorization': getserial(),
                    },
                    timeout=10,
                )
                if response.status_code != 200 or not response.json().get('success'):
                    print(f'Attendance sync deferred for {staffid}: {response.status_code}')
                    continue
            except requests.RequestException as error:
                print(f'Attendance sync deferred: {error}')
                continue

            with sqlite3.connect(QUEUE_DB) as connection:
                connection.execute('DELETE FROM pending_attendance WHERE event_id = ?', (event_id,))
                connection.commit()
            print(f'Attendance synced for {staffid} at {captured_at}')


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
        url = f'{API_URL}/biometric/fetch/staff'

        response = requests.get(url, headers={'Authorization': getserial()}, timeout=10)

        # Check if the request was successful (status code 200)
        if response.status_code == 200:
            zip_buffer = BytesIO(response.content)
            with zipfile.ZipFile(zip_buffer, 'r') as zip_file:
                delete_directory(folder)
                os.makedirs(folder, exist_ok=True)
                zip_file.extractall(folder)
            return True

        else:
            print(f"Error: {response.status_code}")
    except Exception as e:
        print(e)
    print('Using existing local fingerprint templates')
    return False


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
            captured_at = current_local_time().strftime('%Y-%m-%d %H:%M:%S')
            threading.Thread(target=submit_attendance, args=(f, captured_at)).start()
            return True
        if i == adafruit_fingerprint.NOMATCH:
            pass
    return False


def reset_fingerprint_connection():
    global uart, finger
    try:
        finger.close_uart()
    except (AttributeError, OSError):
        pass
    time.sleep(1)
    uart = serial.Serial("/dev/ttyS0", baudrate=57600, timeout=1)
    finger = adafruit_fingerprint.Adafruit_Fingerprint(uart)

def submit_attendance(fingerprint, captured_at):
    staffid = fingerprint.split('.dat')[0]
    try:
        queue_attendance(staffid, captured_at)
        sync_pending_attendance()
    except (OSError, sqlite3.Error) as error:
        print(f'Unable to queue attendance for {staffid}: {error}')


def sync_loop():
    while True:
        try:
            sync_pending_attendance()
        except (OSError, sqlite3.Error) as error:
            print(f'Attendance queue sync error: {error}')
        time.sleep(60)

initialize_queue()
purge_old_attendance()
fetch_fingerprints()
sync_pending_attendance()
threading.Thread(target=sync_loop, daemon=True).start()
while True:
    try:
        find_fingerprint_match()
    except (RuntimeError, OSError) as error:
        print(f'Fingerprint sensor communication error: {error}')
        reset_fingerprint_connection()