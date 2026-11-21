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
PROJECT = (IOS / "KidneyHealth.xcodeproj" / "project.pbxproj").read_text(encoding="utf-8")
SWIFT = {p.relative_to(IOS).as_posix(): p.read_text(encoding="utf-8") for p in sorted(IOS.rglob("*.swift")) if ".build" not in p.parts}
# The code without its comments, which may name what the app refuses.
CODE = {name: re.sub(r"//[^\n]*", "", text) for name, text in SWIFT.items()}
APP = {name: text for name, text in SWIFT.items() if name.startswith("KidneyHealth/")}

pytestmark = pytest.mark.safety


def test_the_entitlements_are_health_reading_and_background_delivery_only():
    entitlements = plistlib.loads((IOS / "KidneyHealth.entitlements").read_bytes())
    assert entitlements == {
        "com.apple.developer.healthkit": True,
        "com.apple.developer.healthkit.access": [],  # no clinical health records
        "com.apple.developer.healthkit.background-delivery": True,
    }


def test_the_app_explains_reading_and_never_asks_to_write():
    assert "INFOPLIST_KEY_NSHealthShareUsageDescription" in PROJECT
    # App Store Connect refuses a HealthKit app without the writing sentence, even one that never writes (the first TestFlight
    # upload, 2026-11-20), so the sentence is there and says the app never writes. What the app asks for is checked below.
    updates = re.findall(r'INFOPLIST_KEY_NSHealthUpdateUsageDescription = "([^"]*)";', PROJECT)
    assert len(updates) == 2 and all(u.startswith("The app never writes to Health.") for u in updates)
    for key in ("NSHealthClinicalHealthRecordsShareUsageDescription", "NSAllowsArbitraryLoads",
                "NSAppTransportSecurity", "UIBackgroundModes"):
        assert key not in PROJECT, key
    asks = re.findall(r"requestAuthorization\(toShare:\s*([^,]*),\s*read:\s*([^)]*)\)", "\n".join(APP.values()))
    assert asks == [("[]", "Self.readTypes")]


def test_the_read_types_come_from_the_package_list_of_three():
    core = SWIFT["KidneyHealthCore/Sources/KidneyHealthCore/Body.swift"]
    assert "public static let readTypes = [weightType, systolicType, diastolicType]" in core
    assert "Body.readTypes.map" in APP["KidneyHealth/HealthSource.swift"]


@pytest.mark.parametrize("word", ["glucose", "insulin", "medication", "dietary", "carbohydrate", "clinical", "HKWorkout",
                                  "HKCategoryType", "toShare: [HK", "HKClinicalType"])
def test_no_code_names_another_health_type(word):
    for name, text in CODE.items():
        if name.endswith("SafetyTests.swift"):
            continue  # the package's own guard lists the words it refuses
        assert word.lower() not in text.lower(), (name, word)


def test_no_third_party_packages_and_only_apple_frameworks():
    assert "XCRemoteSwiftPackageReference" not in PROJECT
    allowed = {"Foundation", "HealthKit", "Security", "SwiftUI", "UIKit", "WebKit", "XCTest", "PackageDescription",
               "KidneyHealthCore", "KidneyHealth"}
    for name, text in SWIFT.items():
        for module in re.findall(r"^(?:@testable )?import (\w+)", text, re.M):
            assert module in allowed, (name, module)
    package = (IOS / "KidneyHealthCore" / "Package.swift").read_text(encoding="utf-8")
    assert "dependencies: [" not in package.replace('dependencies: ["KidneyHealthCore"]', "")


def test_the_app_talks_only_https_and_follows_no_redirect():
    for name, text in APP.items():
        assert "http://" not in text, name
    transport = APP["KidneyHealth/URLSessionTransport.swift"]
    assert "completionHandler(nil)" in transport and "httpCookieStorage = nil" in transport and "urlCache = nil" in transport


def test_the_token_and_anchors_stay_on_this_device():
    keychain = APP["KidneyHealth/Keychain.swift"]
    assert "kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly" in keychain
    assert "kSecAttrSynchronizable" not in keychain
    model = APP["KidneyHealth/SyncModel.swift"]
    assert re.search(r"defaults\.set\([^)]*token", model) is None  # the token never goes to UserDefaults


