// Reads and drives JobRadar through the accessibility interface (probe branch only).
//
//   ax windows                      titles and frames of the windows
//   ax dump                         the whole tree of every window
//   ax texts                        every text on screen, one per line
//   ax has TEXT                     exit 0 when a text contains TEXT
//   ax press ROLE LABEL             the accessibility "press" action (buttons, switches)
//   ax click ROLE LABEL             a real mouse click in the middle of the element
//   ax select LABEL                 selects the list row that shows LABEL
//   ax show ROLE LABEL              scrolls the element into view
//   ax scroll FRACTION [WINDOW]     vertical scroll bars of a window (0 to 1)
//   ax clickat X Y                  a real mouse click at screen coordinates
//   ax resize W H [WINDOW]          moves a window to the top left and gives it this size
// ROLE is an accessibility role (AXButton, AXCheckBox, AXStaticText, AXPopUpButton, AXMenuItem …) or "*".

import AppKit
import ApplicationServices

let bundleID = "com.berkselenay.JobRadar"

func fail(_ message: String) -> Never {
    FileHandle.standardError.write((message + "\n").data(using: .utf8)!)
    exit(2)
}

guard let running = NSRunningApplication.runningApplications(withBundleIdentifier: bundleID).first else {
    fail("JobRadar is not running")
}
let app = AXUIElementCreateApplication(running.processIdentifier)
AXUIElementSetMessagingTimeout(app, 6)

func attribute(_ e: AXUIElement, _ name: String) -> CFTypeRef? {
    var value: CFTypeRef?
    return AXUIElementCopyAttributeValue(e, name as CFString, &value) == .success ? value : nil
}

func text(_ e: AXUIElement, _ name: String) -> String {
    guard let v = attribute(e, name) else { return "" }
    if let s = v as? String { return s }
    if let n = v as? NSNumber { return n.stringValue }
    return ""
}

func kids(_ e: AXUIElement) -> [AXUIElement] {
    (attribute(e, "AXChildren") as? [AXUIElement]) ?? []
}

func frame(_ e: AXUIElement) -> CGRect? {
    guard let p = attribute(e, "AXPosition"), let s = attribute(e, "AXSize"),
          CFGetTypeID(p) == AXValueGetTypeID(), CFGetTypeID(s) == AXValueGetTypeID() else { return nil }
    var point = CGPoint.zero
    var size = CGSize.zero
    AXValueGetValue(p as! AXValue, .cgPoint, &point)
    AXValueGetValue(s as! AXValue, .cgSize, &size)
    return CGRect(origin: point, size: size)
}

func role(_ e: AXUIElement) -> String { text(e, "AXRole") }

/// Texts shown inside an element (a button's title is often a text below it).
func innerTexts(_ e: AXUIElement, depth: Int = 0) -> [String] {
    var out: [String] = []
    for child in kids(e) {
        if role(child) == "AXStaticText" {
            let v = text(child, "AXValue")
            if !v.isEmpty { out.append(v) }
        }
        if depth < 4 { out += innerTexts(child, depth: depth + 1) }
    }
    return out
}

func ownLabels(_ e: AXUIElement) -> [String] {
    [text(e, "AXTitle"), text(e, "AXDescription"), text(e, "AXValue"), text(e, "AXIdentifier")].filter { !$0.isEmpty }
}

let containerRoles: Set<String> = ["AXButton", "AXRow", "AXCell", "AXCheckBox", "AXPopUpButton", "AXMenuItem",
                                   "AXMenuButton", "AXRadioButton", "AXLink"]

func matches(_ e: AXUIElement, _ wantedRole: String, _ label: String) -> Bool {
    let r = role(e)
    if wantedRole != "*" && r != wantedRole { return false }
    if ownLabels(e).contains(label) { return true }
    if containerRoles.contains(r) && innerTexts(e).contains(label) { return true }
    return false
}

func windows() -> [AXUIElement] {
    (attribute(app, "AXWindows") as? [AXUIElement]) ?? []
}

