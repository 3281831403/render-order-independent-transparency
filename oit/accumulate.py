"""Order-independent transparency accumulation primitives.

颜色约定
--------
* 片段的 ``color`` 是直通（straight）RGB 三元组，每个分量在 ``[0, 1]``。
* ``accumulate`` 的输出颜色、``blend_premultiplied`` 的输入与输出都是
  预乘（premultiplied）RGB：透明片元贡献的是 ``color * alpha`` 的等价量。
* ``alpha`` 和 ``depth`` 均为 ``[0, 1]`` 内的有限数。
* 浮点比较与边界判断使用 ``1e-6`` 容差。

所有非法输入通过 :class:`OitError` 报告；``validate_fragments`` 是例外，
它只收集问题而不抛异常。
"""

import math

_EPS = 1e-6


class OitError(Exception):
    """OIT 累积流程中的非法输入或非法状态。"""


def _is_finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _check_unit(value, name: str) -> float:
    """校验 ``[0, 1]`` 内的有限数并返回浮点值。"""
    if not _is_finite(value) or not (0.0 <= value <= 1.0):
        raise OitError(f"{name} 必须是 [0, 1] 内的有限数，得到 {value!r}")
    return float(value)


def _check_rgb(color, name: str) -> tuple[float, float, float]:
    """校验 RGB 三元组并返回浮点三元组。"""
    if (
        not isinstance(color, (tuple, list))
        or len(color) != 3
        or not all(_is_finite(c) and 0.0 <= c <= 1.0 for c in color)
    ):
        raise OitError(f"{name} 必须是三个 [0, 1] 内的有限数，得到 {color!r}")
    return (float(color[0]), float(color[1]), float(color[2]))


def _check_fragment(fragment) -> dict:
    """校验单个片段，非法时抛 :class:`OitError`。"""
    if not isinstance(fragment, dict):
        raise OitError(f"片段必须是字典，得到 {fragment!r}")
    for field in ("color", "alpha", "depth"):
        if field not in fragment:
            raise OitError(f"片段缺少字段 {field!r}")
    color = _check_rgb(fragment["color"], "color")
    alpha = _check_unit(fragment["alpha"], "alpha")
    depth = _check_unit(fragment["depth"], "depth")
    return {"color": color, "alpha": alpha, "depth": depth}


def _check_fragments(fragments) -> list[dict]:
    """校验整个片段列表（非空、字段合法、无重复深度）。"""
    if not fragments:
        raise OitError("片段列表为空（empty）")
    checked = [_check_fragment(f) for f in fragments]
    depths = [f["depth"] for f in checked]
    if len(set(depths)) != len(depths):
        raise OitError("存在重复 depth（duplicate depth），无法稳定解析")
    return checked


def weight(depth: float, alpha: float) -> float:
    """返回 McGuire 风格的深度权重。

    权重公式固定为::

        weight = alpha * max(1e-6, 1.0 - depth) ** 3

    因此近处（``depth`` 小）的片元权重大于远处片元，透明度 ``alpha`` 越大
    权重也越大；它不会退化成 ``1 - alpha``。

    Args:
        depth: 归一化深度，必须是 ``[0, 1]`` 内的有限数。
        alpha: 不透明度，必须是 ``[0, 1]`` 内的有限数。

    Returns:
        非负的浮点权重。

    Raises:
        OitError: ``depth`` 或 ``alpha`` 越界，或者不是有限数。
    """
    depth = _check_unit(depth, "depth")
    alpha = _check_unit(alpha, "alpha")
    return alpha * max(_EPS, 1.0 - depth) ** 3


def accumulate(fragments: list[dict]) -> dict:
    """对片段做与输入顺序无关的加权累积。

    每个片段为 ``{"color": (r, g, b), "alpha": a, "depth": d}``，其中
    ``color`` 是直通 RGB。令 ``w = weight(d, a)``，本函数计算::

        color    = sum((r, g, b) * w)
        weight   = sum(w)
        coverage = 1 - product(1 - a)

    因为 ``w`` 已含 ``alpha``，``color`` 是预乘颜色的加权和。返回值::

        {"color": (cr, cg, cb), "weight": float, "coverage": float}

    空片段列表、字段缺失、``color`` 非三元组、``alpha``/``depth`` 越界或
    重复 ``depth`` 都抛 :class:`OitError`。累加使用 ``math.fsum``，在
    ``1e-6`` 容差内与片段顺序无关。

    Args:
        fragments: 片段字典列表，至少包含一个元素。

    Returns:
        含 ``color``、``weight`` 和 ``coverage`` 的累积字典。

    Raises:
        OitError: 列表为空或任一字段非法。
    """
    checked = _check_fragments(fragments)
    weights = [weight(f["depth"], f["alpha"]) for f in checked]
    color = tuple(
        math.fsum(f["color"][i] * w for f, w in zip(checked, weights))
        for i in range(3)
    )
    total_weight = math.fsum(weights)
    coverage = 1.0 - math.prod(1.0 - f["alpha"] for f in checked)
    return {"color": color, "weight": total_weight, "coverage": coverage}


