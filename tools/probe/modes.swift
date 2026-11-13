// Lists the modes of the main display; with "set W H" switches to the first mode of that size.
import CoreGraphics
import Foundation

let display = CGMainDisplayID()
let options = [kCGDisplayShowDuplicateLowResolutionModes: kCFBooleanTrue] as CFDictionary
let modes = (CGDisplayCopyAllDisplayModes(display, options) as? [CGDisplayMode]) ?? []
let args = CommandLine.arguments
if args.count >= 4, args[1] == "set", let w = Int(args[2]), let h = Int(args[3]) {
    guard let mode = modes.first(where: { $0.width == w && $0.height == h }) else {
        print("no mode \(w)x\(h)")
        exit(1)
    }
    var config: CGDisplayConfigRef?
    CGBeginDisplayConfiguration(&config)
    CGConfigureDisplayWithDisplayMode(config, display, mode, nil)
    let result = CGCompleteDisplayConfiguration(config, .forSession)
    print("set \(w)x\(h): \(result == .success ? "ok" : "error \(result.rawValue)")")
    exit(result == .success ? 0 : 1)
}
var seen = Set<String>()
for m in modes {
    let line = "\(m.width)x\(m.height) pixels \(m.pixelWidth)x\(m.pixelHeight)"
    if seen.insert(line).inserted { print(line) }
}
if let current = CGDisplayCopyDisplayMode(display) {
    print("current \(current.width)x\(current.height) pixels \(current.pixelWidth)x\(current.pixelHeight)")
}
