import Foundation
import Vision
import AppKit
// 사용법: swift ocr.swift 이미지1.png 이미지2.png ...  → 인식한 글을 줄 단위로 출력(좌표 순)
for path in CommandLine.arguments.dropFirst() {
    guard let img = NSImage(contentsOfFile: path), let cg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else { print("[읽기 실패] \(path)"); continue }
    let req = VNRecognizeTextRequest()
    req.recognitionLevel = .accurate
    req.recognitionLanguages = ["ko-KR", "en-US"]
    req.usesLanguageCorrection = false
    try? VNImageRequestHandler(cgImage: cg, options: [:]).perform([req])
    let obs = (req.results ?? []).sorted { a, b in
        let ya = a.boundingBox.midY, yb = b.boundingBox.midY
        if abs(ya - yb) > 0.008 { return ya > yb }
        return a.boundingBox.minX < b.boundingBox.minX
    }
    print("=== \(path)")
    var lastY: CGFloat = -1; var line = ""
    for o in obs {
        guard let t = o.topCandidates(1).first?.string else { continue }
        let y = o.boundingBox.midY
        if lastY >= 0 && abs(y - lastY) > 0.008 { print(line); line = "" }
        line += (line.isEmpty ? "" : "\t") + t; lastY = y
    }
    if !line.isEmpty { print(line) }
}
