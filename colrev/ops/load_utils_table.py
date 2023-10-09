#! /usr/bin/env python
"""Convenience functions to load tabular files (csv, xlsx)"""
from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

import colrev.env.package_manager
import colrev.exceptions as colrev_exceptions
import colrev.settings

if TYPE_CHECKING:
    import colrev.ops.load

# pylint: disable=too-few-public-methods
# pylint: disable=unused-argument
# pylint: disable=duplicate-code


class TableLoadUtility:
    """Utility for tables loading"""

    @classmethod
    def __rename_fields(cls, *, record_dict: dict) -> dict:
        if "issue" in record_dict and "number" not in record_dict:
            record_dict["number"] = record_dict["issue"]
            if record_dict["number"] == "no issue":
                del record_dict["number"]
            del record_dict["issue"]

        if "authors" in record_dict and "author" not in record_dict:
            record_dict["author"] = record_dict["authors"]
            del record_dict["authors"]

        if "publication_year" in record_dict and "year" not in record_dict:
            record_dict["year"] = record_dict["publication_year"]
            del record_dict["publication_year"]

        # Note: this is a simple heuristic:
        if (
            "journal/book" in record_dict
            and "journal" not in record_dict
            and "doi" in record_dict
        ):
            record_dict["journal"] = record_dict["journal/book"]
            del record_dict["journal/book"]

        return record_dict

    @classmethod
    def __set_entrytype(cls, *, record_dict: dict) -> dict:
        record_dict["ENTRYTYPE"] = "misc"
        if "type" in record_dict:
            record_dict["ENTRYTYPE"] = record_dict["type"]
            del record_dict["type"]
            if record_dict["ENTRYTYPE"] == "inproceedings":
                if "journal" in record_dict and "booktitle" not in record_dict:
                    record_dict["booktitle"] = record_dict["journal"]
                    del record_dict["journal"]
            if record_dict["ENTRYTYPE"] == "article":
                if "booktitle" in record_dict and "journal" not in record_dict:
                    record_dict["journal"] = record_dict["booktitle"]
                    del record_dict["booktitle"]

        if "ENTRYTYPE" not in record_dict:
            if record_dict.get("journal", "") != "":
                record_dict["ENTRYTYPE"] = "article"
            if record_dict.get("booktitle", "") != "":
                record_dict["ENTRYTYPE"] = "inproceedings"
        return record_dict

    @classmethod
    def __parse_record_dict(cls, *, record_dict: dict) -> dict:
        record_dict = cls.__set_entrytype(record_dict=record_dict)

        for key, value in record_dict.items():
            record_dict[key] = str(value)

        record_dict = cls.__rename_fields(record_dict=record_dict)

        return record_dict

    @classmethod
    def __get_records_dict(cls, *, records: list) -> dict:
        next_id = 1
        for record_dict in records:
            if "ID" not in record_dict:
                if "citation_key" in record_dict:
                    record_dict["ID"] = record_dict["citation_key"]
                else:
                    record_dict["ID"] = next_id
                    next_id += 1
            record_dict = cls.__parse_record_dict(record_dict=record_dict)

        if all("ID" in r for r in records):
            records_dict = {r["ID"]: r for r in records}
        else:
            records_dict = {}
            for i, record in enumerate(records):
                records_dict[str(i)] = record

        return records_dict

    @classmethod
    def __drop_fields(cls, *, records_dict: dict) -> dict:
        for r_dict in records_dict.values():
            for key in list(r_dict.keys()):
                if r_dict[key] in [f"no {key}", "", "nan"]:
                    del r_dict[key]
            if (
                r_dict.get("number_of_cited_references", "NA")
                == "no Number-of-Cited-References"
            ):
                del r_dict["number_of_cited_references"]
            if "no file" in r_dict.get("file_name", "NA"):
                del r_dict["file_name"]

            if r_dict.get("cited_by", "NA") in [
                "no Times-Cited",
            ]:
                del r_dict["cited_by"]

            if "author_count" in r_dict:
                del r_dict["author_count"]
            if "entrytype" in r_dict:
                del r_dict["entrytype"]
            if "citation_key" in r_dict:
                del r_dict["citation_key"]

        return records_dict

    @classmethod
    def __fix_authors(cls, *, records_dict: dict) -> dict:
        for record in records_dict.values():
            if "author" in record and ";" in record["author"]:
                record["author"] = record["author"].replace("; ", " and ")
        return records_dict

    @classmethod
    def preprocess_records(cls, *, records: list) -> dict:
        """Preprocess records imported from a table"""

        records_dict = cls.__get_records_dict(records=records)
        records_dict = cls.__drop_fields(records_dict=records_dict)
        records_dict = cls.__fix_authors(records_dict=records_dict)

        return records_dict


