"""兼容旧导入路径；新模块统一从 shared.contracts 导入。禁止在此重复定义字段。"""

from shared.contracts import (
    AnalysisResult as AnalysisResult,
)
from shared.contracts import (
    Block as Block,
)
from shared.contracts import (
    Candidate as Candidate,
)
from shared.contracts import (
    Contract as Contract,
)
from shared.contracts import (
    DocumentRef as DocumentRef,
)
from shared.contracts import (
    EntityRecord as EntityRecord,
)
from shared.contracts import (
    EntityResolver as EntityResolver,
)
from shared.contracts import (
    Evidence as Evidence,
)
from shared.contracts import (
    ExtractionResult as ExtractionResult,
)
from shared.contracts import (
    FileRef as FileRef,
)
from shared.contracts import (
    Finding as Finding,
)
from shared.contracts import (
    IngestResult as IngestResult,
)
from shared.contracts import (
    MainRAG as MainRAG,
)
from shared.contracts import (
    Modules as Modules,
)
from shared.contracts import (
    ParsedBlock as ParsedBlock,
)
from shared.contracts import (
    ParsedDocument as ParsedDocument,
)
from shared.contracts import (
    Resolution as Resolution,
)
from shared.contracts import (
    RiskAnalyzer as RiskAnalyzer,
)
from shared.contracts import (
    Scope as Scope,
)
from shared.contracts import (
    Snapshot as Snapshot,
)
from shared.contracts import (
    SuggestionDraft as SuggestionDraft,
)
from shared.contracts import (
    Workflow as Workflow,
)
