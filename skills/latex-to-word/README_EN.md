# LaTeX to Word

Convert an existing LaTeX paper to a Word document (`.docx`) with editable equations (OMML, not a page screenshot), resolved cross-references, and a bibliography from the `.bib` file. The tool writes a report listing what succeeded, what was degraded, and what still needs a manual fix.

Everything runs locally. No network at runtime, no GPU, no login.

The **default command** adds equation numbers to numbered display equations, matching the right-hand column of the comparison figures. Run it twice on the same input, or copy the folder and run it elsewhere, and you should get the same whole-file sha256 and the same content-level sha256 (temporary paths, document timestamps, and the CSL path in `custom.xml` are normalized to a filename such as `ieee.csl`). A measured set of runs on `tests/samples/2509.13972` (2026-11-12, Asia/Shanghai, UTC+8) is in the Chinese `README.md`.

Non-tex input, a missing path, or a broken tex file: one Chinese line on stderr, non-zero exit, no traceback, no docx.

Entries in the `.bib` that have no `year` or `date` get `year = {n.d.}` so citeproc does not drop them silently. Cited keys are also `\nocite`d so a citation that lives only in a caption still reaches the bibliography. The report compares the number of cited keys that exist in the `.bib` with the number of bibliography items in the docx, and records a “silently dropped” manual-fix note if the docx is short. That check is count-only: it cannot catch a reference that is in the bibliography but whose in-text or caption citation is missing. Captions of `wraptable`/`wrapfigure` floats that do not appear in the docx are listed separately as needing a manual fix. The Word table count (`w:tbl` nodes, including nested ones) may exceed the number of LaTeX `table` floats, because subfigure grids, in-cell `tabular`s used for line breaks, and some figure placeholders are also counted as tables.

## Results on public source samples (not an accuracy rate)

Figures are measured counts only. Three rounds were recorded; the same batch was not re-run to pad the numbers. After the second round, equation counts follow the official PDF’s **true numbered display equations** (in-text enumerations, volume numbers and years do not count). This package ships only the third-round outputs, in `tests/outputs/`. Official PDFs are not bundled: download them from the arXiv links and check the sha256 values in `tests/samples/LICENSE_AND_ATTRIBUTION.md`.

Third round (2026-11-12, about 17:48 Asia/Shanghai): all five CC BY 4.0 papers match the official PDF on all three counts — 2509.13972 (8=8, 31=31, 24=24), 2506.21734 (3=3, 25=25, 101=101), 2508.16738 (0=0, 43=43, 75=75), 2506.04667 (4=4, 57=57, **55=55**; the previous round was 54≠55 because citeproc silently dropped the year-less `@misc{nsight-metrics}`), and 2611.14518 (2=2, 10=10, 26=26). Whole-file sha256 for 2509.13972 was identical across directories: `7b2e6937b3ef2d0fa9ceb1fd738f8bf14bd9092a1278f355fbc3710a05e69399`.

First-round and redo numbers are kept in the Chinese README as history (the first round had only 1 of 4 papers matching all three counts; the redo still had 2506.04667 bibliography 54≠55). The counting rule was not changed to pad those earlier figures.

A degradation figure (`visuals/compare_2506.21734_tikz.png`) shows a TikZ figure present in the official PDF, missing under bare pandoc, and explicitly stubbed by this tool. The two earlier figures from paper 2509 are unchanged.

Limitations, license (MIT, copyright Haoxuan XIE), and sample attribution are in the Chinese README and `LICENSE`.
