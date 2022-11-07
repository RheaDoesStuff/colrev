#!/usr/bin/env python3
"""Template for a custom Prep PackageEndpoint"""
from __future__ import annotations

from typing import TYPE_CHECKING

import zope.interface
from dacite import from_dict

import colrev.operation

# import timeout_decorator

if TYPE_CHECKING:
    import colrev.ops.prep

# pylint: disable=too-few-public-methods


@zope.interface.implementer(colrev.env.package_manager.PrepPackageEndpointInterface)
class CustomPrep:
    """Class for custom prep scripts"""

    source_correction_hint = "check with the developer"
    always_apply_changes = True
    settings_class = colrev.env.package_manager.DefaultSettings

    def __init__(
        self,
        *,
        prep_operation: colrev.ops.prep.Prep,  # pylint: disable=unused-argument
        settings: dict,
    ) -> None:
        self.settings = from_dict(data_class=self.settings_class, data=settings)

    # Use timeout decorator to limit the execution time of functions
    # @timeout_decorator.timeout(60, use_signals=False)
    def prepare(
        self,
        prep_operation: colrev.ops.prep.Prep,  # pylint: disable=unused-argument
        record: colrev.record.Record,
    ) -> colrev.record.Record:
        """Update record (metadata)"""

        if "journal" in record.data:
            if "MISQ" == record.data["journal"]:
                record.update_field(
                    key="journal", value="MIS Quarterly", source="custom_prep"
                )

        return record


if __name__ == "__main__":
    pass
