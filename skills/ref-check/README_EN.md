# Reference checker (against public databases)

Paste a reference list and compare it with [Crossref](https://www.crossref.org/), [OpenAlex](https://openalex.org/), and [Europe PMC](https://europepmc.org/). The tool reports whether a work can be found and whether key fields match, and it links to the original record.

**Best suited for** students in science, engineering, or medicine who mainly cite English journal or conference papers. **It is not intended for people whose bibliographies are mostly in Chinese.** CNKI and Wanfang are not supported. A Chinese item that cannot be found is labelled “not found”; **that is not proof that it is fabricated**.

This is not a system that can catch every AI-hallucinated citation, and it does not check whether a sentence in your manuscript is actually supported by the cited work. If nothing is found, the tool **will not invent** a tidier reference to replace yours.

This repository contains the tool and test records only. It includes no paid content, secrets, or personal accounts.

## Usage

### In a browser (no install)

Open `ref-check.html`, paste the references, and click the check button. A network connection is required. You may optionally enter an email for OpenAlex’s `mailto` parameter (default `refcheck@localhost`).

### Command line (Python 3, standard library only)

```bash
python3 check_refs.py references.txt --mailto you@school.edu -o report.html
```

`--md` and `--json` write Markdown or JSON. No third-party Python packages are required.

## How to read the labels

- **Verified**: a public-database record matches, and key fields agree. Please still open the link and look once.
- **Field mismatch**: probably the same work, but year, authors, pages, venue, or DOI/PMID disagree.
- **Not found**: the APIs responded, but no sufficiently similar record was found. **This does not mean the work is fake.**
- **Suspected fabricated**: a complete English entry cannot be found; or the given DOI/PMID points to a completely different work; or a short, generic title collides with another real article in the same journal (the report includes a link to that record for you to check). **Do not treat this label alone as a finding of misconduct.**
- **Check failed / no conclusion**: a network or API error (timeout, connection failure, HTTP 429). **This is not the same as “not found.”** Try again later.

See [`examples/`](examples/) for three worked examples (mixed list, the labelled 20-item set, and DOI-only input), each with input, the recorded report, and a screenshot.

## Results on pre-labelled samples (not an accuracy rate)

Do not read the figures below as an accuracy rate. Labels were written independently before each run. A batch is never re-run to pad the numbers, and labels are not changed to match the output.

| Batch | Notes | Agreement with labels | What that means |
|---|---|---|---|
| Official 20 | Fixed regression set | 20/20 (23:28:51 on 2026-11-11, Asia/Macau, UTC+8; item 19 may be “not found”) | All 20 matched the pre-written labels |
| Batch 1 | Before general fixes | 74/100 | 26 disagreed |
| Batch 2 | Held-out | 96/100 | 4 disagreed |
| Batch 3 | Held-out | 93/100 | 7 disagreed |
| Batch 4 | Held-out | 95/100 | 5 disagreed |
| Batch 5 | Held-out | 98/100 | 2 disagreed |
| Batch 6 | Held-out | 95/100 | 5 disagreed |
| Batch 7 | Held-out; mixed styles (APA / MLA / GB/T 7714 / BibTeX / IEEE / Vancouver) | 89/100 (6 of the disagreements were API failures) | 11 disagreed; 30/30 tampered items matched; none of the 15 publicly documented problem items was labelled “verified” |

No batch reached 100/100, so this project **must not be described as zero-error**. Overview: `visuals/overview_hundred.png`. Per-item comparisons are in each batch folder’s `compare.json`. How to reproduce: `tests/REPRODUCE.md`.

Offline unit tests (they do not replace the live 20-item run):

```bash
python3 tests/test_acceptance_fixes.py
```

The offline suite is 39/39 in this round (the original 29 still pass).

The seven live Chrome scenarios were re-run against the shipped `ref-check.html` on 2026-11-11, 23:53:57–23:54:40 Asia/Macau (UTC+8), and all passed. Screenshots and a structured extract are in `tests/html_browser/`.

## Known limits

- Only Crossref, OpenAlex, and Europe PMC are queried. CNKI and Wanfang are unsupported.
- Rate limits or timeouts are reported as “check failed”, never rewritten as “not found”.
- A short, generic title may collide with another real article in the same journal. The tool then marks the item as suspected and links the record, rather than labelling it verified.
- Dirty author metadata and some BibTeX, IEEE, or mixed Chinese layouts may still produce a field-mismatch on the same work.
- The tool does not check whether a claim in the text is actually supported by the cited paper.
- The HTML and Python tools share the same core rules; the 100-item counts above come from the Python runs.

## License

MIT. See `LICENSE`. This folder is a release-ready copy, with no secrets, personal accounts, or absolute machine paths.
