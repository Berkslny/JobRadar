import SwiftUI

struct StatsView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        CardPage {
            if let s = model.summary {
                SectionBox(title: t("Engine"), systemImage: "server.rack") {
                    Grid(alignment: .leading, horizontalSpacing: 12, verticalSpacing: 6) {
                        row(t("Runs on"), model.config.mode == .local ? t("This Mac (started by the app)")
                                                                    : model.config.normalizedBaseURL)
                        row(t("State"), model.cycleRunning || s.running ? t("Scan running") : t("Idle"))
                        row(t("Last scan"), s.lastCycle.isEmpty ? t("none yet")
                                                                : "\(Dates.short(s.lastCycle)) (\(Dates.relative(s.lastCycle)))")
                        if !s.lastError.isEmpty { row(t("Last error"), s.lastError) }
                        if let q = s.lastQuickCycle, !q.isEmpty {
                            row(t("Last quick scan"), "\(Dates.short(q)) (\(Dates.relative(q)))")
                        }
                        if let m = s.lastMailSync, !m.isEmpty {
                            row(t("E-mail check"), t("%@, %@ replies to review", Dates.relative(m), s.mailSignalsPending ?? 0))
                        }
                        if let e = s.mailSyncError, !e.isEmpty { row(t("E-mail error"), e) }
                        row(t("AI model"), s.llm)
                        row(t("Waiting for evaluation"), "\(s.pendingEvaluation)")
                        row(t("Profile"), s.todoFacts > 0 ? t("%@, %@ TODO notes", s.profileName, s.todoFacts) : s.profileName)
                        row(t("Version"), s.version)
                    }
                    HStack {
                        Button {
                            Task { await model.runCycle() }
                        } label: {
                            Label(t("Scan now"), systemImage: "antenna.radiowaves.left.and.right")
                        }
                        .disabled(model.cycleRunning || s.running || model.sampleData)
                        Button {
                            Task { await model.backupIfNeeded(force: true) }
                        } label: {
                            Label(t("Back up now"), systemImage: "externaldrive.badge.plus")
                        }
                        .disabled(model.sampleData)
                        Button {
                            model.revealBackups()
                        } label: {
                            Label(t("Backups"), systemImage: "folder")
                        }
                    }
                    .buttonStyle(.glass).plainGlass()
                }
            }
            if let st = model.stats {
                SectionBox(title: t("Application funnel"), systemImage: "chart.bar") {
                    let maxCount = max(st.funnel.map(\.count).max() ?? 1, 1)
                    Grid(alignment: .leading, horizontalSpacing: 10, verticalSpacing: 6) {
                        ForEach(st.funnel) { f in
                            GridRow {
                                Text(f.label).frame(width: 130, alignment: .leading)
                                GeometryReader { geo in
                                    RoundedRectangle(cornerRadius: 4)
                                        .fill(Palette.status(f.status).gradient)
                                        .frame(width: max(2, geo.size.width * CGFloat(f.count) / CGFloat(maxCount)))
                                }
                                .frame(height: 12)
                                Text("\(f.count)").font(.callout.monospacedDigit())
                            }
                        }
                    }
                }
                SectionBox(title: t("Sources"), systemImage: "point.3.connected.trianglepath.dotted") {
                    Grid(alignment: .leading, horizontalSpacing: 14, verticalSpacing: 6) {
                        GridRow {
                            Text(t("Source")).bold()
                            Text(t("Jobs")).bold()
                            Text(t("Evaluated")).bold()
                            Text(t("Strong")).bold()
                            Text(t("Applied")).bold()
                            Text(t("Avg.")).bold()
                        }
                        .font(.caption)
                        Divider()
                        ForEach(st.sources) { src in
                            GridRow {
                                Text(src.source)
                                Text("\(src.jobs)")
                                Text("\(src.evaluated)")
                                Text("\(src.strong)")
                                Text("\(src.applied)")
                                Text(src.avgScore.map { String(format: "%.1f", $0) } ?? "·")
                            }
                            .font(.callout.monospacedDigit())
                        }
                    }
                }
                let problems = st.health.filter { ($0.error ?? "").isEmpty == false || ($0.consecutiveEmpty ?? 0) >= 3 }
                SectionBox(title: t("Source health"), systemImage: "stethoscope") {
                    if problems.isEmpty {
                        Label(t("Every source delivered results in the last run."), systemImage: "checkmark.circle")
                            .foregroundStyle(.green)
                    } else {
                        ForEach(problems) { h in
                            VStack(alignment: .leading, spacing: 2) {
                                Text(h.source).bold()
                                if let e = h.error, !e.isEmpty {
                                    Text(e).font(.caption).foregroundStyle(.red)
                                } else {
                                    Text(t("No results in the last %@ runs", h.consecutiveEmpty ?? 0)).font(.caption)
                                        .foregroundStyle(.orange)
                                }
                            }
                        }
                    }
                }
            } else {
                ProgressView().frame(maxWidth: .infinity)
            }
            if let g = model.gaps {
                GapsSection(gaps: g)
            }
        }
        .navigationTitle(t("Status and sources"))
        .task {
            await model.loadStats()
            await model.loadGaps()
        }
        .toolbar {
            Button {
                Task {
                    await model.refreshSummary()
                    await model.loadStats()
                    await model.loadGaps()
                }
            } label: {
                Label(t("Refresh"), systemImage: "arrow.clockwise")
            }
        }
    }

    private func row(_ name: String, _ value: String) -> some View {
        GridRow {
            Text(name).foregroundStyle(.secondary)
            Text(value).textSelection(.enabled)
        }
    }
}

/// Requirements that keep showing up as missing in evaluated jobs: what to learn next.
struct GapsSection: View {
    let gaps: GapsResponse

    var body: some View {
        SectionBox(title: t("Skill gaps"), systemImage: "graduationcap", tint: .orange) {
            Text(t("The requirements that are most often missing or only partly met in %@ jobs scored %@ or higher (last %@ days). Hover over a skill to see examples.",
                   gaps.jobsConsidered, String(format: "%.1f", gaps.minScore), gaps.days))
                .font(.caption)
                .foregroundStyle(.secondary)
            if gaps.terms.isEmpty {
                Text(t("No recurring gap was found.")).foregroundStyle(.secondary)
            } else {
                Grid(alignment: .leading, horizontalSpacing: 14, verticalSpacing: 6) {
                    GridRow {
                        Text(t("Skill")).bold()
                        Text(t("Jobs")).bold()
                        Text(t("Missing")).bold()
                        Text(t("Partly")).bold()
                        Text(t("Required")).bold()
                    }
                    .font(.caption)
                    Divider()
                    ForEach(gaps.terms) { term in
                        GridRow {
                            Text(term.term)
                                .help(term.examples.map { "\($0.title) · \($0.company): \($0.text)" }.joined(separator: "\n"))
                            Text("\(term.jobs)")
                            Text("\(term.gap)")
                            Text("\(term.partial)")
                            Text("\(term.must)")
                        }
                        .font(.callout.monospacedDigit())
                    }
                }
            }
            if !gaps.other.isEmpty {
                DisclosureGroup(t("Repeated gaps that are not technical terms")) {
                    BulletList(items: gaps.other.map { t("%@ (%@ jobs)", $0.text, $0.jobs) }, color: .secondary)
                }
                .font(.caption)
            }
        }
    }
}
