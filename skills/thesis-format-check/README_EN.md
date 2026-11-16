# Thesis format checker

Check a thesis `.docx` against school formatting rules that you first turn into a structured file, write machine-readable issues back as Microsoft Word comments, and produce a one-page summary.

**`rules/example_rules.json` is a fictional example. It does not represent any real university.** For real use, rewrite your own school's rules in the same schema. This tool does not parse arbitrary regulation PDFs by itself.

It only checks the machine-readable items enabled in the rules file. **It does not claim to cover every clause of every school**, and it is not a substitute for official review. It does not provide, and does not discuss, “paraphrase to lower similarity,” “pass a detector,” or similar functions.

This directory is the self-contained package `skills/thesis-format-check/` in the `skills-collection` repository and can be sparse-checked out on its own. The repository ships the tool and test records only. It contains no secrets or personal accounts.

## Where the data goes

Checking runs on your machine. There are no external API calls, no document uploads, and no GPU.

## How to use it

Python 3 and `python-docx` 1.2+ (needed to write Word comments):

```bash
pip install -r requirements.txt
python3 check_thesis.py \
  --rules rules/example_rules.json \
  --input your-thesis.docx \
  --output thesis-commented.docx \
  --summary summary.md
```

See `rules/README.md` for the rule fields, and `SKILL.md` for the agent-side steps.

If the input is not a valid `.docx`, or the rules file is not valid JSON or is not a JSON object, the script prints one line of Chinese on stderr and exits with code 2, without a Python traceback. If the rules file is `{}` (no checks enabled), it says that the rules are empty and that no check was run; it does not say “no problems found.”

## Examples

Two worked examples live in [`examples/`](examples/) (a fictional thesis with 20 planted issues, and a second short paper with 10). Each folder has the input `.docx`, the annotated output, a summary, and a before/after image. The documents are fictional and the rules do not represent any real university.


## Results on 20 planted sample errors (not an accuracy rate)

A short fictional thesis (not a real student paper) and a list of 20 known errors were published and frozen before the test (2026-11-12 16:52:56 Asia/Macau, UTC+8; hashes in `tests/FROZEN.md`). The rules used are the fictional example. The same batch was not re-run to improve the numbers.

On those 20 pre-labeled errors:

- **20 found**: each of the 20 received a matching Word comment.
- **0 missed**: nothing that was pre-labeled was left without a matching comment.
- **0 false positives**: correct control passages (compliant body text, a correct chapter 2 and section 2.1, figures 1 and 2, references [1] and [3], Roman page numbers in the front matter, and so on) were not flagged.

These figures only describe **this fictional sample, on this run**. They are **not an accuracy rate**, must not be written as “zero errors,” and must not be generalized to any school or any thesis. The itemized list is in `tests/sample_errors.md`. The comparison script is `tests/compare_to_gold.py` (it matches on category and location, not on test tags such as【E04】; after those tags are removed, the score is still 20 found, 0 missed, 0 false positives). Reproduction steps are in `tests/REPRODUCE.md`. A commented example output is `tests/recorded_run/annotated.docx`.

Before-and-after figure: `visuals/before_after.png` (script-generated; LibreOffice does not draw Word comment balloons when exporting PDF, so the red balloons on the right are drawn by the script at the comment anchors). Commands and file sha256 values are in `visuals/GENERATE.md`.

## Limitations

- Only the machine-readable items enabled in the rules are checked: margins; body and heading fonts, sizes, and bold; body line spacing and first-line indent; heading numbering continuity; caption format and numbering continuity; header text; presence of page numbers and whether a section restarts at a given page; whether the table of contents is an automatic TOC field; reference numbering and the presence of a four-digit year.
- Items marked “to be confirmed” in the rules are not checked (for example, whether a prescribed cover template is mandatory, or whether every reference punctuation mark follows GB/T 7714).
- Scanned pages, PDFs, `.doc` files, chapter-based captions such as “图 1-1,” English-thesis layouts, and first-page or odd/even headers are not covered.
- You must first rewrite the school's rules as JSON; dropping a regulation PDF onto the script is not enough.
- Online format checkers already exist (some schools mandate one; some offer a daily free quota). If your school already provides one for free, you may not need this tool. The difference here is: your own rules, comments written back into Word, and checking that stays on your machine.
- You need to be able to run the command above, or have an agent run it.

## License

MIT. Copyright Haoxuan XIE. See `LICENSE`.
