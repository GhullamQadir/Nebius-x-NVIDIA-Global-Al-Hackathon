"""
Nexora Context Optimizer
Indexes, ranks, budgets, compresses, and caches repository context
"""
import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from nexora.backend.app.models import ModelRegistry
from nexora.backend.app.schemas import ContextPackageBase as ContextPackageSchema


@dataclass
class FileInfo:
    """Indexed file information"""
    path: str
    language: str
    size: int
    hash: str
    symbols: List[str] = field(default_factory=list)
    imports: List[str] = field(default_factory=list)
    is_test: bool = False
    is_generated: bool = False
    last_modified: float = 0


@dataclass
class RankedFile:
    """File with relevance score"""
    file_info: FileInfo
    score: float
    reasons: List[str] = field(default_factory=list)


@dataclass
class ContextPackage:
    """Prepared context for model"""
    included_files: List[Dict[str, Any]]
    omitted_categories: List[Dict[str, Any]]
    ranking_reasons: Dict[str, str]
    cache_hits: int
    estimated_tokens: int
    compression_ratio: Optional[float]


import ast


def skeletonize_python(source_code: str) -> str:
    """
    Extract class and function signatures, type annotations, imports, 
    and docstrings, replacing function bodies with 'pass'.
    """
    try:
        tree = ast.parse(source_code)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                doc = ast.get_docstring(node)
                if doc:
                    node.body = [ast.Expr(value=ast.Constant(value=doc)), ast.Pass()]
                else:
                    node.body = [ast.Pass()]
        return ast.unparse(tree)
    except Exception:
        # Fallback to source code if syntax cannot be parsed
        return source_code


_CODE_BLOCK_RE = re.compile(r"```(?:python|py)?\n(.*?)```", re.DOTALL | re.IGNORECASE)


def compact_code_blocks_in_text(text: str) -> str:
    """Find Python code blocks in markdown and replace their bodies with AST skeletons."""
    def _repl(match):
        code = match.group(1)
        try:
            tree = ast.parse(code)
            has_defs = any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) for node in ast.walk(tree))
            if has_defs:
                skeleton = skeletonize_python(code)
                return f"```python\n{skeleton}\n```"
        except Exception:
            pass
        return match.group(0)

    return _CODE_BLOCK_RE.sub(_repl, text)


def truncate_head_tail(
    text: Any,
    max_chars: int = 4000,
    head_ratio: float = 0.45,
    tail_ratio: float = 0.45,
    marker: Optional[str] = None,
) -> str:
    """
    Intelligently truncate long text by preserving both the beginning (head)
    and the end (tail), breaking cleanly on newline boundaries where possible.
    
    Prevents loss of top-level imports/signatures and bottom stack traces / return statements.
    """
    if text is None:
        return ""
    if not isinstance(text, str):
        text = str(text)
    if len(text) <= max_chars:
        return text

    avail_chars = max(20, max_chars - 80)
    target_head_len = int(avail_chars * head_ratio)
    target_tail_len = int(avail_chars * tail_ratio)

    if target_head_len + target_tail_len >= len(text):
        return text[:max_chars]

    omitted_chars = max(0, len(text) - target_head_len - target_tail_len)

    if marker is None:
        if max_chars < 300:
            marker = f"\n... [snip {omitted_chars:,} chars] ...\n"
        else:
            marker = f"\n... [Omitted {omitted_chars:,} characters; head & tail preserved] ...\n"

    # Refine available room with actual marker length
    avail_chars = max(20, max_chars - len(marker))
    target_head_len = int(avail_chars * head_ratio)
    target_tail_len = int(avail_chars * tail_ratio)


    # Find clean newline boundary near head
    head_cutoff = text.rfind("\n", 0, target_head_len)
    if head_cutoff == -1 or head_cutoff < int(target_head_len * 0.5):
        head_cutoff = target_head_len

    # Find clean newline boundary near tail
    tail_start_target = len(text) - target_tail_len
    tail_start = text.rfind(
        "\n",
        max(0, tail_start_target - int(target_tail_len * 0.5)),
        tail_start_target + int(target_tail_len * 0.3),
    )
    if tail_start == -1:
        tail_start = text.find("\n", tail_start_target)
        if tail_start == -1 or tail_start > tail_start_target + int(target_tail_len * 0.5):
            tail_start = tail_start_target

    if head_cutoff >= tail_start:
        return text[:max_chars]

    head_part = text[:head_cutoff].rstrip()
    tail_part = text[tail_start:].lstrip()

    result = f"{head_part}{marker}{tail_part}"
    if len(result) > max_chars:
        # Enforce strict ceiling if newline snapping caused slight overflow
        overflow = len(result) - max_chars
        if len(head_part) > overflow + 10:
            head_part = head_part[:-overflow].rstrip()
            result = f"{head_part}{marker}{tail_part}"
        else:
            result = result[:max_chars]

    return result