def resolve(
    accum: dict,
    background: tuple[float, float, float],
) -> tuple[float, float, float]:
    """把累积缓冲解析成最终 RGB，并把背景混入透明区域。

    当 ``accum["weight"]`` 小于等于 ``1e-6`` 时直接返回 ``background``，
    不做除法。否则先求加权平均颜色，再按覆盖面混合背景::

        average  = accum["color"] / accum["weight"]
        coverage = clamp(accum["coverage"], 0.0, 1.0)
        result   = average * coverage + background * (1 - coverage)

    因此单个不透明片段会得到其原色，半透明片段会正确透出背景，全透明
    片段的权重和为零并直接返回背景。

    Args:
        accum: 由 :func:`accumulate` 生成的累积字典。
        background: 不透明背景 RGB，每个分量在 ``[0, 1]``。

    Returns:
        最终 RGB 三元组。

    Raises:
        OitError: 累积字典字段缺失/非有限，或背景不是合法 RGB。
    """
    if not isinstance(accum, dict):
        raise OitError(f"累积缓冲必须是字典，得到 {accum!r}")
    for field in ("color", "weight", "coverage"):
        if field not in accum:
            raise OitError(f"累积缓冲缺少字段 {field!r}")
    color = accum["color"]
    if (
        not isinstance(color, (tuple, list))
        or len(color) != 3
        or not all(_is_finite(c) for c in color)
    ):
        raise OitError(f"累积颜色必须是三个有限数，得到 {color!r}")
    if not _is_finite(accum["weight"]):
        raise OitError(f"累积权重必须是有限数，得到 {accum['weight']!r}")
    if not _is_finite(accum["coverage"]):
        raise OitError(f"累积覆盖率必须是有限数，得到 {accum['coverage']!r}")
    background = _check_rgb(background, "background")

    total_weight = float(accum["weight"])
    if total_weight <= _EPS:
        return background

    coverage = min(1.0, max(0.0, float(accum["coverage"])))
    return tuple(
        (float(color[i]) / total_weight) * coverage + background[i] * (1.0 - coverage)
        for i in range(3)
    )


def peel_layers(fragments: list[dict], layers: int) -> list[list[dict]]:
    """执行深度剥离并返回从近到远的层。

    先按 ``depth`` 升序（近到远）排序，再取前 ``layers`` 个片段；每个片段
    单独组成一层，所以返回值是长度恰为 ``layers`` 的列表，每项是一个只含
    一个片段的列表。

    ``layers`` 必须是 ``1 <= layers <= len(fragments)`` 的整数。层数超过
    片元数、层数小于 1、片段为空、字段非法或存在重复 ``depth`` 时抛
    :class:`OitError`。

    Args:
        fragments: 待剥离的片段列表。
        layers: 期望剥离的层数。

    Returns:
        每层一个片段组的列表，顺序为近到远。

    Raises:
        OitError: 层数非法或片段列表非法。
    """
    checked = _check_fragments(fragments)
    if not isinstance(layers, int) or isinstance(layers, bool):
        raise OitError(f"层数必须是整数，得到 {layers!r}")
    if layers < 1:
        raise OitError(f"层数必须 >= 1，得到 {layers}")
    if layers > len(checked):
        raise OitError(f"层数 {layers} 超过片元数 {len(checked)}")
    ordered = sorted(checked, key=lambda f: f["depth"])
    return [[dict(f)] for f in ordered[:layers]]


def blend_premultiplied(
    a: tuple[float, float, float],
    b: tuple[float, float, float],
    alpha: float,
) -> tuple[float, float, float]:
    """对预乘颜色做 source-over 混合。

    ``a`` 是前景预乘 RGB，``b`` 是背景预乘 RGB。先将 ``alpha`` 钳制到
    ``[0, 1]``，再计算::

        out = a + b * (1 - clamp(alpha, 0, 1))

    ``a`` 已经是预乘颜色，绝不能再乘一次 ``alpha``。``alpha`` 超过 1 时
    按 1 处理，小于 0 时按 0 处理；非有限 ``alpha`` 抛 :class:`OitError`。
    结果在 ``1e-6`` 容差内逐通道比较。

    Args:
        a: 前景预乘 RGB。
        b: 背景预乘 RGB。
        alpha: 前景不透明度，可越界但会被钳制。

    Returns:
        混合后的预乘 RGB。

    Raises:
        OitError: ``alpha`` 不是有限数。
    """
    if not _is_finite(alpha):
        raise OitError(f"alpha 必须是有限数，得到 {alpha!r}")
    clamped = min(1.0, max(0.0, float(alpha)))
    if clamped <= 0.0:
        # 前景完全透明：预乘前景等价于零，只保留背景。
        return tuple(float(c) for c in b)
    return tuple(a[i] + b[i] * (1.0 - clamped) for i in range(3))


