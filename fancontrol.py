#!/usr/bin/env python
# -*- coding: utf8 -*-

import os
import sys
import time
import glob
import argparse
import stat
import os.path

from io import BytesIO
from subprocess import check_output, Popen, PIPE, STDOUT, CalledProcessError

devices_to_check = ['/dev/sg*', '/dev/ses*', '/dev/bsg/*', '/dev/es/ses*']

sg_ses_binary = "sg_ses"

if "sg_ses_path" in os.environ:
    sg_ses_binary = os.getenv("sg_ses_path")


def print_speeds(device, verbose=False):
    print('Device {}:'.format(device))

    fan_speeds = []
    for i in range(0, 6):
        fan_speed = check_output(
            [sg_ses_binary, '--maxlen=32768', '--index=coo,{}'.format(i), '--get=1:2:11', device]
        ).decode('utf-8').split('\n')[0]
        fan_speeds.append(int(fan_speed) if fan_speed.isdigit() else 0)
        print('    Fan {} speed: {}'.format(i, fan_speed))

    active_fan_speeds = [speed for speed in fan_speeds if speed > 0]
    if active_fan_speeds:
        average_speed = int(sum(active_fan_speeds) / len(active_fan_speeds))
        fan_speed_levels = [550, 925, 1100, 1250, 1400, 1575, 1700]
        for level, rpm in enumerate(fan_speed_levels, start=1):
            if average_speed - 50 <= rpm <= average_speed + 50:
                print('    Average Fan Speed: {} RPM (Level {})'.format(average_speed, level))
                break
        else:
            print('    Average Fan Speed: {} RPM (Could not determine level)'.format(average_speed))
    print('\n')


def find_sa120_devices(verbose=False):
    devices = []
    seen_devices = set()
    for device_glob in devices_to_check:
        for device in glob.glob(device_glob):
            try:
                stats = os.stat(device)
            except OSError:
                continue
            if not stat.S_ISCHR(stats.st_mode):
                print('Enclosure not found on ' + device)
                continue
            device_id = format_device_id(stats)
            if device_id in seen_devices:
                print('Enclosure already seen on ' + device)
                continue
            seen_devices.add(device_id)
            try:
                output = check_output([sg_ses_binary, '--maxlen=32768', device], stderr=STDOUT)
                if b'ThinkServerSA120' in output:
                    devices.append(device)
                    if verbose:
                        print('Enclosure found on ' + device)
                else:
                    print('Enclosure not found on ' + device)
            except CalledProcessError:
                print('Enclosure not found on ' + device)
    return devices


def format_device_id(stats):
    return '{},{}'.format(os.major(stats.st_rdev), os.minor(stats.st_rdev))


def set_fan_speeds(device, speed, verbose=False):
    out = check_output(['sg_ses', '--maxlen=32768', '-p', '0x2', device, '--raw'])

    s = out.split()

    print('Device {}:'.format(device))
    for i in range(0, 6):
        print('Setting fan {} to {}'.format(i, speed))
        idx = 88 + 4 * i
        s[idx + 0] = b'80'
        s[idx + 1] = b'00'
        s[idx + 2] = b'00'
        s[idx + 3] = u'{:x}'.format(1 << 5 | speed & 7).encode('utf-8')

    output = BytesIO()
    off = 0
    count = 0

    while True:
        output.write(s[off])
        off = off + 1
        count = count + 1
        if count == 8:
            output.write(b'  ')
        elif count == 16:
            output.write(b'\n')
            count = 0
        else:
            output.write(b' ')
        if off >= len(s):
            break

    output.write(b'\n')
    p = Popen(['sg_ses', '--maxlen=32768', '-p', '0x2', device, '--control', '--data', '-'],
              stdout=PIPE, stdin=PIPE, stderr=PIPE)
    if verbose:
        print(p.communicate(input=output.getvalue())[0].decode('utf-8'))
    else:
        p.communicate(input=output.getvalue())[0].decode('utf-8')


def main():
    parser = argparse.ArgumentParser(description='Fan speed control for enclosure devices')
    parser.add_argument('-v', '--verbose', action='store_true', help='Increase verbosity')
    parser.add_argument('-c', '--check', action='store_true', help='Report current fan speeds')
    parser.add_argument('-s', '--speed', type=int, choices=range(1, 8), help='Set fan speed (1-7)')
    parser.add_argument('-d', '--device', type=ascii, help='Only send commands to <device>')
    args = parser.parse_args()

    devices = find_sa120_devices()
    if not devices:
        print('Could not find enclosure')
        sys.exit(1)

    if args.check:
        for device in devices:
            print_speeds(device, args.verbose)
    elif args.speed:
        for device in devices:
            set_fan_speeds(device, args.speed, args.verbose)
        if args.verbose:
            print('Waiting for fans to stabilize...')
            time.sleep(10)
            for device in devices:
                print_speeds(device)
    else:
        parser.print_help(sys.stderr)

if __name__ == '__main__':
    main()
