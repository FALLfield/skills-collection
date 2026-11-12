#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验收补丁的离线与模拟断网测试。不替代 20 条联网回归。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from check_refs import (  # noqa: E402
    ParsedRef,
    Record,
    compare_fields,
    is_identifier_only,
    is_weak_title,
    last_names,
    parse_one,
    looks_like_romanized_cjk_journal,
    pages_compatible,
    record_supported_by_cite,
    is_clearly_other_work,
    fill_from_bibtex,
)


class ParseIdentifierOnly(unittest.TestCase):
    def test_url_doi(self):
        ref = parse_one("https://doi.org/10.1038/nature16961")
        self.assertEqual(ref.doi, "10.1038/nature16961")
        self.assertIsNone(ref.title)
        self.assertEqual(ref.authors, [])
        self.assertTrue(is_identifier_only(ref))

    def test_bare_doi(self):
        ref = parse_one("10.1038/nature16961")
        self.assertEqual(ref.doi, "10.1038/nature16961")
        self.assertEqual(ref.authors, [])
        self.assertTrue(is_identifier_only(ref))

    def test_doi_prefix(self):
        ref = parse_one("doi:10.1038/nature16961")
        self.assertEqual(ref.doi, "10.1038/nature16961")
        self.assertEqual(ref.authors, [])
        self.assertTrue(is_identifier_only(ref))


class AuthorCompatibility(unittest.TestCase):
    def test_abbreviated_given_name(self):
        cited = last_names(["Vaswani, A."])
        rec = last_names(["Ashish Vaswani"], both_ends=True)
        self.assertEqual(cited, {"vaswani"})
        self.assertIn("vaswani", rec)
        self.assertTrue(cited & rec)

    def test_initial_before_family(self):
        self.assertEqual(last_names(["A. Vaswani"]), {"vaswani"})

    def test_compare_fields_accepts_full_given_name(self):
        cited = ParsedRef(
            raw="Vaswani, A. (2017). Attention is all you need.",
            authors=["Vaswani, A."],
            title="Attention is all you need",
            year=2017,
        )
        rec = Record(
            source="openalex",
            title="Attention is all you need",
            authors=["Ashish Vaswani", "Noam Shazeer"],
            year=2017,
        )
        self.assertEqual(compare_fields(cited, rec), [])

    def test_first_author_still_hard_fail(self):
        cited = ParsedRef(
            raw="Smith, J. (2019). BERT.",
            authors=["Smith, J.", "Chang, M."],
            title="BERT",
            year=2019,
        )
        rec = Record(
            source="crossref",
            title="BERT",
            authors=["Jacob Devlin", "Ming-Wei Chang"],
            year=2019,
        )
        fields = [m["field"] for m in compare_fields(cited, rec)]
        self.assertIn("authors", fields)


class MissingInputFile(unittest.TestCase):
    def test_chinese_error(self):
        missing = ROOT / "tests" / "_no_such_file_验收.txt"
        proc = subprocess.run(
            [sys.executable, str(ROOT / "check_refs.py"), str(missing)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 2)
        self.assertIn("找不到输入文件", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertNotIn("FileNotFoundError", proc.stderr)


class SimulatedDisconnect(unittest.TestCase):
    def test_resnet_is_check_failed_not_not_found(self):
        env = os.environ.copy()
        env["REFCHECK_CROSSREF_BASE"] = "http://127.0.0.1:1"
        env["REFCHECK_OPENALEX_BASE"] = "http://127.0.0.1:1"
        env["REFCHECK_EUROPEPMC_BASE"] = "http://127.0.0.1:1"
        env["REFCHECK_HTTP_TIMEOUT"] = "2"
        inp = ROOT / "tests" / "network_fail_input.txt"
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "net.json"
            html_out = Path(tmp) / "net.html"
            proc = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "check_refs.py"),
                    str(inp),
                    "--json",
                    str(out),
                    "--html",
                    str(html_out),
                    "--delay",
                    "0",
                ],
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertTrue(out.is_file(), proc.stderr)
            data = json.loads(out.read_text(encoding="utf-8"))
            results = data["results"] if isinstance(data, dict) and "results" in data else data
            self.assertEqual(len(results), 1)
            status = results[0]["status"]
            self.assertEqual(
                status,
                "error",
                f"断网时应为核查失败，实际为 {status}；notes={results[0].get('notes')}",
            )
            self.assertNotEqual(status, "not_found")
            zh = results[0].get("status_zh", "")
            self.assertIn("核查失败", zh)
            blob = " ".join(results[0].get("notes") or [])
            self.assertIn("无法下结论", blob)
            self.assertNotEqual(results[0].get("status_zh"), "查无此文")
            # 不得先写「因此标为疑似编造」再改口
            self.assertNotIn("因此标为「疑似编造」", blob)
            leftover = ROOT / "tests" / "network_fail_input_report.html"
            self.assertFalse(leftover.exists(), "不应在夹具旁留下生成报告")




