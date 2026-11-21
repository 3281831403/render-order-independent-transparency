"""render-order-independent-transparency 的验收测试。

初始状态下 ``oit/accumulate.py`` 中 8 个函数全部是桩，因此本文件的 15 个
测试应当全部失败（红），且不应出现 collection/import/syntax error。

测试与缺陷的对应关系：
1. weight 用 1-alpha                     -> test_weight_uses_depth_and_alpha_not_inverse_alpha
2. 累积不预乘颜色                        -> test_accumulate_premultiplies_color_by_alpha
3. 按输入顺序而非权重和解析              -> test_accumulate_order_is_independent
4. 权重和为 0 时除零                     -> test_resolve_returns_background_for_zero_weight
5. 剥离层数不校验                        -> test_peel_layers_rejects_more_layers_than_fragments
6. 预乘混合重复乘 alpha                  -> test_blend_premultiplied_does_not_double_apply_alpha
7. alpha 不钳制                          -> test_blend_premultiplied_clamps_out_of_range_alpha
8. 重复深度不报错                        -> test_validate_fragments_reports_duplicate_depth
9. 批量共用累积缓冲                      -> test_oit_batch_isolates_passes
10. 背景色不参与解析                     -> test_resolve_blends_background_through_transparency
组合：单层不透明、全透明、乱序一致、空片元、批量顺序。
"""

import pytest

