// The native barcode scanner (owner, 2026-11-21: make the most-used parts native, starting with the barcode scanner).
//
// The page's Scan sheet (js/scan.js) asks for a scan ({ kind: "scanBarcode" } through the bridge). The app shows Apple's own scanner
// (VisionKit) for food barcodes only (EAN-13, EAN-8, UPC-E; a UPC-A code reads as EAN-13 with a leading 0, which the server's rules
// accept), and answers the first code it reads: { ok: true, code, format }, or { error: "cancelled" | "unavailable" }. Everything else,
// the look-up, the server's food rules and asking before anything is saved, stays in the page, so the rules live in one place.
import UIKit
import Vision
import VisionKit

@MainActor
final class BarcodeScanner: NSObject, DataScannerViewControllerDelegate {
    static let shared = BarcodeScanner()
    private var continuation: CheckedContinuation<[String: Any], Never>?
    private weak var scanner: DataScannerViewController?

    static var available: Bool { DataScannerViewController.isSupported && DataScannerViewController.isAvailable }

    /// The page's format names (js/engine/gtin.js FORMATS) for what Vision reports.
    static func format(_ symbology: VNBarcodeSymbology) -> String? {
        switch symbology {
        case .ean13: "ean_13"
        case .ean8: "ean_8"
        case .upce: "upc_e"
        default: nil
        }
    }

    func scan() async -> [String: Any] {
        guard Self.available else {
            return ["error": "unavailable", "message": "This iPhone cannot scan barcodes, or the camera is not allowed. Type the digits instead."]
        }
        guard continuation == nil, let top = Self.topController() else { return ["error": "busy", "message": "A scan is already open."] }
        let controller = DataScannerViewController(recognizedDataTypes: [.barcode(symbologies: [.ean13, .ean8, .upce])],
                                                   qualityLevel: .balanced, recognizesMultipleItems: false,
                                                   isHighFrameRateTrackingEnabled: true, isHighlightingEnabled: true)
        controller.delegate = self
        controller.navigationItem.rightBarButtonItem = UIBarButtonItem(systemItem: .cancel, primaryAction: UIAction { [weak self] _ in
            self?.finish(["error": "cancelled"])
        })
        let wrapper = UINavigationController(rootViewController: controller)
        wrapper.presentationController?.delegate = self
        scanner = controller
        return await withCheckedContinuation { (next: CheckedContinuation<[String: Any], Never>) in
            continuation = next
            top.present(wrapper, animated: true) { try? controller.startScanning() }
        }
    }

    nonisolated func dataScanner(_ dataScanner: DataScannerViewController, didAdd items: [RecognizedItem], allItems: [RecognizedItem]) {
        for item in items {
            guard case .barcode(let code) = item, let digits = code.payloadStringValue, let format = Self.format(code.observation.symbology),
                  digits.allSatisfy(\.isNumber) else { continue }
            Task { @MainActor in self.finish(["ok": true, "code": digits, "format": format]) }
            return
        }
    }

    private func finish(_ answer: [String: Any]) {
        guard let next = continuation else { return }
        continuation = nil
        scanner?.stopScanning()
        scanner?.navigationController?.dismiss(animated: true)
        next.resume(returning: answer)
    }

    static func topController() -> UIViewController? {
        guard let scene = UIApplication.shared.connectedScenes.compactMap({ $0 as? UIWindowScene }).first,
              var top = scene.keyWindow?.rootViewController else { return nil }
        while let next = top.presentedViewController { top = next }
        return top
    }
}

extension BarcodeScanner: UIAdaptivePresentationControllerDelegate {
    /// Swiping the scanner away is a cancel.
    nonisolated func presentationControllerDidDismiss(_ presentationController: UIPresentationController) {
        Task { @MainActor in self.finish(["error": "cancelled"]) }
    }
}
