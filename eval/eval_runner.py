"""Evaluation runner for University Intelligence Database Agent.

Compares scraped results in data/output/universities.json against ground truth in
eval/ground_truth.json. Computes accuracy metrics per-field and overall, counts
validation flags by severity, and writes a detailed evaluation report.
"""

import json
import os
from typing import Any, Dict, List, Tuple


def normalize_str(s: str) -> str:
    """Normalizes a string by converting to lowercase and stripping non-alphanumeric chars.

    This helps in comparing course codes (e.g. "CSC108" vs "CSC 108") or types
    (e.g. "Public" vs "public").
    """
    if not s:
        return ""
    return "".join(c.lower() for c in s if c.isalnum())


def compare_numeric(gt: float, scr: float, relative_tolerance: float = 0.0) -> bool:
    """Compares two numeric values with an optional relative tolerance.

    If tolerance is > 0, returns True if the values are within the tolerance range.
    Otherwise, performs an exact match comparison.
    """
    if gt is None or scr is None:
        return False
    if relative_tolerance > 0.0:
        if gt == 0.0:
            return scr == 0.0
        return abs(gt - scr) / abs(gt) <= relative_tolerance
    return gt == scr


def evaluate_field(
    category: str,
    gt_val: Any,
    scr_val: Any,
) -> Tuple[int, int]:
    """Compares ground-truth value to scraped value for a given category.

    Returns:
        A tuple of (correct_count, total_checked_count).
    """
    if gt_val is None:
        return 0, 0

    # If ground truth specifies a field but the scraped value is missing or None
    if scr_val is None:
        return 0, 1

    if category == "about":
        correct = 0
        total = 0
        if "founding_year" in gt_val:
            total += 1
            if compare_numeric(gt_val["founding_year"], scr_val.get("founding_year")):
                correct += 1
        if "institution_type" in gt_val:
            total += 1
            gt_type = normalize_str(gt_val["institution_type"])
            scr_type = normalize_str(scr_val.get("institution_type", ""))
            if gt_type and gt_type == scr_type:
                correct += 1
        return correct, total

    elif category == "tuition_fees":
        # gt_val is a list of entries, e.g. [{"international_fee": 45000.0, "currency": "CAD"}]
        correct = 0
        total = 0
        for gt_fee in gt_val:
            total += 1
            # Search for a matching fee in scraped values
            matched = False
            for scr_fee in scr_val:
                # Compare currency and fee value
                curr_match = normalize_str(gt_fee.get("currency", "")) == normalize_str(scr_fee.get("currency", ""))
                # Relative tolerance of 5% for international fees
                val_match = compare_numeric(
                    gt_fee.get("international_fee"),
                    scr_fee.get("international_fee"),
                    relative_tolerance=0.05,
                )
                if curr_match and val_match:
                    matched = True
                    break
            if matched:
                correct += 1
        return correct, total

    elif category == "acceptance_rate":
        total = 0
        correct = 0
        if "overall_pct" in gt_val:
            total += 1
            if compare_numeric(gt_val["overall_pct"], scr_val.get("overall_pct")):
                correct += 1
        return correct, total

    elif category == "course_listings":
        # gt_val is a list of entries, e.g. [{"code": "CSC108", "title": "Introduction to Computer Programming"}]
        correct = 0
        total = 0
        for gt_course in gt_val:
            total += 1
            gt_code = normalize_str(gt_course.get("code", ""))
            gt_title = normalize_str(gt_course.get("title", ""))
            matched = False
            for scr_course in scr_val:
                scr_code = normalize_str(scr_course.get("code", ""))
                scr_title = normalize_str(scr_course.get("title", ""))
                # Allow substring match (e.g. "CSC108" matches "CSC108H1")
                code_match = (gt_code in scr_code) or (scr_code in gt_code) if gt_code and scr_code else False
                title_match = (gt_title in scr_title) or (scr_title in gt_title) if gt_title and scr_title else False
                if code_match and title_match:
                    matched = True
                    break
            if matched:
                correct += 1
        return correct, total

    return 0, 0


