"""顺序无关透明（OIT）累积工具包。"""

from .accumulate import (
    OitError,
    accumulate,
    blend_premultiplied,
    oit_batch,
    peel_layers,
    resolve,
    sort_reference,
    validate_fragments,
    weight,
)

__all__ = [
    "OitError",
    "accumulate",
    "blend_premultiplied",
    "oit_batch",
    "peel_layers",
    "resolve",
    "sort_reference",
    "validate_fragments",
    "weight",
]
