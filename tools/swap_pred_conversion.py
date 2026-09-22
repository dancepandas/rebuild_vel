"""One-off: switch every pred->physical conversion to NormStats.physical_target."""

from pathlib import Path

EDITS = {
    "rebuild_vel/evaluate.py": [
        (
            "            pred_chunks.append(row[:len(mask)][:k] * norm.v_sd + norm.v_mu)",
            "            pred_chunks.append(norm.physical_target(row[:len(mask)][:k]))",
        ),
    ],
    "tools/eval_generalization.py": [
        (
            "            pred_lines.append(row[:len(mask)] * norm.v_sd + norm.v_mu)",
            "            pred_lines.append(norm.physical_target(row[:len(mask)]))",
        ),
    ],
    "tools/compare_models.py": [
        (
            "            p = row[:len(mask)][:k] * norm.v_sd + norm.v_mu",
            "            p = norm.physical_target(row[:len(mask)][:k])",
        ),
    ],
    "tools/contradiction_analysis.py": [
        (
            "        pred = np.concatenate(pred_chunks) * norm.v_sd + norm.v_mu",
            "        pred = norm.physical_target(np.concatenate(pred_chunks))",
        ),
    ],
    "tools/behaviour_analysis.py": [
        (
            "    pred = np.concatenate(pred_chunks) * norm.v_sd + norm.v_mu",
            "    pred = norm.physical_target(np.concatenate(pred_chunks))",
        ),
    ],
    "tools/report_figs.py": [
        (
            "            p = row[:len(mask)][:k] * norm.v_sd + norm.v_mu",
            "            p = norm.physical_target(row[:len(mask)][:k])",
        ),
    ],
    "tools/plot_section_recon.py": [
        (
            "            p = row[:len(mask)][:k] * norm.v_sd + norm.v_mu",
            "            p = norm.physical_target(row[:len(mask)][:k])",
        ),
    ],
}

for file, pairs in EDITS.items():
    p = Path(file)
    t = p.read_text(encoding="utf-8")
    for old, new in pairs:
        if old in t:
            t = t.replace(old, new)
            print(f"OK   {file}: swapped")
        elif new in t:
            print(f"SKIP {file}: already swapped")
        else:
            print(f"MISS {file}: anchor not found -> {old.strip()[:70]}")
    p.write_text(t, encoding="utf-8")
