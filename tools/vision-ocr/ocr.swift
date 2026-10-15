import Foundation
import Vision
import AppKit

// Usage: ocr <image>...  -> one JSON object per image on stdout
let correction = ProcessInfo.processInfo.environment["VISION_CORRECTION"] == "1"
for path in CommandLine.arguments.dropFirst() {
    guard let image = NSImage(contentsOfFile: path),
          let cg = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
        FileHandle.standardError.write("cannot read \(path)\n".data(using: .utf8)!)
        continue
    }
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.recognitionLanguages = ["zh-Hans", "en-US"]
    request.usesLanguageCorrection = correction
    try VNImageRequestHandler(cgImage: cg, options: [:]).perform([request])
    var rows: [[String: Any]] = []
    for observation in request.results ?? [] {
        guard let top = observation.topCandidates(1).first else { continue }
        let b = observation.boundingBox  // normalized, origin bottom-left
        rows.append([
            "text": top.string, "confidence": top.confidence,
            "x1": b.minX, "y1": 1 - b.maxY, "x2": b.maxX, "y2": 1 - b.minY,
        ])
    }
    let data = try JSONSerialization.data(withJSONObject: ["path": path, "rows": rows])
    print(String(data: data, encoding: .utf8)!)
}