from oit.accumulate import (
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

BACKGROUND = (0.05, 0.10, 0.15)


def _fragment(color, alpha, depth):
    """构造一个符合契约的片段。"""
    return {"color": color, "alpha": alpha, "depth": depth}


def test_weight_uses_depth_and_alpha_not_inverse_alpha():
    """缺陷 1：权重必须随深度和 alpha 增大，而不是使用 1-alpha。"""
    near = weight(0.10, 0.80)
    far = weight(0.90, 0.80)
    low_alpha = weight(0.10, 0.10)

    assert near > far
    assert near > low_alpha
    assert weight(0.0, 1.0) > 0.0


def test_accumulate_premultiplies_color_by_alpha():
    """缺陷 2：累积颜色应按 alpha 预乘，而不是直接累加直通颜色。"""
    alpha = 0.25
    color = (0.8, 1.0, 0.2)
    w = weight(0.0, alpha)
    accum = accumulate([_fragment(color, alpha, 0.0)])

    assert accum["weight"] == pytest.approx(w, abs=1e-6)
    assert accum["color"] == pytest.approx(
        tuple(channel * w for channel in color), abs=1e-6
    )


def test_accumulate_order_is_independent():
    """缺陷 3：打乱输入顺序后累积与解析结果必须一致。"""
    fragments = [
        _fragment((0.90, 0.10, 0.00), 0.70, 0.20),
        _fragment((0.00, 0.60, 0.80), 0.40, 0.80),
        _fragment((0.30, 0.20, 0.10), 0.55, 0.50),
    ]
    reordered = [fragments[2], fragments[0], fragments[1]]

    first = resolve(accumulate(fragments), BACKGROUND)
    second = resolve(accumulate(reordered), BACKGROUND)

    assert first == pytest.approx(second, abs=1e-6)


def test_resolve_returns_background_for_zero_weight():
    """缺陷 4：权重和为 0 时不得除零，应直接返回背景。"""
    zero_accum = {"color": (1.0, 0.5, 0.25), "weight": 0.0, "coverage": 0.0}

    assert resolve(zero_accum, BACKGROUND) == pytest.approx(BACKGROUND, abs=1e-6)


def test_peel_layers_rejects_more_layers_than_fragments():
    """缺陷 5：请求层数超过片元数时必须抛 OitError。"""
    fragments = [
        _fragment((0.9, 0.1, 0.1), 0.5, 0.1),
        _fragment((0.1, 0.9, 0.1), 0.5, 0.5),
        _fragment((0.1, 0.1, 0.9), 0.5, 0.9),
    ]

    with pytest.raises(OitError):
        peel_layers(fragments, len(fragments) + 1)


def test_blend_premultiplied_does_not_double_apply_alpha():
    """缺陷 6：a 已是预乘颜色，混合时不能再乘一次 alpha。"""
    a = (0.5, 0.25, 0.0)
    b = (0.0, 0.2, 0.4)

    result = blend_premultiplied(a, b, 0.5)

    assert result == pytest.approx((0.5, 0.35, 0.2), abs=1e-6)


def test_blend_premultiplied_clamps_out_of_range_alpha():
    """缺陷 7：alpha 必须先钳制到 [0, 1]，否则超过 1 会溢出。"""
    a = (0.2, 0.4, 0.6)
    b = (0.9, 0.8, 0.7)

    assert blend_premultiplied(a, b, 1.5) == pytest.approx(a, abs=1e-6)
    assert blend_premultiplied(a, b, -0.5) == pytest.approx(b, abs=1e-6)


def test_validate_fragments_reports_duplicate_depth():
    """缺陷 8：重复深度必须作为问题返回，不能静默通过。"""
    fragments = [
        _fragment((1.0, 0.0, 0.0), 1.0, 0.5),
        _fragment((0.0, 1.0, 0.0), 0.5, 0.5),
    ]

    issues = validate_fragments(fragments)

    assert any("duplicate" in issue.lower() for issue in issues)


def test_oit_batch_isolates_passes():
    """缺陷 9：每个 pass 必须使用独立缓冲，并在非法 pass 时整体失败。"""
    passes = [
        {"name": "red", "fragments": [_fragment((1.0, 0.0, 0.0), 1.0, 0.0)]},
        {"name": "blue", "fragments": [_fragment((0.0, 0.0, 1.0), 1.0, 0.0)]},
    ]

    batch = oit_batch(passes, {"background": BACKGROUND})
    results = batch["results"]

    assert results[0]["color"] == pytest.approx((1.0, 0.0, 0.0), abs=1e-6)
    assert results[1]["color"] == pytest.approx((0.0, 0.0, 1.0), abs=1e-6)

    bad = {"name": "bad", "fragments": [_fragment((0.0, 1.0, 0.0), 1.5, 0.0)]}
    with pytest.raises(OitError):
        oit_batch([passes[0], bad], {"background": BACKGROUND})


def test_resolve_blends_background_through_transparency():
    """缺陷 10：解析必须让背景透过半透明区域，而不是变成黑色。"""
    accum = accumulate([_fragment((1.0, 0.0, 0.0), 0.5, 0.0)])

    result = resolve(accum, (0.0, 0.0, 1.0))

    assert result == pytest.approx((0.5, 0.0, 0.5), abs=1e-6)


def test_single_opaque_fragment_equals_its_color():
    """组合：单层不透明片元的解析结果等于其颜色。"""
    color = (0.12, 0.34, 0.56)

    accum = accumulate([_fragment(color, 1.0, 0.35)])

    assert resolve(accum, (0.9, 0.8, 0.7)) == pytest.approx(color, abs=1e-6)


def test_all_transparent_fragments_return_background():
    """组合：全部 alpha=0 的片元权重和为 0，返回背景。"""
    fragments = [
        _fragment((1.0, 0.0, 0.0), 0.0, 0.2),
        _fragment((0.0, 1.0, 0.0), 0.0, 0.8),
    ]

    accum = accumulate(fragments)

    assert accum["weight"] == pytest.approx(0.0, abs=1e-6)
    assert resolve(accum, BACKGROUND) == pytest.approx(BACKGROUND, abs=1e-6)


def test_shuffled_fragments_match_reference():
    """组合：乱序输入与参考排序在 1e-6 容差内一致。"""
    fragments = [
        _fragment((0.8, 0.1, 0.1), 0.65, 0.15),
        _fragment((0.1, 0.7, 0.2), 0.35, 0.55),
        _fragment((0.1, 0.2, 0.9), 0.50, 0.85),
    ]
    shuffled = [fragments[2], fragments[0], fragments[1]]

    baseline = resolve(accumulate(fragments), BACKGROUND)
    from_shuffled = resolve(accumulate(shuffled), BACKGROUND)

    assert from_shuffled == pytest.approx(baseline, abs=1e-6)
    assert [f["depth"] for f in sort_reference(fragments)] == [0.85, 0.55, 0.15]


def test_empty_fragments_raise_oit_error():
    """组合：空片元列表必须抛 OitError，而不是静默返回空累积。"""
    with pytest.raises(OitError):
        accumulate([])


def test_batch_preserves_pass_order_on_success():
    """组合：批量全部成功时，结果顺序与输入 passes 顺序一致。"""
    passes = [
        {"name": "sky", "fragments": [_fragment((0.2, 0.5, 0.9), 0.8, 0.2)]},
        {"name": "glass", "fragments": [_fragment((0.9, 0.9, 0.8), 0.6, 0.4)]},
        {"name": "smoke", "fragments": [_fragment((0.3, 0.3, 0.3), 0.4, 0.7)]},
    ]

    batch = oit_batch(passes, {"background": BACKGROUND})

    assert [result["name"] for result in batch["results"]] == [
        "sky",
        "glass",
        "smoke",
    ]
