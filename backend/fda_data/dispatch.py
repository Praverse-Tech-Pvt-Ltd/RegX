"""Which dataset types this system can actually import.

`FDADatasetType` declares eight members. Two of them have an adapter and an
importer; the rest have neither, and until now the ingestion view dispatched
on `dataset_type.startswith("orange_book")`, which produced two distinct
failures:

  * `orange_book_patents` and `orange_book_exclusivity` were parsed by the
    PRODUCTS adapter. A patent row created an `OrangeBookProduct` with an
    empty ingredient, trade name and strength, and reconciliation reported it
    as `imported: 1`.
  * `fda_substance_identifiers`, `fda_route_terminology` and
    `fda_dosage_form_terminology` matched no branch at all, so a release was
    registered with 0 rows and the caller received HTTP 201.

Both are worse than an error, because both look like success. An enum member
existing is not a promise that the system can import it; this module is where
that promise is actually made.
"""

from __future__ import annotations

from .adapters import fda_iid_adapter, orange_book_products_adapter
from .models import FDADatasetType

#: dataset_type -> (adapter, importer function name on `importer`)
#:
#: Add an entry only when a real adapter AND a real destination model exist.
SUPPORTED_IMPORTERS: dict[str, tuple] = {
    FDADatasetType.ORANGE_BOOK_PRODUCTS: (
        orange_book_products_adapter,
        "import_orange_book_rows",
    ),
    FDADatasetType.FDA_IID: (fda_iid_adapter, "import_iid_rows"),
}

#: Why each unsupported type is unsupported. Returned to the caller so the
#: refusal explains itself instead of being a bare 400.
UNSUPPORTED_REASONS: dict[str, str] = {
    FDADatasetType.ORANGE_BOOK_PATENTS: (
        "Patent data has no destination model in this system. Importing it "
        "through the products adapter would create empty product records, so "
        "it is refused rather than partially stored."
    ),
    FDADatasetType.ORANGE_BOOK_EXCLUSIVITY: (
        "Exclusivity data has no destination model in this system. It is "
        "refused for the same reason as patent data."
    ),
    FDADatasetType.ORANGE_BOOK_DISCONTINUED: (
        "The discontinued-products file is not yet mapped. Its rows are "
        "product-shaped but the discontinued flag is not carried through the "
        "products adapter, so importing it would misrepresent the rows as "
        "current products."
    ),
    FDADatasetType.FDA_SUBSTANCE_IDENTIFIERS: (
        "Substance identifier (UNII) ingestion is not implemented. "
        "`SubstanceSynonymMapping` rows are created through the mapping "
        "proposal workflow, not by bulk import."
    ),
    FDADatasetType.FDA_ROUTE_TERMINOLOGY: (
        "Route terminology import through this API is not implemented. `ControlledRoute` "
        "values are governed vocabulary, loaded only by `load_spl_terminology` "
        "from a saved FDA SPL snapshot."
    ),
    FDADatasetType.FDA_DOSAGE_FORM_TERMINOLOGY: (
        "Dosage form terminology import through this API is not implemented. "
        "`ControlledDosageForm` values are governed vocabulary, loaded only by "
        "`load_spl_terminology` from a saved FDA SPL snapshot."
    ),
}


class UnsupportedDatasetType(Exception):
    """The dataset type is declared but cannot be imported.

    Raised before anything is written, so an unsupported type leaves no
    release, no row results and no reconciliation counts behind.
    """

    def __init__(self, dataset_type: str):
        self.dataset_type = dataset_type
        self.reason = UNSUPPORTED_REASONS.get(dataset_type, "This dataset type has no importer.")
        super().__init__(self.reason)


def resolve_importer(dataset_type: str) -> tuple:
    """Return `(adapter, importer_function)` or raise `UnsupportedDatasetType`."""
    from . import importer as importer_module

    try:
        adapter, importer_name = SUPPORTED_IMPORTERS[dataset_type]
    except KeyError:
        raise UnsupportedDatasetType(dataset_type) from None
    return adapter, getattr(importer_module, importer_name)
