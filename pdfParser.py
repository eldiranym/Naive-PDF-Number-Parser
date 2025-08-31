import pdfplumber
import re
import logging
from decimal import Decimal, InvalidOperation

# --- Configuration ---

# Suppress pdfminer noisy pdfminer warnings, but keep errors
logging.getLogger("pdfminer").setLevel(logging.ERROR)

# Dictionary to map textual representations of numbers to their multipliers.
# I considered using shortform modifiers like k, m, b, t (thousands, millions, billions, trillions)
# but the messy ingestion made these false starts more often than not
MULTIPLIERS = {
    "thousand": Decimal("1000"),
    "thousands": Decimal("1000"),
    "million": Decimal("1000000"),
    "millions": Decimal("1000000"),
    "billion": Decimal("1000000000"),
    "billions": Decimal("1000000000"),
    "trillion": Decimal("1000000000000"),
    "trillions": Decimal("1000000000000"),
}

# Keywords that, if found in a table row's first cell, will prevent
# column-level multipliers from being applied to that row.
ROW_EXCLUSION_KEYWORDS = {"percentage", "percent", "%", "number", "rate", "ratio"}

# Regex to find context clues in headers/footers (e.g., "in millions")
# It's case-insensitive and looks for the keyword within parentheses or as standalone words.
CONTEXT_MULTIPLIER_RE = re.compile(
    r"\(in (?P<multiplier_word>\w+)\)|"
    r"\(\$(?P<multiplier_word2>\w+)\)|"
    r"dollars in (?P<multiplier_word3>\w+)",
    re.IGNORECASE,
)

# Regex to find numbers:
# 1. It finds standard numbers, including decimals and commas (e.g., 1,234.56)
# 2. It optionally looks for a multiplier word immediately following the number.
NUMBER_RE = re.compile(
    r"(\$?\s*(?:\d{1,3}(?:,\d{3})*|\d+)(?:\.\d+)?)\s*"
    r"(thousand|million|billion|trillion)?(?=\b)",
    re.IGNORECASE,
)


def clean_number_string(s):
    """Removes common currency symbols and commas from a string."""
    return s.replace("$", "").replace(",", "").strip()


def parse_value(num_str, multiplier_word=None, context_multiplier=Decimal("1")):
    """
    Converts a number string and its potential multipliers into a final Decimal value.

    Args:
        num_str (str): The string representing the number (e.g., "5.2").
        multiplier_word (str, optional): A word found right next to the number (e.g., "million").
        context_multiplier (Decimal, optional): A multiplier derived from the page's context.

    Returns:
        Decimal: The calculated numerical value, or Decimal(0) if parsing fails.
    """
    try:
        base_number = Decimal(clean_number_string(num_str))

        # Priority 1: Use the multiplier word found directly next to the number
        if multiplier_word:
            word_lower = multiplier_word.lower()
            if word_lower in MULTIPLIERS:
                return base_number * MULTIPLIERS[word_lower]

        # Priority 2: If no direct multiplier, use the one from the page context
        return base_number * context_multiplier

    except (InvalidOperation, TypeError):
        return Decimal(0)


def is_within_bboxes(word, bboxes):
    """Checks if a word's bounding box is inside any of a list of bounding boxes."""
    w_x0, w_top, w_x1, w_bottom = word["x0"], word["top"], word["x1"], word["bottom"]
    for b_x0, b_top, b_x1, b_bottom in bboxes:
        # Check for overlap.
        if w_x0 < b_x1 and w_x1 > b_x0 and w_top < b_bottom and w_bottom > b_top:
            return True
    return False


def get_page_level_multiplier(page):
    """
    Extracts a page-level multiplier like '(Dollars in Millions)' by looking
    specifically at words near the top of the page, since pdfplumber's extract_text()
    isn't always reliable for headers.
    """
    words = page.extract_words()
    if not words:
        return Decimal("1")

    # Get words within the top 15% of the page
    page_height = float(page.height)
    top_words = [w["text"] for w in words if w["top"] < page_height * 0.15]
    header_text = " ".join(top_words)

    # Try matching context multiplier in the header area
    context_match = CONTEXT_MULTIPLIER_RE.search(header_text)
    if context_match:
        multiplier_word = next((g for g in context_match.groups() if g), None)
        if multiplier_word and multiplier_word.lower() in MULTIPLIERS:
            return MULTIPLIERS[multiplier_word.lower()]

    return Decimal("1")


