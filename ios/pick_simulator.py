"""Prints the UDID of an available iPhone simulator on the newest iOS runtime, from `xcrun simctl list devices available -j` on stdin.
Used by the ios-app job in .github/workflows/ci.yml, because the device names change with each Xcode."""
import json
import re
import sys


def runtime_version(key: str) -> tuple[int, ...]:
    match = re.search(r"iOS-(\d+)-(\d+)(?:-(\d+))?$", key)
    return tuple(int(part or 0) for part in match.groups()) if match else ()


devices = json.load(sys.stdin)["devices"]
for key in sorted((k for k in devices if runtime_version(k)), key=runtime_version, reverse=True):
    for device in devices[key]:
        if device.get("isAvailable", True) and device["name"].startswith("iPhone"):
            print(device["udid"])
            sys.exit(0)
sys.exit("no available iPhone simulator")
