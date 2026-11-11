"""Skill gaps across evaluated jobs: which requirements keep showing up as missing.

Reads the latest evaluation of every job (requirements marked "gap" or "partial", plus the
free-text gaps list), pulls out technical terms (VHDL, UVM, DO-254, Ü2, C++...) and counts
in how many jobs each one is missing. Answers "what should I learn next" with numbers."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from jobradar.i18n import t
from jobradar.processing.normalize import clean_title
from jobradar.textutil import fold_umlauts

KNOWN = {
    "python", "matlab", "simulink", "linux", "git", "jenkins", "docker", "kubernetes", "yocto", "rust", "java",
    "labview", "altium", "cadence", "modelsim", "questa", "questasim", "vivado", "quartus", "libero", "fpga", "asic",
    "vhdl", "verilog", "systemverilog", "uvm", "osvvm", "uvvm", "cocotb", "radar", "dsp", "sdr", "ethernet", "pcie",
    "axi", "spi", "uart", "rtos", "freertos", "autosar", "misra", "zynq", "versal", "petalinux", "embedded",
    "tcl", "perl", "bash", "scrum", "jira", "confluence", "doors", "polarion", "simulation", "synthese", "synthesis",
    "timing", "sta", "cdc", "hls", "opencl", "cuda", "jesd204", "serdes", "ddr", "lvds", "mipi", "hdmi", "can",
    "rf", "hf", "microwave", "antennen", "antenna", "elektronik", "electronics", "hardware", "schaltplan",
    "leiterplatte", "pcb", "emv", "emc", "sicherheitsüberprüfung", "clearance", "geheimschutz", "nato",
    "xilinx", "altera", "lattice", "microchip", "microsemi", "kintex", "virtex", "artix", "spartan", "cyclone",
    "arria", "stratix", "agilex", "ultrascale", "ultrascale+",
}
STEMS = {"mikrocontroller": "Mikrocontroller", "microcontroller": "Mikrocontroller"}
CLEARANCE_TOKEN = re.compile(r"^(?:s?ue?[23]|sueg|vs-?nfd|geheimschutz|sicherheitsueberpruefung\w*|clearance|nato"
                             r"|secret|geheim|confidential|vertraulich|top)$")
DISPLAY = {
    "python": "Python", "matlab": "MATLAB", "simulink": "Simulink", "linux": "Linux", "git": "Git", "vhdl": "VHDL",
    "verilog": "Verilog", "systemverilog": "SystemVerilog", "uvm": "UVM", "cocotb": "cocotb", "vivado": "Vivado",
    "quartus": "Quartus", "modelsim": "ModelSim", "questa": "Questa", "questasim": "QuestaSim", "fpga": "FPGA",
    "asic": "ASIC", "radar": "Radar", "dsp": "DSP", "pcie": "PCIe", "axi": "AXI", "rtos": "RTOS", "zynq": "Zynq",
    "petalinux": "PetaLinux", "tcl": "Tcl", "c++": "C++", "c#": "C#", "embedded": "Embedded", "hls": "HLS",
    "docker": "Docker", "jenkins": "Jenkins", "labview": "LabVIEW", "altium": "Altium", "doors": "DOORS",
    "synthese": "Synthese", "synthesis": "Synthesis", "rf": "RF", "hf": "HF", "emv": "EMV", "emc": "EMC", "pcb": "PCB",
}
DROP = {"it", "eu", "de", "en", "uk", "us", "ok", "cv", "hr", "mwd", "gmbh", "ag", "todo", "ba", "ma", "bsc", "msc",
        "phd", "dr", "z.b", "bzw", "ca", "inkl", "etc", "ggf", "u.a", "i.e", "e.g", "vs", "ue", "oe"}
CLEARANCE = re.compile(fold_umlauts(r"sicherheitsüberprüf|security clearance|\bclearance\b|\bs?ü ?[23]\b|\bsü[23]\b"
                                    r"|geheimschutz|vs-nfd|güvenlik soruşturma"), re.IGNORECASE)
GERMAN = re.compile(fold_umlauts(r"\b(?:deutsch\w*|german|almanca)\b"), re.IGNORECASE)
ENGLISH = re.compile(r"\b(?:englisch\w*|english|ingilizce)\b", re.IGNORECASE)
LEVEL = re.compile(r"\b([ABC][12])\b")
FLUENT = re.compile(fold_umlauts(r"verhandlungssicher|fließend|fluent|muttersprach|native|sehr gut|akıcı"),
                    re.IGNORECASE)
TOKEN = re.compile(r"[A-Za-zÄÖÜäöüßİıŞşĞğÇç][A-Za-z0-9ÄÖÜäöüßİıŞşĞğÇç+#.\-]*[A-Za-z0-9+#]|[A-Za-z][+#]{1,2}|\b[A-Z]\b")


def _language_terms(text: str) -> list[tuple[str, str]]:
    out = []
    folded = fold_umlauts(text)
    for rx, code, name in ((GERMAN, "de", t("Almanca")), (ENGLISH, "en", t("İngilizce"))):
        if rx.search(folded):
            m = LEVEL.search(text)
            if m:
                out.append((f"lang:{code}:{m.group(1).lower()}", f"{name} {m.group(1)}"))
            elif FLUENT.search(folded):
                out.append((f"lang:{code}:fluent", t("{name} (akıcı)", name=name)))
            else:
                out.append((f"lang:{code}", name))
    return out


def terms(text: str) -> dict[str, str]:
    """Normalised key → display form for the technical terms in one requirement."""
    out: dict[str, str] = {}
    if not text:
        return out
    if CLEARANCE.search(fold_umlauts(text)):
        out["clearance"] = t("Güvenlik soruşturması (Ü2/Ü3)")
    for lang_key, lang in _language_terms(text):
        out[lang_key] = lang
    for raw in TOKEN.findall(text.replace("/", " ").replace(",", " ")):
        tok = raw.strip(".-")
        if not tok:
            continue
        low = fold_umlauts(tok.lower())
        if low in DROP or LEVEL.fullmatch(tok):
            continue
        if GERMAN.fullmatch(fold_umlauts(tok)) or ENGLISH.fullmatch(tok):
            continue
        if "clearance" in out and CLEARANCE_TOKEN.match(low):
            continue
        stem = next((v for k, v in STEMS.items() if low.startswith(k)), None)
        if stem:
            out.setdefault(stem.lower(), stem)
            continue
        keep = (
            low in KNOWN
            or "+" in tok or "#" in tok
            or (re.search(r"\d", tok) and re.search(r"[A-Za-z]", tok) and len(tok) >= 2)
            or (tok.isupper() and len(tok) >= 2)
            or re.search(r"[a-z][A-Z]", tok)
            or (len(tok) == 1 and tok in "CR")
        )
        if not keep:
            continue
        key = low.replace("-", "")
        out.setdefault(key, DISPLAY.get(low, tok))
    return out


def _since(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")


def skill_gaps(conn: sqlite3.Connection, *, min_score: float = 3.0, days: int = 120, limit: int = 25) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT e.job_id, e.score, e.result_json, j.title, j.company, j.status FROM evaluations e
        JOIN (SELECT job_id, MAX(id) AS mid FROM evaluations WHERE created_at >= ? GROUP BY job_id) m ON e.id = m.mid
        JOIN jobs j ON j.id = e.job_id
        WHERE j.status != 'filtered' AND COALESCE(e.score, 0) >= ?
        """,
        (_since(days), min_score),
    ).fetchall()
    stats: dict[str, dict[str, Any]] = {}
    other: dict[str, dict[str, Any]] = {}
    for r in rows:
        try:
            res = json.loads(r["result_json"] or "{}")
        except json.JSONDecodeError:
            continue
        seen: dict[str, dict[str, Any]] = {}
        texts: list[tuple[str, str, str]] = []
        for req in res.get("requirements") or []:
            if not isinstance(req, dict) or req.get("match") not in ("gap", "partial"):
                continue
            texts.append((str(req.get("requirement") or ""), req.get("match", "gap"), req.get("importance", "must")))
        for g in res.get("gaps") or []:
            if isinstance(g, str):
                texts.append((g, "gap", "must"))
        for text, match, importance in texts:
            found = terms(text)
            if not found:
                if match == "gap" and text.strip():
                    key = " ".join(fold_umlauts(text.lower()).split())[:90]
                    o = other.setdefault(key, {"text": text.strip()[:200], "jobs": set()})
                    o["jobs"].add(r["job_id"])
                continue
            for key, display in found.items():
                s = seen.setdefault(key, {"display": display, "gap": False, "partial": False, "must": False,
                                          "text": text})
                s["gap"] |= match == "gap"
                s["partial"] |= match == "partial"
                s["must"] |= importance == "must"
        for key, s in seen.items():
            t = stats.setdefault(key, {"term": s["display"], "jobs": 0, "gap": 0, "partial": 0, "must": 0, "nice": 0,
                                       "score_sum": 0.0, "examples": []})
            t["jobs"] += 1
            t["gap"] += int(s["gap"])
            t["partial"] += int(s["partial"] and not s["gap"])
            t["must"] += int(s["must"])
            t["nice"] += int(not s["must"])
            t["score_sum"] += float(r["score"] or 0)
            if len(t["examples"]) < 3:
                t["examples"].append({"job_id": r["job_id"], "title": clean_title(r["title"] or ""),
                                      "company": r["company"] or "", "text": s["text"][:200]})
    out_terms = []
    for t in stats.values():
        t["avg_score"] = round(t.pop("score_sum") / t["jobs"], 2) if t["jobs"] else None
        out_terms.append(t)
    out_terms.sort(key=lambda t: (-t["gap"], -t["jobs"], -t["must"], t["term"].lower()))
    others = sorted(({"text": o["text"], "jobs": len(o["jobs"])} for o in other.values() if len(o["jobs"]) >= 2),
                    key=lambda o: -o["jobs"])[:10]
    return {"jobs_considered": len(rows), "min_score": min_score, "days": days, "terms": out_terms[:limit],
            "other": others}
