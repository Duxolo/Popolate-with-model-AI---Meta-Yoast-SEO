# Yoast SEO Meta Generator (Ollama + PyQt5)

A small PyQt5 desktop application that reads a WooCommerce product CSV and automatically fills Yoast SEO meta columns using a local Ollama LLM.

## What it generates
For each product row, the tool generates:
- **Yoast Focus Keyphrase** (`Meta: _yoast_wpseo_focuskw`) derived from the product name
- **Yoast SEO Title** (`Meta: _yoast_wpseo_title`) (max ~60 characters)
- **Yoast Meta Description** (`Meta: _yoast_wpseo_metadesc`) (target 120–150 characters, single CTA at the end)
- Optionally ensures the keyphrase appears at the beginning of the long description (**Descrizione**) as the first paragraph

## Key features
- Uses a **local Ollama model** (default: `qwen2.5:3b-instruct`)
- Cleans output from URLs/domains and banned tokens (e.g., WooCommerce/WordPress)
- Enforces meta description length and formatting rules
- GUI with start/stop + live logs
- Automatically detects CSV delimiter (`;` or `,`)
- Outputs a new file: `<input>_con_meta.csv`

## Requirements
- Python 3.x
- Ollama running locally
- Python packages:
  - PyQt5
  - requests

## Setup
1. Install and start Ollama.
2. Pull the model (example):
   - `ollama pull qwen2.5:3b-instruct`
3. Install dependencies:
   - `pip install PyQt5 requests`

## Usage
1. Run the app:
   - `python main.py`
2. Select the input CSV exported from WooCommerce.
3. Enter the product sector/category (used to guide SEO generation).
4. Click **Start**.
5. The tool creates `<input>_con_meta.csv` with Yoast meta columns filled.

## Notes
- Column indexes for product title/description are currently configured as:
  - Title: column E (index 4)
  - Description: column J (index 9)
  Adjust them in the script if your CSV structure differs.

## License
No license specified yet.
