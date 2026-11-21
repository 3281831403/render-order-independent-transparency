# render-order-independent-transparency

## 题面

透明物体改成顺序无关渲染后，玻璃叠在一起发亮、边缘还发黑：权重退化成 1-alpha，深色片元权重过大；累积时直接用直通颜色、没有按 alpha 预乘，透明区域发亮；解析按输入顺序而不是权重和进行，结果随图元顺序变化；权重和为零时直接做除法，出现除零；深度剥离不校验层数，请求层数可能超过片元数；预乘混合又乘了一次 alpha，边缘发暗；alpha 没有钳制到 0..1，超过 1 后颜色溢出；重复深度的片元不报错，稳定解析失败；批量解析共用一份累积缓冲，pass 之间串色；解析时忽略背景色，透明区域被解析成黑色。oit/accumulate.py 是核心，tests/test_accumulate.py 15个红。要修的是：用深度和 alpha 计算 McGuire 风格权重，按 alpha 预乘并做顺序无关的加权累积，用权重和与覆盖率解析并把背景混入透明区域，权重和为零时回退背景，校验剥离层数，单次预乘混合并钳制 alpha，拒绝重复深度，批量解析为每个 pass 使用独立缓冲且任一 pass 非法时整体回滚。

## 运行方式

在仓库根目录执行：

```powershell
cd D:\gsb-20261119\render-order-independent-transparency
python -m pytest tests -q
```

初始状态是故意留下的失败环境：8 个函数都只 `raise NotImplementedError`，15 个测试全部调用这些桩，因此输出尾部应恰好是：

```text
15 failed in ...s
```

必须恰好 `15 failed`，不能出现 collection error、import error 或 syntax error。修复 `oit/accumulate.py` 后，同样的命令应变成 `15 passed`。

## 字段表

| 字段 | 取值 |
| --- | --- |
| 所属领域 | 游戏、图形与多媒体 |
| 子方向 | 图形渲染 |
| 任务类型 | Bugfix |
| 语言/框架 | Python 3, pytest |
| 环境可复现等级 | 无外部依赖 |

## 初始结构

```text
render-order-independent-transparency/
├── README.md
├── conftest.py
├── .gitignore
├── oit/
│   ├── __init__.py
│   └── accumulate.py
└── tests/
    └── test_accumulate.py
```

`conftest.py` 只负责把仓库根加入 `sys.path`。`.gitignore` 只有三行。

## 接口约定

片段统一为 `{"color": (r, g, b), "alpha": a, "depth": d}`：

- `color` 是直通 RGB，每个分量在 `[0, 1]`；`accumulate` 内部按 `alpha` 预乘，输出的是预乘颜色的加权和。
- `alpha` 与 `depth` 是 `[0, 1]` 内的有限数；浮点比较容差为 `1e-6`。
- `blend_premultiplied` 的 `a`、`b` 都是预乘 RGB，`alpha` 会被钳制到 `[0, 1]`。
- 非法输入使用 `OitError`；`validate_fragments` 不抛异常，而是返回问题描述列表。
- 8 个函数是 `weight`、`accumulate`、`resolve`、`peel_layers`、`blend_premultiplied`、`sort_reference`、`validate_fragments`、`oit_batch`，完整契约见 `oit/accumulate.py` 的 docstring。
- `oit_batch` 的 `passes` 为 `[{"name", "fragments", "background"?}, ...]`，`config` 至少包含默认 `background`；结果在 `{"results": [{"name", "color", "accum"}, ...]}` 中保持输入顺序。

## 约束

- 只使用标准库 `math` 与 `pytest`，离线运行，不使用随机数。
- `tests/test_accumulate.py` 不可修改；只能修 `oit/accumulate.py`。
- `tests/test_accumulate.py` 固定 15 个测试：10 个缺陷各 1 条，另加单层不透明、全透明、乱序一致、空片元异常、批量顺序 5 条组合。
