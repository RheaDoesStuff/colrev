#! /usr/bin/env python
"""SearchSource: LocalIndex"""
from __future__ import annotations

import typing
from dataclasses import dataclass
from multiprocessing import Lock
from pathlib import Path

import git
import zope.interface
from dacite import from_dict
from dataclasses_jsonschema import JsonSchemaMixin
from opensearchpy import NotFoundError
from opensearchpy.exceptions import TransportError

import colrev.env.package_manager
import colrev.exceptions as colrev_exceptions
import colrev.ops.search
import colrev.record
import colrev.ui_cli.cli_colors as colors

# pylint: disable=unused-argument
# pylint: disable=duplicate-code


@zope.interface.implementer(
    colrev.env.package_manager.SearchSourcePackageEndpointInterface
)
@dataclass
class LocalIndexSearchSource(JsonSchemaMixin):
    """Performs a search in the LocalIndex"""

    # pylint: disable=too-many-instance-attributes
    settings_class = colrev.env.package_manager.DefaultSourceSettings
    source_identifier = "curation_ID"
    search_type = colrev.settings.SearchType.OTHER
    heuristic_status = colrev.env.package_manager.SearchSourceHeuristicStatus.supported
    short_name = "LocalIndex"
    link = (
        "https://github.com/geritwagner/colrev/blob/main/"
        + "colrev/ops/built_in/search_sources/local_index.py"
    )
    __local_index_md_filename = Path("data/search/md_curated.bib")

    essential_md_keys = [
        "title",
        "author",
        "journal",
        "year",
        "booktitle",
        "number",
        "volume",
        "issue",
        "author",
        "doi",
        "dblp_key",
        "url",
    ]

    def __init__(
        self,
        *,
        source_operation: colrev.operation.Operation,
        settings: dict = None,
    ) -> None:

        if settings:
            # LocalIndex as a search_source
            self.search_source = from_dict(
                data_class=self.settings_class, data=settings
            )

        else:
            # LocalIndex as an md-prep source
            li_md_source_l = [
                s
                for s in source_operation.review_manager.settings.sources
                if s.filename == self.__local_index_md_filename
            ]
            if li_md_source_l:
                self.search_source = li_md_source_l[0]
            else:
                self.search_source = colrev.settings.SearchSource(
                    endpoint="colrev_built_in.local_index",
                    filename=self.__local_index_md_filename,
                    search_type=colrev.settings.SearchType.OTHER,
                    search_parameters={},
                    load_conversion_package_endpoint={
                        "endpoint": "colrev_built_in.bibtex"
                    },
                    comment="",
                )

            self.local_index_lock = Lock()

        self.origin_prefix = self.search_source.get_origin_prefix()

        self.local_index = source_operation.review_manager.get_local_index()
        self.review_manager = source_operation.review_manager

    def validate_source(
        self,
        search_operation: colrev.ops.search.Search,
        source: colrev.settings.SearchSource,
    ) -> None:
        """Validate the SearchSource (parameters etc.)"""

        search_operation.review_manager.logger.debug(
            f"Validate SearchSource {source.filename}"
        )

        # if "query" not in source.search_parameters:
        # Note :  for md-sources, there is no query parameter.
        #     raise colrev_exceptions.InvalidQueryException(
        #         f"Source missing query search_parameter ({source.filename})"
        #     )

        if "query" in source.search_parameters:
            if "simple_query_string" in source.search_parameters["query"]:
                if "query" in source.search_parameters["query"]["simple_query_string"]:
                    pass
                else:
                    raise colrev_exceptions.InvalidQueryException(
                        "Source missing query/simple_query_string/query "
                        f"search_parameter ({source.filename})"
                    )

            elif "url" in source.search_parameters["query"]:
                pass
            else:
                raise colrev_exceptions.InvalidQueryException(
                    f"Source missing query/query search_parameter ({source.filename})"
                )

        search_operation.review_manager.logger.debug(
            f"SearchSource {source.filename} validated"
        )

    def __retrieve_from_index(self) -> typing.List[dict]:

        params = self.search_source.search_parameters
        # query = {
        #     "query": {
        #         "simple_query_string": {
        #             "query": "...",
        #             "fields": selected_fields,
        #         },
        #     }
        # }
        query = params

        returned_records = self.local_index.search(query=query)

        records_to_import = [r.get_data() for r in returned_records]
        records_to_import = [r for r in records_to_import if r]
        keys_to_drop = [
            "colrev_status",
            "colrev_origin",
            "screening_criteria",
        ]
        for record_dict in records_to_import:
            identifier_string = (
                record_dict["colrev_masterdata_provenance"]["CURATED"]["source"]
                + "#"
                + record_dict["ID"]
            )
            record_dict["curation_ID"] = identifier_string
            record_dict = {
                key: value
                for key, value in record_dict.items()
                if key not in keys_to_drop
            }

        return records_to_import

    def __run_md_search_update(
        self,
        *,
        search_operation: colrev.ops.search.Search,
        local_index_feed: colrev.ops.search.GeneralOriginFeed,
    ) -> None:

        records = search_operation.review_manager.dataset.load_records_dict()

        nr_changed = 0
        for feed_record_dict in local_index_feed.feed_records.values():
            feed_record = colrev.record.Record(data=feed_record_dict)

            try:
                # TODO: this should be based on the curation_ID!?
                retrieved_record_dict = self.local_index.retrieve(
                    record_dict=feed_record.get_data(), include_file=False
                )
            except (colrev_exceptions.RecordNotInIndexException, NotFoundError):
                continue

            local_index_feed.set_id(record_dict=retrieved_record_dict)
            prev_record_dict_version = {}
            if retrieved_record_dict["ID"] in local_index_feed.feed_records:
                prev_record_dict_version = local_index_feed.feed_records[
                    retrieved_record_dict["ID"]
                ]

            local_index_feed.add_record(
                record=colrev.record.Record(data=retrieved_record_dict)
            )

            changed = search_operation.update_existing_record(
                records=records,
                record_dict=retrieved_record_dict,
                prev_record_dict_version=prev_record_dict_version,
                source=self.search_source,
            )
            if changed:
                nr_changed += 1

        if nr_changed > 0:
            self.review_manager.logger.info(
                f"{colors.GREEN}Updated {nr_changed} "
                f"records based on LocalIndex{colors.END}"
            )
        else:
            self.review_manager.logger.info(
                f"{colors.GREEN}Records up-to-date with LocalIndex{colors.END}"
            )

        local_index_feed.save_feed_file()
        search_operation.review_manager.dataset.save_records_dict(records=records)
        search_operation.review_manager.dataset.add_record_changes()

    def __run_parameter_search(
        self,
        *,
        search_operation: colrev.ops.search.Search,
        local_index_feed: colrev.ops.search.GeneralOriginFeed,
    ) -> None:

        records = search_operation.review_manager.dataset.load_records_dict()

        nr_retrieved, nr_changed = 0, 0

        for retrieved_record_dict in self.__retrieve_from_index():

            local_index_feed.set_id(record_dict=retrieved_record_dict)
            prev_record_dict_version = {}
            if retrieved_record_dict["ID"] in local_index_feed.feed_records:
                prev_record_dict_version = local_index_feed.feed_records[
                    retrieved_record_dict["ID"]
                ]

            added = local_index_feed.add_record(
                record=colrev.record.Record(data=retrieved_record_dict)
            )
            if added:
                nr_retrieved += 1

            else:
                changed = search_operation.update_existing_record(
                    records=records,
                    record_dict=retrieved_record_dict,
                    prev_record_dict_version=prev_record_dict_version,
                    source=self.search_source,
                )
                if changed:
                    nr_changed += 1

        local_index_feed.save_feed_file()

        if nr_retrieved > 0:
            search_operation.review_manager.logger.info(
                f"{colors.GREEN}Retrieved {nr_retrieved} records {colors.END}"
            )

        if nr_changed > 0:
            self.review_manager.logger.info(
                f"{colors.GREEN}Updated {nr_changed} "
                f"records based on LocalIndex{colors.END}"
            )
        else:
            self.review_manager.logger.info(
                f"{colors.GREEN}Records up-to-date with LocalIndex{colors.END}"
            )

    def run_search(
        self, search_operation: colrev.ops.search.Search, update_only: bool
    ) -> None:
        """Run a search of local-index"""

        local_index_feed = self.search_source.get_feed(
            review_manager=search_operation.review_manager,
            source_identifier=self.source_identifier,
            update_only=False,
        )

        if self.search_source.is_md_source() or self.search_source.is_quasi_md_source():

            self.__run_md_search_update(
                search_operation=search_operation,
                local_index_feed=local_index_feed,
            )

        else:
            self.__run_parameter_search(
                search_operation=search_operation,
                local_index_feed=local_index_feed,
            )

    @classmethod
    def heuristic(cls, filename: Path, data: str) -> dict:
        """Source heuristic for local-index"""

        result = {"confidence": 0.0}
        if "curation_ID" in data:
            result["confidence"] = 1

        return result

    def load_fixes(
        self,
        load_operation: colrev.ops.load.Load,
        source: colrev.settings.SearchSource,
        records: typing.Dict,
    ) -> dict:
        """Load fixes for local-index"""

        for record in records.values():
            curation_url = record["curation_ID"].split("#")[0]
            # TODO : add full curation_ID to colrev_masterdata_provenance/CURATED/source
            # or leave it empty to avoid redundancy?
            record["colrev_masterdata_provenance"] = {
                "CURATED": {"source": curation_url, "note": ""}
            }
            record["colrev_status"] = colrev.record.RecordState.md_prepared
            del curation_url
        return records

    def prepare(
        self, record: colrev.record.Record, source: colrev.settings.SearchSource
    ) -> colrev.record.Record:
        """Source-specific preparation for local-index"""

        return record

    def get_masterdata(
        self,
        *,
        prep_operation: colrev.ops.prep.Prep,
        record: colrev.record.Record,
    ) -> colrev.record.Record:
        """Retrieve masterdata from LocalIndex based on similarity with the record provided"""

        # pylint: disable=too-many-branches

        if any(self.origin_prefix in o for o in record.data["colrev_origin"]):
            # Already linked to a local-index record
            return record

        try:
            retrieved_record_dict = self.local_index.retrieve(
                record_dict=record.get_data(), include_file=False
            )

        except (colrev_exceptions.RecordNotInIndexException, NotFoundError):
            try:
                retrieved_record_dict = self.local_index.retrieve_from_toc(
                    record_dict=record.data,
                    similarity_threshold=prep_operation.retrieval_similarity,
                    include_file=False,
                )
            except colrev_exceptions.RecordNotInTOCException as exc:
                record.prescreen_exclude(
                    reason=f"record not in toc {exc.toc_key}",  # type : ignore
                    print_warning=True,
                )
                return record

            except (
                colrev_exceptions.RecordNotInIndexException,
                colrev_exceptions.NotTOCIdentifiableException,
                NotFoundError,
                TransportError,
            ):
                return record

        retrieved_record = colrev.record.PrepRecord(data=retrieved_record_dict)
        if "colrev_status" in retrieved_record.data:
            del retrieved_record.data["colrev_status"]

        # restriction: if we don't restrict to CURATED,
        # we may have to rethink the LocalIndexSearchFeed.set_ids()
        if "CURATED" not in retrieved_record.data["colrev_masterdata_provenance"]:
            return record

        default_source = "LOCAL_INDEX"
        if "colrev_masterdata_provenance" in retrieved_record.data:
            if "CURATED" in retrieved_record.data["colrev_masterdata_provenance"]:
                default_source = retrieved_record.data["colrev_masterdata_provenance"][
                    "CURATED"
                ]["source"]

        try:
            self.local_index_lock.acquire(timeout=60)

            # Note : need to reload file because the object is not shared between processes
            local_index_feed = self.search_source.get_feed(
                review_manager=prep_operation.review_manager,
                source_identifier=self.source_identifier,
                update_only=False,
            )

            # lock: to prevent different records from having the same origin
            local_index_feed.set_id(record_dict=retrieved_record.data)
            local_index_feed.add_record(record=retrieved_record)

            retrieved_record.remove_field(key="curation_ID")
            record.merge(
                merging_record=retrieved_record,
                default_source=default_source,
            )

            git_repo = prep_operation.review_manager.dataset.get_repo()
            cur_project_source_paths = [str(prep_operation.review_manager.path)]
            for remote in git_repo.remotes:
                if remote.url:
                    shared_url = remote.url
                    shared_url = shared_url.rstrip(".git")
                    cur_project_source_paths.append(shared_url)
                    break

            try:
                local_index_feed.save_feed_file()
                # extend fields_to_keep (to retrieve all fields from the index)
                for key in retrieved_record.data.keys():
                    if key not in prep_operation.fields_to_keep:
                        prep_operation.fields_to_keep.append(key)

            except OSError:
                pass

            self.local_index_lock.release()

        except colrev_exceptions.InvalidMerge:
            self.local_index_lock.release()

        record.set_status(target_state=colrev.record.RecordState.md_prepared)

        return record

    def __get_local_base_repos(self, *, change_itemsets: list) -> dict:
        base_repos = []
        for item in change_itemsets:
            if "CURATED" in item["original_record"].get(
                "colrev_masterdata_provenance", {}
            ):
                # TODO : strip the ID at the end if we add an ID...
                repo_path = item["original_record"]["colrev_masterdata_provenance"][
                    "CURATED"
                ]["source"]
                base_repos.append(repo_path)

        base_repos = list(set(base_repos))

        environment_manager = colrev.env.environment_manager.EnvironmentManager()

        local_base_repos = {
            x["repo_source_url"]: x["repo_source_path"]
            for x in environment_manager.load_environment_registry()
            if x["repo_source_url"] in base_repos
        }
        return local_base_repos

    def apply_correction(self, *, change_itemsets: list) -> None:
        """Apply a correction by opening a pull request in the original repository"""

        # pylint: disable=too-many-branches

        local_base_repos = self.__get_local_base_repos(change_itemsets=change_itemsets)

        for local_base_repo in local_base_repos:
            validated_changes = []
            for item in change_itemsets:
                repo_path = "NA"
                if "CURATED" in item["original_record"].get(
                    "colrev_masterdata_provenance", {}
                ):
                    # TODO : strip the ID at the end if we add an ID...
                    repo_path = item["original_record"]["colrev_masterdata_provenance"][
                        "CURATED"
                    ]["source"]

                if repo_path != local_base_repo:
                    continue

                self.review_manager.logger.info(
                    f"Base repository: {local_base_repos[repo_path]}"
                )

                print()
                self.review_manager.p_printer.pprint(item["original_record"])
                for change_item in item["changes"]:
                    if "change" == change_item[0]:
                        edit_type, field, values = change_item
                        if "colrev_id" == field:
                            continue
                        prefix = f"{edit_type} {field}"
                        print(
                            f"{prefix}"
                            + " " * max(len(prefix), 30 - len(prefix))
                            + f": {values[0]}"
                        )
                        print(" " * max(len(prefix), 30) + f"  {values[1]}")
                    elif "add" == change_item[0]:
                        edit_type, field, values = change_item
                        prefix = f"{edit_type} {values[0][0]}"
                        print(
                            prefix
                            + " " * max(len(prefix), 30 - len(prefix))
                            + f": {values[0][1]}"
                        )
                    else:
                        self.review_manager.p_printer.pprint(change_item)
                validated_changes.append(item)

            response = ""
            while True:
                response = input("\nConfirm changes? (y/n)")
                if response in ["y", "n"]:
                    break

            if "y" == response:
                self.__apply_correction(
                    source_url=local_base_repos[repo_path],
                    change_list=validated_changes,
                )
            elif "n" == response:
                if "y" == input("Discard all corrections (y/n)?"):
                    for validated_change in validated_changes:
                        Path(validated_change["file"]).unlink()

    def __apply_corrections_precondition(
        self, *, check_operation: colrev.operation.Operation, source_url: str
    ) -> bool:
        git_repo = check_operation.review_manager.dataset.get_repo()

        if git_repo.is_dirty():
            msg = f"Repo not clean ({source_url}): commit or stash before updating records"
            raise colrev_exceptions.CorrectionPreconditionException(msg)

        if check_operation.review_manager.dataset.behind_remote():
            origin = git_repo.remotes.origin
            origin.pull()
            if not check_operation.review_manager.dataset.behind_remote():
                self.review_manager.logger.info("Pulled changes")
            else:
                self.review_manager.logger.error(
                    "Repo behind remote. Pull first to avoid conflicts.\n"
                    f"colrev env --update {check_operation.review_manager.path}"
                )
                return False

        return True

    def __retrieve_by_colrev_id(
        self, *, indexed_record_dict: dict, records: list[dict]
    ) -> dict:

        indexed_record = colrev.record.Record(data=indexed_record_dict)

        if "colrev_id" in indexed_record.data:
            cid_to_retrieve = indexed_record.get_colrev_id()
        else:
            cid_to_retrieve = [indexed_record.create_colrev_id()]

        record_l = [
            x
            for x in records
            if any(
                cid in colrev.record.Record(data=x).get_colrev_id()
                for cid in cid_to_retrieve
            )
        ]
        if len(record_l) != 1:
            raise colrev_exceptions.RecordNotInRepoException
        return record_l[0]

    def __retrieve_record_for_correction(
        self,
        *,
        records: dict,
        change_item: dict,
    ) -> dict:
        original_record = change_item["original_record"]

        try:
            record_dict = self.__retrieve_by_colrev_id(
                indexed_record_dict=original_record,
                records=list(records.values()),
            )
            return record_dict
        except colrev_exceptions.RecordNotInRepoException:

            matching_doi_rec_l = [
                r
                for r in records.values()
                if original_record.get("doi", "NDOI") == r.get("doi", "NA")
            ]
            if len(matching_doi_rec_l) == 1:
                record_dict = matching_doi_rec_l[0]
                return record_dict

            matching_url_rec_l = [
                r
                for r in records.values()
                if original_record.get("url", "NURL") == r.get("url", "NA")
            ]
            if len(matching_url_rec_l) == 1:
                record_dict = matching_url_rec_l[0]
                return record_dict

        print(f'Record not found: {original_record["ID"]}')
        return {}

    def __create_correction_branch(
        self, *, git_repo: git.Repo, record_dict: dict
    ) -> str:
        record_branch_name = record_dict["ID"]
        counter = 1
        new_record_branch_name = record_branch_name
        while new_record_branch_name in [ref.name for ref in git_repo.references]:
            new_record_branch_name = f"{record_branch_name}_{counter}"
            counter += 1

        record_branch_name = new_record_branch_name
        git_repo.git.branch(record_branch_name)
        return record_branch_name

    def __apply_record_correction(
        self,
        *,
        check_operation: colrev.operation.Operation,
        records: dict,
        record_dict: dict,
        change_item: dict,
    ) -> None:

        for (edit_type, key, change) in list(change_item["changes"]):
            # Note : by retricting changes to self.essential_md_keys,
            # we also prevent changes in
            # "colrev_status", "colrev_origin", "file"

            # Note: the most important thing is to update the metadata.

            if edit_type == "change":
                if key not in self.essential_md_keys:
                    continue
                record_dict[key] = change[1]
            if edit_type == "add":
                key = change[0][0]
                value = change[0][1]
                if key not in self.essential_md_keys:
                    continue
                record_dict[key] = value
            # gh_issue https://github.com/geritwagner/colrev/issues/63
            # deal with remove/merge

        check_operation.review_manager.dataset.save_records_dict(records=records)
        check_operation.review_manager.dataset.add_record_changes()
        check_operation.review_manager.create_commit(
            msg=f"Update {record_dict['ID']}", script_call="colrev push"
        )

    def __push_corrections_and_reset_branch(
        self,
        *,
        git_repo: git.Repo,
        record_branch_name: str,
        prev_branch_name: str,
        source_url: str,
    ) -> None:

        git_repo.remotes.origin.push(
            refspec=f"{record_branch_name}:{record_branch_name}"
        )
        self.review_manager.logger.info("Pushed corrections")

        for head in git_repo.heads:
            if head.name == prev_branch_name:
                head.checkout()

        git_repo = git.Git(source_url)
        git_repo.execute(["git", "branch", "-D", record_branch_name])

        self.review_manager.logger.info("Removed local corrections branch")

    def __reset_record_after_correction(
        self, *, record_dict: dict, rec_for_reset: dict, change_item: dict
    ) -> None:
        # reset the record - each branch should have changes for one record
        # Note : modify dict (do not replace it) - otherwise changes will not be
        # part of the records.
        for key, value in rec_for_reset.items():
            record_dict[key] = value
        keys_added = [
            key for key in record_dict.keys() if key not in rec_for_reset.keys()
        ]
        for key in keys_added:
            del record_dict[key]

        if Path(change_item["file"]).is_file():
            Path(change_item["file"]).unlink()

    def __apply_change_item_correction(
        self,
        *,
        check_operation: colrev.operation.Operation,
        source_url: str,
        change_list: list,
    ) -> None:

        git_repo = check_operation.review_manager.dataset.get_repo()
        records = check_operation.review_manager.dataset.load_records_dict()

        pull_request_msgs = []
        for change_item in change_list:

            record_dict = self.__retrieve_record_for_correction(
                records=records,
                change_item=change_item,
            )
            if not record_dict:
                continue

            record_branch_name = self.__create_correction_branch(
                git_repo=git_repo, record_dict=record_dict
            )
            prev_branch_name = git_repo.active_branch.name

            remote = git_repo.remote()
            for head in git_repo.heads:
                if head.name == record_branch_name:
                    head.checkout()

            rec_for_reset = record_dict.copy()

            self.__apply_record_correction(
                check_operation=check_operation,
                records=records,
                record_dict=record_dict,
                change_item=change_item,
            )

            self.__push_corrections_and_reset_branch(
                git_repo=git_repo,
                record_branch_name=record_branch_name,
                prev_branch_name=prev_branch_name,
                source_url=source_url,
            )

            self.__reset_record_after_correction(
                record_dict=record_dict,
                rec_for_reset=rec_for_reset,
                change_item=change_item,
            )

            if "github.com" in remote.url:
                pull_request_msgs.append(
                    "\nTo create a pull request for your changes go "
                    f"to \n{colors.ORANGE}{str(remote.url).rstrip('.git')}/"
                    f"compare/{record_branch_name}{colors.END}"
                )

        for pull_request_msg in pull_request_msgs:
            print(pull_request_msg)
        # https://github.com/geritwagner/information_systems_papers/compare/update?expand=1
        # gh_issue https://github.com/geritwagner/colrev/issues/63
        # handle cases where update branch already exists

    def __apply_correction(self, *, source_url: str, change_list: list) -> None:
        """Apply a (list of) corrections"""

        # TBD: other modes of accepting changes?
        # e.g., only-metadata, no-changes, all(including optional fields)
        check_review_manager = self.review_manager.get_review_manager(
            path_str=source_url
        )
        check_operation = colrev.operation.CheckOperation(
            review_manager=check_review_manager
        )

        if check_review_manager.dataset.behind_remote():
            git_repo = check_review_manager.dataset.get_repo()
            origin = git_repo.remotes.origin
            self.review_manager.logger.info(
                f"Pull project changes from {git_repo.remotes.origin}"
            )
            res = origin.pull()
            self.review_manager.logger.info(res)

        try:
            if not self.__apply_corrections_precondition(
                check_operation=check_operation, source_url=source_url
            ):
                return
        except colrev_exceptions.CorrectionPreconditionException as exc:
            print(exc)
            return

        check_review_manager.logger.info(
            "Precondition for correction (pull-request) checked."
        )

        self.__apply_change_item_correction(
            check_operation=check_operation,
            source_url=source_url,
            change_list=change_list,
        )

        print(
            f"\n{colors.GREEN}Thank you for supporting other researchers "
            f"by sharing your corrections ❤{colors.END}\n"
        )


if __name__ == "__main__":
    pass
