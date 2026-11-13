// Lists the on-screen windows of one app: id, layer, x, y, width, height, title (tab separated).
import CoreGraphics
import Foundation

let owner = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "JobRadar"
let list = CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID)
    as? [[String: Any]] ?? []
for w in list where (w[kCGWindowOwnerName as String] as? String) == owner {
    let id = w[kCGWindowNumber as String] as? Int ?? 0
    let layer = w[kCGWindowLayer as String] as? Int ?? 0
    let name = w[kCGWindowName as String] as? String ?? ""
    let b = w[kCGWindowBounds as String] as? [String: Any] ?? [:]
    func n(_ key: String) -> Int { Int((b[key] as? Double) ?? Double((b[key] as? Int) ?? 0)) }
    print("\(id)\t\(layer)\t\(n("X"))\t\(n("Y"))\t\(n("Width"))\t\(n("Height"))\t\(name)")
}
