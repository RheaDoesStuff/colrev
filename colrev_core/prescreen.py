#! /usr/bin/env python
import csv
import logging
import pprint
from pathlib import Path

import pandas as pd

from colrev_core.review_manager import RecordState

report_logger = logging.getLogger("colrev_core_report")
logger = logging.getLogger("colrev_core")
pp = pprint.PrettyPrinter(indent=4, width=140)


def export_table(REVIEW_MANAGER, export_table_format: str) -> None:

    bib_db = REVIEW_MANAGER.load_bib_db()

    tbl = []
    for record in bib_db.entries:

        inclusion_1, inclusion_2 = "NA", "NA"

        if RecordState.md_retrieved == record["status"]:
            inclusion_1 = "TODO"
        if RecordState.rev_prescreen_excluded == record["status"]:
            inclusion_1 = "no"
        else:
            inclusion_1 = "yes"
            inclusion_2 = "TODO"
            if RecordState.rev_excluded == record["status"]:
                inclusion_2 = "no"
            if record["status"] in [
                RecordState.rev_included,
                RecordState.rev_synthesized,
            ]:
                inclusion_2 = "yes"

        excl_criteria = {}
        if "excl_criteria" in record:
            for ecrit in record["excl_criteria"].split(";"):
                criteria = {ecrit.split("=")[0]: ecrit.split("=")[1]}
                excl_criteria.update(criteria)

        row = {
            "ID": record["ID"],
            "author": record.get("author", ""),
            "title": record.get("title", ""),
            "journal": record.get("journal", ""),
            "booktitle": record.get("booktitle", ""),
            "year": record.get("year", ""),
            "volume": record.get("volume", ""),
            "number": record.get("number", ""),
            "pages": record.get("pages", ""),
            "doi": record.get("doi", ""),
            "abstract": record.get("abstract", ""),
            "inclusion_1": inclusion_1,
            "inclusion_2": inclusion_2,
        }
        row.update(excl_criteria)
        tbl.append(row)

    if "csv" == export_table_format.lower():
        screen_df = pd.DataFrame(tbl)
        screen_df.to_csv("screen_table.csv", index=False, quoting=csv.QUOTE_ALL)
        logger.info("Created screen_table (csv)")

    if "xlsx" == export_table_format.lower():
        screen_df = pd.DataFrame(tbl)
        screen_df.to_excel("screen_table.xlsx", index=False, sheet_name="screen")
        logger.info("Created screen_table (xlsx)")

    return


def import_table(REVIEW_MANAGER, import_table_path: str) -> None:

    bib_db = REVIEW_MANAGER.load_bib_db()
    if not Path(import_table_path).is_file():
        logger.error(f"Did not find {import_table_path} - exiting.")
        return
    screen_df = pd.read_csv(import_table_path)
    screen_df.fillna("", inplace=True)
    records = screen_df.to_dict("records")

    logger.warning("import_table not completed (exclusion_criteria not yet imported)")

    for x in [
        [x.get("ID", ""), x.get("inclusion_1", ""), x.get("inclusion_2", "")]
        for x in records
    ]:
        record = [e for e in bib_db.entries if e["ID"] == x[0]]
        if len(record) == 1:
            record = record[0]
            if x[1] == "no":
                record["status"] = RecordState.rev_prescreen_excluded
            if x[1] == "yes":
                record["status"] = RecordState.rev_prescreen_included
            if x[2] == "no":
                record["status"] = RecordState.rev_excluded
            if x[2] == "yes":
                record["status"] = RecordState.rev_included
            # TODO: exclusion-criteria

    REVIEW_MANAGER.save_bib_db(bib_db)

    return


def include_all_in_prescreen(REVIEW_MANAGER) -> None:

    bib_db = REVIEW_MANAGER.load_bib_db()

    saved_args = locals()
    PAD = 50  # TODO
    for record in bib_db.entries:
        if record["status"] in [RecordState.md_retrieved, RecordState.md_processed]:
            continue
        report_logger.info(
            f' {record["ID"]}'.ljust(PAD, " ") + "Included in prescreen (automatically)"
        )
        record.update(status=RecordState.rev_prescreen_included)

    REVIEW_MANAGER.save_bib_db(bib_db)
    git_repo = REVIEW_MANAGER.get_repo()
    git_repo.index.add([str(REVIEW_MANAGER.paths["MAIN_REFERENCES_RELATIVE"])])
    REVIEW_MANAGER.create_commit(
        "Pre-screening (manual)", manual_author=False, saved_args=saved_args
    )

    return


def get_data(REVIEW_MANAGER) -> dict:
    from colrev_core.review_manager import Process, ProcessType

    REVIEW_MANAGER.notify(Process(ProcessType.prescreen))

    record_state_list = REVIEW_MANAGER.get_record_state_list()
    nr_tasks = len(
        [x for x in record_state_list if str(RecordState.md_processed) == x[1]]
    )
    PAD = min((max(len(x[0]) for x in record_state_list) + 2), 40)
    items = REVIEW_MANAGER.read_next_record(
        conditions={"status": str(RecordState.md_processed)}
    )
    prescreen_data = {"nr_tasks": nr_tasks, "PAD": PAD, "items": items}
    logger.debug(pp.pformat(prescreen_data))
    return prescreen_data


def set_data(
    REVIEW_MANAGER, record: dict, prescreen_inclusion: bool, PAD: int = 40
) -> None:

    git_repo = REVIEW_MANAGER.get_repo()

    if prescreen_inclusion:
        report_logger.info(f" {record['ID']}".ljust(PAD, " ") + "Included in prescreen")
        REVIEW_MANAGER.replace_field(
            [record["ID"]], "status", str(RecordState.rev_prescreen_included)
        )
    else:
        report_logger.info(f" {record['ID']}".ljust(PAD, " ") + "Excluded in prescreen")
        REVIEW_MANAGER.replace_field(
            [record["ID"]], "status", str(RecordState.rev_prescreen_excluded)
        )

    git_repo.index.add([str(REVIEW_MANAGER.paths["MAIN_REFERENCES_RELATIVE"])])

    return