class ParserGeneralFixes(unittest.TestCase):
    def test_doi_digits_not_used_as_volume(self):
        ref = parse_one(
            "Baharoglu, M. I. (2016). Platelet transfusion versus standard care. "
            "The Lancet, 387(10038), 2605-2613. https://doi.org/10.1016/s0140-6736(16)30392-0"
        )
        self.assertEqual(ref.volume, "387")
        self.assertEqual(ref.issue, "10038")
        self.assertEqual(ref.pages, "2605-2613")

    def test_vancouver_trailing_initials_are_not_surnames(self):
        self.assertEqual(last_names(["Shoemaker WR"]), {"shoemaker"})
        self.assertIn("shoemaker", last_names(["Shoemaker William R."], both_ends=True))
        self.assertIn("mishra", last_names(["Mishra AK"]))

    def test_clearly_different_journal_not_ignored_when_doi_matches(self):
        from check_refs import ParsedRef, Record, compare_fields
        cited = ParsedRef(
            raw="x",
            authors=["Asano, T."],
            title="Twenty-year trends",
            year=2020,
            journal="Nature",
            doi="10.1093/example.doi",
        )
        rec = Record(
            source="crossref",
            title="Twenty-year trends",
            authors=["Asano Toshiaki"],
            year=2020,
            journal="European Heart Journal",
            doi="10.1093/example.doi",
        )
        fields = [m["field"] for m in compare_fields(cited, rec)]
        self.assertIn("journal", fields)

    def test_chinese_apa_title_and_journal(self):
        ref = parse_one(
            "陈旭峰 (2015). 中医“益气温阳”法联合西药治疗心衰伴偏低血压的临床疗效观察. 浙江临床医学, 17(12), 2218-2218."
        )
        self.assertIn("益气温阳", ref.title or "")
        self.assertIn("浙江临床医学", ref.journal or "")
        self.assertEqual(ref.volume, "17")

    def test_vancouver_with_month_before_volume(self):
        ref = parse_one(
            "Kallajoki M, et al. Homocysteine and bone metabolism. Osteoporos Int. 2002 Oct;13(10):822-7. PMID: 12352394"
        )
        self.assertIn("Homocysteine", ref.title or "")
        self.assertEqual(ref.pmid, "12352394")
        self.assertFalse(is_identifier_only(ref))

    def test_alphanumeric_issue_not_taken_as_pages_volume(self):
        ref = parse_one(
            "Yang, S. (2017). Gravitational wave optical counterpart searching based on GRAWITA and DLT40 project during LIGO O2 run. Proceedings of the International Astronomical Union, 13(S338), 9-13. https://doi.org/10.1017/s1743921318000157"
        )
        self.assertEqual(ref.volume, "13")
        self.assertEqual(ref.issue, "S338")
        self.assertEqual(ref.pages, "9-13")
        self.assertEqual(ref.year, 2017)

    def test_nested_issue_after_volume(self):
        ref = parse_one(
            "Shahini-Hoxhaj R. Facebook and Political Polarization: An Analysis of the Social Media Impact on the Kosovo-Serbia Dialogue[J]. Journal of Media Research, 2018, 11(3(32)): 71-93. DOI: 10.24193/jmr.32.6"
        )
        self.assertEqual(ref.volume, "11")
        self.assertEqual(ref.issue, "3(32)")
        self.assertEqual(ref.pages, "71-93")
        self.assertEqual(ref.year, 2018)

    def test_title_year_range_is_not_publication_year_or_pages(self):
        ref = parse_one(
            "Wron ski M. The relative persistence of income inequality and intra-generational income mobility in Poland during and after the Great Financial Crisis (2008-2015). Economic Analysis Letters. 2023. doi: 10.58567/eal02030004"
        )
        self.assertEqual(ref.year, 2023)
        self.assertIsNone(ref.pages)
        self.assertIn("relative persistence", ref.title or "")
        self.assertIn("Economic Analysis Letters", ref.journal or "")

    def test_html_entity_in_journal_unescaped(self):
        ref = parse_one(
            "Lars M Ittner FD. Genome Editing in Mice Using CRISPR/Cas9: Achievements and Prospects. Cloning &amp; Transgenesis. 2015;04(01). doi: 10.4172/2168-9849.1000135"
        )
        self.assertEqual(ref.journal, "Cloning & Transgenesis")
        self.assertEqual(ref.volume, "04")
        self.assertEqual(ref.issue, "01")


    def test_mid_title_quotes_are_not_the_whole_title(self):
        ref = parse_one(
            "Bisikalo, D. V., & Cherenkov, A. A. (2016). The influence of coronal mass ejections "
            "on the gas dynamics of the atmosphere of a “hot Jupiter” exoplanet. Astronomy Reports, "
            "60(2), 183-192. https://doi.org/10.1134/s1063772916020013"
        )
        self.assertIn("influence of coronal mass ejections", ref.title or "")
        self.assertNotEqual(ref.title, "hot Jupiter")
        self.assertEqual(ref.journal, "Astronomy Reports")
        self.assertEqual(ref.year, 2016)
        self.assertEqual(ref.doi, "10.1134/s1063772916020013")
        rec = Record(
            source="crossref",
            title="The influence of coronal mass ejections on the gas dynamics of the atmosphere of a “hot Jupiter” exoplanet",
            authors=["Bisikalo D. V.", "Cherenkov A. A."],
            year=2016,
            journal="Astronomy Reports",
            volume="60",
            issue="2",
            pages="183-192",
            doi="10.1134/s1063772916020013",
            pmid=None,
            typ="journal-article",
            url="https://doi.org/10.1134/s1063772916020013",
        )
        self.assertTrue(record_supported_by_cite(ref, rec))
        self.assertTrue(is_weak_title("hot Jupiter", ref.raw))

    def test_title_only_curly_quotes_not_split_into_authors(self):
        ref = parse_one(
            "Donald Trump’s “Political Incorrectness”: Neoliberalism as Frontstage Racism on Social Media"
        )
        self.assertIn("Neoliberalism as Frontstage Racism", ref.title or "")
        self.assertEqual(ref.authors, [])
        self.assertIsNone(ref.year)

    def test_html_and_abbrev_periods_in_title_do_not_steal_journal(self):
        ref = parse_one(
            "Abbott, B. P. (2016). Publisher’s Note: Observing gravitational-wave transient "
            "GW150914 with minimal assumptions [Phys. Rev. D<b>93</b>, 122004 (2016)]. "
            "Physical Review D, 94(6). https://doi.org/10.1103/physrevd.94.069903"
        )
        self.assertIn("Publisher", ref.title or "")
        self.assertIn("GW150914", ref.title or "")
        self.assertEqual(ref.journal, "Physical Review D")
        self.assertEqual(ref.volume, "94")
        self.assertEqual(ref.issue, "6")
        self.assertNotIn("<b>", ref.title or "")
        self.assertNotIn("<b>", ref.journal or "")

    def test_cjk_author_order_does_not_flag_same_person(self):
        cited = parse_one(
            "李 佳. 分析中医内科治疗胃食管反流病的临床效果[J]. 内科诊疗与进展, 2022, 3(1): 52-54. "
            "DOI: 10.37155/2717-5693-0301-22"
        )
        rec = Record(
            source="openalex",
            title="分析中医内科治疗胃食管反流病的临床效果",
            authors=["佳 李"],
            year=2022,
            journal="内科诊疗与进展",
            volume="3",
            issue="1",
            pages="52-54",
            doi="10.37155/2717-5693-0301-22",
            pmid=None,
            typ="journal-article",
            url="https://doi.org/10.37155/2717-5693-0301-22",
        )
        mm = compare_fields(cited, rec)
        self.assertFalse(any(m["field"] == "authors" for m in mm), mm)

    def test_related_title_without_authors_is_not_same_paper_fields(self):
        # 相近题名 + 期刊和年份都不符 + 库中无作者，应能被判定为「明显另一篇」所需字段
        cited = parse_one(
            "Flynn, M. (2014). The use of unmanned aerial vehicles in military operations: "
            "A review of the literature. Journal of Military and Strategic Studies, 16(2), 1-19."
        )
        rec = Record(
            source="crossref",
            title="UNMANNED AERIAL VEHICLES FOR MILITARY APPLICATIONS",
            authors=[],
            year=2016,
            journal="Theory, Design, and Applications of Unmanned Aerial Vehicles",
            volume=None,
            issue=None,
            pages="69-124",
            doi="10.1201/9781315371191-8",
            pmid=None,
            typ="book-chapter",
            url="https://doi.org/10.1201/9781315371191-8",
        )
        rec.title_sim = 0.80
        mm = compare_fields(cited, rec)
        fields = {m["field"] for m in mm}
        self.assertTrue("journal" in fields and "year" in fields, fields)


