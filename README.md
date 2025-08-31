# Introduction

This is a (somewhat) simple parser that is meant to showcase how a document could be ingested in Python in order to find the largest value in a PDF. There are some specifics that are important to this:
- This was tested only on the example PDF provided
- This PDF has text and tables, all of which are text based. Other PDFs can provide more complicated formatting such as images
- This does not use any ML or LLMs, it's purely Regex and PDF formatting and some logic meant to provide natural language understanding
- This does not use any external API calls

# How to Run

This project assumes that uv is already installed. If it isn't installed, please follow the steps at: https://docs.astral.sh/uv/getting-started/installation/

After that, it should be relatively simple. Git clone the repo, and once in the repo, use the following commands:
1. `uv pip install -r pyproject.toml`
2. `uv run python pdfParser.py`
Note: This is using a Windows laptop, using a Mac might require slight differences (you may for example be able to use `uv run pdfParser.py` directly, but I cannot confirm this)

That should be it. Ruff is already installed for formatting and linting, and can be run using `uv run ruff check .` or `uv run ruff format .`

# Decisions
I made a few decisions based primarily on the format for this PDF. It will most likely not generalize very well. Some of the decisions I made were:
- Using regexes to identify different words as opposed to an LLM or more complicated NLP approaches
- Not using shortform abbreviations for number modifiers (ie. K, M, B, T). Considering the messiness of the PDF parsing, I preferred to miss these, especially since there were many values already being modified
- Using page level modifications. Too often terms like '(Dollars in Thousands)' would be used outside of a table to indicate modifications to values in the table, so I opted to use the page modification instead.
- I tried to use row level modifiers / words like (Number, Rate, Percent) to cancel these page modifications for a specific row
- I used the pdfPlumber library as it appeared to be the best at finding both text and tables. Other libraries like Tabula seemed too involved with tables specifically, and then others seemed too low level like PDF Miner (which pdfPlumber uses)
- I opted to ignore warnings from pdfPlumber that were not errors. These warnings were being spit out, and didn't really matter too much for the output, but could have been swalled into a better logging system
- I added printed information at different stages to help with debugging and understanding what the system was doing. These could be removed in a system that didn't want as much noise or that was going to process a much larger document or many documents