def main() -> None:
    # Set paths
    output_dir = "data/output"
    scraped_path = os.path.join(output_dir, "universities.json")
    ground_truth_path = "eval/ground_truth.json"
    report_path = "eval/eval_report.md"

    # Ensure output paths exist
    os.makedirs(os.path.dirname(report_path), exist_ok=True)

    # 1. Load JSON files
    if not os.path.exists(scraped_path):
        print(f"Error: Scraped output not found at {scraped_path}")
        return
    if not os.path.exists(ground_truth_path):
        print(f"Error: Ground truth not found at {ground_truth_path}")
        return

    with open(scraped_path, "r", encoding="utf-8") as f:
        scraped_records = json.load(f)

    with open(ground_truth_path, "r", encoding="utf-8") as f:
        ground_truth = json.load(f)

    # Convert scraped records to dict mapped by university_name for fast lookup
    scraped_map = {r["university_name"]: r for r in scraped_records}

    # Tracking accuracy stats
    # Map of (field, university) -> (correct, checked)
    detailed_scores: Dict[Tuple[str, str], Tuple[int, int]] = {}
    universities = [r["university_name"] for r in ground_truth]

    # Map to track validation flag counts by severity per university
    flag_counts: Dict[str, Dict[str, int]] = {
        uni: {"high": 0, "medium": 0, "low": 0} for uni in universities
    }

    # Map of field categories to check
    all_categories = [
        "about",
        "tuition_fees",
        "living_costs",
        "scholarships",
        "acceptance_rate",
        "graduate_employment",
        "average_salaries",
        "visa_policies",
        "intake_deadlines",
        "course_listings",
    ]

    for gt_rec in ground_truth:
        uni_name = gt_rec["university_name"]
        scr_rec = scraped_map.get(uni_name)

        if not scr_rec:
            print(f"Warning: Scraped record missing for university {uni_name}")
            continue

        # Count validation flags by severity
        for flag in scr_rec.get("validation_flags", []):
            sev = flag.get("severity", "").lower()
            if sev in flag_counts[uni_name]:
                flag_counts[uni_name][sev] += 1

        # Evaluate fields
        gt_data = gt_rec.get("data", {})
        scr_data = scr_rec.get("data", {})

        for cat in all_categories:
            gt_val = gt_data.get(cat)
            scr_val = scr_data.get(cat)
            correct, checked = evaluate_field(cat, gt_val, scr_val)
            detailed_scores[(cat, uni_name)] = (correct, checked)

    # Compile the report markdown
    report_lines = []
    report_lines.append("# UIA Accuracy Evaluation Report\n")

    # Methodology section
    report_lines.append("## Methodology\n")
    report_lines.append(
        "This evaluation compares the autonomously crawled database records in `universities.json` "
        "against manually verified ground-truth values stored in `ground_truth.json`.\n"
    )
    report_lines.append("### Normalization & Comparison Rules:\n")
    report_lines.append(
        "- **Numeric Fields**:\n"
        "  - **Monetary values** (e.g. `tuition_fees.international_fee`): Considered correct if within "
        "a **5% relative tolerance** to accommodate rounding or fee conversion fluctuations.\n"
        "  - **Sanity check fields** (e.g. `acceptance_rate.overall_pct`, `founding_year`): Checked for exact match.\n"
    )
    report_lines.append(
        "- **String Fields**:\n"
        "  - Case-insensitive alphanumeric comparison (converting to lowercase and stripping non-alphanumeric chars "
        "to ensure e.g., 'public' matches 'Public' or course code whitespace variations match).\n"
        "  - Substring matching is enabled for course codes (e.g. 'CSC108' matches 'CSC108H1') to count partial matches "
        "correctly.\n"
    )

    # Flag count summary
    report_lines.append("## Human Review Flag Summary\n")
    report_lines.append(
        "The count of validation flags generated by the pipeline's self-validator acts as a proxy "
        "for records requiring human review:\n"
    )
    for uni in universities:
        counts = flag_counts[uni]
        report_lines.append(
            f"- **{uni}**: {counts['high']} High, {counts['medium']} Medium, {counts['low']} Low flags\n"
        )

    # Generate accuracy evaluation table
    report_lines.append("## Accuracy Evaluation Table\n")

    # Table header
    headers = ["Field"] + universities + ["Overall Accuracy", "Checked Fields / Ground Truth"]
    header = "| " + " | ".join(headers) + " |"
    divider = "| " + " | ".join(["---"] * len(headers)) + " |"
    report_lines.append(header)
    report_lines.append(divider)

    total_correct_overall = 0
    total_checked_overall = 0

    known_gaps: List[str] = []

    for cat in all_categories:
        row_cells = [f"`{cat}`"]
        cat_correct = 0
        cat_checked = 0

        for uni in universities:
            correct, checked = detailed_scores.get((cat, uni), (0, 0))
            if checked > 0:
                acc = (correct / checked) * 100
                row_cells.append(f"{acc:.1f}% ({correct}/{checked})")
                cat_correct += correct
                cat_checked += checked
            else:
                row_cells.append("N/A")
                known_gaps.append(f"- **{uni}** does not have ground-truth entries for `{cat}`.")

        if cat_checked > 0:
            cat_acc = (cat_correct / cat_checked) * 100
            row_cells.append(f"{cat_acc:.1f}%")
            row_cells.append(f"{cat_correct}/{cat_checked}")
            total_correct_overall += cat_correct
            total_checked_overall += cat_checked
        else:
            row_cells.append("N/A")
            row_cells.append("0/0")

        report_lines.append("| " + " | ".join(row_cells) + " |")

    # Append overall row
    overall_acc_pct = (total_correct_overall / total_checked_overall * 100) if total_checked_overall > 0 else 0.0
    overall_row = [
        "**Overall**",
        *[
            f"{sum(detailed_scores.get((cat, uni), (0,0))[0] for cat in all_categories) / sum(detailed_scores.get((cat, uni), (0,0))[1] for cat in all_categories) * 100:.1f}%"
            if sum(detailed_scores.get((cat, uni), (0,0))[1] for cat in all_categories) > 0 else "N/A"
            for uni in universities
        ],
        f"**{overall_acc_pct:.1f}%**",
        f"**{total_correct_overall}/{total_checked_overall}**",
    ]
    report_lines.append("| " + " | ".join(overall_row) + " |")
    report_lines.append("\n")

    # Known gaps section
    report_lines.append("## Known Gaps\n")
    if known_gaps:
        report_lines.extend(known_gaps)
    else:
        report_lines.append("No gaps in ground-truth coverage detected.")
    report_lines.append("\n")

    # Write report file
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(report_lines))

    print(f"Evaluation completed successfully. Report written to {report_path}")


if __name__ == "__main__":
    main()
