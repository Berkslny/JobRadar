import AppKit
import WebKit

/// Turns an HTML file into an A4 PDF with the system's WebKit, without showing anything.
/// The engine starts this app's executable with `--html-to-pdf in.html out.pdf` when no
/// Chrome-family browser is installed for making the CV and letter PDFs.
enum PDFHelper {
    private static var delegate: PDFHelperDelegate? = nil

    static func run(html: String, pdf: String) -> Never {
        let app = NSApplication.shared
        app.setActivationPolicy(.accessory)   // no Dock icon, no menu bar
        let worker = PDFHelperDelegate(html: URL(fileURLWithPath: html), pdf: URL(fileURLWithPath: pdf))
        delegate = worker
        app.delegate = worker
        app.run()
        exit(0)
    }
}

final class PDFHelperDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate {
    /// A4 in points.
    private static let paper = NSSize(width: 595.28, height: 841.89)
    private let html: URL
    private let pdf: URL
    private var window: NSWindow? = nil
    private var webView: WKWebView? = nil
    private var printing = false

    init(html: URL, pdf: URL) {
        self.html = html
        self.pdf = pdf
        super.init()
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        guard FileManager.default.isReadableFile(atPath: html.path) else { exit(2) }
        let frame = NSRect(origin: .zero, size: Self.paper)
        let web = WKWebView(frame: frame)
        web.navigationDelegate = self
        // the window is never shown; printing needs one to attach to
        let holder = NSWindow(contentRect: frame, styleMask: [.borderless], backing: .buffered, defer: false)
        holder.isReleasedWhenClosed = false
        holder.contentView = web
        window = holder
        webView = web
        web.loadFileURL(html, allowingReadAccessTo: html.deletingLastPathComponent())
        // never hang: the engine waits for this process
        DispatchQueue.main.asyncAfter(deadline: .now() + 60) { exit(3) }
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        // page margins come from the print settings below, so the result does not depend on how
        // this WebKit version reads the CSS @page rule
        let script = "var s=document.createElement('style');s.textContent='@page{margin:0}';document.head.appendChild(s);true"
        webView.evaluateJavaScript(script) { [weak self] _, _ in
            Task { @MainActor in
                try? await Task.sleep(for: .milliseconds(400))
                self?.printPDF()
            }
        }
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        exit(2)
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        exit(2)
    }

    private func printPDF() {
        guard !printing, let web = webView, let window else { return }
        printing = true
        let info = NSPrintInfo()
        info.paperSize = Self.paper
        info.orientation = .portrait
        info.topMargin = 45.4      // 16 mm, like the browser-made PDFs
        info.bottomMargin = 45.4
        info.leftMargin = 0        // the page centres its own 176 mm column
        info.rightMargin = 0
        info.horizontalPagination = .fit
        info.verticalPagination = .automatic
        info.isHorizontallyCentered = false
        info.isVerticallyCentered = false
        info.jobDisposition = .save
        info.dictionary().setObject(pdf as NSURL, forKey: NSPrintInfo.AttributeKey.jobSavingURL.rawValue as NSString)
        let operation = web.printOperation(with: info)
        operation.showsPrintPanel = false
        operation.showsProgressPanel = false
        operation.view?.frame = NSRect(origin: .zero, size: Self.paper)
        operation.runModal(for: window, delegate: self,
                           didRun: #selector(printDone(_:success:contextInfo:)), contextInfo: nil)
    }

    @objc private func printDone(_ operation: NSPrintOperation, success: Bool, contextInfo: UnsafeMutableRawPointer?) {
        exit(success ? 0 : 4)
    }
}
