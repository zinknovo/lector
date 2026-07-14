# ItemPicker、ShoppingSummary、ForkGuard、工具结果截断与注册设计

## 目标

新增 `item_picker` 工具，根据到手价、品类价格档、物流时效、关税档位和用户偏好，从 `shipping_calc` 的候选中筛选最多 `top_n` 件商品；新增 `shopping_summary` 终结工具生成面向前端的购物结论；新增 `fork_guard` 限制 Subagent 递归派发深度；将现有可用工具统一注册到 `FULL_TOOL_SET`。

## 范围

- 新建 `app/tools/item_picker.py`。
- 新建 `app/tools/shopping_summary.py`。
- 新建 `app/agent/fork_guard.py`。
- 新建 `app/agent/tool_registry.py` 作为工具注册表，并保留 `app/agent/tools.py` 兼容导出。
- 新建 `app/agent/middleware.py`，提供工具长结果截断函数。
- 修改 `app/prompt/prompts.yml`，补充强制收尾与 fork 止损规则。
- 修改 `app/agent/dispatch_tool.py`，在受控上下文中进入下一层 fork，并限制运行时间与图递归次数。
- 定义 `PickedItem` 与 `ItemPickerOutput` Pydantic 模型。
- 定义 `ShoppingSummaryOutput` Pydantic 模型。
- 实现硬偏好过滤、候选评分、降序排序和 Top-N 截断。
- 实现基于现有 `get_llm()` 与 `get_shopping_summary_prompt()` 的最终 Markdown 总结。
- 将 `item_search`、`category_insight`、`item_picker`、`price_compare`、`shipping_calc`、`shopping_summary`、`dispatch_tool` 注册到现有 `app/agent/tools.py` 的 `FULL_TOOL_SET`。
- 不创建当前仓库中没有源码的 `planner`、`chat_fallback`、`web_search`。

## 行为

1. `item_picker` 上报工具开始事件。
2. 用户偏好包含“不爱塑料”且候选为 eBay、商品 ID 以 `-PLASTIC` 结尾时，将其硬过滤，并记录简短拒绝原因。
3. 其余候选按以下规则累加分数：
   - 到手价落在品类 `budget` 价格档：`+0.4`。
   - 物流时效不超过 12 天：`+0.2`。
   - 关税档位为“免征”：`+0.2`。
   - 用户偏好包含“小众”，且平台为 Shopee 或 AliExpress：`+0.2`。
4. 每个候选最多保留 3 条入选理由。
5. 候选按分数降序排列，返回前 `top_n` 件；拒绝摘要最多返回 8 条。
6. 上报工具结束事件并返回结构化 Pydantic 对象。
7. `shopping_summary` 将原始用户 Query 和 `PickedItem` 列表序列化为 JSON，连同现有总结 Prompt 交给主 LLM。
8. `shopping_summary` 返回 LLM 最终文本、原始精选商品和本轮新偏好；新偏好为空时返回空列表。
9. `enter_fork()` 使用 `ContextVar` 保存当前异步上下文的 fork 深度，默认深度为 0，最大深度为 2。
10. 进入 fork 时深度加一；退出或发生异常时恢复进入前的深度。达到上限后抛出 `ForkLimitExceeded`。
11. `dispatch_tool` 在 `enter_fork()` 上下文内创建并执行子 Agent。为避免 `dispatch_tool` 与工具注册表循环导入，`FULL_TOOL_SET` 在函数执行时从 `tool_registry` 延迟导入。
12. 子线程 ID 包含当前 fork 深度，格式为 `sub-<8位随机值>-d<depth>`。
13. 子 Agent 的单次运行超时为 90 秒，LangGraph `recursion_limit` 为 12；超时后返回可读错误文本，不向外抛出异常。
14. fork 深度越界时捕获 `ForkLimitExceeded`，返回可读拒绝文本，提示主 Agent 自行处理或更换拆分方式。
15. `truncate_long_tool_result()` 按 4 字符约等于 1 token，将工具文本限制在约 4000 token（16000 字符）；未超限时原样返回，超限时保留前部并追加明确截断提示。
16. `LoopDetector` 默认保存最近 6 次工具调用；同一个工具名在窗口内出现至少 4 次时返回 `True`，供 Agent 执行图判断是否终止循环。
17. System Prompt 规定：ItemPicker 返回至少一件商品后立即调用 ShoppingSummary，不再调用检索工具，并把本轮新偏好放入 `new_preferences`。
18. System Prompt 规定：子任务尽量在一层 fork 内完成；dispatch 被拒绝或超时后立即换方案；同一工具重复四次仍无进展时检查参数，并在必要时与用户重新对齐。

## 错误与边界

- `insight` 和 `user_preferences` 允许为空。
- 没有 `budget` 档位时跳过价格加分。
- `top_n` 小于等于零时不返回入选商品。
- 监控逻辑沿用现有 `monitor` 接口。
- LLM 返回内容统一转换为字符串，保证符合 `ShoppingSummaryOutput.final_text` 类型。
- fork 深度按协程上下文隔离，不使用进程级可变全局计数器。
- 无论子 Agent 正常完成、抛错还是超时，`thread_id`、`session_dir` 和 fork 深度都必须恢复。

## 测试

- 硬过滤命中和未命中。
- 四类评分规则及理由。
- 排序、Top-N 截断和拒绝摘要。
- ShoppingSummary 的输入消息、输出文本和新偏好透传。
- ForkGuard 的嵌套深度、越界异常、异常后复位和异步任务隔离。
- DispatchTool 的深度线程 ID、90 秒超时、12 次递归配置和降级文本。
- 工具结果在阈值内保持不变，超限时长度受控且包含截断提示。
- LoopDetector 在阈值前返回 `False`，达到阈值后返回 `True`，并正确淘汰滑动窗口外的历史。
- Prompt 文本包含收尾条件、新偏好透传、dispatch 降级和重复调用止损规则。
- `FULL_TOOL_SET` 包含七个现有工具，包括受深度限制的 `dispatch_tool`。
