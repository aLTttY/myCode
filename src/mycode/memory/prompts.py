MEMORY_DECISION_PROMPT = """你负责维护 MyCode 长期记忆。只分析提供的本轮快照和两级索引，不得调用工具。
只记录未来确有复用价值的信息，类别只能是 user_preference、correction_feedback、project_knowledge、reference。
跨项目偏好或通用纠正使用 user scope；项目特定内容使用 project scope；不确定时使用 project。
必须基于语义去重：已有事实应 update 或 ignore，不得因措辞变化重复 create。
不得记录 API Key、令牌、密码、私钥或其他凭据。
输出唯一的 <memory_update>JSON</memory_update>，JSON 顶层只能有 operations 数组。
每个操作 action 为 ignore、create、update。create/update 必须含 scope、category、importance(1-5)、title、summary、body；
update 还必须含索引中已有的 target_id。没有值得记录的信息时输出空 operations。"""

MEMORY_MERGE_PROMPT = """合并一条已有长期记忆与新证据。不得调用工具，不得记录任何凭据。
保留仍然正确的事实，吸收新证据，删除被纠正的旧事实。输出唯一的 <memory_update>JSON</memory_update>，
其中 operations 恰有一个 update，target_id、scope 和 category 必须与输入相同，并给出完整 title、summary、body 和 importance。"""

MEMORY_COMPACT_PROMPT = """精简记忆索引摘要，不得调用工具，不得发明、删除或改写 note ID。
输出唯一的 <memory_index>JSON</memory_index>。JSON 顶层只能有 entries 数组，每项必须包含输入中已有的 id、
精简后的单行 summary 和 importance(1-5)，且必须恰好覆盖全部输入 ID。"""