@dataclass
class ConversationTurn:
    """A user prompt and subsequent assistant reply."""
    user_prompt: str
    assistant_response: str
    created_at: Optional[datetime] = None
    run_id: Optional[str] = None


def distill_session_state(turns: List[ConversationTurn]) -> str:
    """
    Distills a sequence of older conversation turns into a high-density, structured
    <session_state> block to preserve context and continuity without exhausting the context window.
    """
    if not turns:
        return ""

    initial_goal = turns[0].user_prompt.strip()
    initial_goal_line = initial_goal.split("\n")[0][:120]

    file_pattern = re.compile(
        r'\b([\w\-./]+\.(?:py|js|jsx|ts|tsx|html|css|json|yaml|yml|md|sql))\b',
        re.IGNORECASE
    )
    discovered_files: Set[str] = set()
    step_summaries = []

    for idx, turn in enumerate(turns, 1):
        u_clean = turn.user_prompt.strip().replace("\n", " ")
        if len(u_clean) > 80:
            u_clean = u_clean[:80] + "..."

        # Scan for referenced files
        for match in file_pattern.findall(turn.user_prompt + " " + turn.assistant_response):
            cleaned = match.strip("./")
            if cleaned and not cleaned.startswith("."):
                discovered_files.add(cleaned)

        # Classify outcome
        outcome = "Completed request"
        a_text = turn.assistant_response
        if "```" in a_text:
            outcome = "Provided code implementation"
        elif any(k in a_text.lower() for k in ["error", "fail", "issue", "bug"]):
            outcome = "Resolved verification issue"
        else:
            first_line = a_text.strip().split("\n")[0]
            if first_line and len(first_line) < 60:
                outcome = first_line

        step_summaries.append(f"  - Turn {idx} (User): \"{u_clean}\" -> {outcome}")

    files_str = ", ".join(sorted(list(discovered_files))[:8]) if discovered_files else "None explicitly referenced"
    steps_str = "\n".join(step_summaries[:6])
    if len(step_summaries) > 6:
        steps_str += f"\n  - ... ({len(step_summaries) - 6} earlier turns condensed)"

    return (
        "<session_state>\n"
        "[Session History & Distilled State]\n"
        f"• Initial Goal: {initial_goal_line}\n"
        f"• Historical Milestones ({len(turns)} turns condensed):\n"
        f"{steps_str}\n"
        f"• Active / Referenced Files: {files_str}\n"
        "• State: Preceding history condensed to preserve token budget. Full fidelity maintained for recent turns below.\n"
        "</session_state>"
    )