/// Visits every element below `root`; the visitor returns false to stop.
@discardableResult
func walk(_ root: AXUIElement, depth: Int = 0, budget: inout Int, _ visit: (AXUIElement, Int) -> Bool) -> Bool {
    if budget <= 0 { return false }
    budget -= 1
    if !visit(root, depth) { return false }
    if depth > 70 { return true }
    for child in kids(root) {
        if !walk(child, depth: depth + 1, budget: &budget, visit) { return false }
    }
    return true
}

func find(_ wantedRole: String, _ label: String) -> AXUIElement? {
    var found: AXUIElement?
    for window in windows() {
        var budget = 20000
        walk(window, budget: &budget) { e, _ in
            if matches(e, wantedRole, label) {
                found = e
                return false
            }
            return true
        }
        if found != nil { break }
    }
    if found != nil { return found }
    // a control named by the text right before it (switches and pop-up buttons in a form)
    for window in windows() {
        var budget = 20000
        walk(window, budget: &budget) { e, _ in
            let children = kids(e)
            for (i, child) in children.enumerated() where i + 1 < children.count {
                if role(child) == "AXStaticText" && text(child, "AXValue") == label
                    && (wantedRole == "*" || role(children[i + 1]) == wantedRole) {
                    found = children[i + 1]
                    return false
                }
            }
            return true
        }
        if found != nil { break }
    }
    return found
}

func describe(_ e: AXUIElement) -> String {
    let r = role(e)
    let sub = text(e, "AXSubrole")
    var parts = ownLabels(e)
    if containerRoles.contains(r) { parts += innerTexts(e).prefix(4) }
    let shown = parts.map { $0.count > 140 ? String($0.prefix(140)) + "…" : $0 }.joined(separator: " ¦ ")
    var line = r + (sub.isEmpty ? "" : "[\(sub)]") + " \"" + shown.replacingOccurrences(of: "\n", with: "⏎") + "\""
    if let f = frame(e) {
        line += " (\(Int(f.minX)),\(Int(f.minY)) \(Int(f.width))x\(Int(f.height)))"
    }
    if let enabled = attribute(e, "AXEnabled") as? Bool, !enabled { line += " disabled" }
    return line
}

func activate() {
    running.activate(options: [.activateAllWindows])
    AXUIElementSetAttributeValue(app, "AXFrontmost" as CFString, kCFBooleanTrue)
    usleep(300_000)
}

func mouseClick(_ p: CGPoint) {
    let source = CGEventSource(stateID: .hidSystemState)
    let move = CGEvent(mouseEventSource: source, mouseType: .mouseMoved, mouseCursorPosition: p, mouseButton: .left)
    let down = CGEvent(mouseEventSource: source, mouseType: .leftMouseDown, mouseCursorPosition: p, mouseButton: .left)
    let up = CGEvent(mouseEventSource: source, mouseType: .leftMouseUp, mouseCursorPosition: p, mouseButton: .left)
    move?.post(tap: .cghidEventTap)
    usleep(120_000)
    down?.post(tap: .cghidEventTap)
    usleep(80_000)
    up?.post(tap: .cghidEventTap)
    usleep(200_000)
}

let args = Array(CommandLine.arguments.dropFirst())
guard let command = args.first else { fail("no command") }