class Batch4ParserClasses(unittest.TestCase):
    def test_abstract_number_is_part_of_title(self):
        # Vancouver 题名以 P354. 这类文摘号开头，不能把后半句拆成作者
        cite = (
            "Zarate P, Ontiveros A, Velez J, Vales L, Ortega J. "
            "P354. Brain Hippocampal volume, Cortisol and C-Reactive Protein Levels "
            "Relationship With Antidepressant Response in Patients With Major Depressive Disorder. "
            "Biological Psychiatry. 2022;91(9):S230-S231. doi: 10.1016/j.biopsych.2022.02.590"
        )
        ref = parse_one(cite)
        self.assertTrue((ref.title or "").startswith("P354"), ref.title)
        self.assertIn("Hippocampal", ref.title or "")
        joined = " ".join(ref.authors)
        self.assertIn("Zarate", joined)
        self.assertNotIn("Cortisol", joined)

    def test_hyphenated_issue_range_is_not_volume(self):
        cite = (
            "Azadi-Chegeni F, Schiphorst C, Pandit A. In vivo NMR as a tool for probing "
            "molecular structure and dynamics in intact Chlamydomonas reinhardtii cells[J]. "
            "Photosynthesis Research, 2018, 135(1-3): 227-237. DOI: 10.1007/s11120-017-0412-9"
        )
        ref = parse_one(cite)
        self.assertEqual(ref.volume, "135")
        self.assertEqual(ref.issue, "1-3")
        self.assertEqual(ref.pages, "227-237")

    def test_electronic_page_suffix_is_compatible(self):
        cited = parse_one(
            "Guarnera, E., & Berezovsky, I. N. (2019). Toward Comprehensive Allosteric "
            "Control over Protein Activity. Structure, 27(5), 866-878.e1. "
            "https://doi.org/10.1016/j.str.2019.01.014"
        )
        rec = Record(
            source="crossref",
            title="Toward Comprehensive Allosteric Control over Protein Activity",
            authors=["Enrico Guarnera", "Igor N. Berezovsky"],
            year=2019,
            journal="Structure",
            volume="27",
            issue="5",
            pages="866-878.e1",
            doi="10.1016/j.str.2019.01.014",
        )
        self.assertTrue(pages_compatible(cited.pages, rec.pages), cited.pages)
        self.assertFalse(any(m["field"] == "pages" for m in compare_fields(cited, rec)), compare_fields(cited, rec))

    def test_null_volume_token_is_missing_not_pages(self):
        cite = (
            "Kim Hani, & Jeong (2016). Exploring factors and consequences of political "
            "attitude polarization and animosity: focusing on communication, political "
            "participation and social capital. Journal of Political Communication, null(43), "
            "45-82. https://doi.org/10.35731/kpca.2016..43.002"
        )
        ref = parse_one(cite)
        self.assertNotEqual(ref.volume, "45-82")
        self.assertIsNone(ref.volume)
        self.assertEqual(ref.issue, "43")
        self.assertEqual(ref.pages, "45-82")
        self.assertEqual(ref.journal, "Journal of Political Communication")
        rec = Record(
            source="crossref",
            title=ref.title,
            authors=["Kim Hani", "정낙원"],
            year=2016,
            journal="Journal of Political Communication",
            volume="null",
            issue="43",
            pages="45-82",
            doi="10.35731/kpca.2016..43.002",
        )
        mm = compare_fields(ref, rec)
        self.assertFalse(any(m["field"] in {"volume", "journal", "pages"} for m in mm), mm)



    def test_repeated_same_page_is_compatible(self):
        self.assertTrue(pages_compatible("27-27", "27"))
        self.assertTrue(pages_compatible("27", "27-27"))
        self.assertFalse(pages_compatible("27-28", "27"))
        cited = parse_one(
            "官华 李 (2019). 消化内科临床不合理用药的研究对策与分析. 亚洲临床医学杂志, 2(3), 27-27. "
            "https://doi.org/10.26549/yzlcyxzz.v2i3.2009"
        )
        rec = Record(
            source="crossref",
            title="消化内科临床不合理用药的研究对策与分析",
            authors=["李 官华"],
            year=2019,
            journal="亚洲临床医学杂志",
            volume="2",
            issue="3",
            pages="27",
            doi="10.26549/yzlcyxzz.v2i3.2009",
        )
        self.assertFalse(any(m["field"]=="pages" for m in compare_fields(cited, rec)), compare_fields(cited, rec))

    def test_cjk_journal_not_ignored_against_other_journal_pinyin(self):
        self.assertTrue(looks_like_romanized_cjk_journal("Guoji yiyao weisheng daobao"))
        self.assertFalse(looks_like_romanized_cjk_journal("Chin J Postgrad Med"))
        cited = parse_one(
            "陈素娟 (2006). 中西医结合治疗月经过多的临床研究. 中华内科杂志, 12(14), 109-111. "
            "https://doi.org/10.3760/cma.j.issn.1007-1245.2006.14.057"
        )
        rec = Record(
            source="openalex",
            title="中西医结合治疗月经过多的临床研究",
            authors=["陈素娟"],
            year=2006,
            journal="Guoji yiyao weisheng daobao",
            volume="12",
            issue="14",
            pages="109-111",
            doi="10.3760/cma.j.issn.1007-1245.2006.14.057",
        )
        mm = compare_fields(cited, rec)
        self.assertTrue(any(m["field"]=="journal" for m in mm), mm)
        # 中文刊名对英文缩写、DOI+题名锁定，仍不记不符（官方 20 第 6 条同类）
        rec2 = Record(
            source="crossref",
            title="药物降低静息心率治疗心血管疾病现状",
            authors=["李巧元", "柳景华"],
            year=2010,
            journal="Chin J Postgrad Med",
            volume="33",
            issue="34",
            pages="74-76",
            doi="10.3760/cma.j.issn.1673-4904.2010.34.031",
        )
        cited2 = parse_one(
            "李巧元, 柳景华. 药物降低静息心率治疗心血管疾病现状[J]. 中国医师进修杂志, 2010, 33(34): 74-76. "
            "DOI: 10.3760/cma.j.issn.1673-4904.2010.34.031"
        )
        mm2 = compare_fields(cited2, rec2)
        self.assertFalse(any(m["field"]=="journal" for m in mm2), mm2)