def find_highest_value_in_pdf(pdf_path):
    max_value = Decimal("-Infinity")
    max_page = -1

    try:
        with pdfplumber.open(pdf_path) as pdf:
            print(f"Processing '{pdf_path}' with {len(pdf.pages)} pages...")

            for i, page in enumerate(pdf.pages):
                page_num = i + 1

                # --- Step 1: Extract a page-wide context multiplier ---
                page_context_multiplier = get_page_level_multiplier(page)
                if page_context_multiplier != Decimal("1"):
                    print(
                        f"  - Page {page_num}: Page-level context multiplier found ({page_context_multiplier:,})"
                    )

                # --- Step 2: Process Tables ---
                tables = page.extract_tables()
                detected_tables = page.find_tables()
                table_bboxes = [t.bbox for t in detected_tables if t.bbox]

                for t_idx, table in enumerate(tables):
                    if not table or not table[0]:
                        continue

                    # Detect a table-specific context multiplier by scanning near its bounding box
                    table_context_multiplier = page_context_multiplier
                    bbox = detected_tables[t_idx].bbox
                    nearby_text = ""
                    for word in page.extract_words():
                        # Check if the word is above or below the table but horizontally aligned
                        if bbox[0] <= word["x0"] <= bbox[2]:
                            if (
                                abs(word["top"] - bbox[1]) < 80
                                or abs(word["bottom"] - bbox[3]) < 80
                            ):
                                nearby_text += " " + word["text"]
                    nearby_match = CONTEXT_MULTIPLIER_RE.search(nearby_text)
                    if nearby_match:
                        multiplier_word = next(
                            (g for g in nearby_match.groups() if g is not None), None
                        )
                        if multiplier_word and multiplier_word.lower() in MULTIPLIERS:
                            table_context_multiplier = MULTIPLIERS[
                                multiplier_word.lower()
                            ]
                            print(
                                f"  - Page {page_num}: Table-level context multiplier found near table -> '{multiplier_word}' ({table_context_multiplier:,})"
                            )

                    # Find column multipliers from header row
                    column_multipliers = {}
                    header_row = table[0]
                    for col_idx, header_cell in enumerate(header_row):
                        if not header_cell:
                            continue
                        header_text_lower = header_cell.lower()
                        for word, multiplier in MULTIPLIERS.items():
                            if re.search(
                                r"\b" + re.escape(word) + r"\b", header_text_lower
                            ):
                                column_multipliers[col_idx] = multiplier
                                break

                    # Process data rows
                    for row in table[1:]:
                        if not row or not row[0]:
                            continue

                        is_excluded_row = any(
                            kw in row[0].lower() for kw in ROW_EXCLUSION_KEYWORDS
                        )

                        for col_idx, cell in enumerate(row):
                            if not cell:
                                continue

                            matches = NUMBER_RE.finditer(cell)
                            for match in matches:
                                num_str, multiplier_word = match.groups()

                                # Pick best multiplier
                                context_mult = column_multipliers.get(
                                    col_idx,
                                    table_context_multiplier
                                    if not is_excluded_row
                                    else Decimal("1"),
                                )
                                value = parse_value(
                                    num_str, multiplier_word, context_mult
                                )

                                if value > max_value:
                                    max_value = value
                                    max_page = page_num
                                    print(
                                        f"  - Page {page_num} (Table): New max value found -> {max_value:,.2f} (from cell: '{cell.strip()}')"
                                    )

                # --- Step 3: Process Non-Table Text ---
                all_words = page.extract_words()
                non_table_words = [
                    word
                    for word in all_words
                    if not is_within_bboxes(word, table_bboxes)
                ]
                non_table_text = " ".join(word["text"] for word in non_table_words)
                if non_table_text:
                    matches = NUMBER_RE.finditer(non_table_text)
                    for match in matches:
                        num_str, multiplier_word = match.groups()
                        value = parse_value(num_str, multiplier_word, Decimal("1"))
                        if value > max_value:
                            max_value = value
                            max_page = page_num
                            print(
                                f"  - Page {page_num} (Non-Table): New max value found -> {max_value:,.2f} (from text: '{match.group(0).strip()}')"
                            )

    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return None, None

    if max_value == Decimal("-Infinity"):
        print("No valid numbers were found.")
        return None, None

    return max_value, max_page


# --- Main execution block ---
if __name__ == "__main__":
    pdf_file = "AirForceExamplePDF.pdf"

    highest_value, page_number = find_highest_value_in_pdf(pdf_file)

    if highest_value is not None:
        print("\n" + "=" * 40)
        print("         Extraction Complete")
        print("=" * 40)
        print(f"The highest value found in the document is: {highest_value:,.2f}")
        print(f"This value was found on page: {page_number}")
        print("=" * 40)