switch command {
case "trusted":
    print(AXIsProcessTrusted() ? "trusted" : "NOT trusted")

case "windows":
    for w in windows() { print(describe(w)) }

case "dump":
    for w in windows() {
        var budget = 20000
        walk(w, budget: &budget) { e, depth in
            print(String(repeating: "  ", count: depth) + describe(e))
            return true
        }
    }

case "texts":
    for w in windows() {
        print("--- " + text(w, "AXTitle"))
        var budget = 20000
        walk(w, budget: &budget) { e, _ in
            if role(e) == "AXStaticText" {
                let v = text(e, "AXValue")
                if !v.isEmpty { print(v.replacingOccurrences(of: "\n", with: " ⏎ ")) }
            }
            return true
        }
    }

case "has":
    guard args.count > 1 else { fail("has TEXT") }
    var hit = ""
    for w in windows() {
        var budget = 20000
        walk(w, budget: &budget) { e, _ in
            if role(e) == "AXStaticText" {
                let v = text(e, "AXValue")
                if v.contains(args[1]) {
                    hit = v
                    return false
                }
            }
            return true
        }
        if !hit.isEmpty { break }
    }
    if hit.isEmpty {
        print("no")
        exit(1)
    }
    print("yes: " + hit.replacingOccurrences(of: "\n", with: " ⏎ "))

case "press", "click", "show":
    guard args.count > 2 else { fail("\(command) ROLE LABEL") }
    guard let e = find(args[1], args[2]) else {
        print("not found: \(args[1]) \(args[2])")
        exit(1)
    }
    print(describe(e))
    if command == "press" {
        let result = AXUIElementPerformAction(e, "AXPress" as CFString)
        print(result == .success ? "pressed" : "press failed: \(result.rawValue)")
        if result != .success { exit(1) }
    } else if command == "show" {
        let result = AXUIElementPerformAction(e, "AXScrollToVisible" as CFString)
        print(result == .success ? "shown" : "show failed: \(result.rawValue)")
    } else {
        guard let f = frame(e) else { fail("no frame") }
        activate()
        mouseClick(CGPoint(x: f.midX, y: f.midY))
        print("clicked at \(Int(f.midX)),\(Int(f.midY))")
    }

case "clickat":
    guard args.count > 2, let x = Double(args[1]), let y = Double(args[2]) else { fail("clickat X Y") }
    activate()
    mouseClick(CGPoint(x: x, y: y))
    print("clicked at \(Int(x)),\(Int(y))")

case "select":
    guard args.count > 1 else { fail("select LABEL") }
    guard let start = find("AXStaticText", args[1]) else {
        print("not found: \(args[1])")
        exit(1)
    }
    var current: AXUIElement? = start
    var row: AXUIElement?
    for _ in 0..<12 {
        guard let c = current else { break }
        if role(c) == "AXRow" {
            row = c
            break
        }
        current = attribute(c, "AXParent").map { $0 as! AXUIElement }
    }
    guard let row else {
        print("no row around: \(args[1])")
        exit(1)
    }
    let result = AXUIElementSetAttributeValue(row, "AXSelected" as CFString, kCFBooleanTrue)
    print(result == .success ? "selected \(describe(row))" : "select failed: \(result.rawValue)")
    if result != .success { exit(1) }

case "scroll":
    guard args.count > 1, let fraction = Double(args[1]) else { fail("scroll FRACTION [WINDOW]") }
    let wanted = args.count > 2 ? args[2] : ""
    var count = 0
    for w in windows() where wanted.isEmpty || text(w, "AXTitle").contains(wanted) {
        var budget = 20000
        walk(w, budget: &budget) { e, _ in
            if role(e) == "AXScrollBar" && text(e, "AXOrientation") == "AXVerticalOrientation" {
                if AXUIElementSetAttributeValue(e, "AXValue" as CFString, NSNumber(value: fraction)) == .success {
                    count += 1
                }
            }
            return true
        }
        break
    }
    print("scrolled \(count) bars")

case "resize":
    guard args.count > 2, let w = Double(args[1]), let h = Double(args[2]) else { fail("resize W H [WINDOW]") }
    let wantedTitle = args.count > 3 ? args[3] : ""
    for win in windows() where wantedTitle.isEmpty || text(win, "AXTitle").contains(wantedTitle) {
        var origin = CGPoint(x: 80, y: 60)
        if let p = AXValueCreate(.cgPoint, &origin) {
            AXUIElementSetAttributeValue(win, "AXPosition" as CFString, p)
        }
        var size = CGSize(width: w, height: h)
        if let v = AXValueCreate(.cgSize, &size) {
            let result = AXUIElementSetAttributeValue(win, "AXSize" as CFString, v)
            print(result == .success ? "resized to \(Int(w))x\(Int(h))" : "resize failed: \(result.rawValue)")
        }
        break
    }

default:
    fail("unknown command \(command)")
}