def sort_reference(fragments: list[dict]) -> list:
    """返回按深度从远到近排序的片段副本，作为暴力参考解。

    该函数用于验证与顺序无关的累积结果；它不修改输入列表或片段字典。
    排序键仅为 ``depth``（降序）。空列表、字段非法或重复 ``depth`` 抛
    :class:`OitError`，以保证参考顺序唯一、可复现。

    Args:
        fragments: 待排序的片段列表。

    Returns:
        新的片段字典列表，按 ``depth`` 从大到小排列。

    Raises:
        OitError: 列表为空或任一字段非法。
    """
    checked = _check_fragments(fragments)
    return [dict(f) for f in sorted(checked, key=lambda f: f["depth"], reverse=True)]


def validate_fragments(fragments: list[dict]) -> list[str]:
    """返回片段列表的问题描述；空列表表示全部合法。

    检查内容包括：列表为空；片段不是字典或缺少 ``color``/``alpha``/
    ``depth``；``color`` 不是三个 ``[0, 1]`` 有限数；``alpha`` 或 ``depth``
    越界/非有限；``depth`` 重复（重复深度会破坏稳定解析）。

    本函数不抛 :class:`OitError`，而是把所有能发现的问题收集为字符串列表。
    消息分别包含 ``empty``、``alpha``、``depth``、``duplicate`` 等关键字。

    Args:
        fragments: 待校验的片段列表。

    Returns:
        问题描述列表，合法时为空列表。

    Raises:
        OitError: 不抛出；所有问题都通过返回值报告。
    """
    issues: list[str] = []
    if not fragments:
        return ["fragment list is empty（empty）"]

    depths = []
    for index, fragment in enumerate(fragments):
        if not isinstance(fragment, dict):
            issues.append(f"fragment {index} is not a dict")
            continue
        for field in ("color", "alpha", "depth"):
            if field not in fragment:
                issues.append(f"fragment {index} missing field {field!r}")
        color = fragment.get("color")
        if "color" in fragment and (
            not isinstance(color, (tuple, list))
            or len(color) != 3
            or not all(_is_finite(c) and 0.0 <= c <= 1.0 for c in color)
        ):
            issues.append(f"fragment {index} has invalid color {color!r}")
        if "alpha" in fragment:
            alpha = fragment["alpha"]
            if not _is_finite(alpha) or not (0.0 <= alpha <= 1.0):
                issues.append(f"fragment {index} has invalid alpha {alpha!r}")
        if "depth" in fragment:
            depth = fragment["depth"]
            if not _is_finite(depth) or not (0.0 <= depth <= 1.0):
                issues.append(f"fragment {index} has invalid depth {depth!r}")
            else:
                depths.append(float(depth))

    if len(depths) != len(set(depths)):
        issues.append("duplicate depth values found（duplicate）")
    return issues


def oit_batch(passes: list[dict], config: dict) -> dict:
    """批量解析多个 pass；任一 pass 非法时整体失败、不返回部分结果。

    Args:
        passes: 每个元素为::

            {
                "name": str,
                "fragments": list[dict],
                "background": optional tuple[float, float, float],
            }

            ``background`` 省略时使用 ``config["background"]``。
        config: 至少包含 ``{"background": (r, g, b)}``，作为默认背景。

    Returns:
        ::

            {
                "results": [
                    {"name": str, "color": tuple, "accum": dict},
                    ...
                ]
            }

        ``results`` 的顺序与输入 ``passes`` 完全一致。

    本函数先完整校验所有 pass，再逐个使用独立的累积缓冲解析；不会复用
    其它 pass 的累积状态。任一片段列表为空、字段非法、背景非法或 pass
    结构非法时立即抛 :class:`OitError`，不返回部分结果（整体回滚）。

    Raises:
        OitError: 任一 pass 或 config 非法。
    """
    if not isinstance(config, dict) or "background" not in config:
        raise OitError("config 必须包含 background")
    default_background = _check_rgb(config["background"], "config background")
    if not isinstance(passes, (list, tuple)):
        raise OitError("passes 必须是列表")

    # 先完整校验所有 pass，任一非法立即失败（整体回滚）。
    prepared = []
    for index, p in enumerate(passes):
        if not isinstance(p, dict):
            raise OitError(f"pass {index} 必须是字典")
        if "name" not in p or "fragments" not in p:
            raise OitError(f"pass {index} 缺少 name 或 fragments")
        if not isinstance(p["name"], str):
            raise OitError(f"pass {index} 的 name 必须是字符串")
        background = (
            default_background
            if "background" not in p
            else _check_rgb(p["background"], f"pass {index} background")
        )
        fragments = _check_fragments(p["fragments"])
        prepared.append((p["name"], fragments, background))

    # 每个 pass 使用独立的累积缓冲。
    results = []
    for name, fragments, background in prepared:
        accum = accumulate(fragments)
        results.append(
            {"name": name, "color": resolve(accum, background), "accum": accum}
        )
    return {"results": results}
