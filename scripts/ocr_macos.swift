import Foundation
import ImageIO
import Vision

func fail(_ message: String) -> Never {
    FileHandle.standardError.write((message + "\n").data(using: .utf8)!)
    exit(1)
}

guard CommandLine.arguments.count == 2 else {
    fail("Usage: swift scripts/ocr_macos.swift <image-path>")
}

let imagePath = CommandLine.arguments[1]
let imageURL = URL(fileURLWithPath: imagePath) as CFURL

guard let source = CGImageSourceCreateWithURL(imageURL, nil) else {
    fail("Could not load image: \(imagePath)")
}

guard let cgImage = CGImageSourceCreateImageAtIndex(source, 0, nil) else {
    fail("Could not decode image: \(imagePath)")
}

let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.usesLanguageCorrection = true

if let supportedLanguages = try? request.supportedRecognitionLanguages() {
    let preferredLanguages = ["ja-JP", "en-US"].filter { supportedLanguages.contains($0) }
    if !preferredLanguages.isEmpty {
        request.recognitionLanguages = preferredLanguages
    }
}

let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])

do {
    try handler.perform([request])
} catch {
    fail("OCR failed: \(error.localizedDescription)")
}

let lines = (request.results ?? [])
    .compactMap { $0.topCandidates(1).first?.string.trimmingCharacters(in: .whitespacesAndNewlines) }
    .filter { !$0.isEmpty }

print(lines.joined(separator: "\n"))
