"""The iOS app reads weight and blood pressure, and nothing else (design note 15 §4.2 and §5; CLAUDE.md: no insulin or medicine data).

The app is built and tested on a macOS runner (the ios-app job in .github/workflows/ci.yml). These checks read its files as text, so
they run with every pytest, on any machine: what it may read from Health, that it never asks to write, its entitlements, that it has
no third-party packages, and that it talks only HTTPS to the person's own server.
"""
from __future__ import annotations

import plistlib
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
IOS = ROOT / "ios"
PROJECT = (IOS / "KidneyHealthSync.xcodeproj" / "project.pbxproj").read_text(encoding="utf-8")
SWIFT = {p.relative_to(IOS).as_posix(): p.read_text(encoding="utf-8") for p in sorted(IOS.rglob("*.swift")) if ".build" not in p.parts}
# The code without its comments, which may name what the app refuses.
CODE = {name: re.sub(r"//[^\n]*", "", text) for name, text in SWIFT.items()}
APP = {name: text for name, text in SWIFT.items() if name.startswith("KidneyHealthSync/")}

pytestmark = pytest.mark.safety


def test_the_entitlements_are_health_reading_and_background_delivery_only():
    entitlements = plistlib.loads((IOS / "KidneyHealthSync.entitlements").read_bytes())
    assert entitlements == {
        "com.apple.developer.healthkit": True,
        "com.apple.developer.healthkit.access": [],  # no clinical health records
        "com.apple.developer.healthkit.background-delivery": True,
    }


def test_the_app_explains_reading_and_never_asks_to_write():
    assert "INFOPLIST_KEY_NSHealthShareUsageDescription" in PROJECT
    for key in ("NSHealthUpdateUsageDescription", "NSHealthClinicalHealthRecordsShareUsageDescription", "NSAllowsArbitraryLoads",
                "NSAppTransportSecurity", "UIBackgroundModes"):
        assert key not in PROJECT, key
    asks = re.findall(r"requestAuthorization\(toShare:\s*([^,]*),\s*read:\s*([^)]*)\)", "\n".join(APP.values()))
    assert asks == [("[]", "Self.readTypes")]


def test_the_read_types_come_from_the_package_list_of_three():
    core = SWIFT["KidneyHealthCore/Sources/KidneyHealthCore/Body.swift"]
    assert "public static let readTypes = [weightType, systolicType, diastolicType]" in core
    assert "Body.readTypes.map" in APP["KidneyHealthSync/HealthSource.swift"]


@pytest.mark.parametrize("word", ["glucose", "insulin", "medication", "dietary", "carbohydrate", "clinical", "HKWorkout",
                                  "HKCategoryType", "toShare: [HK", "HKClinicalType"])
def test_no_code_names_another_health_type(word):
    for name, text in CODE.items():
        if name.endswith("SafetyTests.swift"):
            continue  # the package's own guard lists the words it refuses
        assert word.lower() not in text.lower(), (name, word)


def test_no_third_party_packages_and_only_apple_frameworks():
    assert "XCRemoteSwiftPackageReference" not in PROJECT
    allowed = {"Foundation", "HealthKit", "Security", "SwiftUI", "UIKit", "XCTest", "PackageDescription", "KidneyHealthCore",
               "KidneyHealthSync"}
    for name, text in SWIFT.items():
        for module in re.findall(r"^(?:@testable )?import (\w+)", text, re.M):
            assert module in allowed, (name, module)
    package = (IOS / "KidneyHealthCore" / "Package.swift").read_text(encoding="utf-8")
    assert "dependencies: [" not in package.replace('dependencies: ["KidneyHealthCore"]', "")


def test_the_app_talks_only_https_and_follows_no_redirect():
    for name, text in APP.items():
        assert "http://" not in text, name
    transport = APP["KidneyHealthSync/URLSessionTransport.swift"]
    assert "completionHandler(nil)" in transport and "httpCookieStorage = nil" in transport and "urlCache = nil" in transport


def test_the_token_and_anchors_stay_on_this_device():
    keychain = APP["KidneyHealthSync/Keychain.swift"]
    assert "kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly" in keychain
    assert "kSecAttrSynchronizable" not in keychain
    model = APP["KidneyHealthSync/SyncModel.swift"]
    assert re.search(r"defaults\.set\([^)]*token", model) is None  # the token never goes to UserDefaults
