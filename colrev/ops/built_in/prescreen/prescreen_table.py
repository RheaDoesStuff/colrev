#! /usr/bin/env python
"""Prescreen based on a table"""
from __future__ import annotations

import csv
import typing
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import zope.interface
from dacite import from_dict
from dataclasses_jsonschema import JsonSchemaMixin

import colrev.env.package_manager
import colrev.record
import colrev.ui_cli.cli_colors as colors

if typing.TYPE_CHECKING:
    import colrev.ops.prescreen.Prescreen

# pylint: disable=too-few-public-methods
# pylint: disable=duplicate-code


@zope.interface.implementer(
    colrev.env.package_manager.PrescreenPackageEndpointInterface
)
@dataclass
class TablePrescreen(JsonSchemaMixin):

    """Prescreen based on a table (exported and imported)"""

    settings_class = colrev.env.package_manager.DefaultSettings

    def __init__(
        self,
        *,
        prescreen_operation: colrev.ops.prescreen.Prescreen,  # pylint: disable=unused-argument
        settings: dict,
    ) -> None:
        self.settings = from_dict(data_class=self.settings_class, data=settings)

    def export_table(
        self,
        *,
        prescreen_operation: colrev.ops.prescreen.Prescreen,
        records: dict,
        split: list,
        export_table_format: str = "csv",
    ) -> None:
        """Export a prescreen table"""

        # gh_issue https://github.com/geritwagner/colrev/issues/73
        # add delta (records not yet in the table)
        # instead of overwriting
        # export_table_format as a settings parameter

        prescreen_operation.review_manager.logger.info("Loading records for export")

        tbl = []
        for record in records.values():

            if record["colrev_status"] not in [
                colrev.record.RecordState.md_processed,
                colrev.record.RecordState.rev_prescreen_excluded,
                colrev.record.RecordState.rev_prescreen_included,
                colrev.record.RecordState.pdf_needs_manual_retrieval,
                colrev.record.RecordState.pdf_imported,
                colrev.record.RecordState.pdf_not_available,
                colrev.record.RecordState.pdf_needs_manual_preparation,
                colrev.record.RecordState.pdf_prepared,
                colrev.record.RecordState.rev_excluded,
                colrev.record.RecordState.rev_included,
                colrev.record.RecordState.rev_synthesized,
            ]:
                continue

            if len(split) > 0:
                if record["ID"] not in split:
                    continue

            if colrev.record.RecordState.md_processed == record["colrev_status"]:
                inclusion_1 = "TODO"
            elif (
                colrev.record.RecordState.rev_prescreen_excluded
                == record["colrev_status"]
            ):
                inclusion_1 = "no"
            else:
                inclusion_1 = "yes"

            # pylint: disable=duplicate-code
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
                "presceen_inclusion": inclusion_1,
            }
            tbl.append(row)

        if "csv" == export_table_format.lower():
            screen_df = pd.DataFrame(tbl)
            screen_df.to_csv("prescreen.csv", index=False, quoting=csv.QUOTE_ALL)
            prescreen_operation.review_manager.logger.info("Created prescreen.csv")

        if "xlsx" == export_table_format.lower():
            screen_df = pd.DataFrame(tbl)
            screen_df.to_excel("prescreen.xlsx", index=False, sheet_name="screen")
            prescreen_operation.review_manager.logger.info("Created prescreen.xlsx")

    def import_table(
        self,
        *,
        prescreen_operation: colrev.ops.prescreen.Prescreen,
        records: dict,
        import_table_path: str = "prescreen.csv",
    ) -> None:
        """Import a prescreen table"""

        prescreen_operation.review_manager.logger.info(f"Load {import_table_path}")

        # pylint: disable=duplicate-code
        if not Path(import_table_path).is_file():
            prescreen_operation.review_manager.logger.error(
                f"Did not find {import_table_path} - exiting."
            )
            return
        prescreen_df = pd.read_csv(import_table_path)
        prescreen_df.fillna("", inplace=True)
        prescreened_records = prescreen_df.to_dict("records")

        if "presceen_inclusion" not in prescreened_records[0]:
            prescreen_operation.review_manager.logger.warning(
                "presceen_inclusion column missing"
            )
            return

        prescreen_included = 0
        prescreen_excluded = 0
        nr_todo = 0
        prescreen_operation.review_manager.logger.info("Update prescreen results")
        for prescreened_record in prescreened_records:
            if prescreened_record.get("ID", "") in records:
                record = records[prescreened_record.get("ID", "")]

                if "no" == prescreened_record.get("presceen_inclusion", ""):
                    if (
                        record["colrev_status"]
                        != colrev.record.RecordState.rev_prescreen_excluded
                    ):
                        prescreen_excluded += 1
                    record[
                        "colrev_status"
                    ] = colrev.record.RecordState.rev_prescreen_excluded

                elif "yes" == prescreened_record.get("presceen_inclusion", ""):
                    if (
                        record["colrev_status"]
                        != colrev.record.RecordState.rev_prescreen_included
                    ):
                        prescreen_included += 1
                    record[
                        "colrev_status"
                    ] = colrev.record.RecordState.rev_prescreen_included
                elif "TODO" == prescreened_record.get("presceen_inclusion", ""):
                    nr_todo += 1
                else:
                    prescreen_operation.review_manager.logger.warning(
                        "Invalid value in prescreen_inclusion: "
                        f"{prescreened_record.get('presceen_inclusion', '')} "
                        f"({prescreened_record.get('ID', 'NO_ID')})"
                    )

            else:
                prescreen_operation.review_manager.logger.warning(
                    f"ID not in records: {prescreened_record.get('ID', '')}"
                )

        prescreen_operation.review_manager.logger.info(
            f" {colors.GREEN}{prescreen_included} records prescreen_included{colors.END}"
        )
        prescreen_operation.review_manager.logger.info(
            f" {colors.RED}{prescreen_excluded} records prescreen_excluded{colors.END}"
        )

        prescreen_operation.review_manager.logger.info(
            f" {colors.ORANGE}{nr_todo} records to prescreen{colors.END}"
        )

        prescreen_operation.review_manager.dataset.save_records_dict(records=records)
        prescreen_operation.review_manager.dataset.add_record_changes()

        prescreen_operation.review_manager.logger.info("Completed import")

    def run_prescreen(
        self,
        prescreen_operation: colrev.ops.prescreen.Prescreen,
        records: dict,
        split: list,
    ) -> dict:
        """Prescreen records based on screening tables"""

        if "y" == input("create prescreen table [y,n]?"):
            self.export_table(
                prescreen_operation=prescreen_operation, records=records, split=split
            )

        if "y" == input("import prescreen table [y,n]?"):
            self.import_table(prescreen_operation=prescreen_operation, records=records)

        if prescreen_operation.review_manager.dataset.has_changes():
            if "y" == input("create commit [y,n]?"):
                prescreen_operation.review_manager.create_commit(
                    msg="Pre-screen (table)",
                    manual_author=True,
                    script_call="colrev prescreen",
                )
        return records


if __name__ == "__main__":
    pass