class HistoryCompactor:
    """
    Token-aware conversation history pruner and AST compactor.
    
    Protects context window from explosive growth during multi-turn chats:
    - Retains newest turns with full fidelity.
    - Condenses older turns into structured <session_state> blocks when budget is exceeded.
    - Compacts Python code blocks via AST skeletonization and conciseness trimming.
    """

    def __init__(self, max_history_tokens: int = 2000):
        self.max_history_tokens = max_history_tokens

    def compact_turn(self, turn: ConversationTurn, is_latest: bool = False) -> Tuple[str, str]:
        """
        Compact a single conversation turn.
        Latest turn keeps full response; older turns get AST skeletonized code and trimmed text.
        """
        user_text = turn.user_prompt.strip()
        assistant_text = turn.assistant_response.strip()

        if is_latest:
            return user_text, assistant_text

        # Older turn: compact Python code blocks via AST
        if "```" in assistant_text:
            assistant_text = compact_code_blocks_in_text(assistant_text)

        # Older turn: preserve head and tail if text is long
        if len(assistant_text) > 400 and "```" not in assistant_text:
            assistant_text = truncate_head_tail(assistant_text, max_chars=350)

        return user_text, assistant_text

    def maybe_compact(
        self,
        turns: List[ConversationTurn],
        preserve_recent_turns: int = 2,
    ) -> Tuple[List[Dict[str, str]], Dict[str, Any]]:
        """
        Intelligently compacts multi-turn conversation history.
        - If history fits comfortably in budget and turn count is low (<= 3), retains turns with code skeletonization.
        - If history exceeds token budget or turn count is high, distills older turns into a high-density
          <session_state> block and retains the newest turns with full fidelity.
        """
        if not turns:
            return [], {
                "total_turns_input": 0,
                "turns_retained": 0,
                "turns_condensed": 0,
                "original_chars": 0,
                "compacted_chars": 0,
                "tokens_saved_pct": 0.0,
                "compacted_tokens": 0,
                "session_state_generated": False,
            }

        original_chars = sum(len(t.user_prompt) + len(t.assistant_response) for t in turns)
        total_turns = len(turns)

        if total_turns == 1:
            turn = turns[0]
            messages = [
                {"role": "user", "content": turn.user_prompt},
                {"role": "assistant", "content": turn.assistant_response},
            ]
            compacted_chars = sum(len(m["content"]) for m in messages)
            return messages, {
                "total_turns_input": 1,
                "turns_retained": 1,
                "turns_condensed": 0,
                "original_chars": original_chars,
                "compacted_chars": compacted_chars,
                "tokens_saved_pct": 0.0,
                "compacted_tokens": compacted_chars // 4,
                "session_state_generated": False,
            }

        compacted_turn_pairs = []
        for i, turn in enumerate(turns):
            is_latest = (i == total_turns - 1)
            u_text, a_text = self.compact_turn(turn, is_latest=is_latest)
            compacted_turn_pairs.append((u_text, a_text))

        # Always retain latest turn
        retained_pairs = [compacted_turn_pairs[-1]]
        used_tokens = (len(compacted_turn_pairs[-1][0]) + len(compacted_turn_pairs[-1][1])) // 4

        older_unretained: List[ConversationTurn] = []
        for idx in range(total_turns - 2, -1, -1):
            u_text, a_text = compacted_turn_pairs[idx]
            pair_tokens = (len(u_text) + len(a_text)) // 4
            if len(retained_pairs) < preserve_recent_turns and used_tokens + pair_tokens <= self.max_history_tokens:
                retained_pairs.insert(0, (u_text, a_text))
                used_tokens += pair_tokens
            elif used_tokens + pair_tokens <= self.max_history_tokens and total_turns <= 3:
                retained_pairs.insert(0, (u_text, a_text))
                used_tokens += pair_tokens
            else:
                older_unretained.insert(0, turns[idx])

        messages = []
        session_state_generated = False

        if older_unretained:
            session_state = distill_session_state(older_unretained)
            session_messages = [
                {"role": "user", "content": session_state},
                {
                    "role": "assistant",
                    "content": "Acknowledged. I have the context of previous milestones, touched files, and constraints from the session state. Continuing with the latest instructions.",
                },
            ]
            messages.extend(session_messages)
            session_state_generated = True

        for u_text, a_text in retained_pairs:
            messages.append({"role": "user", "content": u_text})
            messages.append({"role": "assistant", "content": a_text})

        compacted_chars = sum(len(m["content"]) for m in messages)
        savings_ratio = round((1.0 - (compacted_chars / max(original_chars, 1))) * 100, 1) if original_chars > 0 else 0.0

        telemetry = {
            "total_turns_input": total_turns,
            "turns_retained": len(retained_pairs),
            "turns_condensed": len(older_unretained),
            "original_chars": original_chars,
            "compacted_chars": compacted_chars,
            "tokens_saved_pct": max(0.0, savings_ratio),
            "compacted_tokens": compacted_chars // 4,
            "session_state_generated": session_state_generated,
        }

        return messages, telemetry

    def prune_and_compact(
        self,
        turns: List[ConversationTurn],
    ) -> Tuple[List[Dict[str, str]], Dict[str, Any]]:
        """Backward-compatible alias for maybe_compact."""
        return self.maybe_compact(turns, preserve_recent_turns=2)


