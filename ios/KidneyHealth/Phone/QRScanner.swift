// Scan the pairing QR code from inside the app (owner, 2026-11-21: "what good is a QR code if the app has no way to scan the code?").
// Apple's own scanner (VisionKit's DataScannerViewController) reads QR codes only; the first code read is handed back and the scanner
// closes. Nothing is saved here: the settings screen asks "Pair with …?" first, as it does for a code the Camera app opened.
import SwiftUI
import VisionKit

struct QRScanner: UIViewControllerRepresentable {
    let onCode: (String) -> Void

    /// The phone has a camera the scanner can use, and the person allowed it (or has not been asked yet).
    static var available: Bool {
        DataScannerViewController.isSupported && DataScannerViewController.isAvailable
    }

    func makeCoordinator() -> Coordinator { Coordinator(onCode: onCode) }

    func makeUIViewController(context: Context) -> DataScannerViewController {
        let scanner = DataScannerViewController(recognizedDataTypes: [.barcode(symbologies: [.qr])], qualityLevel: .balanced,
                                                recognizesMultipleItems: false, isHighFrameRateTrackingEnabled: false,
                                                isHighlightingEnabled: true)
        scanner.delegate = context.coordinator
        try? scanner.startScanning()
        return scanner
    }

    func updateUIViewController(_ scanner: DataScannerViewController, context: Context) {}

    static func dismantleUIViewController(_ scanner: DataScannerViewController, coordinator: Coordinator) {
        scanner.stopScanning()
    }

    final class Coordinator: NSObject, DataScannerViewControllerDelegate {
        let onCode: (String) -> Void
        private var done = false

        init(onCode: @escaping (String) -> Void) { self.onCode = onCode }

        func dataScanner(_ scanner: DataScannerViewController, didAdd items: [RecognizedItem], allItems: [RecognizedItem]) {
            guard !done else { return }
            for item in items {
                if case .barcode(let code) = item, let text = code.payloadStringValue {
                    done = true
                    scanner.stopScanning()
                    onCode(text)
                    return
                }
            }
        }
    }
}
