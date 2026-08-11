"""错误码体系：对内数字段（API code 字段）与对外短码的桥接。

规则（SPEC 9.1）：
- API 响应 code 字段用对内数字段；前端据映射表渲染对外短码
- 1xxx 客户端校验 / 2xxx 模型与解析 / 3xxx 检索与搜索 / 5xxx 服务端
- 子码：1901 频率 / 3901 配额熔断 / 5901-5903 配置类 / 5000 通用内部错误
"""

# ---- 1xxx 客户端校验 ----
CODE_INVALID_FORMAT = 1001        # 图片格式不支持
CODE_IMAGE_TOO_LARGE = 1002       # 图片超过大小上限
CODE_IMAGE_UNREADABLE = 1003      # 图片损坏/无法解码
CODE_NOT_FOUND = 1404             # 资源不存在或已过期
CODE_UNAUTHORIZED = 1401          # 管理页鉴权失败

# ---- 2xxx 模型与解析 ----
CODE_VISION_FAILED = 2001         # 视觉模型调用失败
CODE_CLAIM_PARSE_FAILED = 2002    # claim-v1 解析/校验失败
CODE_SCOPE_PARSE_FAILED = 2003    # scope-v1 解析失败
CODE_EVIDENCE_PARSE_FAILED = 2004 # evidence-v1 解析失败
CODE_ANALYSIS_TIMEOUT = 2408      # 核验超时 >60s（对外 T-408）

# ---- 3xxx 检索与搜索 ----
CODE_KB_UNAVAILABLE = 3001        # 知识库不可用（层内降级，不直接对用户）
CODE_SEARCH_UNAVAILABLE = 3002    # 搜索服务不可用
CODE_QUOTA_EXHAUSTED = 3901       # 日配额/成本熔断（对外 Q-429）

# ---- 5xxx 服务端 ----
CODE_INTERNAL_ERROR = 5000        # 通用内部错误（对外 E-500）
CODE_LLM_CONFIG_INVALID = 5901    # 模型 key 缺失/失效（对外 S-503）
CODE_KB_CONFIG_INVALID = 5902     # 知识库配置异常（对外 S-503）
CODE_SEARCH_CONFIG_INVALID = 5903 # 搜索配置异常（对外 S-503）

# 对内数字段 -> 对外短码（SPEC 9.1 映射表）
PUBLIC_CODE_MAP: dict[int, str] = {
    CODE_INVALID_FORMAT: "E-400",
    CODE_IMAGE_TOO_LARGE: "E-400",
    CODE_IMAGE_UNREADABLE: "E-400",
    CODE_NOT_FOUND: "E-404",
    CODE_UNAUTHORIZED: "E-401",
    CODE_VISION_FAILED: "E-500",
    CODE_CLAIM_PARSE_FAILED: "E-500",
    CODE_SCOPE_PARSE_FAILED: "E-500",
    CODE_EVIDENCE_PARSE_FAILED: "E-500",
    CODE_ANALYSIS_TIMEOUT: "T-408",
    CODE_KB_UNAVAILABLE: "S-503",
    CODE_SEARCH_UNAVAILABLE: "S-503",
    CODE_QUOTA_EXHAUSTED: "Q-429",
    CODE_INTERNAL_ERROR: "E-500",
    CODE_LLM_CONFIG_INVALID: "S-503",
    CODE_KB_CONFIG_INVALID: "S-503",
    CODE_SEARCH_CONFIG_INVALID: "S-503",
}


class AppError(Exception):
    """业务异常：携带对内错误码与用户安全文案。message 不暴露技术细节。"""

    def __init__(self, code: int, message: str, http_status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status

    @property
    def public_code(self) -> str:
        return PUBLIC_CODE_MAP.get(self.code, "E-500")


def public_code_of(code: int | None) -> str | None:
    if code is None:
        return None
    return PUBLIC_CODE_MAP.get(code, "E-500")