def prune_conversation_history(
    turns: List[ConversationTurn],
    max_history_tokens: int = 2000,
) -> Tuple[List[Dict[str, str]], Dict[str, Any]]:
    """Helper function to prune and compact conversation history with AST optimization."""
    compactor = HistoryCompactor(max_history_tokens=max_history_tokens)
    return compactor.maybe_compact(turns, preserve_recent_turns=2)


def compact_thread_history(
    thread_history: List[Dict[str, Any]],
    max_history_tokens: int = 2000,
    preserve_recent_turns: int = 2,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Compact a raw threaded chat history (list of role/content dicts) using
    rolling session state summarization and AST code skeletonization.
    """
    if not thread_history:
        return [], {"total_turns_input": 0, "session_state_generated": False}

    turns: List[ConversationTurn] = []
    i = 0
    while i < len(thread_history):
        msg = thread_history[i]
        role = msg.get("role")
        content = msg.get("content", "")

        if role == "user":
            u_text = content
            a_text = ""
            if i + 1 < len(thread_history) and thread_history[i + 1].get("role") == "assistant":
                a_text = thread_history[i + 1].get("content", "")
                i += 2
            else:
                i += 1
            turns.append(ConversationTurn(user_prompt=u_text, assistant_response=a_text))
        elif role == "assistant":
            turns.append(ConversationTurn(user_prompt="", assistant_response=content))
            i += 1
        else:
            i += 1

    compactor = HistoryCompactor(max_history_tokens=max_history_tokens)
    return compactor.maybe_compact(turns, preserve_recent_turns=preserve_recent_turns)


def align_prefix_boundary(text: str) -> str:
    """
    Ensure prompt prefix sections terminate with clean boundary separation.
    Prevents token fusion across prompt prefix chunks in vLLM / Nebius Token Factory.
    """
    if not text:
        return ""
    stripped = text.rstrip()
    return f"{stripped}\n\n"


def calculate_dynamic_output_budget(
    objective: str,
    ceiling: int = 8192,
    thread_context: Optional[str] = None,
) -> int:
    """
    Dynamically scale max_tokens based on task complexity while respecting budget profile ceiling:
    - Generative Web / UI / 3D / Animation / Full-page tasks / Detailed code requests: 3072 - 4096 tokens
    - Complex refactor / architecture / system / multi-file: 1536 - 3072 tokens
    - Standard fixes, features, tests, or function additions: 1024 tokens
    - Simple DSA / concise utility tasks (< 12 words without code/detailed keywords): 512 tokens
    """
    obj_words = len(objective.split())
    obj_lower = objective.lower()
    combined_lower = f"{obj_lower} {(thread_context or '').lower()}".strip()

    # Generative web, portfolio, detailed code requests, or full applications
    if any(k in obj_lower for k in [
        "portfolio", "html css", "fullstack", "gui app", "web app", "code in proper manner",
        "detailed", "not simple", "complete code", "full code", "comprehensive"
    ]) or (
        any(k in combined_lower for k in ["portfolio", "html css", "fullstack", "web app", "website", "landing page"])
        and any(w in obj_lower for w in ["code", "detailed", "more", "add", "give", "show", "make", "generate", "expand"])
    ) or obj_words >= 50:
        budget = 4096
    elif any(k in combined_lower for k in ["website", "animation", "3d", "threejs", "frontend", "landing page", "html page", "animated"]):
        budget = 3072
    elif any(k in obj_lower for k in ["refactor", "system", "architecture", "multi", "suite"]) or obj_words >= 25:
        budget = 1536
    elif any(k in obj_lower for k in ["test", "add", "function", "fix", "implement", "feature"]) or obj_words >= 12:
        budget = 1024
    else:
        budget = 512
    return min(budget, ceiling)


@dataclass
class AdaptiveBudget:
    """Calculated dynamic context allocation based on model tier and capacity."""
    context_capacity: int
    tier: str
    max_output_tokens: int
    history_budget_tokens: int
    repo_context_budget_tokens: int
    instruction_budget_tokens: int
    safety_margin_tokens: int
    usable_input_tokens: int


def calculate_adaptive_budget(
    model: Any,
    budget_profile: Optional[Any] = None,
    objective: Optional[str] = None,
    thread_context: Optional[str] = None,
) -> AdaptiveBudget:
    """
    Dynamically scale input, history, and repository context allocations
    according to active model context capacity, tier (Nano, Super, Ultra), and optional budget profiles.
    
    Prevents both context-overflow crashes on smaller models (8k-16k) and
    artificial bottlenecking on 128k+ long-context models.
    """
    capacity_val = getattr(model, "context_capacity", None)
    if isinstance(capacity_val, int) and not isinstance(capacity_val, bool) and capacity_val > 0:
        capacity = capacity_val
    else:
        capacity = 32000

    tier_val = getattr(model, "tier", None)
    if isinstance(tier_val, str) and tier_val.lower().strip() in ("nano", "super", "ultra"):
        tier = tier_val.lower().strip()
    else:
        if capacity <= 16384:
            tier = "nano"
        elif capacity <= 65536:
            tier = "super"
        else:
            tier = "ultra"

    # 1. Output budget ceiling
    profile_max_out = getattr(budget_profile, "max_output_tokens", None)
    model_max_out_val = getattr(model, "max_output_tokens", None)
    if isinstance(model_max_out_val, int) and not isinstance(model_max_out_val, bool) and model_max_out_val > 0:
        model_max_out = model_max_out_val
    else:
        model_max_out = 4096

    if isinstance(profile_max_out, int) and not isinstance(profile_max_out, bool) and profile_max_out > 0:
        effective_out_cap = profile_max_out
    else:
        effective_out_cap = model_max_out

    if objective:
        max_output_tokens = calculate_dynamic_output_budget(
            objective, ceiling=effective_out_cap, thread_context=thread_context
        )
    else:
        max_output_tokens = min(effective_out_cap, 8192)

    # 2. Safety margin (buffer to prevent token context spill)
    safety_margin = max(500, min(int(capacity * 0.08), 4000))

    # 3. Instruction & tools schema budget
    if tier == "nano":
        instruction_budget = 1200
        history_ratio = 0.30
    elif tier == "super":
        instruction_budget = 2000
        history_ratio = 0.35
    else:  # ultra or massive context
        instruction_budget = 3000
        history_ratio = 0.35

    # 4. Usable input capacity
    usable_input = capacity - max_output_tokens - safety_margin - instruction_budget
    usable_input = max(usable_input, 1500)

    # If an explicit budget profile constrains input tokens, respect it
    profile_max_in = getattr(budget_profile, "max_input_tokens", None)
    if isinstance(profile_max_in, int) and not isinstance(profile_max_in, bool) and profile_max_in > 0:
        usable_input = min(usable_input, profile_max_in)

    # 5. Distribute usable input between Conversation History and Repository Files
    history_budget = max(2000, int(usable_input * history_ratio))
    repo_budget = max(1000, usable_input - history_budget)

    return AdaptiveBudget(
        context_capacity=capacity,
        tier=tier,
        max_output_tokens=max_output_tokens,
        history_budget_tokens=history_budget,
        repo_context_budget_tokens=repo_budget,
        instruction_budget_tokens=instruction_budget,
        safety_margin_tokens=safety_margin,
        usable_input_tokens=usable_input,
    )


class ContextOptimizer:
    """
    Context Optimizer - builds model context from repository.
    
    Pipeline: query extraction -> candidate retrieval -> ranking -> 
    budget allocation -> compression -> cache -> model context package.
    """
    
    def __init__(self, workspace_path: str):
        self.workspace_path = Path(workspace_path)
        self.optimizer_version = "1.0.0"
        self._cache: Dict[str, Any] = {}
        self._index: Dict[str, FileInfo] = {}
        self._indexed = False
    
    def build_context(
        self,
        task_query: str,
        model: ModelRegistry,
        current_diff: Optional[str] = None,
        recent_tool_output: Optional[str] = None,
        step_number: int = 1,
    ) -> ContextPackage:
        """
        Build optimized context package for model inference.
        
        Args:
            task_query: The task/question for the model
            model: Model registry entry with capacity info
            current_diff: Current patch/diff if any
            recent_tool_output: Recent tool execution output
            step_number: Current step number
            
        Returns:
            ContextPackage ready for model
        """
        # Refresh repository index if workspace exists
        if self.workspace_path.exists():
            self._build_index()
        
        # Extract query terms
        query_terms = self._extract_query_terms(task_query)
        
        # Retrieve candidate files
        candidates = self._retrieve_candidates(query_terms, current_diff)
        
        # Rank candidates
        ranked = self._rank_candidates(candidates, query_terms, current_diff, recent_tool_output)
        
        # Allocate budget
        budget = self._calculate_budget(model)
        selected, omitted = self._allocate_budget(ranked, budget, current_diff, recent_tool_output)
        
        # Compress context using AST skeletonization and cache reuse
        compressed, cache_hits, compression_ratio = self._compress_context(
            selected, budget, task_query, current_diff
        )
        # Deterministically sort included files by path for KV-cache prefix stability
        compressed.sort(key=lambda f: f.get("path", ""))
        
        # Estimate tokens
        estimated_tokens = self._estimate_tokens(compressed, task_query, current_diff, recent_tool_output)
        
        # Build ranking reasons
        ranking_reasons = {r.file_info.path: "; ".join(r.reasons) for r in selected}
        
        # Build omitted categories
        omitted_categories = self._categorize_omitted(omitted)
        
        return ContextPackage(
            included_files=compressed,
            omitted_categories=omitted_categories,
            ranking_reasons=ranking_reasons,
            cache_hits=cache_hits,
            estimated_tokens=estimated_tokens,
            compression_ratio=compression_ratio,
        )
    
    def _build_index(self) -> None:
        """Build repository index using Python AST"""
        self._index = {}
        if not self.workspace_path.exists():
            self._indexed = True
            return
        
        for py_file in self.workspace_path.rglob("*.py"):
            # Skip excluded directories
            if any(part in py_file.parts for part in {".git", "__pycache__", ".venv", "venv", "env", "build", "dist"}):
                continue
            
            try:
                rel_path = py_file.relative_to(self.workspace_path)
                content = py_file.read_text(encoding="utf-8")
                
                file_info = FileInfo(
                    path=str(rel_path),
                    language="python",
                    size=len(content),
                    hash=hashlib.sha256(content.encode()).hexdigest()[:16],
                    is_test="test" in str(rel_path).lower() or "test_" in py_file.name,
                    is_generated=self._is_generated(py_file),
                    last_modified=py_file.stat().st_mtime,
                )
                
                # Extract symbols and imports using AST
                file_info.symbols, file_info.imports = self._extract_symbols(content)
                
                self._index[str(rel_path)] = file_info
                
            except Exception:
                # Skip files that can't be parsed
                continue
        
        self._indexed = True
    
    def _is_generated(self, path: Path) -> bool:
        """Check if file is likely generated"""
        generated_patterns = [
            "generated",
            "auto",
            "migrations",
            "proto",
            "pb2.py",
            "_grpc.py",
        ]
        path_str = str(path).lower()
        return any(p in path_str for p in generated_patterns)
    
    def _extract_symbols(self, content: str) -> Tuple[List[str], List[str]]:
        """Extract symbols and imports using AST"""
        import ast
        
        symbols = []
        imports = []
        
        try:
            tree = ast.parse(content)
            
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    symbols.append(f"func:{node.name}")
                elif isinstance(node, ast.ClassDef):
                    symbols.append(f"class:{node.name}")
                    for method in node.body:
                        if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            symbols.append(f"method:{node.name}.{method.name}")
                elif isinstance(node, (ast.Import, ast.ImportFrom)):
                    for alias in node.names:
                        imports.append(alias.name)
                        
        except SyntaxError:
            pass
        
        return symbols, imports
    
    def _extract_query_terms(self, query: str) -> Set[str]:
        """Extract meaningful terms from query"""
        # Simple tokenization - in production use proper NLP
        stopwords = {"the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of", "with", "by", "is", "are", "was", "were", "be", "been", "being", "have", "has", "had", "do", "does", "did", "will", "would", "could", "should", "may", "might", "must", "can", "this", "that", "these", "those", "i", "you", "he", "she", "it", "we", "they", "me", "him", "her", "us", "them"}
        
        words = re.findall(r'\b[a-zA-Z_][a-zA-Z0-9_]*\b', query.lower())
        return {w for w in words if w not in stopwords and len(w) > 2}
    
    def _retrieve_candidates(
        self,
        query_terms: Set[str],
        current_diff: Optional[str],
    ) -> List[FileInfo]:
        """Retrieve candidate files based on query"""
        candidates = []
        
        for file_info in self._index.values():
            # Skip generated files unless explicitly needed
            if file_info.is_generated:
                continue
            
            # Always include test files if they might be relevant
            score = 0
            reasons = []
            
            # Keyword overlap
            path_lower = file_info.path.lower()
            symbols_lower = [s.lower() for s in file_info.symbols]
            
            for term in query_terms:
                if term in path_lower:
                    score += 3
                    reasons.append(f"path_match:{term}")
                for sym in symbols_lower:
                    if term in sym:
                        score += 2
                        reasons.append(f"symbol_match:{term}")
            
            # Test file relevance
            if file_info.is_test:
                score += 1
                reasons.append("test_file")
            
            # Diff relevance
            if current_diff and file_info.path in current_diff:
                score += 5
                reasons.append("in_current_diff")
            
            if score > 0:
                candidates.append(file_info)
        
        return candidates
    
    def _rank_candidates(
        self,
        candidates: List[FileInfo],
        query_terms: Set[str],
        current_diff: Optional[str],
        recent_tool_output: Optional[str],
    ) -> List[RankedFile]:
        """Rank candidates by relevance"""
        ranked = []
        
        for file_info in candidates:
            score = 0
            reasons = []
            
            path_lower = file_info.path.lower()
            symbols_lower = [s.lower() for s in file_info.symbols]
            
            # Keyword overlap (already computed, but recompute for clarity)
            for term in query_terms:
                if term in path_lower:
                    score += 3
                    reasons.append(f"path:{term}")
                for sym in symbols_lower:
                    if term in sym:
                        score += 2
                        reasons.append(f"symbol:{term}")
            
            # Import/dependency relationship
            # TODO: Build import graph
            
            # Failing test location
            if file_info.is_test and recent_tool_output:
                if "FAILED" in recent_tool_output and file_info.path in recent_tool_output:
                    score += 10
                    reasons.append("failing_test_location")
            
            # Git history signal (simplified)
            # TODO: Integrate git log
            
            # Generated file penalty
            if file_info.is_generated:
                score -= 5
                reasons.append("generated_file_penalty")
            
            # File type bonus
            if file_info.path.endswith(".py"):
                score += 1
                reasons.append("python_file")
            
            if score > 0:
                ranked.append(RankedFile(file_info=file_info, score=score, reasons=reasons))
        
        # Sort by score descending
        ranked.sort(key=lambda r: r.score, reverse=True)
        return ranked
    
    def _calculate_budget(self, model: ModelRegistry) -> int:
        """Calculate token budget for repository context based on adaptive model capacity"""
        adaptive = calculate_adaptive_budget(model)
        return adaptive.repo_context_budget_tokens
    
    def _allocate_budget(
        self,
        ranked: List[RankedFile],
        budget: int,
        current_diff: Optional[str],
        recent_tool_output: Optional[str],
    ) -> Tuple[List[RankedFile], List[RankedFile]]:
        """Allocate token budget across ranked files"""
        selected = []
        omitted = []
        used_tokens = 0
        
        # Always include current diff if present
        diff_tokens = 0
        if current_diff:
            diff_tokens = self._estimate_tokens_for_text(current_diff)
            if diff_tokens <= budget * 0.3:  # Max 30% for diff
                # Create a pseudo-ranked file for diff
                pass
        
        for ranked_file in ranked:
            file_tokens = self._estimate_file_tokens(ranked_file.file_info)
            
            if used_tokens + file_tokens <= budget:
                selected.append(ranked_file)
                used_tokens += file_tokens
            else:
                omitted.append(ranked_file)
        
        return selected, omitted
    
    def _compress_context(
        self,
        selected: List[RankedFile],
        budget: int,
        task_query: str = "",
        current_diff: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], int, float]:
        """
        Compress selected files using AST skeletonization and active cache reuse.
        Safeguard: explicitly targeted files and files in the current diff retain full contents;
        other selected Python files are skeletonized.
        """
        compressed = []
        cache_hits = 0
        original_chars = 0
        compressed_chars = 0
        query_lower = task_query.lower()
        diff_str = current_diff or ""

        for ranked_file in selected:
            file_info = ranked_file.file_info
            path = file_info.path
            path_filename = Path(path).name.lower()
            path_stem = Path(path).stem.lower()

            # Safeguard: targeted files or files in diff retain full content
            is_target = (
                path in diff_str
                or path_filename in query_lower
                or (len(path_stem) > 2 and path_stem in query_lower)
                or "in_current_diff" in ranked_file.reasons
            )
            mode = "full" if (is_target or file_info.language != "python") else "skeleton"
            cache_key = f"{path}:{file_info.hash}:{mode}"

            if cache_key in self._cache:
                cache_hits += 1
                entry = dict(self._cache[cache_key])
                entry["relevance_score"] = ranked_file.score
                entry["reasons"] = ranked_file.reasons
                compressed.append(entry)
                compressed_chars += len(entry.get("content", ""))
                original_chars += file_info.size
                continue

            full_path = self.workspace_path / path
            try:
                raw_content = full_path.read_text(encoding="utf-8")
            except Exception:
                raw_content = f"# Could not read {path}"

            original_chars += len(raw_content)

            if mode == "skeleton":
                final_content = skeletonize_python(raw_content)
            else:
                final_content = raw_content

            compressed_chars += len(final_content)

            entry = {
                "path": path,
                "content": final_content,
                "language": file_info.language,
                "symbols": file_info.symbols,
                "relevance_score": ranked_file.score,
                "reasons": ranked_file.reasons,
                "content_mode": mode,
            }
            self._cache[cache_key] = entry
            compressed.append(entry)

        ratio = round(1.0 - (compressed_chars / max(original_chars, 1)), 2) if original_chars > 0 else 0.0
        return compressed, cache_hits, ratio

    def _check_cache(self, selected: List[RankedFile]) -> int:
        """Check cache for file summaries"""
        hits = 0
        for ranked_file in selected:
            cache_key = f"{ranked_file.file_info.path}:{ranked_file.file_info.hash}:skeleton"
            if cache_key in self._cache or f"{ranked_file.file_info.path}:{ranked_file.file_info.hash}:full" in self._cache:
                hits += 1
        return hits
    
    def _estimate_tokens(self, compressed: List[Dict], task_query: str, current_diff: Optional[str], recent_tool_output: Optional[str]) -> int:
        """Estimate total tokens (rough approximation: 1 token ≈ 4 chars)"""
        total_chars = len(task_query)
        
        if current_diff:
            total_chars += len(current_diff)
        if recent_tool_output:
            total_chars += len(recent_tool_output)
        
        for file_data in compressed:
            total_chars += len(file_data.get("content", ""))
        
        return total_chars // 4
    
    def _estimate_file_tokens(self, file_info: FileInfo) -> int:
        """Estimate tokens for a file"""
        return file_info.size // 4
    
    def _estimate_tokens_for_text(self, text: str) -> int:
        return len(text) // 4
    
    def _categorize_omitted(self, omitted: List[RankedFile]) -> List[Dict[str, Any]]:
        """Categorize omitted files by reason"""
        categories: Dict[str, List[str]] = {}
        
        for ranked_file in omitted:
            reason = "low_relevance"
            if ranked_file.file_info.is_generated:
                reason = "generated_file"
            elif ranked_file.file_info.is_test:
                reason = "test_file_low_relevance"
            
            if reason not in categories:
                categories[reason] = []
            categories[reason].append(ranked_file.file_info.path)
        
        return [
            {"category": cat, "count": len(files), "files": files[:10]}
            for cat, files in categories.items()
        ]
    
    def to_schema(self, package: ContextPackage, run_id: str, step_number: int, model_id: Optional[str] = None) -> ContextPackageSchema:
        """Convert to API schema"""
        return ContextPackageSchema(
            id=run_id,
            run_id=run_id,
            step_number=step_number,
            model_id=model_id,
            included_files=package.included_files,
            omitted_categories=package.omitted_categories,
            ranking_reasons=package.ranking_reasons,
            cache_hits=package.cache_hits,
            estimated_input_tokens=package.estimated_tokens,
            actual_input_tokens=None,
            compression_ratio=package.compression_ratio,
            context_optimizer_version=self.optimizer_version,
            created_at=datetime.now(),
        )


# Need to import datetime
from datetime import datetime
import re