def test_the_app_opens_only_its_pairing_links_and_asks_before_it_saves():
    from app import brand

    info = plistlib.loads((IOS / "KidneyHealth-Info.plist").read_bytes())
    assert info == {"ITSAppUsesNonExemptEncryption": False,  # only standard HTTPS, so no export questions in App Store Connect
                    "UIFileSharingEnabled": True, "LSSupportsOpeningDocumentsInPlace": True,  # the safety copy shows in Files
                    "CFBundleURLTypes": [{"CFBundleTypeRole": "Viewer", "CFBundleURLName": "io.github.ksullivan86.kidneyhealth.pair",
                                                              "CFBundleURLSchemes": [brand.PAIRING_SCHEME]}]}
    app_configs = [block for block in PROJECT.split("isa = XCBuildConfiguration;") if "PRODUCT_BUNDLE_IDENTIFIER = io.github.ksullivan86.kidneyhealth;" in block]
    assert len(app_configs) == 2 and all('INFOPLIST_FILE = "KidneyHealth-Info.plist";' in b for b in app_configs)
    assert len(re.findall(r"\sINFOPLIST_FILE =", PROJECT)) == 2  # the tests target has none
    pairing = SWIFT["KidneyHealthCore/Sources/KidneyHealthCore/Pairing.swift"]
    assert f'public static let scheme = "{brand.PAIRING_SCHEME}"' in pairing
    view = APP["KidneyHealth/ContentView.swift"]
    assert ".onOpenURL { url in" in view and "Pairing.parse(url.absoluteString)" in view
    # nothing is saved when the link arrives: only the alert's Pair button saves
    opened = view[view.index(".onOpenURL"):view.index(".alert(")]
    assert "model.save" not in opened
    alert = view[view.index(".alert("):]
    assert alert.index('Button("Pair")') < alert.index("model.save(address: link.server, token: link.token)")
    assert 'Button("Cancel", role: .cancel)' in alert and "model.pairingQuestion(link)" in alert


TEAM_ID = "579992SASJ"  # the owner's Apple Developer team (not a secret)
TESTFLIGHT = ROOT / ".github" / "workflows" / "testflight.yml"


def test_the_project_signs_for_the_owners_team_and_has_an_icon():
    assert PROJECT.count(f"DEVELOPMENT_TEAM = {TEAM_ID};") == 4 and 'DEVELOPMENT_TEAM = "";' not in PROJECT
    app_configs = [block for block in PROJECT.split("isa = XCBuildConfiguration;") if "PRODUCT_BUNDLE_IDENTIFIER = io.github.ksullivan86.kidneyhealth;" in block]
    assert all("ASSETCATALOG_COMPILER_APPICON_NAME = AppIcon;" in b for b in app_configs)
    iconset = IOS / "KidneyHealth" / "Assets.xcassets" / "AppIcon.appiconset"
    import json

    images = json.loads((iconset / "Contents.json").read_text(encoding="utf-8"))["images"]
    assert images == [{"filename": "AppIcon-1024.png", "idiom": "universal", "platform": "ios", "size": "1024x1024"}]
    png = (iconset / "AppIcon-1024.png").read_bytes()
    assert png[:8] == b"\x89PNG\r\n\x1a\n" and png[12:16] == b"IHDR"
    width, height = int.from_bytes(png[16:20], "big"), int.from_bytes(png[20:24], "big")
    assert (width, height) == (1024, 1024)
    assert png[24] == 8 and png[25] == 2  # 8-bit RGB: App Store Connect refuses an icon with an alpha channel


def test_testflight_runs_by_hand_from_main_with_the_key_only_where_it_is_used():
    text = TESTFLIGHT.read_text(encoding="utf-8")
    code = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))
    assert re.search(r"^on:\n  workflow_dispatch:\n\n", code, re.M)  # never on a push or a pull request
    assert "if: github.ref == 'refs/heads/main'" in code and "environment: release" in code
    assert f'TEAM_ID: "{TEAM_ID}"' in code
    # the key is read by the two steps that need it and nowhere else
    assert code.count("${{ secrets.") == 6 and set(re.findall(r"secrets\.(\w+)", code)) == {"ASC_KEY_ID", "ASC_ISSUER_ID", "ASC_KEY_P8"}
    job_env = code[code.index("    env:\n"):code.index("    steps:\n")]
    assert "secrets." not in job_env
    # the key file is private to the job and removed however the job ends
    assert "umask 077" in code and """trap 'rm -f "$key"' EXIT""" in code
    assert code.index("trap 'rm -f") < code.index('> "$key"')
    assert "-allowProvisioningUpdates" in code and "app-store-connect" in code and 'CURRENT_PROJECT_VERSION="$GITHUB_RUN_NUMBER"' in code


