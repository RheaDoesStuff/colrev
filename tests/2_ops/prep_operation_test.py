#!/usr/bin/env python
"""Tests of the CoLRev prep operation"""
import colrev.review_manager


def test_prep(  # type: ignore
    base_repo_review_manager: colrev.review_manager.ReviewManager, helpers
) -> None:
    """Test the prep operation"""

    helpers.reset_commit(review_manager=base_repo_review_manager, commit="load_commit")

    base_repo_review_manager.verbose_mode = True
    prep_operation = base_repo_review_manager.get_prep_operation()
    prep_operation.main()


def test_skip_prep(  # type: ignore
    base_repo_review_manager: colrev.review_manager.ReviewManager, helpers
) -> None:
    """Test skip-prep"""

    helpers.reset_commit(review_manager=base_repo_review_manager, commit="load_commit")
    prep_operation = base_repo_review_manager.get_prep_operation()
    prep_operation.skip_prep()


def test_prep_set_id(  # type: ignore
    base_repo_review_manager: colrev.review_manager.ReviewManager, helpers
) -> None:
    """Test prep set_id"""

    helpers.reset_commit(review_manager=base_repo_review_manager, commit="prep_commit")
    prep_operation = base_repo_review_manager.get_prep_operation()
    prep_operation.set_ids()


def test_prep_setup_custom_script(  # type: ignore
    base_repo_review_manager: colrev.review_manager.ReviewManager, helpers
) -> None:
    """Test prep setup_custom_script"""

    helpers.reset_commit(review_manager=base_repo_review_manager, commit="prep_commit")
    prep_operation = base_repo_review_manager.get_prep_operation()
    prep_operation.setup_custom_script()


def test_prep_reset_id(  # type: ignore
    base_repo_review_manager: colrev.review_manager.ReviewManager, helpers
) -> None:
    """Test prep reset_id"""

    helpers.reset_commit(review_manager=base_repo_review_manager, commit="prep_commit")
    prep_operation = base_repo_review_manager.get_prep_operation()
    prep_operation.reset_ids()


def test_prep_reset_records(  # type: ignore
    base_repo_review_manager: colrev.review_manager.ReviewManager, helpers
) -> None:
    """Test prep reset_records"""

    helpers.reset_commit(review_manager=base_repo_review_manager, commit="prep_commit")
    prep_operation = base_repo_review_manager.get_prep_operation()
    prep_operation.reset_records(reset_ids=["Srivastava2015"])


# TODO : difference set_ids - reset_ids?
