# The iOS app

A small iPhone app is planned that sends new weights and blood pressure readings from Apple Health to your own server
([design note 15](../docs/dev/research/15-native-ios-app.md)). The web app stays the place for every screen.

What is here so far:

* `KidneyHealthCore/`: a Swift package with the rules the app must share with the server. They cover the plausible ranges, the time of
  day a reading gets, the watch rule, kilogram rounding, the key that stops a reading being added twice, and requests of at most 50 rows.
  It checks each row the way `POST /push/v1/body` does before the app sends it, because one refused row makes the whole request fail.
  It has no dependencies and no HealthKit code.

The app itself comes next.

## Running the tests

You need Swift 6.4 on Linux or a Mac. From the repository root:

```bash
swift test --package-path ios/KidneyHealthCore
```

The tests replay `tests/data/body_vectors.json`, `apple_health_vectors.json` and `push_vectors.json`, which hold the server's own answers.
If a replay fails, fix the Swift code, not the vectors. When the server's rules change, regenerate the vectors first
(`python3 tests/data/gen_push_vectors.py` and the others in [`tests/data/README.md`](../tests/data/README.md)).

## Rules for this folder

* No third-party packages.
* The app reads weight and the two blood pressure numbers from Health, and nothing else. It never reads glucose, insulin or medicines,
  and it never writes to Health. `SafetyTests.swift` checks the list.
* No analytics, and no network but the person's own server.
