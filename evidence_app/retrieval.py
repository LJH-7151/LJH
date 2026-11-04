"""Literal keyword retrieval with references to immutable source chunks."""
from .common import ValidationError

# SQLite's built-in lower() folds ASCII only. Use the same one-to-one mapping
# for excerpts so source positions stay correct for all uploaded Unicode text.
ASCII_FOLD = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")
EXCERPT_LENGTH = 240


def excerpt(content, terms):
    folded = content.translate(ASCII_FOLD)
    first_match = min(folded.find(term.translate(ASCII_FOLD)) for term in terms)
    start = max(0, first_match - 40)
    end = min(len(content), start + EXCERPT_LENGTH)
    return ("…" if start else "") + content[start:end] + ("…" if end < len(content) else "")


def search(store, query, document_id=None, limit=20):
    if not isinstance(query, str) or not 0 < len(query) <= 200:
        raise ValidationError("请输入1至200个字符的检索词")
    if "\x00" in query:
        raise ValidationError("检索词不能包含空字符")
    terms = query.split()
    if not terms or len(terms) > 8:
        raise ValidationError("请输入检索词，以空格分隔，最多8个词")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
        raise ValidationError("返回条数必须是1至50之间的整数")
    if document_id is not None:
        if not isinstance(document_id, str) or len(document_id) > 64:
            raise ValidationError("资料编号无效")
        if document_id and not store.document(document_id):
            raise LookupError("资料不存在")
    normalized_id = document_id or None
    total, rows = store.search_chunks(terms, normalized_id, limit)
    results = []
    for row in rows:
        content = row.pop("content")
        start, end = row["start_line"], row["end_line"]
        row["location"] = f"第{start}行" if start == end else f"第{start}–{end}行"
        row["excerpt"] = excerpt(content, terms)
        results.append(row)
    return {
        "query": " ".join(terms),
        "terms": terms,
        "document_id": normalized_id,
        "total": total,
        "limit": limit,
        "has_more": total > len(results),
        "results": results,
    }