class UVWXAndFormatFixes(unittest.TestCase):
    def test_title_only_unbracketed_year_range_is_not_publication_year(self):
        ref = parse_one(
            "Intragenerational occupational mobility of South Korea, 1998–2017: "
            "Implications of the gendered life course approach for mobility and inequality studies"
        )
        self.assertIsNone(ref.year)
        self.assertIn("Intragenerational occupational mobility", ref.title or "")
        self.assertEqual(ref.authors, [])

    def test_apa_volume_and_article_number(self):
        ref = parse_one(
            "Ullrich, S., Thriene, K., Binder, N., Amend, L., Strowig, T., & Michels, K. (2021). "
            "Influence of Fermented Vegetable Consumption on Gut Microbiome Diversity. "
            "Current Developments in Nutrition, 5, 1188. https://doi.org/10.1093/cdn/nzab054_043"
        )
        self.assertEqual(ref.volume, "5")
        self.assertEqual(ref.pages, "1188")
        rec = Record(
            source="crossref",
            title=ref.title,
            authors=["Ullrich Sina", "Thriene Kerstin", "Michels Karin"],
            year=2021,
            journal="Current Developments in Nutrition",
            volume="5",
            pages="1188",
            doi="10.1093/cdn/nzab054_043",
        )
        self.assertFalse(any(m["field"] in {"volume", "pages"} for m in compare_fields(ref, rec)), compare_fields(ref, rec))

    def test_decimal_abstract_pages_and_supplement_issue(self):
        ref = parse_one(
            "Owen, D. L., LaRue, R., & Farrar, M. A. (2021). "
            "Developing a model of thymic regulatory T cell development with single-cell RNA sequencing. "
            "The Journal of Immunology, 206(1_Supplement), 108.11-108.11. "
            "https://doi.org/10.4049/jimmunol.206.supp.108.11"
        )
        self.assertEqual(ref.volume, "206")
        self.assertIn("Supplement", ref.issue or "")
        self.assertEqual(ref.pages, "108.11-108.11")
        self.assertTrue(pages_compatible("108.11-108.11", "108.11-108.11"))
        rec = Record(
            source="crossref",
            title=ref.title,
            authors=["Owen David L", "LaRue Rebecca", "Farrar Michael A"],
            year=2021,
            journal="The Journal of Immunology",
            volume="206",
            issue="1_Supplement",
            pages="108.11-108.11",
            doi="10.4049/jimmunol.206.supp.108.11",
        )
        self.assertEqual(compare_fields(ref, rec), [])

    def test_cjk_jammed_author_field_is_compatible(self):
        ref = parse_one(
            "林惠京，刘芳芳，黄女娜柯琼菲 (2024). "
            "加味黄连温胆汤“异病同治”2型糖尿病和高脂血症的网络药理学及分子对接分析. "
            "医学研究, 1(11). https://doi.org/10.69979/3029-2808.24.11.011"
        )
        rec = Record(
            source="crossref",
            title=ref.title,
            authors=["林惠京，刘芳芳，黄女娜 柯琼菲"],
            year=2024,
            journal="医学研究",
            volume="1",
            issue="11",
            doi="10.69979/3029-2808.24.11.011",
        )
        mm = compare_fields(ref, rec)
        self.assertFalse(any(m["field"]=="authors" for m in mm), mm)

    def test_short_generic_title_same_journal_is_other_work(self):
        cited = parse_one("Geen, R. G. (2001). Human aggression. Annual Review of Psychology, 52, 21-41.")
        rec = Record(
            source="openalex",
            title="Human Aggression",
            authors=["Craig A. Anderson", "Brad J. Bushman"],
            year=2002,
            journal="Annual Review of Psychology",
            volume="53",
            issue="1",
            pages="27-51",
            doi="10.1146/annurev.psych.53.100901.135231",
        )
        fields = {m["field"] for m in compare_fields(cited, rec)}
        self.assertIn("authors", fields)
        self.assertTrue(is_clearly_other_work(cited, rec, fields, title_is_strong=True))

    def test_single_field_tamper_is_not_other_work(self):
        cited = parse_one(
            "Vaswani, A., Shazeer, N., Parmar, N., Uszkoreit, J., Jones, L., Gomez, A. N., Kaiser, L., & Polosukhin, I. "
            "(2018). Attention is all you need. Nature, 30. https://doi.org/10.5555/3295222.3295349"
        )
        rec = Record(
            source="crossref",
            title="Attention is all you need",
            authors=["Ashish Vaswani", "Noam Shazeer", "Niki Parmar"],
            year=2017,
            journal="Advances in Neural Information Processing Systems",
            volume="30",
            doi="10.5555/3295222.3295349",
        )
        # 期刊被改且年份也不同，但 DOI 锁定同一篇，不得当另一篇
        fields = {m["field"] for m in compare_fields(cited, rec)}
        self.assertFalse(is_clearly_other_work(cited, rec, fields, title_is_strong=True), fields)

    def test_bibtex_and_ieee_and_mla_fields(self):
        bib = parse_one(
            "@article{u2021, title={Influence of Fermented Vegetable Consumption on Gut Microbiome Diversity}, "
            "author={Ullrich, Sina and Thriene, Kerstin}, journal={Current Developments in Nutrition}, "
            "volume={5}, pages={1188}, year={2021}, doi={10.1093/cdn/nzab054_043}}"
        )
        self.assertEqual(bib.year, 2021)
        self.assertEqual(bib.volume, "5")
        self.assertEqual(bib.pages, "1188")
        self.assertEqual(bib.doi, "10.1093/cdn/nzab054_043")
        self.assertIn("Ullrich", bib.authors[0])
        ieee = parse_one(
            'S. Ullrich, K. Thriene, and K. Michels, '
            '"Influence of Fermented Vegetable Consumption on Gut Microbiome Diversity," '
            "Current Developments in Nutrition, vol. 5, p. 1188, 2021, "
            "doi: 10.1093/cdn/nzab054_043."
        )
        self.assertEqual(ieee.year, 2021)
        self.assertEqual(ieee.volume, "5")
        self.assertEqual(ieee.pages, "1188")
        self.assertIn("Ullrich", " ".join(ieee.authors))
        mla = parse_one(
            'Ullrich, Sina, et al. "Influence of Fermented Vegetable Consumption on Gut Microbiome Diversity." '
            "Current Developments in Nutrition, vol. 5, 2021, p. 1188, "
            "https://doi.org/10.1093/cdn/nzab054_043."
        )
        self.assertEqual(mla.year, 2021)
        self.assertEqual(mla.volume, "5")
        self.assertEqual(mla.pages, "1188")


    def test_gbt_year_is_not_taken_as_volume(self):
        ref = parse_one(
            "Schirber M. A Quantum Entanglement Assembly Line[J]. Physics, 2022, 15. DOI: 10.1103/physics.15.s135"
        )
        self.assertEqual(ref.year, 2022)
        self.assertEqual(ref.volume, "15")
        self.assertIsNone(ref.pages)
        rec = Record(
            source="crossref",
            title="A Quantum Entanglement Assembly Line",
            authors=["Schirber Michael"],
            year=2022,
            journal="Physics",
            volume="15",
            doi="10.1103/physics.15.s135",
        )
        self.assertFalse(any(m["field"]=="volume" for m in compare_fields(ref, rec)), compare_fields(ref, rec))

    def test_bibtex_authors_are_not_overwritten(self):
        ref = parse_one(
            "@article{li2006, title={重型颅脑损伤中西医结合治疗的临床研究}, "
            "author={李卫贤 and 魏璐城 and 邝英桥}, journal={中国医师杂志}, "
            "year={2006}, volume={8}, number={11}, pages={1510-1511}, "
            "doi={10.3760/cma.j.issn.1008-1372.2006.11.029}}"
        )
        self.assertEqual(ref.authors, ["李卫贤", "魏璐城", "邝英桥"])
        self.assertEqual(ref.volume, "8")
        self.assertEqual(ref.issue, "11")

    def test_chinese_ieee_quoted_title(self):
        ref = parse_one(
            '王城, "血管内介入治疗技术在缺血性脑血管疾病中的应用效果," '
            "亚洲临床医学杂志, vol. 3, no. 7, p. 29, 2021, "
            "doi: 10.26549/yzlcyxzz.v3i7.6224."
        )
        self.assertIn("血管内介入治疗技术", ref.title or "")
        self.assertIn("亚洲临床医学杂志", ref.journal or "")
        self.assertEqual(ref.volume, "3")
        self.assertEqual(ref.issue, "7")
        self.assertEqual(ref.pages, "29")
        self.assertEqual(ref.year, 2021)
        self.assertTrue(any("王城" in a or a=="王城" for a in ref.authors), ref.authors)



if __name__ == "__main__":
    unittest.main(verbosity=2)