class CSVLoader:

    """Loads csv files (based on pandas)"""

    def __init__(
        self,
        *,
        load_operation: colrev.ops.load.Load,
        source: colrev.settings.SearchSource,
        unique_id_field: str = "",
    ):
        self.load_operation = load_operation
        self.source = source
        self.unique_id_field = unique_id_field

    def load_table_entries(self) -> dict:
        """Load table entries from the source"""

        if self.unique_id_field == "":
            self.load_operation.ensure_append_only(file=self.source.filename)
        # TODO : else: plausibility check: the old uique_ids should still be available

        try:
            data = pd.read_csv(self.source.filename)
        except pd.errors.ParserError as exc:
            raise colrev_exceptions.ImportException(
                f"Error: Not a csv file? {self.source.filename.name}"
            ) from exc

        data.columns = data.columns.str.replace(" ", "_")
        data.columns = data.columns.str.replace("-", "_")
        data.columns = data.columns.str.lower()
        records_value_list = data.to_dict("records")

        records_dict = TableLoadUtility.preprocess_records(records=records_value_list)
        return records_dict

    def convert_to_records(self, *, entries: dict) -> dict:
        """Converts table entries it to bib records"""

        for i, record in enumerate(entries.values()):
            if self.unique_id_field == "":
                _id = str(i + 1).zfill(6)
            else:
                _id = record[self.unique_id_field].replace(" ", "").replace(";", "_")
            record["ID"] = _id

        records = {r["ID"]: r for r in entries.values()}

        return records


class ExcelLoader:
    """Loads Excel (xls, xlsx) files (based on pandas)"""

    def __init__(
        self,
        *,
        load_operation: colrev.ops.load.Load,
        source: colrev.settings.SearchSource,
        unique_id_field: str = "",
    ):
        self.load_operation = load_operation
        self.source = source
        self.unique_id_field = unique_id_field

    def load_table_entries(self) -> dict:
        """Load records from the source"""

        if self.unique_id_field == "":
            self.load_operation.ensure_append_only(file=self.source.filename)

        try:
            data = pd.read_excel(
                self.source.filename, dtype=str
            )  # dtype=str to avoid type casting
        except pd.errors.ParserError:
            self.load_operation.review_manager.logger.error(
                f"Error: Not an xlsx file: {self.source.filename.name}"
            )
            return {}

        data.columns = data.columns.str.replace(" ", "_")
        data.columns = data.columns.str.replace("-", "_")
        data.columns = data.columns.str.lower()
        record_value_list = data.to_dict("records")
        records_dict = TableLoadUtility.preprocess_records(records=record_value_list)
        return records_dict

    def convert_to_records(self, *, entries: dict) -> dict:
        """Converts table entries it to bib records"""

        for i, record in enumerate(entries.values()):
            if self.unique_id_field == "":
                _id = str(i + 1).zfill(6)
            else:
                _id = record[self.unique_id_field].replace(" ", "").replace(";", "_")
            record["ID"] = _id

        records = {r["ID"]: r for r in entries.values()}

        return records