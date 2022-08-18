#! /usr/bin/env python
import re
import typing
from collections import Counter
from pathlib import Path

import git
import pandas as pd

import colrev.built_in.dedupe_built_in as built_in_dedupe
import colrev.exceptions as colrev_exceptions
import colrev.process
import colrev.record


class Dedupe(colrev.process.Process):

    built_in_scripts: typing.Dict[str, typing.Dict[str, typing.Any]] = {
        "simple_dedupe": {
            "endpoint": built_in_dedupe.SimpleDedupeEndpoint,
        },
        "active_learning_training": {
            "endpoint": built_in_dedupe.ActiveLearningDedupeTrainingEndpoint,
        },
        "active_learning_automated": {
            "endpoint": built_in_dedupe.ActiveLearningDedupeAutomatedEndpoint,
        },
        "curation_full_outlet_dedupe": {
            "endpoint": built_in_dedupe.CurationDedupeEndpoint,
        },
        "curation_missing_dedupe": {
            "endpoint": built_in_dedupe.CurationMissingDedupeEndpoint,
        },
    }

    SIMPLE_SIMILARITY_BASED_DEDUPE = "simple_similarity_based_dedupe"
    ACTIVE_LEARNING_DEDUPE = "active_learning_dedupe"
    ACTIVE_LEARNING_NON_MEMORY_DEDUPE = "active_learning_non_memory_dedupe"

    def __init__(
        self,
        *,
        REVIEW_MANAGER,
        notify_state_transition_process=True,
    ):

        super().__init__(
            REVIEW_MANAGER=REVIEW_MANAGER,
            process_type=colrev.process.ProcessType.dedupe,
            notify_state_transition_process=notify_state_transition_process,
        )

        self.training_file = self.REVIEW_MANAGER.path / Path(
            ".records_dedupe_training.json"
        )
        self.settings_file = self.REVIEW_MANAGER.path / Path(
            ".records_learned_settings"
        )
        self.non_dupe_file_xlsx = self.REVIEW_MANAGER.path / Path(
            "non_duplicates_to_validate.xlsx"
        )
        self.non_dupe_file_txt = self.REVIEW_MANAGER.path / Path("dupes.txt")
        self.dupe_file = self.REVIEW_MANAGER.path / Path("duplicates_to_validate.xlsx")
        self.source_comparison_xlsx = self.REVIEW_MANAGER.path / Path(
            "source_comparison.xlsx"
        )

        self.REVIEW_MANAGER.report_logger.info("Dedupe")
        self.REVIEW_MANAGER.logger.info("Dedupe")

    def prep_records(self, *, records_df: pd.DataFrame) -> dict:
        def preProcess(*, key, value):
            if key in ["ID", "ENTRYTYPE", "colrev_status", "colrev_origin"]:
                return value

            value = str(value)
            if any(
                value == x
                for x in ["no issue", "no volume", "no pages", "no author", "nan"]
            ):
                value = None
                return value

            # Note unidecode may be an alternative to rmdiacritics/remove_accents.
            # It would be important to operate on a per-character basis
            # instead of throwing an exception when processing whole strings
            # value = unidecode(value)
            value = re.sub("  +", " ", value)
            value = re.sub("\n", " ", value)
            value = value.strip().strip('"').strip("'").lower().strip()
            # If data is missing, indicate that by setting the value to `None`
            if not value:
                value = None
            return value

        if "colrev_status" in records_df:
            records_df["colrev_status"] = records_df["colrev_status"].astype(str)

        if "volume" not in records_df:
            records_df["volume"] = "nan"
        if "number" not in records_df:
            records_df["number"] = "nan"
        if "pages" not in records_df:
            records_df["pages"] = "nan"
        if "year" not in records_df:
            records_df["year"] = "nan"
        else:
            records_df["year"] = records_df["year"].astype(str)
        if "author" not in records_df:
            records_df["author"] = "nan"

        records_df["author"] = records_df["author"].str[:60]

        records_df.loc[
            records_df.ENTRYTYPE == "inbook", "container_title"
        ] = records_df.loc[records_df.ENTRYTYPE == "inbook", "title"]
        if "chapter" in records_df:
            records_df.loc[records_df.ENTRYTYPE == "inbook", "title"] = records_df.loc[
                records_df.ENTRYTYPE == "inbook", "chapter"
            ]

        if "title" not in records_df:
            records_df["title"] = "nan"
        else:
            records_df["title"] = (
                records_df["title"]
                .str.replace(r"[^A-Za-z0-9, ]+", " ", regex=True)
                .str.lower()
            )
            records_df.loc[records_df["title"].isnull(), "title"] = "nan"

        if "journal" not in records_df:
            records_df["journal"] = ""
        else:
            records_df["journal"] = (
                records_df["journal"]
                .str.replace(r"[^A-Za-z0-9, ]+", "", regex=True)
                .str.lower()
            )
        if "booktitle" not in records_df:
            records_df["booktitle"] = ""
        else:
            records_df["booktitle"] = (
                records_df["booktitle"]
                .str.replace(r"[^A-Za-z0-9, ]+", "", regex=True)
                .str.lower()
            )

        if "series" not in records_df:
            records_df["series"] = ""
        else:
            records_df["series"] = (
                records_df["series"]
                .str.replace(r"[^A-Za-z0-9, ]+", "", regex=True)
                .str.lower()
            )

        records_df["container_title"] = (
            records_df["journal"].fillna("")
            + records_df["booktitle"].fillna("")
            + records_df["series"].fillna("")
        )

        # To validate/improve preparation in jupyter notebook:
        # return records_df
        # Copy to notebook:
        # from colrev.review_manager import ReviewManager
        # from colrev import dedupe
        # from colrev.process import Process, ProcessType
        # REVIEW_MANAGER = ReviewManager()
        # df = dedupe.readData(REVIEW_MANAGER)
        # EDITS
        # df.to_csv('export.csv', index=False)

        records_df.drop(
            labels=records_df.columns.difference(
                [
                    "ID",
                    "author",
                    "title",
                    "year",
                    "journal",
                    "container_title",
                    "volume",
                    "number",
                    "pages",
                    "colrev_id",
                    "colrev_origin",
                    "colrev_status",
                ]
            ),
            axis=1,
            inplace=True,
        )
        records_df[
            ["author", "title", "journal", "container_title", "pages"]
        ] = records_df[
            ["author", "title", "journal", "container_title", "pages"]
        ].astype(
            str
        )
        records_list = records_df.to_dict("records")
        self.REVIEW_MANAGER.logger.debug(self.REVIEW_MANAGER.pp.pformat(records_list))

        records = {}

        for row in records_list:
            # Note: we need the ID to identify/remove duplicates in the RECORDS_FILE.
            # It is ignored in the field-definitions by the deduper!
            # clean_row = [(k, preProcess(k, v)) for (k, v) in row.items() if k != "ID"]
            clean_row = [(k, preProcess(key=k, value=v)) for (k, v) in row.items()]
            records[row["ID"]] = dict(clean_row)

        return records

    def readData(self):

        records = self.REVIEW_MANAGER.REVIEW_DATASET.load_records_dict()

        # Note: Because we only introduce individual (non-merged records),
        # there should be no semicolons in colrev_origin!
        records_queue = [
            x
            for x in records.values()
            if x["colrev_status"]
            not in [
                colrev.record.RecordState.md_imported,
                colrev.record.RecordState.md_needs_manual_preparation,
            ]
        ]

        # Do not merge records with non_latin_alphabets:
        records_queue = [
            x
            for x in records_queue
            if not (
                colrev.record.RecordState.rev_prescreen_excluded == x["colrev_status"]
                and "script:non_latin_alphabet" == x.get("prescreen_exclusion", "")
            )
        ]

        for r in records_queue:
            try:
                RECORD = colrev.record.Record(data=r)
                r["colrev_id"] = RECORD.create_colrev_id()
            except colrev_exceptions.NotEnoughDataToIdentifyException:
                r["colrev_id"] = "NA"

        records_df = pd.DataFrame.from_dict(records_queue)
        records = self.prep_records(records_df=records_df)

        return records

    def select_primary_merge_record(self, rec_ID1, rec_ID2) -> list:

        # Heuristic

        # 1. if both records are prepared (or the same status),
        # merge into the record with the lower colrev_id
        if rec_ID1["colrev_status"] == rec_ID2["colrev_status"]:
            if rec_ID1["ID"][-1].isdigit() and not rec_ID2["ID"][-1].isdigit():
                main_record = rec_ID1
                dupe_record = rec_ID2
            # TODO : elif: check which of the appended letters is first in the alphabet
            else:
                main_record = rec_ID2
                dupe_record = rec_ID1

        # 2. If a record is md_prepared, use it as the dupe record
        elif rec_ID1["colrev_status"] == colrev.record.RecordState.md_prepared:
            main_record = rec_ID2
            dupe_record = rec_ID1
        elif rec_ID2["colrev_status"] == colrev.record.RecordState.md_prepared:
            main_record = rec_ID1
            dupe_record = rec_ID2

        # 3. If a record is md_processed, use the other record as the dupe record
        # -> during the fix_errors procedure, records are in md_processed
        # and beyond.
        elif rec_ID1["colrev_status"] == colrev.record.RecordState.md_processed:
            main_record = rec_ID1
            dupe_record = rec_ID2
        elif rec_ID2["colrev_status"] == colrev.record.RecordState.md_processed:
            main_record = rec_ID2
            dupe_record = rec_ID1

        # 4. Merge into curated record (otherwise)
        else:
            if colrev.record.Record(data=rec_ID2).masterdata_is_curated():
                main_record = rec_ID2
                dupe_record = rec_ID1
            else:
                main_record = rec_ID1
                dupe_record = rec_ID2
        return [main_record, dupe_record]

    def apply_merges(self, *, results: list, remaining_non_dupe: bool = False):
        """Apply automated deduplication decisions

        Level: IDs (not colrev_origins), requiring IDs to be immutable after md_prepared

        record['colrev_status'] can only be set to md_processed after running the
        active-learning classifier and checking whether the record is not part of
        any other duplicate-cluster
        - If the results list does not contain a 'score' value, it is generated
        manually and we cannot set the 'colrev_status' to md_processed
        - If the results list contains a 'score value'

        """

        # The merging also needs to consider whether IDs are propagated
        # Completeness of comparisons should be ensured by the
        # dedupe clustering routine

        import colrev.cli_colors as colors

        def same_source_merge(main_record: dict, dupe_record: dict) -> bool:

            main_rec_sources = [
                x.split("/")[0] for x in main_record["colrev_origin"].split(";")
            ]
            dupe_rec_sources = [
                x.split("/")[0] for x in dupe_record["colrev_origin"].split(";")
            ]
            same_sources = set(main_rec_sources).intersection(set(dupe_rec_sources))
            if len(same_sources) > 0:
                return True

            return False

        def export_same_source_merge(main_record: dict, dupe_record: dict) -> None:

            merge_info = main_record["ID"] + "," + dupe_record["ID"]
            same_source_merge_file = Path("same_source_merges.txt")
            with same_source_merge_file.open("a", encoding="utf8") as f:
                f.write(merge_info + "\n")
            self.REVIEW_MANAGER.logger.warning(
                f"Prevented same-source merge: ({merge_info})"
            )

        def cross_level_merge(main_record, dupe_record) -> bool:
            cross_level_merge_attempt = False
            if main_record["ENTRYTYPE"] in ["proceedings"] or dupe_record[
                "ENTRYTYPE"
            ] in ["proceedings"]:
                cross_level_merge_attempt = True
            # TODO: book vs. inbook?
            return cross_level_merge_attempt

        records = self.REVIEW_MANAGER.REVIEW_DATASET.load_records_dict()

        for non_dupe in [x["ID1"] for x in results if "no_duplicate" == x["decision"]]:
            if non_dupe in records:
                records[non_dupe].update(
                    colrev_status=colrev.record.RecordState.md_processed
                )

        removed_duplicates = []
        duplicates_to_process = [x for x in results if "duplicate" == x["decision"]]
        for dupe in duplicates_to_process:

            rec_ID1 = records[dupe["ID1"]]
            rec_ID2 = records[dupe["ID2"]]

            # Simple way of implementing the closure
            # cases where the main_record has already been merged into another record
            while "MOVED_DUPE" in rec_ID1:
                rec_ID1 = records[rec_ID1["MOVED_DUPE"]]
            while "MOVED_DUPE" in rec_ID2:
                rec_ID2 = records[rec_ID2["MOVED_DUPE"]]
            if rec_ID1["ID"] == rec_ID2["ID"]:
                continue

            main_record, dupe_record = self.select_primary_merge_record(
                rec_ID1, rec_ID2
            )

            if cross_level_merge(main_record, dupe_record):
                continue

            if same_source_merge(main_record, dupe_record):
                if "apply" != self.REVIEW_MANAGER.settings.dedupe.same_source_merges:
                    MAIN_REC = colrev.record.Record(data=main_record)
                    DUPE_REC = colrev.record.Record(data=dupe_record)
                    print(
                        f"\n{colors.ORANGE}"
                        "Warning: applying same source merge "
                        f"{colors.END} "
                        f"{main_record.get('colrev_origin', '')}/"
                        f"{dupe_record.get('colrev_origin', '')}\n"
                        f"  {MAIN_REC.format_bib_style()}\n"
                        f"  {DUPE_REC.format_bib_style()}"
                    )
                elif (
                    "prevent" == self.REVIEW_MANAGER.settings.dedupe.same_source_merges
                ):
                    export_same_source_merge(main_record, dupe_record)
                    continue  # with next pair
                else:
                    print(
                        "Invalid setting: dedupe.same_source_merges: "
                        f"{self.REVIEW_MANAGER.settings.dedupe.same_source_merges}"
                    )
                    continue  # with next pair

            dupe_record["MOVED_DUPE"] = main_record["ID"]
            MAIN_RECORD = colrev.record.Record(data=main_record)
            MAIN_RECORD.merge(
                MERGING_RECORD=colrev.record.Record(data=dupe_record),
                default_source="merged",
            )
            main_record = MAIN_RECORD.get_data()

            if "score" in dupe:
                conf_details = f"(confidence: {str(round(dupe['score'], 3))})"
            else:
                conf_details = ""
            self.REVIEW_MANAGER.logger.debug(
                f"Removed duplicate{conf_details}: "
                + f'{main_record["ID"]} <- {dupe_record["ID"]}'
            )

            removed_duplicates.append(dupe_record["ID"])

        for record in records.values():
            if "MOVED_DUPE" in record:
                del record["MOVED_DUPE"]
        for removed_duplicate in removed_duplicates:
            if removed_duplicate in records:
                del records[removed_duplicate]

        if remaining_non_dupe:
            # Set remaining records to md_processed (not duplicate) because all records
            # have been considered by dedupe
            for record in records.values():
                if record["colrev_status"] == colrev.record.RecordState.md_prepared:
                    record["colrev_status"] = colrev.record.RecordState.md_processed

        self.REVIEW_MANAGER.REVIEW_DATASET.save_records_dict(records=records)
        self.REVIEW_MANAGER.REVIEW_DATASET.add_record_changes()

    def apply_manual_deduplication_decisions(self, *, results: list):
        """Apply manual deduplication decisions

        Level: IDs (not colrev_origins), requiring IDs to be immutable after md_prepared

        Note : record['colrev_status'] can only be set to md_processed after running the
        active-learning classifier and checking whether the record is not part of
        any other duplicate-cluster
        """

        # The merging also needs to consider whether IDs are propagated

        records = self.REVIEW_MANAGER.REVIEW_DATASET.load_records_dict()

        non_dupe_list = []
        dupe_list = []
        for x in results:
            if "no_duplicate" == x["decision"]:
                non_dupe_list.append([x["ID1"], x["ID2"]])
            if "duplicate" == x["decision"]:
                dupe_list.append([x["ID1"], x["ID2"]])

        removed_duplicates = []
        for ID1, ID2 in dupe_list:

            rec_ID1 = records[ID1]
            rec_ID2 = records[ID2]

            self.REVIEW_MANAGER.logger.debug(
                f'applying {rec_ID1["ID"]}-{rec_ID2["ID"]}'
            )

            # Simple way of implementing the closure
            # cases where the main_record has already been merged into another record
            while "MOVED_DUPE" in rec_ID1:
                rec_ID1 = records[rec_ID1["MOVED_DUPE"]]
            while "MOVED_DUPE" in rec_ID2:
                rec_ID2 = records[rec_ID2["MOVED_DUPE"]]

            if rec_ID1["ID"] == rec_ID2["ID"]:
                continue

            main_record, dupe_record = self.select_primary_merge_record(
                rec_ID1, rec_ID2
            )

            # TODO : prevent same-source merges (like in the automated part?!)
            dupe_rec_id = dupe_record["ID"]
            main_rec_id = main_record["ID"]
            self.REVIEW_MANAGER.logger.debug(main_rec_id + " < " + dupe_rec_id)

            dupe_record["MOVED_DUPE"] = main_record["ID"]
            MAIN_RECORD = colrev.record.Record(data=main_record)
            MAIN_RECORD.merge(
                MERGING_RECORD=colrev.record.Record(data=dupe_record),
                default_source="merged",
            )
            main_record = MAIN_RECORD.get_data()

            self.REVIEW_MANAGER.logger.debug(
                f"Removed duplicate: {dupe_rec_id} (duplicate of {main_rec_id})"
            )
            removed_duplicates.append(dupe_rec_id)

        for record in records.values():
            if "MOVED_DUPE" in record:
                del record["MOVED_DUPE"]
        for removed_duplicate in removed_duplicates:
            if removed_duplicate in records:
                del records[removed_duplicate]

        self.REVIEW_MANAGER.REVIEW_DATASET.save_records_dict(records=records)
        self.REVIEW_MANAGER.REVIEW_DATASET.add_record_changes()

    def source_comparison(self) -> None:
        """Exports a spreadsheet to support analyses of records that are not
        in all sources (for curated repositories)"""

        source_filenames = [x.filename for x in self.REVIEW_MANAGER.settings.sources]
        print("sources: " + ",".join(source_filenames))

        records = self.REVIEW_MANAGER.REVIEW_DATASET.load_records_dict()
        records = {
            k: v
            for k, v in records.items()
            if not all(x in v["colrev_origin"] for x in source_filenames)
        }
        if len(records) == 0:
            print("No records unmatched")
            return

        for record in records.values():
            origins = record["colrev_origin"].split(";")
            for source_filename in source_filenames:
                if not any(source_filename in origin for origin in origins):
                    record[source_filename] = ""
                else:
                    record[source_filename] = [
                        origin for origin in origins if source_filename in origin
                    ][0]
            record["merge_with"] = ""

        records_df = pd.DataFrame.from_records(list(records.values()))
        records_df.to_excel(self.source_comparison_xlsx, index=False)
        print(f"Exported {self.source_comparison_xlsx}")

    def fix_errors(self) -> None:
        """Fix errors as highlighted in the Excel files"""

        self.REVIEW_MANAGER.report_logger.info("Dedupe: fix errors")
        self.REVIEW_MANAGER.logger.info("Dedupe: fix errors")
        saved_args = locals()

        git_repo = git.Repo(str(self.REVIEW_MANAGER.paths["REPO_DIR"]))
        if self.dupe_file.is_file():
            dupes = pd.read_excel(self.dupe_file)
            dupes.fillna("", inplace=True)
            c_to_correct = dupes.loc[dupes["error"] != "", "cluster_id"].to_list()
            dupes = dupes[dupes["cluster_id"].isin(c_to_correct)]
            IDs_to_unmerge = dupes.groupby(["cluster_id"])["ID"].apply(list).tolist()

            if len(IDs_to_unmerge) > 0:
                records = self.REVIEW_MANAGER.REVIEW_DATASET.load_records_dict()

                RECORDS_FILE_RELATIVE = self.REVIEW_MANAGER.paths[
                    "RECORDS_FILE_RELATIVE"
                ]
                revlist = (
                    ((commit.tree / str(RECORDS_FILE_RELATIVE)).data_stream.read())
                    for commit in git_repo.iter_commits(
                        paths=str(RECORDS_FILE_RELATIVE)
                    )
                )

                # Note : there could be more than two IDs in the list
                filecontents = next(revlist)

                prior_records_dict = self.REVIEW_MANAGER.REVIEW_DATASET.load_records(
                    load_str=filecontents.decode("utf-8")
                )

                for ID_list_to_unmerge in IDs_to_unmerge:
                    self.REVIEW_MANAGER.report_logger.info(
                        f'Undo merge: {",".join(ID_list_to_unmerge)}'
                    )

                    # delete new record,
                    # add previous records (from history) to records
                    records = {
                        k: v for k, v in records.items() if k not in ID_list_to_unmerge
                    }

                    if all(ID in prior_records_dict for ID in ID_list_to_unmerge):
                        for r in prior_records_dict.values():
                            if r["ID"] in ID_list_to_unmerge:
                                # add manual_dedupe/non_dupe decision to the records
                                manual_non_duplicates = ID_list_to_unmerge.copy()
                                manual_non_duplicates.remove(r["ID"])

                                r[
                                    "colrev_status"
                                ] = colrev.record.RecordState.md_processed
                                r_dict = {r["ID"]: r}
                                records.append(r_dict)
                                self.REVIEW_MANAGER.logger.info(f'Restored {r["ID"]}')
                    else:
                        self.REVIEW_MANAGER.logger.error(
                            f"Could not retore {ID_list_to_unmerge} - "
                            "please fix manually"
                        )

                self.REVIEW_MANAGER.REVIEW_DATASET.save_records_dict(records=records)
                self.REVIEW_MANAGER.REVIEW_DATASET.add_record_changes()

        if self.non_dupe_file_xlsx.is_file() or self.non_dupe_file_txt.is_file():
            IDs_to_merge = []
            if self.non_dupe_file_xlsx.is_file():
                non_dupes = pd.read_excel(self.non_dupe_file_xlsx)
                non_dupes.fillna("", inplace=True)
                c_to_correct = non_dupes.loc[
                    non_dupes["error"] != "", "cluster_id"
                ].to_list()
                non_dupes = non_dupes[non_dupes["cluster_id"].isin(c_to_correct)]
                IDs_to_merge = (
                    non_dupes.groupby(["cluster_id"])["ID"].apply(list).tolist()
                )
            if self.non_dupe_file_txt.is_file():
                content = self.non_dupe_file_txt.read_text()
                IDs_to_merge = [x.split(",") for x in content.splitlines()]
                for ID1, ID2 in IDs_to_merge:
                    print(f"{ID1} - {ID2}")

            if len(IDs_to_merge) > 0:
                auto_dedupe = []
                for ID1, ID2 in IDs_to_merge:
                    auto_dedupe.append(
                        {
                            "ID1": ID1,
                            "ID2": ID2,
                            "decision": "duplicate",
                        }
                    )
                self.apply_manual_deduplication_decisions(results=auto_dedupe)

        if (
            self.dupe_file.is_file()
            or self.non_dupe_file_xlsx.is_file()
            or self.non_dupe_file_txt.is_file()
        ):
            self.REVIEW_MANAGER.create_commit(
                msg="Validate and correct duplicates",
                manual_author=True,
                script_call="colrev dedupe",
                saved_args=saved_args,
            )
        else:
            self.REVIEW_MANAGER.logger.error("No file with potential errors found.")

    def get_info(self) -> dict:
        """Get info on cuts (overlap of search sources) and same source merges"""

        records = self.REVIEW_MANAGER.REVIEW_DATASET.load_records_dict()

        origins = [record["colrev_origin"].split(";") for record in records.values()]
        origins = [item.split("/")[0] for sublist in origins for item in sublist]
        origins = list(set(origins))

        same_source_merges = []

        for record in records.values():

            rec_sources = [x.split("/")[0] for x in record["colrev_origin"].split(";")]

            duplicated_sources = [
                item for item, count in Counter(rec_sources).items() if count > 1
            ]
            if len(duplicated_sources) > 0:
                all_cases = []
                for ds in duplicated_sources:
                    cases = [
                        o.split("/")[1]
                        for o in record["colrev_origin"].split(";")
                        if ds in o
                    ]
                    all_cases.append(f"{ds}: {cases}")
                same_source_merges.append(f"{record['ID']} ({', '.join(all_cases)})")

        info = {
            "same_source_merges": same_source_merges,
        }
        return info

    def main(self):

        for DEDUPE_SCRIPT in self.REVIEW_MANAGER.settings.dedupe.scripts:

            AdapterManager = self.REVIEW_MANAGER.get_environment_service(
                service_identifier="AdapterManager"
            )
            dedupe_script = AdapterManager.load_scripts(
                PROCESS=self,
                scripts=[DEDUPE_SCRIPT],
            )

            ENDPOINT = dedupe_script[DEDUPE_SCRIPT["endpoint"]]

            ENDPOINT.run_dedupe(self)
            print()


if __name__ == "__main__":
    pass