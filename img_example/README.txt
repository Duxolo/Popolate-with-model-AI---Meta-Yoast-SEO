Folder contents
---------------
This folder contains:
- Dashboard screenshots (to show the software UI and settings used)
- A sample CSV file in the root directory (used as the reference structure/order)
- Optional sample images (if included) to illustrate the workflow


Prerequisites before running the SEO generation
-----------------------------------------------
Before launching the software and starting the Automatic SEO generation, make sure that:

1) The CSV columns are in the exact same order as the sample CSV located in the root folder.
2) The column 'Meta: _yoast_wpseo_title' exists.
   - If it is missing, create it exactly as shown in the sample CSV.
3) Clear (empty) the following columns before processing:
   - 'Meta: _yoast_wpseo_title'
   - 'Meta: _yoast_wpseo_metadesc'
   - 'Meta: _yoast_wpseo_focuskw'


Execution procedure
-------------------
1) Launch the software: SEO Meta Generator

2) In "CSV Input", select the CSV file you want to process.

3) In the section "Sector / Product category", enter a brief description of the product category you are importing.

4) Click "Start".

5) When the process ends, the program automatically generates a new CSV with the SEO columns populated by AI.
   The newly processed CSV will be saved in the same directory as the input CSV.


Notes
-----
To run this system, the PC must have Ollama installed and the following models available:
- qwen2.5:3b-instruct
- qwen2.5:7b-instruct