def test_the_app_is_named_like_the_project():
    """The owner's rule (2026-11-20): the iPhone app has the project's name, Kidney Health, on the Home Screen and its title bar."""
    from app import brand

    names = re.findall(r'INFOPLIST_KEY_CFBundleDisplayName = "([^"]*)";', PROJECT)
    assert names == [brand.NAME, brand.NAME]
    assert f'.navigationTitle("{brand.NAME}")' in APP["KidneyHealth/ContentView.swift"]


CHECK = IOS / "KidneyHealth" / "StorageCheck"


def test_the_storage_test_page_has_no_inline_script_and_no_network():
    """Design note 38, step 0: the page is served from the app under its own scheme, runs only its own file, and never reaches
    the network (CLAUDE.md: no network from the browser, no inline scripts)."""
    html = (CHECK / "storage-check.html").read_text(encoding="utf-8")
    assert re.findall(r"<script\b[^>]*>", html) == ['<script src="storage-check.js" defer>']
    assert re.search(r"\son\w+\s*=", html) is None  # no inline event handlers either
    js = (CHECK / "storage-check.js").read_text(encoding="utf-8")
    for word in ("fetch(", "XMLHttpRequest", "WebSocket", "sendBeacon", "EventSource", "innerHTML", "eval(", "import("):
        assert word not in js, word
    swift = APP["KidneyHealth/StorageCheck/LocalFiles.swift"]
    assert "connect-src 'none'" in swift and "unsafe-inline" not in swift
    assert set(re.findall(r'"(/[\w.-]+)":', swift)) == {"/storage-check.html", "/storage-check.js", "/storage-check.css"}
    view = APP["KidneyHealth/StorageCheck/StorageCheckView.swift"]
    assert ": .cancel" in view  # every navigation outside the listed files is cancelled
    assert "HealthKit" not in view and "Keychain" not in view  # the test keeps dates only

SHELL = IOS / "KidneyHealth" / "WebShell"


def test_the_web_shell_serves_only_its_packed_files_and_opens_nothing_else():
    """Design note 38, step 1: the packed web app in a web view, under the app's own scheme, with no network of its own."""
    files = APP["KidneyHealth/WebShell/WebAppFiles.swift"]
    assert '"..", ' not in files or '$0 != ".."' in files
    assert '$0 != ".."' in files and '!$0.hasPrefix(".")' in files and 'file.path.hasPrefix(base + "/")' in files
    assert "URLSession" not in files and "URLSession" not in APP["KidneyHealth/WebShell/WebAppView.swift"]
    view = APP["KidneyHealth/WebShell/WebAppView.swift"]
    # only the packed page may message the app; every other navigation is cancelled, and a tapped https link goes to Safari
    assert "message.frameInfo.securityOrigin.protocol == WebShellConfig.scheme" in view
    assert 'url.scheme == "https", action.navigationType == .linkActivated' in view and "UIApplication.shared.open(url)" in view
    assert view.count("decisionHandler(.cancel)") == 2 and "decisionHandler(.download)" in view
    assert "WKWebsiteDataStore(forIdentifier: WebShellConfig.storeID)" in view
    assert ".completeFileProtectionUntilFirstUserAuthentication" in view and ".atomic" in view
    # the shell is product-neutral: names live in WebShellConfig (a second app changes only that file)
    for name in ("WebAppFiles.swift", "WebAppView.swift"):
        assert "kidney" not in APP[f"KidneyHealth/WebShell/{name}"].lower(), name


def test_the_packed_web_app_is_built_before_every_xcode_build():
    assert "lastKnownFileType = folder; path = WebApp;" in PROJECT and "WebApp in Resources" in PROJECT
    assert "ios/WebApp/" in (ROOT / ".gitignore").read_text(encoding="utf-8")  # built, never committed
    for workflow in ("ci.yml", "testflight.yml"):
        text = (ROOT / ".github" / "workflows" / workflow).read_text(encoding="utf-8")
        assert text.index("python scripts/build_preview.py --device ios/WebApp") < text.index("xcodebuild -version"), workflow
